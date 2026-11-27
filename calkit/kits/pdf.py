"""Kits in PDFs, as an attached file added in an incremental update."""

from __future__ import annotations

ATTACHMENT_NAME = "calkit-kit.zip"


def embed(data: bytes, kit: bytes) -> bytes:
    """Return a copy of a PDF with a kit attached.

    The attachment is appended as an incremental update, so viewers list it
    with the document's attachments, and truncating to the original size
    restores the original bytes exactly.
    """
    import io

    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    pdf = pdfium.PdfDocument(data)
    try:
        attachment = pdf.new_attachment(ATTACHMENT_NAME)
        attachment.set_data(kit)
        buf = io.BytesIO()
        pdf.save(buf, flags=pdfium_c.FPDF_INCREMENTAL)
    finally:
        pdf.close()
    out = buf.getvalue()
    if not out.startswith(data):
        raise ValueError("Attaching kit rewrote the PDF")
    return out


def extract(data: bytes) -> tuple[bytes, bytes] | None:
    """Get a PDF's kit and the PDF without it, or None if it has none.

    The PDF without its kit is the prefix with the size the kit's manifest
    records.
    """
    import io
    import json
    import zipfile

    import pypdfium2 as pdfium

    from calkit.kits.core import MANIFEST_NAME

    pdf = pdfium.PdfDocument(data)
    try:
        kit = None
        for i in range(pdf.count_attachments()):
            attachment = pdf.get_attachment(i)
            if attachment.get_name() == ATTACHMENT_NAME:
                kit = bytes(attachment.get_data())
                break
    finally:
        pdf.close()
    if kit is None:
        return None
    with zipfile.ZipFile(io.BytesIO(kit)) as z:
        size = json.loads(z.read(MANIFEST_NAME))["artifact"]["size"]
    return kit, data[:size]
