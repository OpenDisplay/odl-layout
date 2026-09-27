"""Generate README screenshots.

- Every ``### `name` `` section in README.md with a ```yaml payload is laid out and
  rendered to docs/screenshots/<name>.png (400x200, or the size given by a
  ``# canvas: WxH`` first line in the block).
- docs/examples/dashboard.yaml is rendered at each typical display size to
  docs/screenshots/dashboard_<W>x<H>.png.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import yaml
from odl_renderer import generate_image
from PIL import Image, ImageOps

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from odl_layout import layout  # noqa: E402

OUTPUT_DIR = ROOT / "docs" / "screenshots"
README_PATH = ROOT / "README.md"
DASHBOARD_PATH = ROOT / "docs" / "examples" / "dashboard.yaml"
DASHBOARD_SIZES = [(400, 300), (800, 480), (1972, 1404), (1200, 1600)]
DEFAULT_CANVAS = (400, 200)

SECTION_RE = re.compile(r"\n(?=### `[a-z_]+`)")
HEADING_RE = re.compile(r"^### `([a-z_]+)`$")
CODE_BLOCK_RE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
CANVAS_RE = re.compile(r"^# canvas: (\d+)x(\d+)")


def parse_examples(readme: str) -> dict[str, tuple[list[dict], tuple[int, int]]]:
    """Extract (payload, canvas size) keyed by section name."""
    examples = {}
    for section in SECTION_RE.split(readme):
        heading = HEADING_RE.match(section.split("\n")[0].strip())
        code = CODE_BLOCK_RE.search(section)
        if not heading or not code:
            continue
        block = code.group(1)
        canvas = CANVAS_RE.match(block)
        size = (int(canvas.group(1)), int(canvas.group(2))) if canvas else DEFAULT_CANVAS
        payload = yaml.safe_load(block)
        examples[heading.group(1)] = (payload if isinstance(payload, list) else [payload], size)
    return examples


async def render(payload: list[dict], size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = await generate_image(width=width, height=height, elements=layout(payload, width, height))
    return ImageOps.expand(image.convert("RGB"), border=1, fill="black")


async def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    examples = parse_examples(README_PATH.read_text())
    print(f"Found {len(examples)} README examples")

    failed = []
    for name, (payload, size) in examples.items():
        try:
            (await render(payload, size)).save(OUTPUT_DIR / f"{name}.png")
            print(f"  OK  {name}.png")
        except Exception as err:  # noqa: BLE001 - report every failure, then exit non-zero
            print(f"  FAIL {name}: {err}")
            failed.append(name)

    dashboard = yaml.safe_load(DASHBOARD_PATH.read_text())
    for width, height in DASHBOARD_SIZES:
        name = f"dashboard_{width}x{height}"
        (await render(dashboard, (width, height))).save(OUTPUT_DIR / f"{name}.png")
        print(f"  OK  {name}.png")

    if failed:
        print(f"\nFailed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
