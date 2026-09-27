"""Property-based invariants over random container trees."""

from hypothesis import given, settings
from hypothesis import strategies as st

from odl_layout import layout
from tests.conftest import box

leaf = st.builds(lambda g: {"type": "rectangle", "fill": "black", "grow": g}, st.integers(min_value=1, max_value=3))


def container(children):
    return st.builds(
        lambda kind, gap, padding, kids: {
            "type": kind,
            "gap": gap,
            "padding": padding,
            "align": "stretch",
            "children": kids,
        },
        st.sampled_from(["row", "column", "stack"]),
        st.integers(min_value=0, max_value=5),
        st.integers(min_value=0, max_value=5),
        st.lists(children, min_size=1, max_size=4),
    )


trees = st.recursive(leaf, container, max_leaves=12).filter(lambda t: t["type"] != "rectangle")


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _stack_free(tree):
    if tree["type"] == "stack":
        return False
    return all(_stack_free(c) for c in tree.get("children", []) if c["type"] != "rectangle")


@settings(max_examples=200, deadline=None)
@given(trees)
def test_leaves_stay_inside_canvas(tree):
    for element in layout([tree], 400, 300):
        x, y, w, h = box(element)
        assert x >= 0 and y >= 0
        assert x + w <= 400 and y + h <= 300


@settings(max_examples=200, deadline=None)
@given(trees.filter(_stack_free))
def test_leaves_do_not_overlap_without_stacks(tree):
    rects = [b for b in (box(e) for e in layout([tree], 400, 300)) if b[2] > 0 and b[3] > 0]
    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            assert not _overlap(a, b)
