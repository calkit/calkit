"""Kits in HTML documents, as a base64 script element before ``</body>``."""

from __future__ import annotations

import base64
import re

OPEN_TAG = (
    b'<script type="application/vnd.calkit.kit+zip;base64" id="calkit-kit">'
)
CLOSE_TAG = b"</script>"
BLOCK_RE = re.compile(
    re.escape(OPEN_TAG) + rb"(.*?)" + re.escape(CLOSE_TAG), re.S
)


def embed(data: bytes, kit: bytes) -> bytes:
    """Return a copy of an HTML document with a kit inserted before
    ``</body>``, or at the end if it has none.
    """
    block = OPEN_TAG + b"\n" + base64.encodebytes(kit) + CLOSE_TAG
    pos = data.lower().rfind(b"</body>")
    if pos < 0:
        pos = len(data)
    return data[:pos] + block + data[pos:]


def extract(data: bytes) -> tuple[bytes, bytes] | None:
    """Get an HTML document's kit and the document without it, or None."""
    match = BLOCK_RE.search(data)
    if match is None:
        return None
    kit = base64.b64decode(match.group(1))
    return kit, data[: match.start()] + data[match.end() :]
