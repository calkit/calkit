"""Tests for ``calkit.kits.png``."""

import io

import pytest
from PIL import Image

from calkit.kits import png


def test_embed_extract():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
    original = buf.getvalue()
    assert png.extract(original) is None
    kit = b"PK\x03\x04 some kit bytes"
    data = png.embed(original, kit)
    assert data.endswith(original[-12:])
    # Image readers skip the chunk
    assert Image.open(io.BytesIO(data)).size == (4, 4)
    assert png.extract(data) == (kit, original)
    # A corrupt chunk is caught rather than read
    pos = data.index(png.CHUNK_TYPE) + len(png.CHUNK_TYPE)
    corrupt = data[:pos] + b"X" + data[pos + 1 :]
    with pytest.raises(ValueError, match="corrupt"):
        png.extract(corrupt)
    with pytest.raises(ValueError, match="Not a PNG"):
        png.embed(b"GIF89a", kit)
    with pytest.raises(ValueError, match="IEND"):
        png.embed(original[:-12], kit)
