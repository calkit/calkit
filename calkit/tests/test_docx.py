"""Tests for the LaTeX/Word review round trip.

The .docx fixtures were produced with Word on macOS: ``word-import.docx`` is
Word's own import of the compiled paper, ``export.docx`` is ``to-docx``'s
output, ``returned.docx`` has a reviewer's tracked edits and a comment,
``accepted.docx`` is that after accepting every change in Word, and
``resolved.docx`` additionally has the exported thread resolved.
The ``libreoffice-*.docx`` fixtures are made by
``make-libreoffice-fixtures.py``; see the README there.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

import calkit.cli.latex
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
    doc = calkit.docx.Document("paper/main-for-review.docx")
    original = doc.read_original()
    assert original is not None
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
    # The record stays on this machine unless asked for, named by time
    records = os.listdir(calkit.latex.LOCAL_DOCX_EXPORTS_DIR)
    assert len(records) == 1
    assert re.fullmatch(
        rf"\d{{4}}-\d\d-\d\dT\d\d-\d\d-\d\d-{original.id}\.json",
        records[0],
    )
    assert not os.path.exists(calkit.latex.DOCX_EXPORTS_DIR)
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
    # A thread resolved in Word is marked resolved in the source, and
    # exports back to Word as resolved
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/resolved.docx"], check=True
    )
    methods = Path("paper/methods.tex").read_text(encoding="utf-8")
    assert "% COMMENT resolved=true\n%   T. Author:" in methods
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
