"""Tests for ``calkit.latex``."""

import gzip
import os
from pathlib import Path

import calkit.latex


def test_localize_synctex(tmp_dir):
    # Nothing to localize is not an error
    assert calkit.latex.localize_synctex("paper/main.pdf") is False
    os.makedirs("paper")
    with open("paper/main.tex", "w") as f:
        f.write("\\documentclass{article}\n")
    with gzip.open("paper/main.synctex.gz", "wt") as f:
        f.write(
            "SyncTeX Version:1\n"
            "Input:1:/work/paper/./main.tex\n"
            "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls\n"
            "Content:\n"
        )
    assert calkit.latex.localize_synctex("paper/main.pdf") is True
    with gzip.open("paper/main.synctex.gz", "rt") as f:
        text = f.read()
    here = (Path(".").resolve() / "paper/main.tex").as_posix()
    assert f"Input:1:{here}" in text
    # A file the project doesn't have is left alone
    assert "Input:2:/usr/local/texlive/2025/tex/latex/base/article.cls" in text
    # Already local
    assert calkit.latex.localize_synctex("paper/main.pdf") is False
