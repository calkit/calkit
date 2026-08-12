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
