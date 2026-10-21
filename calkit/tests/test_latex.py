"""Tests for ``calkit.latex``."""

import gzip
import os
from pathlib import Path

import calkit.latex


def test_set_content_id(tmp_dir):
    import hashlib
    import re

    def pdf(section: bytes) -> bytes:
        # Just enough of a file for the trailer to be found, its
        # cross-reference section last and pointed to by startxref
        body = b"%PDF-1.5\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        return (
            body + section + b"startxref\n" + str(len(body)).encode() + b"\n"
            b"%%EOF\n"
        )

    table = (
        b"xref\n0 2\n0000000000 65535 f \n0000000009 00000 n \n"
        b"trailer\n<< /Size 2 /Root 1 0 R >>\n"
    )
    # A cross-reference stream whose data happens to hold '/ID'
    stream = (
        b"2 0 obj\n<< /Type /XRef /Size 3 /Length 4 >>\nstream\n/ID \n"
        b"endstream\nendobj\n"
    )
    for section in [table, stream]:
        data = pdf(section)
        Path("main.pdf").write_bytes(data)
        assert calkit.latex.set_content_id("main.pdf")
        out = Path("main.pdf").read_bytes()
        digest = hashlib.md5(data).hexdigest().upper()
        assert f"<< /ID [<{digest}> <{digest}>]".encode() in out
        # Inside the last section's dictionary, which every offset precedes
        m = re.search(rb"startxref\n(\d+)", out)
        assert m is not None
        assert out[int(m.group(1)) :].startswith(section[:6])
        assert out.index(b"/ID") > int(m.group(1))
        # An ID is left alone, so a second pass changes nothing
        assert not calkit.latex.set_content_id("main.pdf")
        assert Path("main.pdf").read_bytes() == out
    # A file that isn't a PDF is left alone
    Path("main.pdf").write_bytes(b"not a PDF")
    assert not calkit.latex.set_content_id("main.pdf")


def test_localize_synctex(tmp_dir):
    # Nothing to localize is not an error
    assert (
        calkit.latex.localize_synctex("paper/main.synctex.gz", "paper")
        is False
    )
    os.makedirs("paper")
    # Both exist, and the relative input is the paper's own
    for path in ("paper/main.tex", "paper/section.tex", "section.tex"):
        with open(path, "w") as f:
            f.write("\\documentclass{article}\n")
    with gzip.open("paper/main.synctex.gz", "wt") as f:
        f.write(
            "SyncTeX Version:1\n"
            "Input:1:/work/paper/./main.tex\n"
            "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls\n"
            "Input:3:./section.tex\n"
            "Content:\n"
        )
    assert (
        calkit.latex.localize_synctex("paper/main.synctex.gz", "paper") is True
    )
    with gzip.open("paper/main.synctex.gz", "rt") as f:
        text = f.read()
    here = Path(".").resolve()
    assert f"Input:1:{(here / 'paper/main.tex').as_posix()}" in text
    assert f"Input:3:{(here / 'paper/section.tex').as_posix()}" in text
    # A file the project doesn't have is left alone
    assert "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls" in text
    # Already local
    assert (
        calkit.latex.localize_synctex("paper/main.synctex.gz", "paper")
        is False
    )
