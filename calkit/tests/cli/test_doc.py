"""Tests for ``calkit.cli.doc``."""

import dataclasses
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

import calkit

TEST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test")


def test_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from calkit.cli import export as cli_export
    from calkit.cli import latex as cli_latex
    from calkit.cli.main.core import app

    monkeypatch.chdir(tmp_path)
    calkit.save_calkit_info({"name": "test"})
    Path("paper.tex").write_text("\\documentclass{article}\n")
    Path("report.qmd").write_text("Hi\n")
    Path("nb.ipynb").write_text("{}\n")
    os.makedirs("book")
    Path("book/_quarto.yml").write_text("project: {type: book}\n")
    shutil.copy(os.path.join(TEST_DIR, "slides.pptx"), "deck.pptx")
    Path("letter.docx").write_bytes(b"")
    # Each tool's command records what it was asked to do rather than run
    # the tool
    calls: list[tuple] = []
    monkeypatch.setattr(cli_latex, "_tex_cmd", lambda cmd, **kwargs: cmd)
    monkeypatch.setattr(cli_latex, "_get_texlive_env", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_latex,
        "_run_latexmk",
        lambda cmd, **kwargs: calls.append(("latexmk", cmd)),
    )
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda cmd, **kwargs: calls.append(("quarto", cmd[1:])),
    )
    monkeypatch.setattr(
        "docx2pdf.convert",
        lambda **kwargs: calls.append(("word", kwargs)),
    )
    monkeypatch.setattr(
        cli_export,
        "export_slides",
        lambda source, outputs, **kwargs: calls.append(
            ("pptx", source, outputs, kwargs)
        ),
    )
    quarto = ["-e", "_system", "--allow-machine-quarto", "--to", "pdf"]
    # Each type is built by its tool's command, with what's after the path
    # passed through, the same as the command itself, under either name
    for new_args, old_args, expected in [
        (
            ["doc", "build", "paper.tex", "-f", "--latexmk-arg=-gg"],
            ["latex", "build", "paper.tex", "-f", "--latexmk-arg=-gg"],
            ("latexmk", ["-gg", "paper.tex"]),
        ),
        (
            ["document", "build", "report.qmd", *quarto, "--", "--execute"],
            ["quarto", "render", "report.qmd", *quarto, "--", "--execute"],
            ("quarto", ["render", "report.qmd", "--to", "pdf", "--execute"]),
        ),
        (
            ["doc", "build", "nb.ipynb", *quarto],
            ["quarto", "render", "nb.ipynb", *quarto],
            ("quarto", ["render", "nb.ipynb", "--to", "pdf"]),
        ),
        (
            ["doc", "build", "letter.docx", "-o", "out/letter.pdf"],
            ["office", "word-to-pdf", "letter.docx", "-o", "out/letter.pdf"],
            ("word", "out/letter.pdf"),
        ),
        # A deck is built to a PDF beside it, unless told otherwise
        (
            ["doc", "build", "deck.pptx"],
            ["export", "pptx", "deck.pptx", "-o", "deck.pdf"],
            ("pptx", [(None, "deck.pdf")]),
        ),
        (
            ["doc", "build", "deck.pptx", "-o", "2=fig.png", "--dpi", "72"],
            ["export", "pptx", "deck.pptx", "-o", "2=fig.png", "--dpi", "72"],
            ("pptx", [([2], "fig.png")]),
        ),
    ]:
        results = []
        for args in [new_args, old_args]:
            calls.clear()
            result = CliRunner().invoke(app, args)
            assert result.exit_code == 0, (args, result.output)
            results.append(list(calls))
        assert results[0] == results[1], new_args
        kind, *call = results[0][0]
        assert kind == expected[0], new_args
        if kind == "latexmk":
            assert "-f" in call[0]
            assert call[0][-2:] == expected[1]
        elif kind == "quarto":
            assert call[0] == expected[1]
        elif kind == "word":
            assert call[0]["output_path"] == expected[1]
        else:
            assert call[0] == "deck.pptx"
            assert call[1] == expected[1]
    # Help for what's after the path is the tool's command's
    for args, expected_text in [
        (["doc", "build", "--help"], "Build a document with its tool"),
        (["doc", "build", "paper.tex", "--help"], "--latexmk-arg"),
        (["doc", "build", "report.qmd", "-h"], "--allow-machine-quarto"),
        (["doc", "build", "deck.pptx", "--help"], "--trim"),
    ]:
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert expected_text in result.output, args
    # Types without a build yet, or unknown, say so
    Path("notes.md").write_text("Hi\n")
    os.makedirs("site")
    Path("site/myst.yml").write_text("version: 1\n")
    Path("notes.txt").write_text("Hi\n")
    for args, expected_text in [
        (["doc", "build", "notes.md"], "build not supported for Markdown yet"),
        (["doc", "build", "site"], "build not supported for MyST yet"),
        (["doc", "build", "book"], "not supported for Quarto project yet"),
        (["doc", "build", "notes.txt"], "Unknown document type: notes.txt"),
        (["doc", "build", "-e", "tex", "paper.tex"], "path before -e"),
    ]:
        result = CliRunner().invoke(app, args)
        assert result.exit_code != 0, args
        assert expected_text in result.output, args


def test_review_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import calkit.docx
    from calkit.cli.doc import _get_pdf_path
    from calkit.cli.main.core import app

    monkeypatch.chdir(tmp_path)
    calkit.save_calkit_info({"name": "test"})
    Path("paper.tex").write_text("\\documentclass{article}\n")
    Path("report.qmd").write_text("Hi\n")
    # The PDF a .tex builds is its stage's, or else beside it
    stages = {
        "paper": {
            "kind": "latex",
            "environment": "tex",
            "target_path": "paper/main.tex",
            "output_dir": "build",
        },
        "thesis": {
            "kind": "latex",
            "environment": "tex",
            "wdir": "thesis",
            "target_path": "main.tex",
        },
    }
    for tex_path, expected in [
        ("paper/main.tex", "build/main.pdf"),
        ("./thesis/main.tex", "thesis/main.pdf"),
        ("talk/main.tex", "talk/main.pdf"),
    ]:
        ck_info = {"pipeline": {"stages": stages}}
        assert _get_pdf_path(tex_path, ck_info) == expected
    # A .tex is handled by its LaTeX command, which finds no PDF here, and
    # other types aren't yet
    plain_path = "plain.docx"
    with zipfile.ZipFile(os.path.join(TEST_DIR, "docx", "export.docx")) as z:
        with zipfile.ZipFile(plain_path, "w") as out:
            for name in z.namelist():
                if not name.startswith("customXml/"):
                    out.writestr(name, z.read(name))
    doc = calkit.docx.Document(os.path.join(TEST_DIR, "docx", "export.docx"))
    original = doc.read_original()
    assert original is not None
    for source, fname in [("main.tex", "tex.docx"), ("r.qmd", "qmd.docx")]:
        doc.write_original(dataclasses.replace(original, source=source))
        doc.save(fname)
    for args, expected_text in [
        (["doc", "diff", "paper.tex", "--help"], "--from"),
        (["doc", "diff", "report.qmd"], "diff not supported for Quarto yet"),
        (["doc", "to-docx", "paper.tex"], "paper.pdf does not exist"),
        (["doc", "to-docx", "paper.pdf"], "supported: .tex"),
        (["doc", "merge-docx", "paper.tex"], "Expected reviewed .docx"),
        (["doc", "merge-docx", "nope.docx"], "nope.docx doesn't exist"),
        (["doc", "merge-docx", plain_path], "was not exported by Calkit"),
        (["doc", "merge-docx", "tex.docx"], "Source main.tex does not exist"),
        (["doc", "merge-docx", "qmd.docx"], "not supported for Quarto yet"),
        # The LaTeX commands themselves are as they were
        (["latex", "to-docx", "paper.pdf"], "paper.pdf does not exist"),
        (["tex", "merge-docx", "tex.docx"], "Source main.tex does not exist"),
    ]:
        result = CliRunner().invoke(app, args)
        assert expected_text in result.output, (args, result.output)
        assert (result.exit_code == 0) == ("--help" in args), args
