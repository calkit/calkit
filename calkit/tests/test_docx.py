"""Tests for the LaTeX/Word review round trip.

The .docx fixtures were produced with Word on macOS: ``word-import.docx`` is
Word's own import of the compiled paper, ``export.docx`` is ``to-docx``'s
output, ``returned.docx`` has a reviewer's tracked edits and a comment,
``accepted.docx`` is that after accepting every change in Word, and
``resolved.docx`` additionally has the exported thread resolved.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import calkit.cli.latex
import calkit.docx
import calkit.latex

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
    assert tc.replies == [("P. Bachant", "Probably fine for x/D > 3.")]
    assert src[tc.lineno - 1 : tc.lineno - 1 + tc.nlines] == tc.render()
    long = calkit.latex.TexComment([("A", "word " * 30)], highlight='a "b"')
    rendered = long.render()
    assert rendered[0] == "% COMMENT highlight=\"a 'b'\""
    assert all(len(ln) <= 79 for ln in rendered) and len(rendered) > 3
    assert calkit.latex.parse_comments(rendered)[0].entries == [
        ("A", ("word " * 30).strip())
    ]
    assert calkit.latex.bookmark_name("paper/main.tex", 19).startswith("ck_")


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
    calkit.cli.latex.to_docx("paper/main.pdf")
    doc = calkit.docx.Document("paper/main-for-review.docx")
    original = doc.read_original()
    assert original is not None
    assert original.source == "paper/main.tex"
    assert original.uuid
    assert doc.tracking() and doc.protection() is None
    paras = doc.paragraphs()
    assert sum(p.bookmark is not None for p in paras) == len(
        original.paragraphs
    )
    assert all(
        original.paragraphs[p.bookmark] == p.text for p in paras if p.bookmark
    )
    # The .tex thread went out as a Word comment with its reply linked
    comments = doc.comments()
    assert [c.author for c in comments] == ["T. Author", "P. Bachant"]
    assert comments[1].parent_id == comments[0].para_id
    model = next(p for p in paras if p.text.startswith("The mean velocity"))
    assert comments[0].bookmark == model.bookmark
    records = os.listdir(calkit.latex.DOCX_EXPORTS_DIR)
    assert records == [f"{original.uuid}.json"]
    # Word bookkeeping survives Word: the fixtures were made from an export
    # like this one and edited in Word
    returned = calkit.docx.Document(str(FIXTURES / "returned.docx"))
    assert returned.read_original() is not None
    assert sum(p.pending for p in returned.paragraphs()) == 2
    assert returned.comments()[-1].author == "A. Reviewer"
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
            calkit.latex.DOCX_MERGES_DIR,
            os.listdir(calkit.latex.DOCX_MERGES_DIR)[0],
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
    assert "%   A. Reviewer:" in Path("paper/main.tex").read_text(
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
    assert (
        "% COMMENT\n"
        "%   A. Reviewer:\n"
        "%     Quantify this: give an RMS error.\n"
        "The model in Eq."
    ) in main
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
        p for p in doc.paragraphs() if p.text.startswith("Wakes matter")
    )
    assert intro.element is not None
    doc.add_comments(
        [[("R. Viewer", "Cite more")]], [intro.element], ["wind farm layout"]
    )
    doc.save("reviews/highlight.docx")
    again = calkit.docx.Document("reviews/highlight.docx")
    assert [(c.author, c.highlight) for c in again.comments()][-1] == (
        "R. Viewer",
        "wind farm layout",
    )
    assert (
        next(
            p for p in again.paragraphs() if p.text.startswith("Wakes matter")
        ).text
        == intro.text
    )
    subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/highlight.docx"],
        check=True,
    )
    assert (
        '% COMMENT highlight="wind farm layout"\n'
        "%   R. Viewer:\n"
        "%     Cite more\n"
        "Wakes matter"
    ) in Path("paper/main.tex").read_text(encoding="utf-8")
    main = Path("paper/main.tex").read_text(encoding="utf-8")
    # A table value edited in Word lands in the tabular row, and a figure
    # swapped in Word is warned about, since figures come from the pipeline
    doc = calkit.docx.Document("reviews/accepted.docx")
    for para in doc.paragraphs():
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
    os.remove("paper/main-for-review.docx")
    calkit.cli.latex.to_docx("paper/main.pdf")
    exported = calkit.docx.Document("paper/main-for-review.docx").comments()
    assert [c.done for c in exported if c.author == "T. Author"] == [True]
    assert Path("paper/main.tex").read_text(encoding="utf-8") == main
    merges = sorted(os.listdir(calkit.latex.DOCX_MERGES_DIR))
    assert len(merges) == 7
    fixture = returned.read_original()
    assert fixture is not None
    fixture_uuid = fixture.uuid
    assert merges[0].startswith(fixture_uuid) and merges[0].endswith(".json")
    # A document without Calkit's metadata is refused
    shutil.copy(FIXTURES / "word-import.docx", "reviews/plain.docx")
    res = subprocess.run(
        ["calkit", "latex", "merge-docx", "reviews/plain.docx"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "not exported by Calkit" in res.stderr + res.stdout
