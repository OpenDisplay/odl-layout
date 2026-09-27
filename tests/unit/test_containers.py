"""Container geometry, verified on fixed-size leaves (no font metrics)."""

import pytest

from odl_layout import LayoutError, layout
from tests.conftest import box, rect


def boxes(payload, width=200, height=100):
    return [box(e) for e in layout(payload, width, height)]


# -- column -------------------------------------------------------------------


def test_column_stacks_and_stretches():
    payload = [{"type": "column", "padding": 10, "gap": 5, "children": [rect(h=20), rect(h=30)]}]
    assert boxes(payload) == [(10, 10, 180, 20), (10, 35, 180, 30)]


def test_column_align_center_uses_child_width():
    payload = [{"type": "column", "align": "center", "children": [rect(w=50, h=10)]}]
    assert boxes(payload) == [(75, 0, 50, 10)]


def test_column_grow_fills_height():
    payload = [{"type": "column", "children": [rect(h=20), rect(grow=1), rect(h=10)]}]
    assert boxes(payload) == [(0, 0, 200, 20), (0, 20, 200, 70), (0, 90, 200, 10)]


# -- row ----------------------------------------------------------------------


def test_row_grow_takes_remaining_width_and_centers_vertically():
    payload = [{"type": "row", "gap": 10, "children": [rect(w=50, h=20), rect(grow=1, h=20), rect(w=30, h=20)]}]
    assert boxes(payload) == [(0, 40, 50, 20), (60, 40, 100, 20), (170, 40, 30, 20)]


def test_row_grow_weights():
    payload = [{"type": "row", "children": [rect(grow=1, h=10), rect(grow=3, h=10)]}]
    assert [b[2] for b in boxes(payload)] == [50, 150]


def test_row_percent_width():
    payload = [{"type": "row", "padding": [0, 20], "children": [rect(w="25%", h=10)]}]
    # 25% of the 160px content box
    assert boxes(payload)[0][2] == 40


@pytest.mark.parametrize(
    ("justify", "xs"),
    [("start", [0, 30]), ("center", [70, 100]), ("end", [140, 170]), ("space-between", [0, 170])],
)
def test_row_justify(justify, xs):
    payload = [{"type": "row", "justify": justify, "children": [rect(w=30, h=10), rect(w=30, h=10)]}]
    assert [b[0] for b in boxes(payload)] == xs


@pytest.mark.parametrize(("align", "y", "h"), [("start", 0, 10), ("end", 90, 10), ("stretch", 0, 100)])
def test_row_align(align, y, h):
    payload = [{"type": "row", "align": align, "children": [rect(w=30, h=10 if align != "stretch" else None)]}]
    b = boxes(payload)[0]
    assert (b[1], b[3]) == (y, h)


def test_align_self_overrides_parent():
    payload = [{"type": "row", "align": "start", "children": [rect(w=10, h=10), rect(w=10, h=10, align_self="end")]}]
    assert [b[1] for b in boxes(payload)] == [0, 90]


def test_nested_row_in_column():
    payload = [
        {
            "type": "column",
            "gap": 10,
            "children": [rect(h=20), {"type": "row", "gap": 10, "children": [rect(grow=1, h=30), rect(grow=1, h=30)]}],
        }
    ]
    assert boxes(payload) == [(0, 0, 200, 20), (0, 30, 95, 30), (105, 30, 95, 30)]


def test_spacer_pushes_to_end():
    payload = [{"type": "row", "align": "start", "children": [rect(w=10, h=10), {"type": "spacer"}, rect(w=10, h=10)]}]
    assert [b[0] for b in boxes(payload)] == [0, 190]


# -- stack --------------------------------------------------------------------


def test_stack_aligns_children():
    payload = [{"type": "stack", "align": "center", "valign": "center", "children": [rect(w=20, h=10)]}]
    assert boxes(payload) == [(90, 45, 20, 10)]


def test_stack_stretch_by_default():
    assert boxes([{"type": "stack", "children": [rect()]}]) == [(0, 0, 200, 100)]


def test_stack_absolute_child_uses_local_coordinates():
    payload = [
        {
            "type": "stack",
            "x": 20,
            "y": 10,
            "w": 100,
            "h": 50,
            "children": [rect(w=10, h=10, position="absolute", x="50%", y=5)],
        }
    ]
    assert boxes(payload) == [(70, 15, 10, 10)]


# -- grid ---------------------------------------------------------------------


def test_grid_cells_fill_rows():
    payload = [{"type": "grid", "cols": 2, "gap": 10, "children": [rect(h=10) for _ in range(4)]}]
    # 2 rows of content height 10 share the spare 70px -> 45px each
    assert boxes(payload, 210, 100) == [(0, 0, 100, 45), (110, 0, 100, 45), (0, 55, 100, 45), (110, 55, 100, 45)]


def test_grid_span():
    payload = [{"type": "grid", "cols": 2, "gap": 10, "children": [rect(h=10, span=2), rect(h=10), rect(h=10)]}]
    result = boxes(payload, 210, 100)
    assert result[0][2] == 210
    assert result[1][:1] + result[2][:1] == (0, 110)


# -- list ---------------------------------------------------------------------


def test_list_hides_items_that_do_not_fit():
    payload = [{"type": "list", "gap": 5, "items": [rect(h=30) for _ in range(10)]}]
    assert [b[1] for b in boxes(payload)] == [0, 35, 70]


def test_list_best_fit_columns():
    payload = [{"type": "list", "gap": 5, "max_cols": 2, "items": [rect(h=30) for _ in range(10)]}]
    result = boxes(payload, 205, 100)
    assert len(result) == 6  # 3 per column (0, 35, 70)
    assert {b[0] for b in result} == {0, 105}


def test_list_prefers_fewer_columns_on_tie():
    payload = [{"type": "list", "max_cols": 3, "items": [rect(h=10) for _ in range(3)]}]
    assert {b[0] for b in boxes(payload)} == {0}


def test_list_overflow_counter():
    payload = [{"type": "list", "gap": 5, "overflow_counter": True, "items": [rect(h=30) for _ in range(10)]}]
    result = layout(payload, 200, 100)
    counter = result[-1]
    assert counter["type"] == "text"
    rects = result[:-1]
    assert counter["value"] == f"+{10 - len(rects)} more"
    # Counter sits below the last visible item and inside the list
    assert counter["y"] > rects[-1]["y_end"]
    assert len(rects) == 2


# -- containers in general ----------------------------------------------------


def test_background_and_border_painted_first():
    payload = [{"type": "column", "background": "red", "border": "black", "radius": 4, "children": [rect(h=10)]}]
    first, child = layout(payload, 200, 100)
    assert first["type"] == "rectangle"
    assert (first["fill"], first["outline"], first["radius"]) == ("red", "black", 4)
    assert box(first) == (0, 0, 200, 100)
    assert box(child) == (0, 0, 200, 10)


def test_size_tokens_scale_with_canvas():
    payload = [{"type": "column", "padding": "md", "children": [rect(h=10)]}]
    assert box(layout(payload, 800, 480)[0])[0] == 8
    assert box(layout(payload, 1972, 1404)[0])[0] == 16
    assert box(layout(payload, 400, 300)[0])[0] == 6


def test_hidden_children_take_no_space():
    payload = [{"type": "column", "gap": 10, "children": [rect(h=10), rect(h=10, visible="false"), rect(h=10)]}]
    assert [b[1] for b in boxes(payload)] == [0, 20]


def test_layout_keys_are_stripped():
    [emitted] = layout([{"type": "row", "children": [rect(w=10, h=10, grow=0, align_self="start")]}], 100, 100)
    assert not {"w", "h", "grow", "align_self"} & emitted.keys()


def test_invalid_canvas():
    with pytest.raises(LayoutError):
        layout([], 0, 100)


def test_unsupported_leaf_in_container():
    with pytest.raises(LayoutError, match="diagram"):
        layout([{"type": "column", "children": [{"type": "diagram", "x": 0, "height": 10}]}], 100, 100)


def test_children_must_be_objects():
    with pytest.raises(LayoutError):
        layout([{"type": "column", "children": ["nope"]}], 100, 100)


def test_unknown_justify():
    with pytest.raises(LayoutError):
        layout([{"type": "row", "justify": "around", "children": [rect(w=1, h=1)]}], 100, 100)
