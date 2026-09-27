"""Leaf adapters: intrinsic size of an ODL element and its placement into a box.

Each supported renderer element type gets two operations:

- ``intrinsic(element, max_w)``: preferred ``(width, height)`` when at most ``max_w`` pixels wide.
- ``emit(element, box)``: the element with its geometry fields filled in for ``box``.

Field names and defaults mirror the handlers in ``odl_renderer.elements``.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Callable

import qrcode
from odl_renderer import FontManager, TextMetrics, measure_text
from odl_renderer.coordinates import coerce_number

from .errors import LayoutError
from .units import Box, Scale, coerce_bool, resolve_length

_LOGGER = logging.getLogger(__name__)

# Keys that only mean something to the layout engine; never passed to the renderer.
LAYOUT_KEYS = frozenset({"w", "h", "grow", "span", "position", "align_self", "clamp"})

_DEFAULT_FONT = "ppb.ttf"

Size = tuple[int, int]


@lru_cache(maxsize=64)
def _qr_side(data: str, boxsize: int, border: int) -> int:
    """Pixel side length of a QR code, using the renderer's QR settings."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=boxsize, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    return int((qr.modules_count + 2 * border) * boxsize)


class Leaves:
    """Sizes and places renderer elements for one canvas."""

    def __init__(self, canvas: Box, scale: Scale, fonts: FontManager) -> None:
        self.canvas = canvas
        self.scale = scale
        self.fonts = fonts
        self._handlers: dict[
            str, tuple[Callable[[dict[str, Any], int | None], Size], Callable[..., dict[str, Any]]]
        ] = {
            "text": (self._text_size, self._text_emit),
            "multiline": (self._multiline_size, self._multiline_emit),
            "icon": (self._icon_size, self._icon_emit),
            "icon_sequence": (self._icon_sequence_size, self._icon_sequence_emit),
            "qrcode": (self._qrcode_size, self._qrcode_emit),
            "dlimg": (self._dlimg_size, self._dlimg_emit),
            "rectangle": (self._zero_size, self._span_emit),
            "ellipse": (self._zero_size, self._span_emit),
            "progress_bar": (self._zero_size, self._span_emit),
            "plot": (self._zero_size, self._span_emit),
            "line": (self._line_size, self._line_emit),
            "circle": (self._round_size, self._round_emit),
            "arc": (self._round_size, self._round_emit),
            "polygon": (self._polygon_size, self._polygon_emit),
        }

    # -- public -------------------------------------------------------------

    def supports(self, element_type: str) -> bool:
        return element_type in self._handlers

    def intrinsic(self, element: dict[str, Any], max_w: int | None) -> Size:
        size_fn, _ = self._handler(element)
        return size_fn(element, max_w)

    def emit(self, element: dict[str, Any], box: Box) -> dict[str, Any]:
        _, emit_fn = self._handler(element)
        placed = emit_fn(dict(element), box)
        return {k: v for k, v in placed.items() if k not in LAYOUT_KEYS}

    def _handler(self, element: dict[str, Any]) -> tuple[Callable[..., Size], Callable[..., dict[str, Any]]]:
        element_type = element.get("type")
        if element_type not in self._handlers:
            raise LayoutError(
                f"Element type {element_type!r} cannot be placed inside a layout container "
                "(use it at the top level of the payload instead)"
            )
        return self._handlers[element_type]

    # -- helpers ------------------------------------------------------------

    def _text_px(self, value: Any, default: str) -> int:
        """Resolve a text/icon size: token, px, or % of canvas height (renderer semantics)."""
        px = resolve_length(default if value is None else value, self.canvas.h, self.scale, kind="text")
        return max(1, px or 1)

    def _font(self, element: dict[str, Any]) -> Any:
        return self.fonts.get_font(element.get("font", _DEFAULT_FONT), self._text_px(element.get("size"), "md"))

    # -- text ---------------------------------------------------------------

    def _text_metrics(self, element: dict[str, Any], max_w: int | None) -> TextMetrics:
        font = self._font(element)
        kwargs = {
            "spacing": int(coerce_number(element.get("spacing", 5), 5)),
            "stroke_width": int(coerce_number(element.get("stroke_width", 0), 0)),
        }
        clamp = element.get("clamp")
        max_lines = int(coerce_number(clamp, 0)) or None if clamp is not None else None

        if coerce_bool(element.get("parse_colors", False)):
            # Markup is kept verbatim for the renderer, so the text cannot be pre-wrapped.
            return measure_text(element["value"], font, parse_colors=True, **kwargs)

        limit = max_w
        if element.get("max_width") is not None:
            explicit = resolve_length(element["max_width"], self.canvas.w, self.scale)
            limit = explicit if limit is None or explicit is None else min(limit, explicit)

        unwrapped = measure_text(element["value"], font, max_lines=max_lines, **kwargs)
        if limit is None or unwrapped.width <= limit:
            return unwrapped
        truncate = coerce_bool(element.get("truncate", False))
        return measure_text(element["value"], font, limit, truncate=truncate, max_lines=max_lines, **kwargs)

    def _text_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        metrics = self._text_metrics(element, max_w)
        return metrics.width, metrics.height

    def _text_emit(self, out: dict[str, Any], box: Box) -> dict[str, Any]:
        metrics = self._text_metrics(out, box.w)
        _warn_geometry(out, ("x", "y"))
        x = box.x + _align_offset(out.get("align", "left"), box.w - metrics.width)
        if not coerce_bool(out.get("parse_colors", False)):
            out["value"] = metrics.text
        for key in ("max_width", "truncate", "y_padding"):
            out.pop(key, None)
        out.update(x=x, y=box.y, anchor="la", size=self._text_px(out.get("size"), "md"))
        return out

    # -- multiline ----------------------------------------------------------

    def _multiline_lines(self, element: dict[str, Any]) -> list[str]:
        return str(element["value"]).replace("\n", "").split(element.get("delimiter", "\n") or "\n")

    def _multiline_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        font = self._font(element)
        lines = self._multiline_lines(element)
        offset_y = int(coerce_number(element.get("offset_y", 0), 0))
        ascent, descent = font.getmetrics()
        width = measure_text("\n".join(lines), font).width
        return width, (len(lines) - 1) * offset_y + ascent + descent

    def _multiline_emit(self, out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x", "y", "start_y"))
        out.pop("start_y", None)
        out.pop("y_padding", None)
        out.update(x=box.x, y=box.y, anchor="la", size=self._text_px(out.get("size"), "md"))
        return out

    # -- icons --------------------------------------------------------------

    def _icon_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        side = self._text_px(element.get("size"), "md")
        return side, side

    def _icon_emit(self, out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x", "y"))
        out.update(x=box.x + box.w // 2, y=box.y + box.h // 2, anchor="mm", size=self._text_px(out.get("size"), "md"))
        return out

    def _icon_sequence_metrics(self, element: dict[str, Any]) -> tuple[int, int, int]:
        size = self._text_px(element.get("size"), "md")
        spacing = int(coerce_number(element.get("spacing", size // 4), size // 4))
        return size, spacing, len(element.get("icons") or [])

    def _icon_sequence_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        size, spacing, count = self._icon_sequence_metrics(element)
        length = max(0, count * size + (count - 1) * spacing)
        if element.get("direction", "right") in ("down", "up"):
            return size, length
        return length, size

    def _icon_sequence_emit(self, out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x", "y"))
        size, _, _ = self._icon_sequence_metrics(out)
        direction = out.get("direction", "right")
        # Icons step away from (x, y); reversed directions start at the far end of the box.
        x = box.x1 - size if direction == "left" else box.x
        y = box.y1 - size if direction == "up" else box.y
        out.update(x=x, y=y, anchor="lt", size=size)
        return out

    # -- media --------------------------------------------------------------

    def _qrcode_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        border = int(coerce_number(element.get("border", 1), 1))
        boxsize = int(coerce_number(element.get("boxsize", 2), 2))
        side = _qr_side(str(element["data"]), boxsize, border)
        return side, side

    def _qrcode_emit(self, out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x", "y"))
        side, _ = self._qrcode_size(out, None)
        out.update(x=box.x + max(0, box.w - side) // 2, y=box.y + max(0, box.h - side) // 2)
        return out

    def _dlimg_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        w = resolve_length(element.get("xsize"), self.canvas.w, self.scale) or 0
        h = resolve_length(element.get("ysize"), self.canvas.h, self.scale) or 0
        return w, h

    def _dlimg_emit(self, out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x", "y"))
        out.update(x=box.x, y=box.y, xsize=box.w, ysize=box.h)
        return out

    # -- shapes -------------------------------------------------------------

    @staticmethod
    def _zero_size(element: dict[str, Any], max_w: int | None) -> Size:
        return 0, 0

    @staticmethod
    def _span_emit(out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x_start", "y_start", "x_end", "y_end"))
        out.update(x_start=box.x, y_start=box.y, x_end=box.x1 - 1, y_end=box.y1 - 1)
        return out

    @staticmethod
    def _line_size(element: dict[str, Any], max_w: int | None) -> Size:
        thickness = int(coerce_number(element.get("width", 1), 1))
        return (thickness, 0) if coerce_bool(element.get("vertical", False)) else (0, thickness)

    @staticmethod
    def _line_emit(out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x_start", "y_start", "x_end", "y_end"))
        out.pop("y_padding", None)
        if coerce_bool(out.pop("vertical", False)):
            cx = box.x + box.w // 2
            out.update(x_start=cx, x_end=cx, y_start=box.y, y_end=box.y1 - 1)
        else:
            cy = box.y + box.h // 2
            out.update(x_start=box.x, x_end=box.x1 - 1, y_start=cy, y_end=cy)
        return out

    def _round_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        radius = resolve_length(element.get("radius"), self.canvas.w, self.scale) or 0
        return 2 * radius, 2 * radius

    @staticmethod
    def _round_emit(out: dict[str, Any], box: Box) -> dict[str, Any]:
        _warn_geometry(out, ("x", "y"))
        out.update(x=box.x + box.w // 2, y=box.y + box.h // 2, radius=min(box.w, box.h) // 2)
        return out

    def _polygon_size(self, element: dict[str, Any], max_w: int | None) -> Size:
        # Points are local to the box; percentages only resolve once the box is known.
        xs = [resolve_length(p[0], None, self.scale) for p in element["points"]]
        ys = [resolve_length(p[1], None, self.scale) for p in element["points"]]
        return max((x + 1 for x in xs if x is not None), default=0), max(
            (y + 1 for y in ys if y is not None), default=0
        )

    def _polygon_emit(self, out: dict[str, Any], box: Box) -> dict[str, Any]:
        out["points"] = [
            (
                box.x + (resolve_length(px, box.w, self.scale) or 0),
                box.y + (resolve_length(py, box.h, self.scale) or 0),
            )
            for px, py in out["points"]
        ]
        return out


def _align_offset(align: str, free: int) -> int:
    if free <= 0:
        return 0
    if align in ("center", "middle"):
        return free // 2
    if align in ("right", "end"):
        return free
    return 0


def _warn_geometry(element: dict[str, Any], keys: tuple[str, ...]) -> None:
    present = [k for k in keys if k in element]
    if present:
        _LOGGER.warning(
            "%s: %s ignored inside a layout container (position comes from the layout)",
            element.get("type"),
            ", ".join(present),
        )
