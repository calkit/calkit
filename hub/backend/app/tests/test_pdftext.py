"""Tests for ``app.pdftext``."""

from app import pdftext


def test_normalize() -> None:
    # A ligature is one glyph in the PDF, and toolchains decompose it
    # differently, so two builds of the same sentence would differ
    assert pdftext.normalize("signiﬁcantly eﬃcient") == (
        "significantly efficient"
    )
    # A word broken across lines is one word
    assert pdftext.normalize("recur-\nrent networks") == "recurrent networks"
    # Whatever spacing the layout produced collapses
    assert pdftext.normalize("  a\n\n b \t c  ") == "a b c"


def test_diff_finds_the_change_and_keeps_its_surroundings() -> None:
    filler = " ".join(f"w{i}" for i in range(80))
    base = f"{filler} the quick brown fox {filler}"
    head = f"{filler} the quick red fox {filler}"
    diff = pdftext.diff(
        base=base, head=head, path="p.pdf", base_ref="main", head_ref="branch"
    )
    assert not diff.identical
    assert [(s.kind, s.text) for s in diff.segments if s.kind != "equal"] == [
        ("delete", "brown"),
        ("insert", "red"),
    ]
    # The change is placed by the words around it, not by returning the
    # whole document twice
    context = " ".join(s.text for s in diff.segments if s.kind == "equal")
    assert "the quick" in context
    assert "fox" in context
    assert context.count("w0") <= 1
    assert any(s.elided for s in diff.segments)


def test_diff_of_identical_text() -> None:
    text = "the same words either way"
    diff = pdftext.diff(
        base=text, head=text, path="p.pdf", base_ref="main", head_ref="branch"
    )
    assert diff.identical
    # Nothing to show; the segments would just be the document
    assert diff.segments == []
    # Two builds of one source differ in spacing and ligatures without
    # differing in a single word
    spaced = pdftext.diff(
        base="the same\nwords  either way",
        head="the same words either way",
        path="p.pdf",
        base_ref="main",
        head_ref="branch",
    )
    assert spaced.identical


def test_diff_insertion_and_deletion() -> None:
    diff = pdftext.diff(
        base="alpha beta gamma",
        head="alpha beta delta gamma",
        path="p.pdf",
        base_ref="main",
        head_ref="branch",
    )
    assert [(s.kind, s.text) for s in diff.segments if s.kind != "equal"] == [
        ("insert", "delta")
    ]
    diff = pdftext.diff(
        base="alpha beta gamma",
        head="alpha gamma",
        path="p.pdf",
        base_ref="main",
        head_ref="branch",
    )
    assert [(s.kind, s.text) for s in diff.segments if s.kind != "equal"] == [
        ("delete", "beta")
    ]


def test_pdf_layout() -> None:
    from pathlib import Path

    # Built with pdflatex from the sources beside it
    data = (
        Path(__file__).parents[4] / "test" / "latex-comments" / "main.pdf"
    ).read_bytes()
    layout = pdftext.PdfLayout(data)
    assert len(layout.pages) == 1
    # A paragraph is found by runs of its words, though the source's text
    # has lost its math
    para = (
        "The model fits the data reasonably well, and we can see that the "
        "wake recovers by in all cases considered here, so the wake recovers "
        "quickly."
    )
    span = layout.paragraph(para)
    assert span is not None
    start, end = span
    # Text is found across line breaks, in order, within the paragraph
    hits = layout.find("the wake recovers", start, end)
    assert len(hits) == 2 and hits[0][1] < hits[1][1]
    assert layout.find("the wake recovers", (1, hits[0][2] + 1), end) == [
        hits[1]
    ]
    assert layout.find("absent text") == [] and layout.find("  ") == []
    # A thread goes on its highlighted text, else its paragraph's first line
    pos = layout.place(para, "the wake recovers", 1)
    assert pos is not None and pos["pageNumber"] == 1
    assert pos == layout.position(*hits[1])
    first = layout.place(para, None)
    assert first is not None and len(first["rects"]) == 1
    assert first["boundingRect"]["y1"] < pos["boundingRect"]["y1"]
    rect = first["rects"][0]
    page = layout.pages[0]
    assert (rect["width"], rect["height"]) == (page.width, page.height)
    assert (
        layout.place("Nothing like this is in the document at all.", None)
        is None
    )
    # A selection made in a viewer at another scale gives back where it
    # starts and the text of its lines
    scaled = {
        "boundingRect": {
            k: v * 2 if k in ("x1", "x2", "y1", "y2", "width", "height") else v
            for k, v in pos["boundingRect"].items()
        },
        "rects": [
            {
                k: v * 2
                if k in ("x1", "x2", "y1", "y2", "width", "height")
                else v
                for k, v in r.items()
            }
            for r in pos["rects"]
        ],
        "pageNumber": 1,
    }
    selection = layout.selection(scaled)
    assert selection is not None
    (n, i), context = selection
    assert (n, i) == (1, hits[1][1])
    assert "so the wake recovers" in context
    # Hyphenation and line breaks don't survive normalizing a selection
    assert (
        pdftext.normalize_selection("re-\ncovers  ﬁne’s") == "recovers fine's"
    )
