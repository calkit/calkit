"""Kits in SVG images, as base64 in a ``<metadata>`` element."""

from __future__ import annotations

import base64
import re

OPEN_TAG = (
    b'<metadata id="calkit-kit">'
    b'<kit xmlns="https://docs.calkit.org/kits" version="1" '
    b'encoding="base64">'
)
CLOSE_TAG = b"</kit></metadata>"
BLOCK_RE = re.compile(
    re.escape(OPEN_TAG) + rb"(.*?)" + re.escape(CLOSE_TAG), re.S
)


def embed(data: bytes, kit: bytes) -> bytes:
    """Return a copy of an SVG with a kit inserted before its last
    ``</svg>``.
    """
    pos = data.rfind(b"</svg>")
    if pos < 0:
        raise ValueError("SVG has no closing </svg> tag")
    block = OPEN_TAG + b"\n" + base64.encodebytes(kit) + CLOSE_TAG
    return data[:pos] + block + data[pos:]


def extract(data: bytes) -> tuple[bytes, bytes] | None:
    """Get an SVG's kit and the SVG without it, or None if it has none."""
    match = BLOCK_RE.search(data)
    if match is None:
        return None
    kit = base64.b64decode(match.group(1))
    return kit, data[: match.start()] + data[match.end() :]
