"""Tests for ``calkit.reviews``."""

from pathlib import Path

import pytest

import calkit
import calkit.reviews as reviews


@pytest.fixture
def tmp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture to change to a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_comments_are_numbered_items_saying_where(tmp_dir: Path) -> None:
    text = """# Review

A summary, with a list that isn't comments:

1. Not a comment.

## Major comments

1. Page 3, line 120 ("Reynolds number"): Which length is it based on?
2. Page 5, lines 10-12: This runs
   onto a second line,
lazily onto a third,

   and into a second paragraph.

10. The numbers don't have to be right.

## Minor comments

1. Page 2 ("a "quoted" word"): Typo.

## Other

1. Not a comment either.
"""
    comments = reviews.parse(text.split("\n"))
    assert [c.number for c in comments] == [1, 2, 10, 1]
    first, second, third, fourth = comments
    assert [c.section for c in comments] == [
        "Major comments",
        "Major comments",
        "Major comments",
        "Minor comments",
    ]
    assert (first.page, first.line, first.quote, first.text) == (
        3,
        120,
        "Reynolds number",
        "Which length is it based on?",
    )
    assert (first.lineno, first.nlines) == (9, 1)
    assert (second.page, second.line, second.end_line) == (5, 10, 12)
    assert second.quote is None
    assert second.text == (
        "This runs\nonto a second line,\nlazily onto a third,\n\n"
        "and into a second paragraph."
    )
    assert (second.lineno, second.nlines) == (10, 5)
    assert third.page is None and third.text == (
        "The numbers don't have to be right."
    )
    assert fourth.quote == 'a "quoted" word'
    # Rendering reads back the same
    for comment in comments:
        again = reviews.parse(["## Comments", *comment.render()])[0]
        assert (again.page, again.line, again.end_line, again.quote) == (
            comment.page,
            comment.line,
            comment.end_line,
            comment.quote,
        )
        assert again.text == comment.text
    # Adding goes right after the last comments section's items, numbered
    # after them
    lines = reviews.add(
        text.split("\n"), reviews.ReviewComment(text="New.", page=7)
    )
    added = reviews.parse(lines)[-1]
    assert (added.number, added.page, added.section) == (
        2,
        7,
        "Minor comments",
    )
    assert lines[added.lineno - 2 : added.lineno + 2] == [
        '1. Page 2 ("a "quoted" word"): Typo.',
        "2. Page 7: New.",
        "",
        "## Other",
    ]
    # Or to a named section, matched whatever its case, and numbered by
    # position
    lines = reviews.add(
        text.split("\n"), reviews.ReviewComment(text="Big."), "MAJOR"
    )
    assert [(c.section, c.number) for c in reviews.parse(lines)][3] == (
        "Major comments",
        4,
    )
    # A missing section is made after the others, but major before minor
    lines = ["A summary and assessment."]
    for section, body in [
        ("minor", "Typo."),
        ("major", "Missing data."),
        ("Comments on the figures", "Why?"),
        ("major", "No baseline."),
        (None, "And this."),
    ]:
        lines = reviews.add(lines, reviews.ReviewComment(text=body), section)
    assert "\n".join(lines) == (
        "A summary and assessment.\n\n"
        "## Major comments\n\n1. Missing data.\n2. No baseline.\n\n"
        "## Minor comments\n\n1. Typo.\n\n"
        "## Comments on the figures\n\n1. Why?\n2. And this.\n"
    )
    # Deleting from a list without blank lines leaves none behind
    lines = reviews.delete(lines, 1)
    assert "## Major comments\n\n1. No baseline.\n\n## Minor" in (
        "\n".join(lines)
    )
    # Deleting counts across sections and renumbers what's left
    lines = reviews.delete(text.split("\n"), 1)
    assert [c.number for c in reviews.parse(lines)] == [1, 2, 1]
    assert reviews.parse(lines)[0].page == 5
    assert "\n".join(lines).count("\n\n\n") == 0
    with pytest.raises(ValueError, match="No comment 9"):
        reviews.delete(lines, 9)
    # A file with no comments section gets one, and an empty one is filled
    for start in [["A summary."], ["## Comments", ""], []]:
        lines = reviews.add(start, reviews.ReviewComment(text="First."))
        assert lines[-3:] == ["", "1. First.", ""]
        assert reviews.parse(lines)[0].lineno == len(lines) - 1
    assert reviews.add(["A summary."], reviews.ReviewComment(text="x"))[
        :3
    ] == ["A summary.", "", "## Comments"]
    # As JSON, a comment looks like a thread, plus where in the PDF
    out = reviews.to_dict("paper/review.md", 1, first)
    assert (out["number"], out["section"]) == (1, "Major comments")
    assert out["highlight"] == {"text": "Reynolds number", "occ": 0}
    assert (out["page"], out["pdf_line"], out["review"]) == (3, 120, True)
    assert out["messages"][0]["text"] == "Which length is it based on?"


def test_a_publication_lists_its_review(tmp_dir: Path) -> None:
    (tmp_dir / "paper").mkdir()
    (tmp_dir / "paper" / "manuscript.pdf").write_bytes(b"%PDF")
    (tmp_dir / "calkit.yaml").write_text("name: review\n")
    # A review is made beside the PDF and listed under its publication,
    # which is added if it isn't there
    assert reviews.ensure_review("paper/manuscript.pdf") == "paper/review.md"
    assert (tmp_dir / "paper" / "review.md").read_text() == ""
    ck_info = calkit.load_calkit_info()
    assert ck_info["publications"] == [
        {
            "path": "paper/manuscript.pdf",
            "reviews": [{"path": "paper/review.md"}],
        }
    ]
    # One that's listed is used as it is
    (tmp_dir / "paper" / "review.md").unlink()
    ck_info["publications"][0]["reviews"] = [{"path": "notes/mine.md"}]
    calkit.save_calkit_info(ck_info)
    assert reviews.ensure_review("paper/manuscript.pdf") == "notes/mine.md"
    assert (tmp_dir / "notes" / "mine.md").is_file()
    assert reviews.review_path("paper/./manuscript.pdf", ck_info) == (
        "notes/mine.md"
    )
    assert reviews.review_path("other.pdf", ck_info) is None
    # An existing publication gets the review rather than a duplicate
    calkit.save_calkit_info(
        {"publications": [{"path": "paper/manuscript.pdf", "kind": "report"}]}
    )
    reviews.ensure_review("paper/manuscript.pdf")
    pubs = calkit.load_calkit_info()["publications"]
    assert len(pubs) == 1 and pubs[0]["kind"] == "report"
    assert pubs[0]["reviews"] == [{"path": "paper/review.md"}]
    # And the project's model reads it
    info = calkit.load_calkit_info_object()
    assert info.publications[0].reviews[0].path == "paper/review.md"
