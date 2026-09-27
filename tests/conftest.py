"""Shared fixtures and helpers."""

from __future__ import annotations

from typing import Any


def rect(w: Any = None, h: Any = None, **extra: Any) -> dict[str, Any]:
    """Fixed-size rectangle leaf (no font metrics involved)."""
    element: dict[str, Any] = {"type": "rectangle", "fill": "black", **extra}
    if w is not None:
        element["w"] = w
    if h is not None:
        element["h"] = h
    return element


def box(element: dict[str, Any]) -> tuple[int, int, int, int]:
    """(x, y, w, h) of an emitted rectangle-like element."""
    return (
        element["x_start"],
        element["y_start"],
        element["x_end"] - element["x_start"] + 1,
        element["y_end"] - element["y_start"] + 1,
    )
