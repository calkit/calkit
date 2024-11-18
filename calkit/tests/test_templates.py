"""Tests for ``calkit.templates``."""

import calkit


def test_use_template(tmp_dir):
    calkit.templates.use_template("latex/article", "paper", title="Cool title")
    with open("paper/paper.tex") as f:
        txt = f.read()
    assert r"\title{Cool title}" in txt
