"""Tests for the LaTeX/Word review round trip.

The .docx fixtures were produced with Word on macOS: ``word-import.docx`` is
Word's own import of the compiled paper, ``export.docx`` is ``to-docx``'s
output, ``returned.docx`` has a reviewer's tracked edits and a comment,
``accepted.docx`` is that after accepting every change in Word, and
``resolved.docx`` additionally has the exported thread resolved.
The ``libreoffice-*.docx`` fixtures are made by
``make-libreoffice-fixtures.py``; see the README there.
"""

import copy
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import typer

import calkit.cli.latex
import calkit.core
import calkit.docx
import calkit.latex
from calkit.models.docx import LatexDocxExport, LatexDocxMerge

FIXTURES = Path(__file__).parent.parent.parent / "test" / "docx"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with the fixture paper at paper/, as the exports expect."""
    monkeypatch.chdir(tmp_path)
    os.makedirs("paper")
    for name in ["main.tex", "methods.tex"]:
        shutil.copy(FIXTURES / name, f"paper/{name}")
    Path("calkit.yaml").write_text("")
    subprocess.run(["git", "init", "-q"], check=True)
    return tmp_path


def test_latex_source_helpers(project: Path) -> None:
    # Flattening follows \input and keeps file and line for every line
    lines = calkit.latex.flatten("paper/main.tex")
    files = {ln.path for ln in lines}
    assert files == {"paper/main.tex", "paper/methods.tex"}
    methods = [ln for ln in lines if ln.path == "paper/methods.tex"]
    assert methods[0].lineno == 1 and methods[0].text == "\\section{Methods}"
    # Blocks split at blank lines and structure, not at interior comments
    blks = calkit.latex.blocks(lines)
    intro = next(b for b in blks if b.text.startswith("Wakes matter"))
    assert "% A comment" in "\n".join(ln.text for ln in intro.lines)
    assert "inline equation" in intro.text
    assert "comment that should not appear" not in intro.text
    # A comment block above a paragraph isn't part of it
    model = next(b for b in blks if "mean velocity deficit" in b.text)
    assert model.lines[0].text.startswith("The mean velocity")
    # Rendered text aligns to the source in order
    texts = [
        "Introduction",
        "Wakes matter for wind farm layout, as discussed by Smith and Jones",
        "September 6, 2026",
        "We measured the velocity field with a two-component laser Doppler",
    ]
    matched = calkit.latex.align(texts, blks)
    assert [m.lineno if m else None for m in matched] == [16, 19, None, 4]
    methods_blk = matched[3]
    assert methods_blk is not None and methods_blk.path == "paper/methods.tex"
    # Edits: a replacement, a deletion spanning lines and inline math, an
    # insertion, and one inside markup
    sent = "Wakes matter for wind farm layout, as discussed by Smith"
    edited = calkit.latex.apply_edit(
        intro, sent, sent.replace("discussed", "shown")
    )
    assert edited is not None
    assert edited[0].endswith("as shown by \\citet{smith2020}")
    m_sent = (
        "We measured the velocity field with a two-component laser Doppler "
        "velocimeter [Lee, 2018]. The sampling frequency was fs = 1 kHz and "
        "the integral time scale was estimated from the autocorrelation."
    )
    short = m_sent.split(". ")[0] + "."
    assert calkit.latex.apply_edit(methods_blk, m_sent, short) == [
        "We measured the velocity field with a two-component laser Doppler",
        "velocimeter~\\citep{lee2018}.",
    ]
    inserted = calkit.latex.apply_edit(
        intro, "Wakes matter for", "Wakes really matter for"
    )
    assert inserted is not None
    assert inserted[0].startswith("Wakes really matter for wind")
    # An insertion whose preceding word ("a") recurs elsewhere in the block
    # still lands, by widening the anchor phrase until it's unique.
    abstract = next(b for b in blks if b.text.startswith("We study the wake"))
    ambiguous = calkit.latex.apply_edit(
        abstract,
        "We study the wake of a model turbine.",
        "We study the wake of a sick model turbine.",
    )
    assert ambiguous is not None
    assert "of a sick model turbine" in "\n".join(ambiguous)
    assert (
        calkit.latex.apply_edit(
            methods_blk, "frequency was fs = 1 kHz", "frequency was fs = 2 kHz"
        )
        is None
    )
    # Word's typographic characters come back as LaTeX conventions, and
    # match the source across ties and quotes
    quoted = calkit.latex.from_word_text(
        "compound like \u201chigh-Reynolds-number\u201d plus a "
        "non-breaking\u00a0space and an em dash\u2014like this one."
    )
    assert quoted == (
        "compound like ``high-Reynolds-number'' plus a non-breaking~space "
        "and an em dash---like this one."
    )
    fixed = calkit.latex.apply_edit(
        intro, quoted, quoted.replace("this one", "that one")
    )
    assert fixed is not None and fixed[-1].endswith("dash---like that one.")
    assert calkit.latex.already_applied(intro, sent, sent) is True
    assert not calkit.latex.already_applied(
        intro, sent, sent.replace("discussed", "shown")
    )
    # A common word inserted isn't there just for being in the paragraph
    # elsewhere, though once inserted it is
    assert not calkit.latex.already_applied(
        intro, sent, sent.replace("for wind", "for a wind")
    )
    applied = calkit.latex.Block(
        [
            calkit.latex.SourceLine(ln.path, ln.lineno, ln.text)
            for ln in intro.lines
        ]
    )
    # An edit inside a parenthetical with a year isn't taken for a
    # citation that didn't change, nor an insertion beside a textual
    # citation for missing once merged
    dated = calkit.latex.Block(
        [calkit.latex.SourceLine("x.tex", 1, "The campaign (June 2019) ran.")]
    )
    assert not calkit.latex.already_applied(
        dated, "The campaign (June 2019) ran.", "The campaign (July 2019) ran."
    )
    textual = calkit.latex.Block(
        [
            calkit.latex.SourceLine(
                "x.tex", 1, r"As \citet{lee} showed, it works."
            )
        ]
    )
    sent_t = calkit.latex.from_word_text("As Lee (2018) showed, it works.")
    edit_t = sent_t.replace("showed", "clearly showed")
    once = calkit.latex.apply_edit(textual, sent_t, edit_t)
    assert once == [r"As \citet{lee} clearly showed, it works."]
    assert once is not None
    textual.lines[0].text = once[0]
    assert calkit.latex.apply_edit(textual, sent_t, edit_t) == once
    applied.lines[0].text = applied.lines[0].text.replace(
        "for wind", "for a wind"
    )
    assert calkit.latex.already_applied(
        applied, sent, sent.replace("for wind", "for a wind")
    )
    # An insertion where the words before it repeat goes after a longer
    # run of them, across braces, else before the words after it, e.g.,
    # past a citation
    styled = calkit.latex.Block(
        [
            calkit.latex.SourceLine(
                "x.tex",
                1,
                r"A \textit{fast model} for wind, and a \textit{slow model} "
                r"for wind too.",
            )
        ]
    )
    sent_s = "A fast model for wind, and a slow model for wind too."
    assert calkit.latex.apply_edit(
        styled, sent_s, sent_s.replace("wind too", "wind farms too")
    ) == [
        r"A \textit{fast model} for wind, and a \textit{slow model} for wind "
        r"farms too."
    ]
    cited = calkit.latex.Block(
        [
            calkit.latex.SourceLine(
                "x.tex",
                1,
                r"See \cite{a} for wind farms, and see \cite{b} for wind "
                r"farms too.",
            )
        ]
    )
    sent_c = "See [1] for wind farms, and see [2] for wind farms too."
    assert calkit.latex.apply_edit(
        cited, sent_c, sent_c.replace("farms too", "small farms too")
    ) == [
        r"See \cite{a} for wind farms, and see \cite{b} for wind small farms "
        r"too."
    ]
    # A word changed inside markup changes there, where what changed sits
    # together in the source, else it's left to do by hand
    labeled = calkit.latex.Block(
        [
            calkit.latex.SourceLine(
                "x.tex", 1, r"For \ce{^{2}H} and \ce{^{15}N} labels."
            )
        ]
    )
    sent_l = "For 2H and 15N labels."
    assert calkit.latex.apply_edit(
        labeled, sent_l, sent_l.replace("15N", "16N")
    ) == [r"For \ce{^{2}H} and \ce{^{16}N} labels."]
    assert (
        calkit.latex.apply_edit(labeled, sent_l, sent_l.replace("15N", "1X"))
        is None
    )
    # Comment blocks parse and render back to the same lines
    src = Path("paper/methods.tex").read_text(encoding="utf-8").split("\n")
    comments = calkit.latex.parse_comments(src)
    assert len(comments) == 1
    tc = comments[0]
    assert tc.author == "T. Author"
    assert tc.text == "Is this the right model for near wake?"
    assert tc.messages()[1:] == [("P. Bachant", "Probably fine for x/D > 3.")]
    assert src[tc.lineno - 1 : tc.lineno - 1 + tc.nlines] == tc.render()
    # The full schema: emails, timestamps, quoted highlight text with an
    # occurrence index, a header continued onto a second line, and bodies
    # wrapped at 79 columns
    long = calkit.latex.TexComment(
        [
            calkit.latex.Entry(
                "A", ("word " * 30).strip(), "a@x.org", "2026-09-06 08:44"
            ),
            calkit.latex.Entry("Person, Other", "Reply: yes."),
        ],
        highlight='a "b", c',
        highlight_occ=2,
        resolved=True,
    )
    rendered = long.render()
    assert rendered[0] == (
        '% COMMENT resolved=true highlight={text: "a \\"b\\", c", occ: 2}'
    )
    assert rendered[1] == "%   A <a@x.org> (2026-09-06 08:44):"
    assert all(len(ln) <= 79 for ln in rendered) and len(rendered) > 5
    back = calkit.latex.parse_comments(rendered)[0]
    assert back.entries == long.entries
    assert (back.highlight, back.highlight_occ, back.resolved) == (
        'a "b", c',
        2,
        True,
    )
    split = [
        "% COMMENT resolved=false",
        '%   highlight={text: "something", occ: 0}',
        "%   Someone Name <email@mail.com> (2025-01-01 01:00):",
        "%     This is a comment.",
    ]
    back = calkit.latex.parse_comments(split)[0]
    assert (back.highlight, back.highlight_occ, back.resolved) == (
        "something",
        0,
        False,
    )
    assert back.entries[0].email == "email@mail.com"
    # An ID, an issue, and attributes from a newer schema survive a rewrite
    newer = [
        "% COMMENT id=0a1b2c3d issue=https://github.com/o/r/issues/7",
        '%   origin={tool: "x", v: 2} note="two words"',
        "%   A:",
        "%     Hi.",
    ]
    back = calkit.latex.parse_comments(newer)[0]
    assert (back.id, back.issue) == (
        "0a1b2c3d",
        "https://github.com/o/r/issues/7",
    )
    assert back.attrs == {"origin": {"tool": "x", "v": 2}, "note": "two words"}
    again = calkit.latex.parse_comments(back.render())[0]
    assert (again.id, again.issue, again.attrs, again.entries) == (
        back.id,
        back.issue,
        back.attrs,
        back.entries,
    )
    assert calkit.latex.word_date("2026-09-06T08:44:00Z") == "2026-09-06 08:44"
    assert calkit.latex.make_bookmark_name("paper/main.tex", 19).startswith(
        "ck_"
    )
    # Display math is a block of its own through its closing line, and the
    # prose after it starts another
    eq = next(b for b in blks if b.display)
    assert eq.display == "equation" and eq.text == ""
    assert eq.lines[-1].text == "\\end{equation}"
    after = blks[blks.index(eq) + 1]
    assert after.text.startswith("where is the thrust")
    assert eq.rows == [
        (
            "\\[\n  \\frac{\\Delta U}{U_\\infty} = "
            "\\frac{C_T}{8 (1 + k x/D)^2},\n  \n\\]",
            True,
        )
    ]
    # Rows of an align are numbered one by one, unless marked otherwise
    src = [
        "\\begin{align}",
        "  a &= b, \\label{eq:a} \\\\",
        "  c &= \\begin{cases} 1 \\\\ 2 \\end{cases} \\nonumber \\\\",
        "  e &= f.",
        "\\end{align}",
        "Then \\[ x = y \\] inline, and",
        "\\begin{equation*} z \\end{equation*}",
        "ends it.",
    ]
    disp = calkit.latex.blocks(
        [calkit.latex.SourceLine("x.tex", i + 1, t) for i, t in enumerate(src)]
    )
    assert [b.display for b in disp] == ["align", None, "equation*", None]
    assert [n for _, n in disp[0].rows] == [True, False, True]
    assert "cases" in disp[0].rows[1][0] and "label" not in disp[0].rows[0][0]
    assert disp[2].rows == [("\\[ z \\]", False)]
    # An equation edited in Word lands in the source's own spelling: the
    # converter reads macros, wrappers, and function names differently
    block = calkit.latex.Block(
        [
            calkit.latex.SourceLine("x.tex", i + 1, t)
            for i, t in enumerate(
                [
                    "\\begin{equation}",
                    "  K_{\\mathrm{eq}} = \\frac{\\prod (\\sigma_j}{\\prod",
                    "  (\\beta_j} + \\ln x",
                    "\\end{equation}",
                ]
            )
        ]
    )
    sent = "K_{eq} = \\frac{\\prod(\\sigma_{j}}{\\prod(\\beta_{j}} + \\ln x"
    assert calkit.latex.apply_math_edit(
        block, sent, sent.replace("\\prod", "\\sum")
    ) == [
        "\\begin{equation}",
        "  K_{\\mathrm{eq}} = \\frac{\\sum (\\sigma_j}{\\sum",
        "  (\\beta_j} + \\ln x",
        "\\end{equation}",
    ]
    edited = calkit.latex.apply_math_edit(
        block, sent, sent.replace("\\beta_{j}}", "\\beta_{j}} \\cdot 2")
    )
    assert edited is not None and "(\\beta_j}\\cdot 2 + \\ln x" in edited[2]
    edited = calkit.latex.apply_math_edit(
        block, sent, sent.replace("\\ln x", "ln y")
    )
    assert edited is not None and edited[2].endswith("\\ln y")
    assert calkit.latex.apply_math_edit(block, sent, "q = r") is None
    # What LibreOffice respells on saving an unchanged equation isn't a
    # change
    assert calkit.latex.math_tokens(
        "\\begin{aligned} K & = \\frac{a}{b},\\quad {}^{i}\\ln x "
        "\\end{aligned}"
    ) == calkit.latex.math_tokens(
        "\\begin{array}{r} K\\text{\\&}\\text{=}\\frac{a}{b},^{i}ln x "
        "\\end{array}"
    )
    # Nor is Word joining symbols beside a math alphabet's letters into it,
    # but a different letter is
    assert calkit.latex.math_tokens(
        "\\mathcal{L}(x), z \\in \\mathcal{E}, \\boldsymbol{\\alpha}+1"
    ) == calkit.latex.math_tokens(
        "\\mathcal{L(}x), z\\mathcal{\\in E,} \\boldsymbol{\\alpha+}1"
    )
    assert calkit.latex.math_tokens(
        "z \\in \\mathcal{E}"
    ) != calkit.latex.math_tokens("z\\mathcal{\\in F}")
    # Nor an accent another Pandoc version reads back another way
    assert calkit.latex.math_tokens(
        "\\widehat{y} + \\widetilde{x} + \\overrightarrow{v}"
    ) == calkit.latex.math_tokens("\\hat{y} + \\tilde{x} + \\vec{v}")
    # Nor Word saving a function name after a command as letters
    assert calkit.latex.math_tokens(
        "e^{\\Delta\\ln x}"
    ) == calkit.latex.math_tokens("e^{\\Delta ln x}")


def test_docx_round_trip(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Export, with Word's PDF import replaced by its recorded output
    monkeypatch.setattr(
        calkit.docx,
        "pdf_to_docx",
        lambda pdf, out: shutil.copy(FIXTURES / "word-import.docx", out),
    )
    Path("paper/main.pdf").write_bytes(b"")
    # When the PDF is a latex stage's implied output, the stage runs first
    # and the source comes from its target
    Path("calkit.yaml").write_text(
        "environments:\n  tex:\n    kind: docker\n    image: texlive\n"
        "pipeline:\n  stages:\n    build-paper:\n      kind: latex\n"
        "      target_path: paper/main.tex\n      environment: tex\n",
        encoding="utf-8",
    )
    runs: list[list[str]] = []
    run = subprocess.run
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            calkit.cli.latex.subprocess,
            "run",
            lambda cmd, **kw: (
                runs.append(cmd) if "calkit" in cmd else run(cmd, **kw)
            ),
        )
        calkit.cli.latex.to_docx("paper/main.pdf", engine="word")
    assert runs and runs[0][-3:] == ["calkit", "run", "build-paper"]
    Path("calkit.yaml").write_text("", encoding="utf-8")
    first = calkit.docx.Document("paper/main-for-review.docx").read_original()
    assert first is not None
    # Exported again for a reproducible build, it makes the same file
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1790000000")
    exports = []
    for _ in range(2):
        calkit.cli.latex.to_docx("paper/main.pdf", engine="word", force=True)
        exports.append(Path("paper/main-for-review.docx").read_bytes())
    assert exports[0] == exports[1]
    # TeX4ht gets the same date, so \today in the Word copy matches the PDF,
    # run directly or in the stage's environment; it makes no ODT here
    dated = {"SOURCE_DATE_EPOCH": "1790000000", "FORCE_SOURCE_DATE": "1"}
    envs: list[dict[str, str]] = []

    class Make4ht:
        pid = 0

        def __init__(
            self, cmd: list[str], env: dict | None = None, **kw: object
        ) -> None:
            envs.append(env or {})

        def communicate(self, timeout: float) -> tuple[bytes, None]:
            return b"", None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calkit.docx, "find_soffice", lambda: "soffice")
        mp.setattr(calkit, "check_dep_exists", lambda dep: True)
        mp.setattr(calkit.cli.latex.subprocess, "Popen", Make4ht)
        with pytest.raises(typer.Exit):
            calkit.cli.latex.to_docx(
                "paper/main.pdf", engine="libreoffice", force=True
            )
    assert len(envs) == 1 and dated.items() <= envs[0].items()
    Path("calkit.yaml").write_text(
        "pipeline:\n  stages:\n    build-paper:\n      kind: latex\n"
        "      target_path: paper/main.tex\n      environment: tex\n",
        encoding="utf-8",
    )
    runs = []

    def run_recorded(
        cmd: list[str], **kw: object
    ) -> subprocess.CompletedProcess:
        runs.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(calkit.docx, "find_soffice", lambda: "soffice")
        mp.setattr(calkit.cli.latex.subprocess, "run", run_recorded)
        with pytest.raises(typer.Exit):
            calkit.cli.latex.to_docx(
                "paper/main.pdf", engine="libreoffice", force=True
            )
    xenv = next(cmd for cmd in runs if "xenv" in cmd)
    assert {f"--env-var={k}={v}" for k, v in dated.items()} <= set(xenv)
    Path("calkit.yaml").write_text("", encoding="utf-8")
    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    doc = calkit.docx.Document("paper/main-for-review.docx")
    original = doc.read_original()
    assert original is not None
    assert original.id != first.id
    assert original.source == "paper/main.tex"
    assert original.id
    assert doc.tracking and doc.protection is None
    # Package parts keep their default namespace, since LibreOffice refuses
    # a document whose relationships are prefixed
    assert doc.parts["word/_rels/document.xml.rels"].startswith(
        b"<?xml version='1.0' encoding='UTF-8'?>\n<Relationships xmlns="
    )
    assert b"<Types xmlns=" in doc.parts["[Content_Types].xml"]
    paras = doc.paragraphs
    assert sum(p.bookmark is not None for p in paras) == len(
        original.paragraphs
    ) + len(original.equations)
    assert all(
        original.paragraphs[p.bookmark] == p.text
        for p in paras
        if p.bookmark in original.paragraphs
    )
    # The .tex thread went out as a Word comment with its reply linked
    # The display equation went in converted from the source, numbered as
    # in the PDF, in place of Word's picture of it
    eq_name = calkit.latex.make_bookmark_name("paper/methods.tex", 15)
    assert list(original.equations) == [eq_name]
    assert "\\frac{C_{T}}{8(1 + kx/D)^{2}}" in original.equations[eq_name]
    math, pending = doc.equations([eq_name])[eq_name]
    assert math is not None and pending is None
    assert any(p.text == "(1)" for p in paras)
    # Inline math Word left as text went in as equations too, leaving the
    # prose around it, and a table cell's value after it, alone
    inline = next(p for p in paras if "inline equation" in p.text)
    assert inline.element is not None
    assert inline.element.find(f"{{{calkit.docx.M}}}oMath") is not None
    assert "contains an inline equation and a hyphenated" in inline.text
    assert any(
        p.text.startswith("Growth rate") and "0.05" in p.text for p in paras
    )
    assert not any(p.text.strip() in (", (1)", ",(1)") for p in paras)
    comments = doc.comments
    assert [c.author for c in comments] == ["T. Author", "P. Bachant"]
    assert comments[1].parent_id == comments[0].para_id
    model = next(p for p in paras if p.text.startswith("The mean velocity"))
    assert comments[0].bookmark == model.bookmark
    # The record stays on this machine unless asked for, named by time,
    # one per export
    records = sorted(os.listdir(calkit.latex.LOCAL_DOCX_EXPORTS_DIR))
    matches = [
        re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d(\.\d)?-(.+)\.json", r)
        for r in records
    ]
    assert sorted(m.group(2) for m in matches if m) == sorted(
        [first.id, original.id, original.id]
    )
    assert not os.path.exists(calkit.latex.DOCX_EXPORTS_DIR)
    assert Path(calkit.core.LOCAL_DIR, ".gitignore").read_text() == "*\n"
    export = LatexDocxExport.model_validate_json(
        Path(calkit.latex.LOCAL_DOCX_EXPORTS_DIR, records[0]).read_text()
    )
    assert export.inline_equations > 0
    assert set(export.files) == {
        "paper/main.tex",
        "paper/methods.tex",
        "paper/main.pdf",
        "paper/main-for-review.docx",
    }
    assert export.files["paper/main.tex"] == "md5:" + calkit.get_md5(
        "paper/main.tex"
    )
    # Word bookkeeping survives Word: the fixtures were made from an export
    # like this one and edited in Word
    returned = calkit.docx.Document(str(FIXTURES / "returned.docx"))
    assert returned.read_original() is not None
    assert sum(p.pending for p in returned.paragraphs) == 2
    assert returned.comments[-1].author == "A. Reviewer"
    # Merging with changes still tracked warns and applies only comments
    os.makedirs("reviews")
    for name in ["returned", "accepted", "resolved"]:
        shutil.copy(FIXTURES / f"{name}.docx", f"reviews/{name}.docx")
    res = subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/returned.docx"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "not yet accepted" in res.stderr + res.stdout
    record = json.loads(
        Path(
            calkit.latex.LOCAL_DOCX_MERGES_DIR,
            os.listdir(calkit.latex.LOCAL_DOCX_MERGES_DIR)[0],
        ).read_text(encoding="utf-8")
    )
    assert [c["author"] for c in record["changes"]] == ["Bachant, Pete"] * 2
    assert "A. Reviewer" in record["authors"]
    assert record["last_modified_by"]
    assert "as shown by" not in Path("paper/main.tex").read_text(
        encoding="utf-8"
    )
    assert "sampling frequency" in Path("paper/methods.tex").read_text(
        encoding="utf-8"
    )
    assert "%   A. Reviewer" in Path("paper/main.tex").read_text(
        encoding="utf-8"
    )
    # After accepting in Word, both edits land and the comment is written
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/accepted.docx"], check=True
    )
    main = Path("paper/main.tex").read_text(encoding="utf-8")
    methods = Path("paper/methods.tex").read_text(encoding="utf-8")
    assert "as shown by \\citet{smith2020}" in main
    assert "sampling frequency" not in methods
    assert re.search(
        r"% COMMENT\n%   A\. Reviewer \(\d{4}-\d\d-\d\d \d\d:\d\d\):\n"
        r"%     Quantify this: give an RMS error\.\nThe model in Eq\.",
        main,
    )
    assert methods.count("% COMMENT") == 1
    # Merging again changes nothing
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/accepted.docx"], check=True
    )
    assert Path("paper/main.tex").read_text(encoding="utf-8") == main
    assert Path("paper/methods.tex").read_text(encoding="utf-8") == methods
    # A thread whose replies changed in Word is rewritten in place, not
    # duplicated or displaced
    src = Path("paper/methods.tex").read_text(encoding="utf-8").split("\n")
    at = next(i for i, ln in enumerate(src) if ln.startswith("% COMMENT"))
    del src[at + 3 : at + 5]
    Path("paper/methods.tex").write_text("\n".join(src), encoding="utf-8")
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/accepted.docx"], check=True
    )
    assert Path("paper/methods.tex").read_text(encoding="utf-8") == methods
    # A comment on a selection carries the selected text as its highlight,
    # in both directions
    doc = calkit.docx.Document("reviews/accepted.docx")
    intro = next(
        p for p in doc.paragraphs if p.text.startswith("Wakes matter")
    )
    assert intro.element is not None
    doc.add_comments(
        [[("R. Viewer", "Cite more")]], [intro.element], [("layout", 0)]
    )
    doc.save("reviews/highlight.docx")
    again = calkit.docx.Document("reviews/highlight.docx")
    assert [(c.author, c.highlight, c.highlight_occ) for c in again.comments][
        -1
    ] == ("R. Viewer", "layout", 0)
    assert (
        next(
            p for p in again.paragraphs if p.text.startswith("Wakes matter")
        ).text
        == intro.text
    )
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/highlight.docx"],
        check=True,
    )
    assert (
        '% COMMENT highlight={text: "layout"}\n'
        "%   R. Viewer:\n"
        "%     Cite more\n"
        "Wakes matter"
    ) in Path("paper/main.tex").read_text(encoding="utf-8")
    main = Path("paper/main.tex").read_text(encoding="utf-8")
    # A table value edited in Word lands in the tabular row, and a figure
    # swapped in Word is warned about, since figures come from the pipeline
    doc = calkit.docx.Document("reviews/accepted.docx")
    for para in doc.paragraphs:
        assert para.element is not None
        for t in para.element.iter(f"{{{calkit.docx.W}}}t"):
            if t.text and "0.05" in t.text:
                t.text = t.text.replace("0.05", "0.07")
    doc.parts["word/media/image1.png"] = b"not the same picture"
    doc.save("reviews/table.docx")
    res = subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/table.docx"],
        capture_output=True,
        text=True,
        check=True,
    )
    out = res.stderr + res.stdout
    assert "Growth rate & $k$ & 0.07" in Path("paper/main.tex").read_text(
        encoding="utf-8"
    )
    assert "Figures were changed in Word" in out and "image1.png" in out
    main = Path("paper/main.tex").read_text(encoding="utf-8")
    # A thread resolved in Word is marked resolved in the source, keeping
    # the ID and issue Word can't carry, and exports back to Word as
    # resolved
    methods = Path("paper/methods.tex").read_text(encoding="utf-8")
    assert "% COMMENT\n%   T. Author:" in methods
    Path("paper/methods.tex").write_text(
        methods.replace(
            "% COMMENT\n%   T. Author:",
            "% COMMENT id=0a1b2c3d issue=https://github.com/o/r/issues/7\n"
            "%   T. Author:",
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/resolved.docx"], check=True
    )
    methods = Path("paper/methods.tex").read_text(encoding="utf-8")
    assert (
        "% COMMENT id=0a1b2c3d resolved=true "
        "issue=https://github.com/o/r/issues/7\n%   T. Author:"
    ) in methods
    parsed = calkit.latex.parse_comments(methods.split("\n"))
    assert [c.resolved for c in parsed] == [True]
    # With --log, the record is kept in the project too
    os.remove("paper/main-for-review.docx")
    calkit.cli.latex.to_docx("paper/main.pdf", engine="word", log=True)
    assert len(os.listdir(calkit.latex.DOCX_EXPORTS_DIR)) == 1
    assert os.listdir(calkit.latex.DOCX_EXPORTS_DIR)[0] in os.listdir(
        calkit.latex.LOCAL_DOCX_EXPORTS_DIR
    )
    exported = calkit.docx.Document("paper/main-for-review.docx").comments
    assert [c.done for c in exported if c.author == "T. Author"] == [True]
    assert Path("paper/main.tex").read_text(encoding="utf-8") == main
    merges = sorted(os.listdir(calkit.latex.LOCAL_DOCX_MERGES_DIR))
    assert len(merges) == 7
    fixture = returned.read_original()
    assert fixture is not None
    fixture_id = fixture.id
    # Named by time first, so the first listed is the first merged
    assert merges[0].endswith(f"-{fixture_id}.json")
    merge = LatexDocxMerge.model_validate_json(
        Path(calkit.latex.LOCAL_DOCX_MERGES_DIR, merges[-1]).read_text()
    )
    assert set(merge.files) == {
        "paper/main.tex",
        "paper/methods.tex",
        merge.docx,
    }
    assert merge.files["paper/main.tex"] == "md5:" + calkit.get_md5(
        "paper/main.tex"
    )
    # A document without Calkit's metadata is refused
    shutil.copy(FIXTURES / "word-import.docx", "reviews/plain.docx")
    res = subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/plain.docx"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "not exported by Calkit" in res.stderr + res.stdout
    # An equation edited in Word merges into the source, though Word moves
    # a bookmark at the start of a table cell out to the row
    doc = calkit.docx.Document("paper/main-for-review.docx")
    # A merge above took a line out ahead of the equation
    sent_doc = doc.read_original()
    assert sent_doc is not None
    eq_name = list(sent_doc.equations)[0]
    m_t = f"{{{calkit.docx.M}}}t"
    for t in doc.doc.iter(m_t):
        if t.text == "8":
            t.text = "4"
    start = next(
        b
        for b in doc.doc.iter(f"{{{calkit.docx.W}}}bookmarkStart")
        if b.get(f"{{{calkit.docx.W}}}name") == eq_name
    )
    start_para = doc._parents[start]
    cell = doc._parents[start_para]
    row = doc._parents[cell]
    start_para.remove(start)
    row.insert(list(row).index(cell), start)
    doc.save("reviews/eq.docx")
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/eq.docx"], check=True
    )
    methods = Path("paper/methods.tex").read_text(encoding="utf-8")
    assert "\\frac{C_T}{4 (1 + k x/D)^2}" in methods
    # A review done in LibreOffice merges like one done in Word, though
    # LibreOffice rewrites every equation's markup on saving and doesn't
    # track changes inside one. The source has moved on since the export.
    for name in ["returned", "accepted"]:
        shutil.copy(
            FIXTURES / f"libreoffice-{name}.docx", f"reviews/lo-{name}.docx"
        )
    res = subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/lo-returned.docx"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "not yet accepted" in res.stderr + res.stdout
    assert "Wakes really matter" not in Path("paper/main.tex").read_text(
        encoding="utf-8"
    )
    assert "\\frac{C_P}{" in Path("paper/methods.tex").read_text(
        encoding="utf-8"
    )
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/lo-accepted.docx"],
        check=True,
    )
    main = Path("paper/main.tex").read_text(encoding="utf-8")
    methods = Path("paper/methods.tex").read_text(encoding="utf-8")
    assert "Wakes really matter" in main
    assert (
        '% COMMENT highlight={text: "reasonably well"}\n'
        "%   Libre Reviewer:\n"
        "%     Quantify this.\n"
    ) in main
    assert "\\frac{C_P}{4 (1 + k x/D)^2}" in methods
    assert "Edited this equation" not in methods
    # Without Word, TeX4ht and LibreOffice make the copy from the source,
    # leaving nothing beside it, and it anchors and merges the same way
    if shutil.which("make4ht") and calkit.docx.find_soffice():
        # A figure for TeX4ht to convert: a blank one-page PDF
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] >>",
        ]
        pdf, offsets = b"%PDF-1.4\n", []
        for i, obj in enumerate(objs, 1):
            offsets.append(len(pdf))
            pdf += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
        xref = len(pdf)
        pdf += b"xref\n0 4\n0000000000 65535 f \n"
        pdf += b"".join(b"%010d 00000 n \n" % o for o in offsets)
        pdf += b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n%d\n" % xref
        Path("paper/fig1.pdf").write_bytes(pdf + b"%%EOF\n")
        beside = sorted(os.listdir("paper"))
        calkit.cli.latex.to_docx(
            "paper/main.pdf",
            output="reviews/lo-export.docx",
            engine="libreoffice",
        )
        assert sorted(os.listdir("paper")) == beside
        lo = calkit.docx.Document("reviews/lo-export.docx")
        lo_sent = lo.read_original()
        assert lo_sent is not None and len(lo_sent.equations) == 1
        assert len(lo_sent.paragraphs) >= 15
        assert any(p.text == "(1)" for p in lo.paragraphs)
        # A reference to an equation links to it inside the document, not
        # to TeX4ht's build directory
        body = lo.parts["word/document.xml"].decode("utf-8")
        anchors = re.findall(r'w:anchor="([^"]+)"', body)
        marks = set(re.findall(r'w:bookmarkStart [^>]*w:name="([^"]+)"', body))
        assert anchors and set(anchors) <= marks
        assert "HYPERLINK" not in body and ".4om" not in body
        main = Path("paper/main.tex").read_text(encoding="utf-8")
        methods = Path("paper/methods.tex").read_text(encoding="utf-8")
        res = subprocess.run(
            ["calkit", "latex", "merge-docx", "reviews/lo-export.docx"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Applied 0 edits" in res.stdout
        assert Path("paper/main.tex").read_text(encoding="utf-8") == main
        assert Path("paper/methods.tex").read_text(encoding="utf-8") == methods
    # A hyphen Word's import drops at a line's end goes back, as sent too,
    # where the source spells the word with it
    for name in ["main.tex", "methods.tex"]:
        shutil.copy(FIXTURES / name, f"paper/{name}")
    joined = calkit.docx.Document(str(FIXTURES / "word-import.docx"))
    t = next(
        t
        for t in joined.doc.iter(calkit.docx._tag(calkit.docx.W, "t"))
        if "two-component" in (t.text or "")
    )
    t.text = (t.text or "").replace("two-component", "twocomponent")
    # A paragraph Word's import split, here right after inline math with a
    # symbol after it, is one again, and a space it dropped before math goes
    # back
    intro_src = Path("paper/main.tex").read_text(encoding="utf-8")
    Path("paper/main.tex").write_text(
        intro_src.replace("10^5$\n", "10^5$\\textperthousand{}\n"),
        encoding="utf-8",
    )
    w_t = calkit.docx._tag(calkit.docx.W, "t")
    w_ppr = calkit.docx._tag(calkit.docx.W, "pPr")
    w_val = calkit.docx._tag(calkit.docx.W, "val")
    para = next(
        p
        for p in joined.paragraphs
        if p.element is not None and "inline equation" in p.text
    ).element
    assert para is not None
    rest = next(r for r in para if "and a hyphenated" in joined._run_text(r))
    rest_t = rest.find(w_t)
    assert rest_t is not None
    rest_t.text = "‰ " + (rest_t.text or "")
    split = ET.Element(calkit.docx._tag(calkit.docx.W, "p"))
    split.extend(copy.deepcopy(para[:1]))
    for r in list(para)[list(para).index(rest) :]:
        para.remove(r)
        split.append(r)
    holder = joined._parents[para]
    holder.insert(list(holder).index(para) + 1, split)
    # Word's import taking the first piece for right-aligned
    ET.SubElement(
        para[0], calkit.docx._tag(calkit.docx.W, "jc"), {w_val: "right"}
    )
    where = next(t for t in joined.doc.iter(w_t) if t.text == "where ")
    where.text = "where"
    # With the math after it as a picture
    symbol = next(t for t in joined.doc.iter(w_t) if t.text == "C")
    symbol_run = joined._parents[symbol]
    symbol_run.remove(symbol)
    ET.SubElement(symbol_run, calkit.docx._tag(calkit.docx.W, "drawing"))
    joined.save("joined.docx")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            calkit.docx,
            "pdf_to_docx",
            lambda pdf, out: shutil.copy("joined.docx", out),
        )
        calkit.cli.latex.to_docx(
            "paper/main.pdf", output="reviews/joined.docx", engine="word"
        )
    rejoined = calkit.docx.Document("reviews/joined.docx")
    sent = rejoined.read_original()
    assert sent is not None
    for text in [
        "\n".join(p.text for p in rejoined.paragraphs),
        "\n".join(sent.paragraphs.values()),
    ]:
        assert "a two-component laser" in text and "twocomponent" not in text
    intro = next(
        p for p in rejoined.paragraphs if p.text.startswith("Wakes matter")
    )
    assert intro.element is not None
    assert intro.text.endswith("like this one.")
    assert (
        intro.element.find(f"{w_ppr}/{calkit.docx._tag(calkit.docx.W, 'jc')}")
        is None
    )
    assert "inline equation ‰ and a hyphenated" in intro.text
    assert intro.element.find(f"{{{calkit.docx.M}}}oMath") is not None
    assert not any(p.text.startswith("‰") for p in rejoined.paragraphs)
    model = next(p for p in rejoined.paragraphs if p.text.startswith("where"))
    assert model.text.startswith("where is the thrust coefficient")
    assert model.element is not None
    lead = next(t for t in model.element.iter(w_t) if t.text)
    assert lead.text == "where "
    assert lead.get(calkit.docx.XML_SPACE) == "preserve"


def test_word_export_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w_ns = calkit.docx.W

    def make_word_import(
        paras: list[tuple[str, str | None]], path: str
    ) -> None:
        # Paragraphs as Word's PDF import might give them, with alignment
        Path(path).write_bytes(
            calkit.docx._pandoc(
                ["-f", "markdown", "-t", "docx", "-o", "-"], b"x"
            )
        )
        doc = calkit.docx.Document(path)
        body = doc.doc.find(calkit.docx._tag(w_ns, "body"))
        assert body is not None
        for child in list(body)[:-1]:
            body.remove(child)
        for i, (text, jc) in enumerate(paras):
            ppr = f'<w:pPr><w:jc w:val="{jc}"/></w:pPr>' if jc else ""
            body.insert(
                i,
                ET.fromstring(
                    f'<w:p xmlns:w="{w_ns}">{ppr}<w:r>'
                    f'<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'
                ),
            )
        doc.save()

    def get_math_and_text(doc: calkit.docx.Document, start: str) -> tuple:
        para = next(p for p in doc.paragraphs if p.text.startswith(start))
        assert para.element is not None
        maths = [
            "".join(t.text or "" for t in m.iter(f"{{{calkit.docx.M}}}t"))
            for m in para.element.iter(f"{{{calkit.docx.M}}}oMath")
        ]
        return para, maths

    monkeypatch.chdir(tmp_path)
    Path("calkit.yaml").write_text("")
    subprocess.run(["git", "init", "-q"], check=True)
    Path("main.tex").write_text(
        "\n".join(
            [
                r"\documentclass{article}",
                r"\newcommand{\cotwo}{\mathrm{CO_2}}",
                r"\begin{document}",
                r"\section{Results}",
                "",
                r"The rate is $k=2$ \citep{lee} and the gain $g$ "
                r"(Appendix~\ref{sec:a}) holds.",
                "",
                r"We fit the model to data. Then we fit the model $f(x)$ well.",
                "",
                r"At \SI{20}{\kelvin} the value $T_c$ drops, from $1$--$2$ "
                "units.",
                "",
                r"Only the $^{2}$H label, the $\cotwo$ flux, and the "
                r"$\arccos x$ term.",
                "",
                r"As \citet{lee} showed, the ratio%",
                r"$x$%",
                ", so it holds.",
                "",
                "The campaign (June 2019) ran long.",
                "",
                "A paragraph Word split at the end of a page, which carries",
                "on here with more words than its first piece has.",
                "",
                "One more split paragraph, longer before its break than after",
                "it, ending with a well-known effect.",
                "",
                r"Line one\\",
                "Line two",
                "",
                r"\begin{abstract}",
                "Short abstract text here.",
                r"\end{abstract}",
                r"\end{document}",
            ]
        )
    )
    Path("main.pdf").write_bytes(b"")
    make_word_import(
        [
            ("1 Results", None),
            (
                "The rate is k=2 (Lee, 2018) and the gain g (Appendix A) holds.",
                None,
            ),
            (
                "We fit the model to data. Then we fit the model f(x) well.",
                None,
            ),
            ("At 20K the value Tc drops, from 1–2 units.", None),
            ("Only the 2H label, the CO2 flux, and the arccos x term.", None),
            ("As Lee (2018) showed, the ratiox, so it holds.", None),
            ("The campaign (June 2019) ran long.", None),
            ("A paragraph Word split at the end of a page, which", "right"),
            (
                "carries on here with more words than its first piece has.",
                None,
            ),
            (
                "One more split paragraph, longer before its break than after it,"
                " ending with a well",
                "both",
            ),
            ("known effect.", None),
            ("Line one", None),
            ("Line two", None),
            ("Abstract", None),
            ("Short abstract text here.", None),
        ],
        "word.docx",
    )
    monkeypatch.setattr(
        calkit.docx,
        "pdf_to_docx",
        lambda pdf, out: shutil.copy("word.docx", out),
    )
    calkit.cli.latex.to_docx("main.pdf", source="main.tex", engine="word")
    doc = calkit.docx.Document("main-for-review.docx")
    # Inline math goes in past a citation and a reference beside it, after
    # the right one of repeated words, by a unit Word ran into a number,
    # between dashes, with the document's macros and operator names, and
    # with no space where a comment ended the line, but a superscript
    # alone stays text
    cases = {
        "The rate is": (["k=2", "g"], "The rate is (Lee, 2018) and the gain"),
        "We fit": (
            ["f(x)"],
            "We fit the model to data. Then we fit the model well.",
        ),
        "At 20K": (["Tc", "1", "2"], "At 20K the value drops, from – units."),
        "Only the": (
            ["CO2", "arccosx"],
            "Only the 2H label, the flux, and the term.",
        ),
        "As Lee": (["x"], "As Lee (2018) showed, the ratio, so it holds."),
    }
    for start, (maths, text) in cases.items():
        para, found = get_math_and_text(doc, start)
        assert found == maths, start
        assert para.text.startswith(text), start
    # A split paragraph is whole again, aligned as its longer piece is,
    # with a hyphen Word dropped at the break back; lines broken in the
    # source and an environment's heading stay apart
    texts = [p.text for p in doc.paragraphs]
    w_jc = f"{calkit.docx._tag(w_ns, 'pPr')}/{calkit.docx._tag(w_ns, 'jc')}"
    split, _ = get_math_and_text(doc, "A paragraph Word split")
    assert split.text.endswith("than its first piece has.")
    assert split.element is not None and split.element.find(w_jc) is None
    longer, _ = get_math_and_text(doc, "One more split")
    assert longer.text.endswith("ending with a well-known effect.")
    assert longer.element is not None
    jc = longer.element.find(w_jc)
    assert jc is not None and jc.get(calkit.docx._tag(w_ns, "val")) == "both"
    assert "Line one" in texts and "Line two" in texts
    assert "Abstract" in texts and "Short abstract text here." in texts
    # An insertion beside a textual citation and an edit inside a
    # parenthetical with a year merge back, once however often merged
    para, _ = get_math_and_text(doc, "As Lee")
    assert para.element is not None
    doc.insert_text(
        para.element, doc.linear_text(para.element).index("showed"), "clearly "
    )
    campaign, _ = get_math_and_text(doc, "The campaign")
    assert campaign.element is not None
    t = next(t for t in campaign.element.iter(calkit.docx._tag(w_ns, "t")))
    t.text = (t.text or "").replace("June", "July")
    doc.save("returned.docx")
    for _ in range(2):
        calkit.cli.latex.merge_docx("returned.docx")
    src = Path("main.tex").read_text()
    assert src.count("clearly") == 1
    assert r"As \citet{lee} clearly showed" in src
    assert "The campaign (July 2019) ran long." in src


def test_equation_links() -> None:
    content = (
        "<text:p>See (<text:a xlink:href='main-m7.4om#x7-3001r2' "
        "xlink:type='simple'>2</text:a>), "
        '<text:a xlink:href="main-m7.4om#x7-3001r3">3</text:a>, '
        "<text:a xlink:href='#Xsmith2020'>Smith</text:a>, "
        "<text:a xlink:href='https://calkit.io/a.html#b'>web</text:a> and "
        "<text:a xlink:href='other.4om#x9'>gone</text:a>.</text:p>"
        "<text:p><draw:frame draw:name='obj-7'><draw:object "
        "xlink:href='./main-m7' xlink:show='embed'/></draw:frame></text:p>"
    )
    out = calkit.docx._link_into_objects(content)
    # Links into an object point at bookmarks beside it
    assert "xlink:href='#x7-3001r2'" in out
    assert 'xlink:href="#x7-3001r3"' in out
    assert (
        "<text:p><text:bookmark text:name='x7-3001r2'/>"
        "<text:bookmark text:name='x7-3001r3'/><draw:frame" in out
    )
    # Links within the document or out of it, or to an object that isn't
    # there, are left alone
    assert "xlink:href='#Xsmith2020'" in out
    assert "xlink:href='https://calkit.io/a.html#b'" in out
    assert "xlink:href='other.4om#x9'" in out
    assert calkit.docx._link_into_objects(out) == out
    # A kept bookmark goes on the row it's for, not just the first
    doc = calkit.docx.Document(str(FIXTURES / "export.docx"))
    w, m = calkit.docx.W, calkit.docx.M
    before = next(doc.doc.iter(calkit.docx._tag(w, "p")))
    rows = [
        (ET.Element(calkit.docx._tag(m, "oMath")), "4", "ck_a"),
        (ET.Element(calkit.docx._tag(m, "oMath")), "5", "ck_a_r2"),
    ]
    doc.insert_equations(before, rows, 100, keep={1: [("x13-3004r5", "7")]})
    tbl = next(doc.doc.iter(calkit.docx._tag(w, "tbl")))
    names = [
        [
            b.get(calkit.docx._tag(w, "name"))
            for b in tr.iter(calkit.docx._tag(w, "bookmarkStart"))
        ]
        for tr in tbl.iter(calkit.docx._tag(w, "tr"))
    ]
    assert names == [["ck_a"], ["ck_a_r2", "x13-3004r5"]]


def test_flatten_heavy_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def word(cmd: list[str], **kw: object) -> subprocess.CompletedProcess:
        # Word's import, writing a .docx where it's asked to save
        saved = re.search(r'file name "([^"]+)"', cmd[-1])
        assert saved is not None
        Path(saved.group(1)).write_bytes(b"docx")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    # A light figure is left alone, with nothing written
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.plot([0, 1], [0, 1])
    fig.savefig(tmp_path / "light.pdf")
    out = tmp_path / "out.pdf"
    assert (
        calkit.docx.flatten_heavy_figures(
            str(tmp_path / "light.pdf"), str(out)
        )
        == 0
    )
    assert not out.exists()
    # A dense one is left alone where the page's text is in a Type 3 font,
    # which pdfium can't write back
    x = np.linspace(-5, 5, 60_000)
    ax.plot(x, 10 * np.sin(3 * x), color="white")
    # Over a filled background, which an image of it mustn't hide
    ax.set(xlim=(-5, 5), ylim=(-5, 5), title="Dense", facecolor="#3366cc")
    # Every point drawn, as a scatter's would be
    matplotlib.rcParams["path.simplify"] = False
    fig.savefig(tmp_path / "heavy.pdf")
    assert (
        calkit.docx.flatten_heavy_figures(
            str(tmp_path / "heavy.pdf"), str(out), max_segments=10_000
        )
        == 0
    )
    assert not out.exists()
    # Otherwise, clipped to its axes, it becomes an image of what's drawn,
    # in its place among the page's other objects
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig.savefig(tmp_path / "heavy.pdf")
    plt.close(fig)
    assert (
        calkit.docx.flatten_heavy_figures(
            str(tmp_path / "heavy.pdf"), str(out), max_segments=10_000
        )
        == 1
    )
    before = pdfium.PdfDocument(tmp_path / "heavy.pdf")[0]
    after = pdfium.PdfDocument(out)[0]
    kinds_before = [
        pdfium_c.FPDFPageObj_GetType(o.raw)
        for o in before.get_objects(max_depth=1)
    ]
    kinds_after = [
        pdfium_c.FPDFPageObj_GetType(o.raw)
        for o in after.get_objects(max_depth=1)
    ]
    i = next(
        j
        for j, o in enumerate(before.get_objects(max_depth=1))
        if pdfium_c.FPDFPageObj_GetType(o.raw) == pdfium_c.FPDF_PAGEOBJ_PATH
        and pdfium_c.FPDFPath_CountSegments(o.raw) > 10_000
    )
    assert kinds_after == (
        kinds_before[:i]
        + [pdfium_c.FPDF_PAGEOBJ_IMAGE]
        + kinds_before[i + 1 :]
    )
    img = list(after.get_objects(max_depth=1))[i]
    left, bottom, right, top = img.get_bounds()
    width, height = before.get_size()
    assert 0 <= left < right <= width and 0 <= bottom < top <= height
    # The page looks the same
    a = np.asarray(before.render(scale=1).to_pil().convert("L"), float)
    b = np.asarray(after.render(scale=1).to_pil().convert("L"), float)
    assert np.abs(a - b).mean() < 2
    # The copy Word gets is a file of its own, never the PDF itself, even
    # one named as it would be, and it's gone after
    blank = pdfium.PdfDocument.new()
    blank.new_page(72, 72)
    blank.save(tmp_path / "paper.tmp.pdf")
    monkeypatch.setattr(calkit.docx.subprocess, "run", word)
    monkeypatch.setattr(calkit.docx.sys, "platform", "darwin")
    calkit.docx.pdf_to_docx(
        str(tmp_path / "paper.tmp.pdf"), str(tmp_path / "paper.docx")
    )
    assert sorted(p.name for p in tmp_path.iterdir() if "paper" in p.name) == [
        "paper.docx",
        "paper.tmp.pdf",
    ]


def test_latex_to_omml(monkeypatch: pytest.MonkeyPatch) -> None:
    # Text symbols, and text in text from the document's macros, which
    # Pandoc can't convert as written
    preamble = (
        "\\def\\xspace{}%\n"
        "\\newcommand{\\degC}{\\text{\\textdegree C}\\xspace}\n"
        "\\newcommand{\\note}[1]{}"
    )
    maths = calkit.docx.latex_to_omml(
        [
            "\\[\\text{T (\\degC)} = \\frac{1}{N}\\sum_A x_A\\]",
            "$20\\degC$",
            "$\\text{a \\textperthousand{} \\textbf{b}}$",
            "\\[x = y\\]",
        ],
        preamble,
    )
    assert all(m is not None for m in maths)
    text = "".join(
        t.text or ""
        for m in maths
        if m is not None
        for t in m.iter(calkit.docx._tag(calkit.docx.M, "t"))
    )
    assert "T (°C)" in text and "‰" in text
    # The same whatever Pandoc's version: primes a superscript with the
    # subscript, apostrophes in text left alone, \mathbf upright bold,
    # \boldsymbol of letters bold italic, and bold text in math bold
    m_ns = calkit.docx.M

    def look(math: ET.Element | None) -> str:
        assert math is not None
        out = []
        for el in math.iter():
            name = el.tag.split("}")[1]
            if name in ("sSub", "sSup", "sSubSup", "sub", "sup"):
                out.append(name)
            elif name == "r":
                sty = el.find(f"{{{m_ns}}}rPr/{{{m_ns}}}sty")
                scr = el.find(f"{{{m_ns}}}rPr/{{{m_ns}}}scr")
                nor = el.find(f"{{{m_ns}}}rPr/{{{m_ns}}}nor")
                text = "".join(t.text or "" for t in el.iter(f"{{{m_ns}}}t"))
                # The style only counts on letters, which it slants
                style = (
                    sty.get(f"{{{m_ns}}}val") if sty is not None else ""
                ) or ""
                if scr is not None:
                    style += "/" + (scr.get(f"{{{m_ns}}}val") or "")
                if nor is not None:
                    style = "text"
                elif not any(c.isalpha() for c in text):
                    style = ""
                out.append(f"{style}:{text}")
        return " ".join(out)

    cases = {
        "$\\omega_j'$": "sSubSup :ω sub :j sup :′",
        "$L'_{\\mathrm{C}}$": "sSubSup :L sub p:C sup :′",
        "$u'^2$": "sSup :u sup :′ :2",
        "$\\text{model's}$": "text:model’s",
        "$\\mathbf{F}$": "b:F",
        "$\\boldsymbol{F} + \\bm{\\nabla}$": "bi:F :+ :∇",
        "$\\textbf{h}$": "b:h",
    }
    maths = calkit.docx.latex_to_omml(list(cases))
    for (tex, want), math in zip(cases.items(), maths):
        assert look(math) == want, tex
    # Sans serif math of the document's own keeps its look
    sans = calkit.docx.latex_to_omml(["$\\mathsf{A}\\mathbf{F}$"])[0]
    assert (
        "/sans-serif:A" in look(sans)
        and "/sans-serif" not in look(sans).split("A", 1)[1]
    )
    # Brackets that are part of the syntax stay so: an array's column
    # rules, an arrow's label, \genfrac's delimiters; and commands Pandoc
    # doesn't know go in as ones it does
    m_t = f"{{{m_ns}}}t"
    syntax = {
        "$\\left(\\begin{array}{c|c} a & b \\\\ c & d \\end{array}\\right)$": (
            "abcd"
        ),
        "$A \\xrightarrow[k]{f} B$": "A→fkB",
        "$\\genfrac{(}{)}{0pt}{}{n}{k}$": "nk",
        "$\\cfrac[l]{1}{x}$": "1x",
        "$\\textnormal{it's}$": "it’s",
    }
    for (tex, want), math in zip(
        syntax.items(), calkit.docx.latex_to_omml(list(syntax))
    ):
        assert math is not None, tex
        assert "".join(t.text or "" for t in math.iter(m_t)) == want, tex
    # Plain sans serif beside bold keeps both
    both = look(calkit.docx.latex_to_omml(["$\\mathsf{A} + \\mathbf{F}$"])[0])
    assert "/sans-serif:A" in both and "b:F" in both
    # Its version, which the export warns about when old
    version = calkit.docx.get_pandoc_version()
    assert version is not None and len(version) >= 2
    # As Windows names it too
    for printed in ("pandoc 3.6.1", "pandoc.exe 3.7.0.2"):
        monkeypatch.setattr(
            calkit.docx.subprocess,
            "run",
            lambda cmd, printed=printed, **kw: subprocess.CompletedProcess(
                cmd, 0, stdout=f"{printed}\nFeatures: +server\n", stderr=""
            ),
        )
        version = calkit.docx.get_pandoc_version()
        assert version == tuple(int(n) for n in printed.split()[1].split("."))
