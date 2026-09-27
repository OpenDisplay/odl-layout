"""Layout engine: sizes and places container trees, emitting flat ODL elements.

Two recursive operations drive everything:

- ``size(node, avail_w, avail_h)``: preferred outer size of a node within the available space.
- ``place(node, box, out)``: assigns ``box`` to the node and appends the resulting ODL elements to ``out``.

Containers call ``size`` on their children to divide their own box, then ``place`` each child.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from odl_renderer import FontManager, should_show_element
from odl_renderer.coordinates import coerce_number

from .adapters import Leaves
from .errors import LayoutError
from .units import Box, Scale, coerce_bool, is_auto, resolve_length, resolve_sides

_LOGGER = logging.getLogger(__name__)

CONTAINERS = frozenset({"row", "column", "stack", "grid", "list"})

# Default cross-axis alignment: rows center vertically (icon + text), columns fill the width.
_DEFAULT_ALIGN = {"row": "center", "column": "stretch"}

# Renderer elements that continue below the previous element when they have no y.
_FLOW_Y = {"text": ("y", 10), "multiline": ("y", 10), "line": ("y_start", 0)}

Size = tuple[int, int]


class Engine:
    """Lays out one payload on one canvas."""

    def __init__(self, width: int, height: int, font_dirs: list[str] | None = None) -> None:
        if width <= 0 or height <= 0:
            raise LayoutError(f"Invalid canvas size: {width}x{height}")
        self.canvas = Box(0, 0, width, height)
        self.scale = Scale.for_canvas(width, height)
        self.leaves = Leaves(self.canvas, self.scale, FontManager(font_dirs))

    # -- top level ----------------------------------------------------------

    def run(self, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        flow_bottom: int | None = None
        for element in payload:
            if not isinstance(element, dict):
                raise LayoutError(f"Payload entries must be objects, got {type(element).__name__}")
            if _is_container(element):
                if not should_show_element(element):
                    continue
                box = self._region(element)
                self.place(element, box, out)
                flow_bottom = box.y1
                continue
            if flow_bottom is not None:
                element = _continue_flow(element, flow_bottom)
                flow_bottom = None
            out.append(element)
        return out

    def _region(self, node: dict[str, Any]) -> Box:
        """Canvas region of a top-level container: x/y/w/h (px or %), or right/bottom insets."""
        cw, ch = self.canvas.w, self.canvas.h
        x = resolve_length(node.get("x", 0), cw, self.scale) or 0
        y = resolve_length(node.get("y", 0), ch, self.scale) or 0
        right = resolve_length(node.get("right", 0), cw, self.scale) or 0
        bottom = resolve_length(node.get("bottom", 0), ch, self.scale) or 0
        avail_w, avail_h = max(0, cw - x - right), max(0, ch - y - bottom)

        w = resolve_length(node.get("w"), cw, self.scale)
        h = resolve_length(node.get("h"), ch, self.scale)
        if w is None or h is None:
            # Missing size fills the remaining canvas; explicit "auto" shrinks to content.
            pref_w, pref_h = self.size(node, avail_w, avail_h)
            if w is None:
                w = pref_w if "w" in node and is_auto(node["w"]) else avail_w
            if h is None:
                h = pref_h if "h" in node and is_auto(node["h"]) else avail_h
        return Box(x, y, w, h)

    # -- sizing -------------------------------------------------------------

    def size(self, node: dict[str, Any], avail_w: int | None, avail_h: int | None) -> Size:
        """Preferred outer size of ``node`` within the available space."""
        w = resolve_length(node.get("w"), avail_w, self.scale)
        h = resolve_length(node.get("h"), avail_h, self.scale)
        if w is not None and h is not None:
            return w, h

        constraint_w = w if w is not None else avail_w
        if not _is_container(node):
            if node.get("type") == "spacer":
                iw, ih = 0, 0
            else:
                iw, ih = self.leaves.intrinsic(node, constraint_w)
            return (w if w is not None else iw), (h if h is not None else ih)

        top, right, bottom, left = resolve_sides(node.get("padding"), self.scale)
        content_w = None if constraint_w is None else max(0, constraint_w - left - right)
        outer_h = h if h is not None else avail_h
        content_h = None if outer_h is None else max(0, outer_h - top - bottom)
        iw, ih = self._content_size(node, content_w, content_h)
        return (w if w is not None else iw + left + right), (h if h is not None else ih + top + bottom)

    def _content_size(self, node: dict[str, Any], cw: int | None, ch: int | None) -> Size:
        kind = node["type"]
        children = _children(node)
        gap = self._gap(node)
        if not children:
            return 0, 0

        if kind == "column":
            widths = [self._cross_size(c, cw, ch, node, horizontal=False) for c in children]
            heights = [self.size(c, wi, ch)[1] for c, wi in zip(children, widths)]
            return max(widths), sum(heights) + gap * (len(children) - 1)

        if kind == "row":
            if cw is not None:
                widths = self._allocate(children, cw, gap, "w", lambda _, c: self.size(c, cw, ch)[0], shrink=True)
            else:
                widths = [self.size(c, None, ch)[0] for c in children]
            heights = [self.size(c, wi, ch)[1] for c, wi in zip(children, widths)]
            return sum(widths) + gap * (len(children) - 1), max(heights)

        if kind == "stack":
            sizes = [self.size(c, cw, ch) for c in children if not _is_absolute(c)]
            return max((s[0] for s in sizes), default=0), max((s[1] for s in sizes), default=0)

        if kind == "grid":
            cols = self._cols(node)
            col_w = None if cw is None else max(0, (cw - gap * (cols - 1)) // cols)
            rows = self._grid_rows(children, cols)
            row_heights = [
                max(self.size(c, None if col_w is None else _span_w(col_w, gap, span), None)[1] for c, _, span in row)
                for row in rows
            ]
            width = cw if cw is not None else 0
            return width, sum(row_heights) + gap * (len(rows) - 1)

        if kind == "list":
            heights = [self.size(c, cw, None)[1] for c in children]
            return (cw or 0), sum(heights) + gap * (len(children) - 1)

        raise AssertionError(kind)

    def _cross_size(
        self, child: dict[str, Any], avail: int | None, main_avail: int | None, parent: dict[str, Any], horizontal: bool
    ) -> int:
        """Size of ``child`` across the parent's main axis (width in a column, height in a row)."""
        key = "w" if not horizontal else "h"
        explicit = resolve_length(child.get(key), avail, self.scale)
        if explicit is not None:
            return explicit
        if self._align(child, parent) == "stretch" and avail is not None:
            return avail
        if not horizontal:
            pref = self.size(child, avail, main_avail)[0]
        else:
            pref = self.size(child, main_avail, avail)[1]
        return pref if avail is None else min(pref, avail)

    def _allocate(
        self,
        children: list[dict[str, Any]],
        avail: int,
        gap: int,
        key: str,
        measure: Callable[[int, dict[str, Any]], int],
        *,
        shrink: bool,
    ) -> list[int]:
        """Divide ``avail`` along the main axis: explicit sizes, then content, then ``grow`` weights.

        Args:
            children: Visible children.
            avail: Main-axis content size.
            gap: Gap between children.
            key: Main-axis size key (``"w"`` or ``"h"``).
            measure: Content size of child ``i`` along the main axis.
            shrink: On overflow, shrink content-sized children proportionally (widths only: text re-wraps).
        """
        free = avail - gap * (len(children) - 1)
        sizes: list[int] = []
        grows: list[float] = []
        for i, child in enumerate(children):
            explicit = resolve_length(child.get(key), avail, self.scale)
            grows.append(_grow(child) if explicit is None else 0.0)
            if explicit is not None:
                sizes.append(explicit)
            else:
                sizes.append(0 if grows[-1] > 0 else measure(i, child))

        remaining = free - sum(sizes)
        total_grow = sum(grows)
        if remaining > 0 and total_grow > 0:
            given = 0
            last = max(i for i, g in enumerate(grows) if g > 0)
            for i, g in enumerate(grows):
                if g > 0:
                    share = remaining - given if i == last else int(remaining * g / total_grow)
                    sizes[i] += share
                    given += share
        elif remaining < 0:
            auto = [resolve_length(c.get(key), avail, self.scale) is None and g == 0 for c, g in zip(children, grows)]
            shrinkable = sum(s for s, a in zip(sizes, auto) if a)
            if shrink and shrinkable > 0:
                factor = max(0.0, (shrinkable + remaining) / shrinkable)
                sizes = [int(s * factor) if a else s for s, a in zip(sizes, auto)]
            if sum(sizes) > free:
                _LOGGER.warning("Layout overflow: content needs %spx, %spx available", sum(sizes), free)
        return sizes

    # -- placement ----------------------------------------------------------

    def place(self, node: dict[str, Any], box: Box, out: list[dict[str, Any]]) -> None:
        if not _is_container(node):
            if node.get("type") != "spacer":
                out.append(self.leaves.emit(node, box))
            return

        self._emit_background(node, box, out)
        top, right, bottom, left = resolve_sides(node.get("padding"), self.scale)
        content = box.inset(top, right, bottom, left)
        children = _children(node)
        if not children:
            return
        kind = node["type"]
        if kind in ("row", "column"):
            self._place_linear(node, children, content, out, horizontal=kind == "row")
        elif kind == "stack":
            self._place_stack(node, children, content, out)
        elif kind == "grid":
            self._place_grid(node, children, content, out)
        elif kind == "list":
            self._place_list(node, children, content, out)

    def _place_linear(
        self,
        node: dict[str, Any],
        children: list[dict[str, Any]],
        content: Box,
        out: list[dict[str, Any]],
        *,
        horizontal: bool,
    ) -> None:
        gap = self._gap(node)
        main_avail, cross_avail = (content.w, content.h) if horizontal else (content.h, content.w)

        if horizontal:
            mains = self._allocate(
                children, main_avail, gap, "w", lambda _, c: self.size(c, main_avail, cross_avail)[0], shrink=True
            )
            crosses = [self._cross_size(c, cross_avail, m, node, horizontal=True) for c, m in zip(children, mains)]
        else:
            # Heights depend on each child's width (text wraps), so measure at the resolved widths.
            crosses = [self._cross_size(c, cross_avail, main_avail, node, horizontal=False) for c in children]
            mains = self._allocate(
                children, main_avail, gap, "h", lambda i, c: self.size(c, crosses[i], main_avail)[1], shrink=False
            )

        used = sum(mains) + gap * (len(children) - 1)
        offset, spacing = _justify(node.get("justify", "start"), main_avail - used, len(children))
        cursor = offset
        for child, main, cross in zip(children, mains, crosses):
            cross_offset = _align_offset(self._align(child, node), cross_avail - cross)
            if horizontal:
                child_box = Box(content.x + cursor, content.y + cross_offset, main, cross)
            else:
                child_box = Box(content.x + cross_offset, content.y + cursor, cross, main)
            self.place(child, child_box, out)
            cursor += main + gap + spacing

    def _place_stack(
        self, node: dict[str, Any], children: list[dict[str, Any]], content: Box, out: list[dict[str, Any]]
    ) -> None:
        h_align = node.get("align", "stretch")
        v_align = node.get("valign", "stretch")
        for child in children:
            if _is_absolute(child):
                x = resolve_length(child.get("x", 0), content.w, self.scale) or 0
                y = resolve_length(child.get("y", 0), content.h, self.scale) or 0
                w, h = self.size(child, max(0, content.w - x), max(0, content.h - y))
                local = {k: v for k, v in child.items() if k not in ("x", "y")}
                self.place(local, Box(content.x + x, content.y + y, w, h), out)
                continue
            pref_w, _ = self.size(child, content.w, content.h)
            ha = child.get("align_self", h_align)
            va = child.get("valign_self", v_align)
            w = content.w if ha == "stretch" and "w" not in child else min(pref_w, content.w)
            if va == "stretch" and "h" not in child:
                h = content.h
            else:
                # Height at the final width (text may wrap differently).
                h = min(self.size(child, w, content.h)[1], content.h)
            box = Box(content.x + _align_offset(ha, content.w - w), content.y + _align_offset(va, content.h - h), w, h)
            self.place(child, box, out)

    def _place_grid(
        self, node: dict[str, Any], children: list[dict[str, Any]], content: Box, out: list[dict[str, Any]]
    ) -> None:
        cols = self._cols(node)
        gap = self._gap(node)
        col_w = max(0, (content.w - gap * (cols - 1)) // cols)
        rows = self._grid_rows(children, cols)
        heights = [max(self.size(c, _span_w(col_w, gap, span), None)[1] for c, _, span in row) for row in rows]
        # Rows keep their content height; spare space is shared equally so tiles fill the grid.
        spare = content.h - sum(heights) - gap * (len(rows) - 1)
        if spare > 0:
            heights = [h + spare // len(rows) + (1 if i < spare % len(rows) else 0) for i, h in enumerate(heights)]
        elif spare < 0:
            _LOGGER.warning("Layout overflow: grid needs %spx more height", -spare)
        y = content.y
        for row, row_h in zip(rows, heights):
            for child, col, span in row:
                x = content.x + col * (col_w + gap)
                self.place(child, Box(x, y, _span_w(col_w, gap, span), row_h), out)
            y += row_h + gap

    def _place_list(
        self, node: dict[str, Any], items: list[dict[str, Any]], content: Box, out: list[dict[str, Any]]
    ) -> None:
        """Flow items top-to-bottom into columns; hide what does not fit, optionally with a "+N more" counter."""
        gap = self._gap(node)
        if node.get("cols") is not None:
            candidates = [self._cols(node)]
        else:
            candidates = list(range(1, max(1, int(coerce_number(node.get("max_cols", 1), 1))) + 1))
        counter = coerce_bool(node.get("overflow_counter", False))

        best: tuple[int, int, list[tuple[int, int, int]]] | None = None  # (visible, cols, positions)
        for cols in candidates:
            col_w = max(0, (content.w - gap * (cols - 1)) // cols)
            heights = [self.size(item, col_w, None)[1] for item in items]
            positions = _flow(heights, cols, content.h, gap, 0)
            if counter and len(positions) < len(items):
                reserve = self._counter_height(node, col_w, len(items)) + gap
                positions = _flow(heights, cols, content.h, gap, reserve)
            if best is None or len(positions) > best[0]:
                best = (len(positions), cols, positions)

        if best is None:
            return
        visible, cols, positions = best
        col_w = max(0, (content.w - gap * (cols - 1)) // cols)
        for item, (col, y, h) in zip(items, positions):
            self.place(item, Box(content.x + col * (col_w + gap), content.y + y, col_w, h), out)

        hidden = len(items) - visible
        if hidden and counter:
            col, y = (positions[-1][0], positions[-1][1] + positions[-1][2] + gap) if positions else (0, 0)
            label = self._counter(node, hidden)
            h = self.size(label, col_w, None)[1]
            self.place(label, Box(content.x + col * (col_w + gap), content.y + y, col_w, h), out)
        elif hidden:
            _LOGGER.info("List: %s of %s items hidden (no space)", hidden, len(items))

    def _counter(self, node: dict[str, Any], hidden: int) -> dict[str, Any]:
        template = str(node.get("overflow_text", "+{n} more"))
        return {
            "type": "text",
            "value": template.replace("{n}", str(hidden)),
            "size": node.get("overflow_size", "sm"),
            "color": node.get("overflow_color", "black"),
            **({"font": node["font"]} if "font" in node else {}),
        }

    def _counter_height(self, node: dict[str, Any], col_w: int, total: int) -> int:
        return self.size(self._counter(node, total), col_w, None)[1]

    def _emit_background(self, node: dict[str, Any], box: Box, out: list[dict[str, Any]]) -> None:
        if node.get("background") is None and node.get("border") is None:
            return
        rect: dict[str, Any] = {
            "type": "rectangle",
            "x_start": box.x,
            "y_start": box.y,
            "x_end": box.x1 - 1,
            "y_end": box.y1 - 1,
            "fill": node.get("background"),
            "outline": node.get("border", node.get("background")),
            "width": int(coerce_number(node.get("border_width", 1), 1)) if node.get("border") is not None else 0,
        }
        if node.get("radius") is not None:
            rect["radius"] = resolve_length(node["radius"], None, self.scale) or 0
        out.append(rect)

    # -- small helpers ------------------------------------------------------

    def _gap(self, node: dict[str, Any]) -> int:
        return resolve_length(node.get("gap", 0), None, self.scale) or 0

    @staticmethod
    def _cols(node: dict[str, Any]) -> int:
        cols = int(coerce_number(node.get("cols", 1), 1))
        if cols < 1:
            raise LayoutError(f"{node['type']}: cols must be >= 1, got {node.get('cols')!r}")
        return cols

    @staticmethod
    def _grid_rows(children: list[dict[str, Any]], cols: int) -> list[list[tuple[dict[str, Any], int, int]]]:
        """Pack children into rows of (child, column, span)."""
        rows: list[list[tuple[dict[str, Any], int, int]]] = [[]]
        col = 0
        for child in children:
            span = min(cols, max(1, int(coerce_number(child.get("span", 1), 1))))
            if col + span > cols:
                rows.append([])
                col = 0
            rows[-1].append((child, col, span))
            col += span
        return [r for r in rows if r]

    @staticmethod
    def _align(child: dict[str, Any], parent: dict[str, Any]) -> str:
        return str(child.get("align_self", parent.get("align", _DEFAULT_ALIGN.get(parent["type"], "start"))))


def _is_container(node: dict[str, Any]) -> bool:
    return node.get("type") in CONTAINERS


def _is_absolute(node: dict[str, Any]) -> bool:
    return node.get("position") == "absolute"


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    key = "items" if node["type"] == "list" else "children"
    raw = node.get(key) or []
    if not isinstance(raw, list):
        raise LayoutError(f"{node['type']}: {key} must be a list")
    for child in raw:
        if not isinstance(child, dict):
            raise LayoutError(f"{node['type']}: {key} entries must be objects, got {type(child).__name__}")
    return [c for c in raw if should_show_element(c)]


def _grow(node: dict[str, Any]) -> float:
    default = 1.0 if node.get("type") == "spacer" else 0.0
    return max(0.0, float(coerce_number(node.get("grow", default), default)))


def _span_w(col_w: int, gap: int, span: int) -> int:
    return col_w * span + gap * (span - 1)


def _align_offset(align: str, free: int) -> int:
    if free <= 0 or align in ("start", "stretch", "left", "top"):
        return 0
    if align in ("center", "middle"):
        return free // 2
    if align in ("end", "right", "bottom"):
        return free
    raise LayoutError(f"Unknown alignment: {align!r}")


def _justify(justify: str, free: int, count: int) -> tuple[int, int]:
    """Return (start offset, extra spacing between children) for main-axis justification."""
    if free <= 0:
        return 0, 0
    if justify == "center":
        return free // 2, 0
    if justify == "end":
        return free, 0
    if justify == "space-between":
        return (0, free // (count - 1)) if count > 1 else (0, 0)
    if justify == "start":
        return 0, 0
    raise LayoutError(f"Unknown justify: {justify!r}")


def _flow(heights: list[int], cols: int, max_h: int, gap: int, reserve: int) -> list[tuple[int, int, int]]:
    """Place items column by column; the last column keeps ``reserve`` pixels free.

    Returns (column, y, height) for each visible item, in order. Stops at the first item that does not fit.
    """
    positions: list[tuple[int, int, int]] = []
    col, y = 0, 0
    for h in heights:
        limit = max_h - (reserve if col == cols - 1 else 0)
        if y > 0 and y + h > limit:
            col, y = col + 1, 0
            if col >= cols:
                break
            limit = max_h - (reserve if col == cols - 1 else 0)
        if y + h > limit:
            break
        positions.append((col, y, h))
        y += h + gap
    return positions


def _continue_flow(element: dict[str, Any], bottom: int) -> dict[str, Any]:
    """Anchor a y-less flowing element below the preceding container instead of its last emitted leaf."""
    spec = _FLOW_Y.get(str(element.get("type")))
    if spec is None:
        return element
    key, default_padding = spec
    if key in element or "start_y" in element:
        return element
    padding = int(coerce_number(element.get("y_padding", default_padding), default_padding))
    return {**element, key: bottom + padding}
