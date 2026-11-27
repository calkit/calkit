"""Tests for ``calkit.kits.pdf``."""

import io
import json

import pypdfium2 as pdfium

from calkit.kits import pdf
from calkit.kits.core import MANIFEST_NAME, write_zip


def test_embed_extract():
    doc = pdfium.PdfDocument.new()
    doc.new_page(100, 100)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    original = buf.getvalue()
    assert pdf.extract(original) is None
    manifest = {"artifact": {"size": len(original)}}
    kit = write_zip({MANIFEST_NAME: (json.dumps(manifest).encode(), False)})
    data = pdf.embed(original, kit)
    # Appended, so the original is a prefix and the attachment is listed
    assert data.startswith(original)
    doc = pdfium.PdfDocument(data)
    assert len(doc) == 1
    assert doc.get_attachment(0).get_name() == pdf.ATTACHMENT_NAME
    doc.close()
    assert pdf.extract(data) == (kit, original)
