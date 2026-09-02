"""Small previews of images and PDFs.

The figures page is a grid of thumbnails a couple of hundred pixels tall, but
a figure is whatever the pipeline produced: a 400 kB plot, or a PDF page. Sent
whole, twenty of them are megabytes of base64 to draw twenty postage stamps.

A thumbnail is a pure function of the bytes it came from, so it is cached by
their hash and computed once per distinct figure across every worker and every
viewer. See ``app.cache``.

Keying on content rather than on a project and revision means an entry is
never wrong, but also that nothing knows to delete it when the figure it came
from stops existing. That is left to the cache's own eviction
(``maxmemory-policy allkeys-lru``): a thumbnail nobody has asked for in a long
time is exactly what should go first. If that stops being enough, the way out
is a second key per project revision listing what it produced.
"""

import base64
import hashlib
import io
import threading

from app import cache
from app.core import logger

# Wide enough to stay sharp on a high-density display at the size the grid
# draws them, small enough that a page of them is tens of kilobytes.
THUMBNAIL_MAX_PX = 320
# WebP at this quality is visually clean for plots and line art and roughly a
# third the size of the equivalent PNG.
_WEBP_QUALITY = 82
THUMBNAIL_MEDIA_TYPE = "image/webp"

# What we can rasterize. SVG is left alone: it is vector, usually smaller than
# the thumbnail would be, and scales by itself.
_RASTER_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"}
_PDF_EXTS = {"pdf"}

# pdfium is not safe to call from several threads at once, and the figures a
# page shows are resolved concurrently. Sharing one lock across the process
# costs little -- a rendered page is cached, so each distinct PDF is rasterized
# once -- and without it the worker segfaults rather than raising.
_PDF_LOCK = threading.Lock()


def can_thumbnail(path: str) -> bool:
    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    return ext in _RASTER_EXTS or ext in _PDF_EXTS


def _render_pdf_first_page(data: bytes, max_px: int) -> bytes | None:
    """The first page of a PDF, rasterized to fit ``max_px``."""
    import pypdfium2

    with _PDF_LOCK:
        return _render_pdf_locked(pypdfium2, data, max_px)


def _render_pdf_locked(pypdfium2, data: bytes, max_px: int) -> bytes | None:
    pdf = pypdfium2.PdfDocument(data)
    try:
        if len(pdf) == 0:
            return None
        page = pdf[0]
        width, height = page.get_size()
        longest = max(width, height)
        if longest <= 0:
            return None
        # `scale` is in units of 72 dpi, so this lands the longest side on
        # max_px rather than rendering the page at full size and shrinking.
        bitmap = page.render(scale=max_px / longest)
        try:
            image = bitmap.to_pil()
            buf = io.BytesIO()
            image.convert("RGB").save(
                buf, format="WEBP", quality=_WEBP_QUALITY, method=4
            )
            return buf.getvalue()
        finally:
            bitmap.close()
    finally:
        pdf.close()


def _render_raster(data: bytes, max_px: int) -> bytes | None:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((max_px, max_px))
        # A plot saved with transparency goes on white rather than on
        # whatever the page behind it happens to be.
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            converted = image.convert("RGBA")
            background.paste(converted, mask=converted.split()[-1])
            image = background
        else:
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="WEBP", quality=_WEBP_QUALITY, method=4)
        return buf.getvalue()


def get_thumbnail_b64(
    data: bytes, path: str, max_px: int = THUMBNAIL_MAX_PX
) -> str | None:
    """A base64 WebP thumbnail of ``data``, or None if it can't be made.

    Never raises: a figure that won't rasterize (a corrupt file, a PDF with
    no pages, a format Pillow was built without) falls back to whatever the
    caller was doing before, which is showing the file itself.
    """
    if not can_thumbnail(path):
        return None
    key = cache.make_key(
        "thumb", hashlib.sha256(data).hexdigest(), str(max_px)
    )
    cached = cache.get_json(key)
    if isinstance(cached, str):
        return cached
    ext = path.lower().rsplit(".", 1)[-1]
    try:
        if ext in _PDF_EXTS:
            rendered = _render_pdf_first_page(data, max_px)
        else:
            rendered = _render_raster(data, max_px)
    except Exception as e:
        logger.warning(f"Could not make a thumbnail for {path}: {e}")
        return None
    if not rendered:
        return None
    # Only worth sending if it actually saved something; a small figure is
    # already its own best thumbnail.
    if len(rendered) >= len(data):
        return None
    encoded = base64.b64encode(rendered).decode()
    cache.set_json(key, encoded)
    return encoded
