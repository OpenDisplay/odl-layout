"""Leaf adapters: intrinsic sizes and emitted geometry."""

import pytest
from odl_renderer import FontManager, measure_text

from odl_layout import layout

LONG = "The quick brown fox jumps over the lazy dog and keeps running"


def ppb(size):
    return FontManager().get_font("ppb.ttf", size)


def only(payload, width=800, height=480):
    [element] = layout(payload, width, height)
    return element


def test_text_is_top_left_anchored_with_resolved_size():
    text = only([{"type": "column", "padding": 10, "children": [{"type": "text", "value": "Hi", "size": "xl"}]}])
    assert (text["x"], text["y"], text["anchor"], text["size"]) == (10, 10, "la", 40)


def test_text_wraps_to_container_width():
    text = only([{"type": "column", "w": 150, "children": [{"type": "text", "value": LONG, "size": 20}]}])
    assert "\n" in text["value"]
    assert "max_width" not in text
    assert all(ppb(20).getlength(line) <= 150 for line in text["value"].split("\n"))


def test_text_clamp():
    text = only([{"type": "column", "w": 150, "children": [{"type": "text", "value": LONG, "size": 20, "clamp": 2}]}])
    lines = text["value"].split("\n")
    assert len(lines) == 2
    assert lines[-1].endswith("...")
    assert "clamp" not in text


def test_text_truncate():
    child = {"type": "text", "value": LONG, "size": 20, "truncate": True}
    text = only([{"type": "column", "w": 150, "children": [child]}])
    assert "\n" not in text["value"]
    assert text["value"].endswith("...")


def test_text_align_center_within_stretched_box():
    text = only([{"type": "column", "children": [{"type": "text", "value": "Hi", "size": 20, "align": "center"}]}])
    width = measure_text("Hi", ppb(20)).width
    assert text["x"] == (800 - width) // 2


def test_text_height_drives_column_layout():
    payload = [
        {
            "type": "column",
            "children": [{"type": "text", "value": "Hi", "size": 20}, {"type": "text", "value": "There", "size": 20}],
        }
    ]
    first, second = layout(payload, 800, 480)
    assert second["y"] - first["y"] == measure_text("Hi", ppb(20)).height


def test_icon_centered_in_box():
    icon = only([{"type": "row", "align": "start", "children": [{"type": "icon", "value": "home", "size": 32}]}])
    assert (icon["x"], icon["y"], icon["anchor"], icon["size"]) == (16, 16, "mm", 32)


def test_icon_sequence_intrinsic_width():
    payload = [
        {
            "type": "row",
            "align": "start",
            "children": [
                {"type": "icon_sequence", "icons": ["a", "b", "c"], "size": 20, "spacing": 5},
                {"type": "rectangle", "w": 10, "h": 10},
            ],
        }
    ]
    _, marker = layout(payload, 800, 480)
    assert marker["x_start"] == 3 * 20 + 2 * 5


def test_qrcode_centered_in_stretched_box():
    qr = only([{"type": "column", "w": 200, "children": [{"type": "qrcode", "data": "hello", "boxsize": 2}]}])
    assert qr["y"] == 0
    assert 0 < qr["x"] < 100


def test_dlimg_gets_box_size():
    img = only([{"type": "column", "children": [{"type": "dlimg", "url": "x.png", "h": 100}]}], 300, 200)
    assert (img["x"], img["y"], img["xsize"], img["ysize"]) == (0, 0, 300, 100)


def test_vertical_line_divider_in_row():
    payload = [
        {
            "type": "row",
            "align": "stretch",
            "children": [{"type": "rectangle", "grow": 1}, {"type": "line", "vertical": True, "width": 2}],
        }
    ]
    _, line = layout(payload, 200, 100)
    assert line["x_start"] == line["x_end"] == 199
    assert (line["y_start"], line["y_end"]) == (0, 99)
    assert "vertical" not in line


def test_circle_fits_box():
    circle = only([{"type": "row", "children": [{"type": "circle", "radius": 10}]}], 200, 100)
    assert (circle["x"], circle["y"], circle["radius"]) == (10, 50, 10)


def test_polygon_points_are_box_local():
    payload = [
        {"type": "column", "padding": 10, "children": [{"type": "polygon", "points": [[0, 0], ["100%", 0], [0, 9]]}]}
    ]
    polygon = only(payload, 200, 100)
    assert polygon["points"] == [(10, 10), (190, 10), (10, 19)]


@pytest.mark.parametrize("element_type", ["progress_bar", "plot", "ellipse"])
def test_span_elements_fill_box(element_type):
    element = only([{"type": "column", "padding": 5, "children": [{"type": element_type, "h": 20}]}], 200, 100)
    assert (element["x_start"], element["y_start"], element["x_end"], element["y_end"]) == (5, 5, 194, 24)
