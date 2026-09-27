"""Mixing plain ODL elements with layout containers in one payload."""

import logging

from odl_layout import layout
from tests.conftest import box, rect


def test_plain_payload_passes_through_unchanged():
    payload = [
        {"type": "text", "value": "Hi", "x": 5, "y": 5},
        {"type": "diagram", "x": 0, "height": 50},
        {"type": "rectangle", "x_start": 0, "y_start": 0, "x_end": 10, "y_end": 10},
    ]
    assert layout(payload, 200, 100) == payload


def test_containers_expand_in_place():
    header = {"type": "rectangle", "x_start": 0, "y_start": 0, "x_end": 199, "y_end": 19}
    footer = {"type": "text", "value": "x", "x": 0, "y": 90}
    payload = [header, {"type": "column", "y": 20, "children": [rect(h=10), rect(h=10)]}, footer]
    result = layout(payload, 200, 100)
    assert result[0] is header
    assert result[-1] is footer
    assert [box(e)[1] for e in result[1:3]] == [20, 30]


def test_top_level_region_with_insets():
    payload = [{"type": "column", "x": "10%", "y": 20, "right": 20, "bottom": 10, "children": [rect(grow=1)]}]
    assert box(layout(payload, 200, 100)[0]) == (20, 20, 160, 70)


def test_top_level_auto_height_and_flow_continuation():
    payload = [
        {"type": "column", "h": "auto", "children": [rect(h=20)]},
        {"type": "text", "value": "below", "x": 0},
        {"type": "text", "value": "renderer flows this one", "x": 0},
    ]
    _, first, second = layout(payload, 200, 100)
    assert first["y"] == 20 + 10  # container bottom + default text y_padding
    assert "y" not in second  # later elements keep the renderer's own pos_y flow


def test_flow_continuation_respects_explicit_position():
    payload = [{"type": "column", "h": "auto", "children": [rect(h=20)]}, {"type": "line", "x_start": 0, "x_end": 9}]
    assert layout(payload, 200, 100)[1]["y_start"] == 20


def test_hidden_top_level_container_is_dropped():
    assert layout([{"type": "column", "visible": False, "children": [rect(h=10)]}], 200, 100) == []


def test_geometry_inside_container_is_overwritten_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        [emitted] = layout([{"type": "column", "children": [rect(h=10, x_start=99, y_start=99)]}], 200, 100)
    assert box(emitted) == (0, 0, 200, 10)
    assert "ignored inside a layout container" in caplog.text
