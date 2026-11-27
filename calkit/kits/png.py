"""Kits in PNG images, in a private chunk just before the image's end."""

from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Ancillary, private, and unsafe to copy, so an editor that changes the image
# drops the kit rather than carrying a claim that no longer holds
CHUNK_TYPE = b"caLK"


def get_chunk_spans(data: bytes) -> list[tuple[int, int, bytes]]:
    """Get the start, end, and type of each chunk, up to and including IEND."""
    if not data.startswith(SIGNATURE):
        raise ValueError("Not a PNG")
    spans = []
    pos = len(SIGNATURE)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunk_type = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("PNG is truncated")
        spans.append((pos, end, chunk_type))
        pos = end
        if chunk_type == b"IEND":
            break
    return spans


def embed(data: bytes, kit: bytes) -> bytes:
    """Return a copy of a PNG with a kit chunk inserted before IEND.

    Removing the chunk restores the original bytes exactly.
    """
    iend_start = next(
        (s for s, _, t in get_chunk_spans(data) if t == b"IEND"), None
    )
    if iend_start is None:
        raise ValueError("PNG has no IEND chunk")
    chunk = (
        struct.pack(">I", len(kit))
        + CHUNK_TYPE
        + kit
        + struct.pack(">I", zlib.crc32(CHUNK_TYPE + kit))
    )
    return data[:iend_start] + chunk + data[iend_start:]


def extract(data: bytes) -> tuple[bytes, bytes] | None:
    """Get a PNG's kit and the PNG without it, or None if it has none."""
    for start, end, chunk_type in get_chunk_spans(data):
        if chunk_type != CHUNK_TYPE:
            continue
        kit = data[start + 8 : end - 4]
        (crc,) = struct.unpack(">I", data[end - 4 : end])
        if crc != zlib.crc32(CHUNK_TYPE + kit):
            raise ValueError("PNG's kit chunk is corrupt")
        return kit, data[:start] + data[end:]
    return None
