"""End-to-end: layout() output rendered by odl_renderer.generate_image()."""

import pytest
from odl_renderer import generate_image
from PIL import Image, ImageChops

from odl_layout import layout

SIZES = [(400, 300), (800, 480), (1972, 1404), (1200, 1600)]


def dashboard():
    events = [{"type": "text", "value": f"Event {i}: something happens", "size": "sm"} for i in range(40)]
    return [
        {"type": "rectangle", "x_start": 0, "y_start": 0, "x_end": "100%", "y_end": "10%", "fill": "black"},
        {
            "type": "column",
            "y": "10%",
            "padding": "md",
            "gap": "md",
            "children": [
                {
                    "type": "row",
                    "gap": "md",
                    "children": [
                        {"type": "icon", "value": "weather-rainy", "size": "xxl"},
                        {"type": "text", "value": "21.5°", "size": "xxl", "grow": 1},
                        {"type": "progress_bar", "progress": 60, "w": "30%", "h": "md", "fill": "red"},
                    ],
                },
                {"type": "line", "width": 2},
                {
                    "type": "grid",
                    "cols": 2,
                    "gap": "md",
                    "children": [
                        {"type": "text", "value": "Humidity 45%", "size": "md"},
                        {"type": "text", "value": "Wind 12 km/h", "size": "md"},
                    ],
                },
                {"type": "list", "grow": 1, "max_cols": 3, "gap": "xs", "overflow_counter": True, "items": events},
            ],
        },
    ]


def _ink_box(img):
    return ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, "white")).getbbox()


@pytest.mark.parametrize(("width", "height"), SIZES)
async def test_dashboard_renders_at_typical_sizes(width, height):
    elements = layout(dashboard(), width, height)
    img = await generate_image(width=width, height=height, elements=elements, background="white")
    assert img.size == (width, height)
    assert _ink_box(img) is not None
    texts = [e for e in elements if e["type"] == "text"]
    # The list never spills past the canvas and accounts for every event: shown + "+N more" == 40
    assert all(e["y"] < height for e in texts)
    shown = sum(str(e["value"]).startswith("Event") for e in texts)
    counters = [int(str(e["value"]).split()[0][1:]) for e in texts if str(e["value"]).endswith("more")]
    assert shown + sum(counters) == 40


async def test_rendered_text_stays_in_its_box():
    """A text leaf measured by layout must not ink past the next sibling's top edge."""
    payload = [
        {
            "type": "column",
            "children": [
                {"type": "text", "value": "Typography gjpq", "size": 40},
                {"type": "rectangle", "h": 1, "fill": "white"},
            ],
        }
    ]
    text, marker = layout(payload, 400, 200)
    img = await generate_image(width=400, height=200, elements=[text], background="white")
    assert _ink_box(img)[3] <= marker["y_start"]
