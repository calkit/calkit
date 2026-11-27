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
        (["doc", "build", "letter.docx", "--help"], "Word document to PDF"),
        (["doc", "build", "book", "--help"], "--as-stage"),
    ]:
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert expected_text in result.output, args
        # Not pointing to itself
        assert "calkit doc build`" not in result.output, args
    # Types without a build yet, or unknown, say so
    Path("notes.md").write_text("Hi\n")
    os.makedirs("site")
    Path("site/myst.yml").write_text("version: 1\n")
    Path("notes.txt").write_text("Hi\n")
    for args, expected_text in [
        (["doc", "build", "notes.md"], "build not supported for Markdown yet"),
        (["doc", "build", "site"], "build not supported for MyST yet"),
        (["doc", "build", "book"], "No quarto stage renders a document in"),
        (["doc", "build", "missing.tex"], "missing.tex doesn't exist"),
        (["doc", "build", "notes.txt"], "Unknown document type: notes.txt"),
        (["doc", "build", "-e", "tex", "paper.tex"], "path before -e"),
    ]:
        result = CliRunner().invoke(app, args)
        assert result.exit_code != 0, args
        assert expected_text in result.output, args


def test_build_as_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calkit.cli import latex as cli_latex
    from calkit.cli.main.core import app

    monkeypatch.chdir(tmp_path)
    root = os.getcwd()
    calkit.save_calkit_info(
        {
            "name": "test",
            "environments": {"tex": {"kind": "texlive"}},
            "pipeline": {
                "stages": {
                    "paper": {
                        "kind": "latex",
                        "environment": "tex",
                        "target_path": "paper/main.tex",
                        "output_dir": "build",
                    },
                    "pub": {
                        "kind": "quarto",
                        "environment": "_system",
                        "target_path": "index.ipynb",
                        "args": ["--execute"],
                    },
                    "nb": {
                        "kind": "jupyter-notebook",
                        "environment": "py",
                        "notebook_path": "analysis.ipynb",
                    },
                }
            },
        }
    )
    os.makedirs("paper")
    Path("paper/main.tex").write_text("\\documentclass{article}\n")
    nb = '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}'
    Path("index.ipynb").write_text(nb)
    Path("analysis.ipynb").write_text(nb)
    Path("_quarto.yml").write_text("project: {type: default}\n")
    os.makedirs("book")
    Path("book/_quarto.yml").write_text("project: {type: book}\n")
    calls: list[tuple] = []
    monkeypatch.setattr(cli_latex, "_tex_cmd", lambda cmd, **kwargs: cmd)
    monkeypatch.setattr(cli_latex, "_get_texlive_env", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_latex,
        "_run_latexmk",
        lambda cmd, **kwargs: calls.append(
            ("latexmk", kwargs["environment"], cmd, os.getcwd())
        ),
    )
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda cmd, **kwargs: calls.append(
            ("quarto", None, cmd[1:], os.getcwd())
        ),
    )
    # A document a stage builds is built as the stage does, from anywhere,
    # unless told otherwise, and a Quarto project as the documents its
    # stages render
    for cwd, args, expected in [
        (".", ["paper/main.tex"], ("latexmk", "tex", "-outdir=../build")),
        ("paper", ["main.tex", "-f"], ("latexmk", "tex", "-outdir=../build")),
        (".", ["paper/main.tex", "-e", "tex2"], ("latexmk", "tex2", None)),
        (
            ".",
            ["index.ipynb", "--", "--no-cache"],
            (
                "quarto",
                None,
                ["render", "index.ipynb", "--execute", "--no-cache"],
            ),
        ),
        (".", ["."], ("quarto", None, ["render", "index.ipynb", "--execute"])),
        (
            "paper",
            ["..", "--no-check"],
            ("quarto", None, ["render", "index.ipynb", "--execute"]),
        ),
        (
            ".",
            ["analysis.ipynb", "-e", "_system"],
            ("quarto", None, ["render", "analysis.ipynb"]),
        ),
    ]:
        monkeypatch.chdir(os.path.join(root, cwd))
        calls.clear()
        result = CliRunner().invoke(app, ["doc", "build", *args])
        assert result.exit_code == 0, (args, result.output)
        kind, env, cmd, ran_in = calls[0]
        assert (kind, env) == expected[:2], args
        assert os.path.samefile(ran_in, root), args
        if kind == "latexmk":
            outdirs = [a for a in cmd if a.startswith("-outdir=")]
            assert outdirs == ([expected[2]] if expected[2] else []), args
            assert ("-f" in cmd) == ("-f" in args), args
        else:
            assert cmd == expected[2], args
    # A notebook a stage executes is run with the pipeline, and a Quarto
    # project needs a stage rendering something in it
    monkeypatch.chdir(root)
    for args, expected_text in [
        (["analysis.ipynb"], "Stage 'nb' executes analysis.ipynb"),
        (["book"], "No quarto stage renders a document in book"),
        (
            ["index.ipynb", "--as-stage", "--to", "pdf"],
            "format from the stage",
        ),
    ]:
        result = CliRunner().invoke(app, ["doc", "build", *args])
        assert result.exit_code != 0, args
        assert expected_text in result.output, (args, result.output)


def test_review_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import calkit.docx
    from calkit.cli.main.core import app

    monkeypatch.chdir(tmp_path)
    root = os.getcwd()
    calkit.save_calkit_info(
        {
            "name": "test",
            "pipeline": {
                "stages": {
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
            },
        }
    )
    for tex_path in ["paper.tex", "paper/main.tex", "thesis/main.tex"]:
        os.makedirs(os.path.dirname(tex_path) or ".", exist_ok=True)
        Path(tex_path).write_text("\\documentclass{article}\n")
    Path("report.qmd").write_text("Hi\n")
    # The PDF a .tex builds is its stage's, from anywhere, which is run
    # first, or else beside it. Nothing builds the PDFs here, so it stops
    # before exporting.
    runs: list[tuple[list[str], str]] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kwargs: runs.append((cmd[-1], kwargs.get("cwd") or ".")),
    )
    for cwd, args, stage, expected_text in [
        (".", ["doc", "to-docx", "paper/main.tex"], "paper", "build/main.pdf"),
        (
            "paper",
            ["doc", "to-docx", "main.tex"],
            "paper",
            "../build/main.pdf",
        ),
        (
            ".",
            ["doc", "to-docx", "thesis/main.tex"],
            "thesis",
            "thesis/main.pdf",
        ),
        (".", ["doc", "to-docx", "build/main.pdf"], "paper", "build/main.pdf"),
        (".", ["latex", "to-docx", "thesis/main.pdf"], "thesis", "thesis/"),
        (
            ".",
            ["doc", "to-docx", "paper.tex"],
            None,
            "paper.pdf does not exist",
        ),
        (".", ["latex", "to-docx", "paper.pdf"], None, "paper.pdf does not"),
        (".", ["doc", "to-docx", "talk.tex"], None, "talk.tex doesn't exist"),
    ]:
        monkeypatch.chdir(os.path.join(root, cwd))
        runs.clear()
        result = CliRunner().invoke(app, args)
        assert result.exit_code != 0, args
        assert expected_text in result.output, (args, result.output)
        assert [r[0] for r in runs] == ([stage] if stage else []), args
        for _, ran_in in runs:
            assert os.path.samefile(ran_in, root), args
    monkeypatch.chdir(root)
    # A .docx goes back to its source's tool, which is only LaTeX yet
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
        (["doc", "diff", "nope.tex"], "nope.tex doesn't exist"),
        (["doc", "merge-docx", "paper.tex"], "Expected reviewed .docx"),
        (["doc", "merge-docx", "nope.docx"], "nope.docx doesn't exist"),
        (["doc", "merge-docx", plain_path], "was not exported by Calkit"),
        (["doc", "merge-docx", "tex.docx"], "Source main.tex does not exist"),
        (["doc", "merge-docx", "qmd.docx"], "not supported for Quarto yet"),
        (["tex", "merge-docx", "tex.docx"], "Source main.tex does not exist"),
    ]:
        result = CliRunner().invoke(app, args)
        assert expected_text in result.output, (args, result.output)
        assert (result.exit_code == 0) == ("--help" in args), args
    # Help reads no files, so it's there whatever state they're in
    Path("calkit.yaml").write_text("pipeline: [\n")
    for args, expected_text in [
        (["doc", "to-docx", "paper.tex", "--help"], "Compiled PDF"),
        (["doc", "merge-docx", "nope.docx", "-h"], "Reviewed .docx"),
    ]:
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert expected_text in result.output, args
        assert "calkit doc " not in result.output.replace("calkit doc to", "")
