"""Tests for ``calkit.kits.svg``."""

import xml.etree.ElementTree as ET

import pytest

from calkit.kits import svg


def test_embed_extract():
    kit = b"PK kit bytes"
    original = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>\n'
    assert svg.extract(original) is None
    data = svg.embed(original, kit)
    # Still well-formed, with the kit in a metadata element
    root = ET.fromstring(data)
    assert root.find("{http://www.w3.org/2000/svg}metadata") is not None
    assert svg.extract(data) == (kit, original)
    with pytest.raises(ValueError, match="</svg>"):
        svg.embed(b"<svg>", kit)
