"""Tests for ``calkit.kits.html``."""

import base64

from calkit.kits import html


def test_embed_extract():
    kit = bytes(range(256)) * 4
    original = b"<!DOCTYPE html><html><body><p>Hi</p></BODY></html>\n"
    assert html.extract(original) is None
    data = html.embed(original, kit)
    # Before the closing body tag, in any case, as wrapped base64
    assert data.index(html.OPEN_TAG) < data.index(b"</BODY>")
    assert base64.encodebytes(kit).splitlines()[0] in data
    assert html.extract(data) == (kit, original)
    # A fragment with no body gets it at the end
    data = html.embed(b"<p>Hi</p>", kit)
    assert data.startswith(b"<p>Hi</p>" + html.OPEN_TAG)
    assert html.extract(data) == (kit, b"<p>Hi</p>")
