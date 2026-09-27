"""ODL Layout.

Layout compiler for the OpenDisplay Language: containers in, positioned ODL elements out.
"""

from __future__ import annotations

from typing import Any

from .engine import CONTAINERS, Engine
from .errors import LayoutError
from .units import Scale

__version__ = "0.1.0"

__all__ = ["CONTAINERS", "LayoutError", "Scale", "layout"]


def layout(
    payload: list[dict[str, Any]],
    width: int,
    height: int,
    font_dirs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Expand layout containers in an ODL payload into positioned ODL elements.

    Plain ODL elements pass through unchanged (canvas-absolute). Containers
    (``row``, ``column``, ``stack``, ``grid``, ``list``) are replaced in place by
    the elements they lay out, so payload order stays paint order.

    The function is synchronous but loads font files; async callers should run
    it in an executor.

    Args:
        payload: ODL element list, optionally containing layout containers.
        width: Canvas width in pixels (after rotation).
        height: Canvas height in pixels (after rotation).
        font_dirs: Extra font directories, as passed to ``generate_image``.

    Returns:
        A flat ODL element list for ``odl_renderer.generate_image``.

    Raises:
        LayoutError: If the layout configuration is invalid.
    """
    return Engine(width, height, font_dirs).run(payload)
