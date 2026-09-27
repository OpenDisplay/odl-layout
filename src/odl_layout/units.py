"""Length, size-token and box primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from odl_renderer.coordinates import coerce_number

from .errors import LayoutError

# Size tokens at the medium size class (e.g. 800x480). Text/icon sizes and spacing
# use separate tables because spacing grows much slower than type.
_TEXT_TOKENS = {"xs": 12, "sm": 16, "md": 20, "lg": 28, "xl": 40, "xxl": 64}
_SPACE_TOKENS = {"xs": 2, "sm": 4, "md": 8, "lg": 12, "xl": 16, "xxl": 24}

# Size classes keyed by the canvas short side, with a multiplier for the token tables.
# 400x300 -> small, 800x480 -> medium, 1972x1404 / 1200x1600 -> large.
_SIZE_CLASSES = ((300, "small", 0.75), (600, "medium", 1.0), (10**9, "large", 2.0))


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in canvas pixels; ``x1``/``y1`` are exclusive."""

    x: int
    y: int
    w: int
    h: int

    @property
    def x1(self) -> int:
        return self.x + self.w

    @property
    def y1(self) -> int:
        return self.y + self.h

    def inset(self, top: int, right: int, bottom: int, left: int) -> Box:
        return Box(self.x + left, self.y + top, max(0, self.w - left - right), max(0, self.h - top - bottom))


@dataclass(frozen=True)
class Scale:
    """Resolves size tokens for one canvas."""

    size_class: str
    factor: float

    @classmethod
    def for_canvas(cls, width: int, height: int) -> Scale:
        short = min(width, height)
        for limit, name, factor in _SIZE_CLASSES:
            if short <= limit:
                return cls(name, factor)
        raise AssertionError("unreachable")

    def text(self, token: str) -> int:
        return round(_TEXT_TOKENS[token] * self.factor)

    def space(self, token: str) -> int:
        return round(_SPACE_TOKENS[token] * self.factor)


def is_token(value: Any) -> bool:
    return isinstance(value, str) and value.strip() in _TEXT_TOKENS


def is_auto(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in ("", "auto"))


def resolve_length(value: Any, reference: int | None, scale: Scale, *, kind: str = "space") -> int | None:
    """Resolve a length to pixels.

    Args:
        value: Pixels (number or numeric string), ``"N%"`` of ``reference``, a size token, or ``"auto"``/``None``.
        reference: Pixel size that percentages refer to; ``None`` when unknown.
        scale: Token resolver for the canvas.
        kind: ``"space"`` or ``"text"``: which token table to use.

    Returns:
        Pixels, or ``None`` for auto (or a percentage without a known reference).
    """
    if is_auto(value):
        return None
    if is_token(value):
        token = value.strip()
        return scale.text(token) if kind == "text" else scale.space(token)
    if isinstance(value, str) and value.strip().endswith("%"):
        if reference is None:
            return None
        pct = coerce_number(value.strip()[:-1], float("nan"))
        if math.isnan(pct):
            raise LayoutError(f"Invalid percentage: {value!r}")
        return int(pct / 100 * reference)
    number = coerce_number(value, float("nan"))
    if math.isnan(number):
        raise LayoutError(f"Invalid length: {value!r}")
    return int(number)


def resolve_sides(value: Any, scale: Scale) -> tuple[int, int, int, int]:
    """Resolve ``padding``-style values: one value, ``[vertical, horizontal]`` or ``[top, right, bottom, left]``."""
    if value is None:
        return (0, 0, 0, 0)
    if isinstance(value, (list, tuple)):
        parts = [resolve_length(v, None, scale) or 0 for v in value]
        if len(parts) == 2:
            return (parts[0], parts[1], parts[0], parts[1])
        if len(parts) == 4:
            return (parts[0], parts[1], parts[2], parts[3])
        raise LayoutError(f"padding needs 1, 2 or 4 values, got {len(parts)}")
    px = resolve_length(value, None, scale) or 0
    return (px, px, px, px)


def coerce_bool(value: Any) -> bool:
    """Lenient bool (templates render ``"false"``)."""
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "", "0", "no", "off", "none")
    return bool(value)
