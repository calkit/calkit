"""Prepare Chrome Web Store screenshots from the ones in the docs.

The store takes 1280x800 (or 640x400) images with no alpha channel, and a
screenshot is whatever shape the window was. Every one of ours is taller
than 1280x800, so they're scaled to fit and centered rather than cropped:
the panel sits in the bottom right, which is exactly what cropping to the
right aspect ratio would cut off.

Padding is filled with the colour around the edge of the screenshot, so a
page with a dark background doesn't end up in a white box.

    uv run python browser-ext/scripts/store-screenshots.py
"""

from __future__ import annotations

import pathlib
import statistics

from PIL import Image

SIZE = (1280, 800)
SOURCE = pathlib.Path("docs/img/browser-ext")
DEST = pathlib.Path("browser-ext/store/screenshots")


def edge_color(image: Image.Image) -> tuple[int, int, int]:
    """The colour around the border, so padding reads as more of the page."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    step = max(1, min(width, height) // 100)
    pixels = (
        [rgb.getpixel((x, 0)) for x in range(0, width, step)]
        + [rgb.getpixel((x, height - 1)) for x in range(0, width, step)]
        + [rgb.getpixel((0, y)) for y in range(0, height, step)]
        + [rgb.getpixel((width - 1, y)) for y in range(0, height, step)]
    )
    return tuple(  # type: ignore[return-value]
        int(statistics.median(channel)) for channel in zip(*pixels)
    )


def main() -> None:
    sources = sorted(SOURCE.glob("*.png"))
    if not sources:
        raise SystemExit(f"No screenshots found in {SOURCE}")
    DEST.mkdir(parents=True, exist_ok=True)
    for path in sources:
        image = Image.open(path)
        background = edge_color(image)
        # Flattened onto the background rather than kept as RGBA: the
        # store wants 24-bit PNGs, and transparency has nothing to mean
        # in a screenshot anyway
        flattened = Image.new("RGB", image.size, background)
        flattened.paste(
            image, mask=image.getchannel("A") if image.mode == "RGBA" else None
        )
        scale = min(SIZE[0] / image.width, SIZE[1] / image.height)
        scaled = flattened.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.LANCZOS,
        )
        canvas = Image.new("RGB", SIZE, background)
        canvas.paste(
            scaled,
            ((SIZE[0] - scaled.width) // 2, (SIZE[1] - scaled.height) // 2),
        )
        out = DEST / path.name
        canvas.save(out, optimize=True)
        print(
            f"{path.name}: {image.width}x{image.height} -> "
            f"{scaled.width}x{scaled.height} on {SIZE[0]}x{SIZE[1]}"
        )


if __name__ == "__main__":
    main()
