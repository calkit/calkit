"""Reviews of a publication, kept in Markdown files beside it.

A reviewer usually has only a PDF to comment on, with no source to put
comments in, and has to paste the review into a form. So each comment is a
numbered item in a Markdown review file, in a section whose heading says
"comments", e.g., ``## Comments`` or ``## Minor comments``. Where it's about
is written into the item, so the authors can find it and a PDF viewer can
highlight it again::

    1. Page 3, line 120 ("Reynolds number"): Which length is it based on?

A publication lists its reviews in ``calkit.yaml``, whether the project is
the reviewer's or the authors'::

    publications:
      - path: paper/manuscript.pdf
        reviews:
          - path: paper/review.md
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass
from typing import Any

_ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
# Where an item is about, e.g., Page 3, lines 120-122 ("some text"):
_WHERE_RE = re.compile(
    r"^Page (\d+)(?:, lines? (\d+)(?:[-–](\d+))?)?"
    r'(?: \("(.*?)"\))?: (.*)$',
    re.S,
)


@dataclass
class ReviewComment:
    """One numbered item in a review file's comments."""

    text: str
    page: int | None = None
    line: int | None = None
    end_line: int | None = None
    quote: str | None = None
    number: int = 0
    # Where the item is in the review file, 1-based, and how many lines
    lineno: int = 0
    nlines: int = 0

    def render(self) -> list[str]:
        """The item as Markdown lines."""
        where = ""
        if self.page is not None:
            where = f"Page {self.page}"
            if self.line is not None:
                lines = (
                    f"lines {self.line}-{self.end_line}"
                    if self.end_line and self.end_line != self.line
                    else f"line {self.line}"
                )
                where += f", {lines}"
            if self.quote:
                where += f' ("{" ".join(self.quote.split())}")'
            where += ": "
        marker = f"{self.number}. "
        body = (where + self.text.strip()).split("\n")
        return [marker + body[0]] + [
            " " * len(marker) + part if part.strip() else ""
            for part in body[1:]
        ]


def is_comments_heading(title: str) -> bool:
    return "comment" in title.lower()


def parse(lines: list[str]) -> list[ReviewComment]:
    """The numbered items in a review file's comments sections."""
    out: list[ReviewComment] = []
    in_comments = False
    current: list[str] | None = None
    start = 0
    indent = 0

    def finish(end: int) -> None:
        nonlocal current
        if current is None:
            return
        # Blank lines between items aren't part of either
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        item = _ITEM_RE.match(current[0])
        assert item is not None
        rest = [
            part[min(indent, len(part) - len(part.lstrip())) :]
            for part in current[1:]
        ]
        body = "\n".join([item.group(2)] + rest).rstrip()
        comment = ReviewComment(text=body, number=int(item.group(1)))
        where = _WHERE_RE.match(body)
        if where:
            comment.page = int(where.group(1))
            if where.group(2):
                comment.line = int(where.group(2))
            if where.group(3):
                comment.end_line = int(where.group(3))
            comment.quote = where.group(4) or None
            comment.text = where.group(5)
        comment.lineno = start + 1
        comment.nlines = end - start
        out.append(comment)
        current = None

    for i, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if heading:
            finish(i)
            in_comments = is_comments_heading(heading.group(1))
            continue
        if not in_comments:
            continue
        item = _ITEM_RE.match(line)
        if item:
            finish(i)
            current, start = [line], i
            indent = len(line) - len(item.group(2))
        # An indented line continues the item, and so does an unindented
        # one right after its text, as in Markdown
        elif current is not None and (
            not line.strip()
            or line.startswith(" " * indent)
            or current[-1].strip()
        ):
            current.append(line)
        else:
            finish(i)
    finish(len(lines))
    return out


def renumber(lines: list[str]) -> list[str]:
    """Number each comments section's items from 1, in order."""
    out = list(lines)
    section_at = []
    section = -1
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line):
            section = i
        section_at.append(section)
    counts: dict[int, int] = {}
    for comment in parse(lines):
        section = section_at[comment.lineno - 1]
        counts[section] = counts.get(section, 0) + 1
        i = comment.lineno - 1
        out[i] = re.sub(r"^\d+", str(counts[section]), out[i])
    return out


def add(lines: list[str], comment: ReviewComment) -> list[str]:
    """Append a comment to the last comments section, making one if
    there's none, and return the new lines."""
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    sections = [
        i
        for i, line in enumerate(out)
        if (h := _HEADING_RE.match(line)) and is_comments_heading(h.group(1))
    ]
    if not sections:
        out += ([""] if out else []) + ["## Comments"]
        sections = [len(out) - 1]
    section = sections[-1]
    # The section runs to the next heading, less its trailing blank lines
    end = next(
        (i for i in range(section + 1, len(out)) if _HEADING_RE.match(out[i])),
        len(out),
    )
    at = end
    while at > section + 1 and not out[at - 1].strip():
        at -= 1
    del out[at:end]
    comment.number = 1 + sum(
        1 for c in parse(out) if section < c.lineno - 1 < at
    )
    rendered = comment.render()
    out[at:at] = [""] + rendered + ([""] if at < len(out) else [])
    comment.lineno = at + 2
    comment.nlines = len(rendered)
    return out + [""]


def delete(lines: list[str], number: int) -> list[str]:
    """Remove the comment with this ordinal, counting across sections from
    1, and renumber the rest."""
    comments = parse(lines)
    if not 1 <= number <= len(comments):
        raise ValueError(
            f"No comment {number}; there are {len(comments)} in the review"
        )
    comment = comments[number - 1]
    start, end = comment.lineno - 1, comment.lineno - 1 + comment.nlines
    # Take one blank line with it, so the list stays evenly spaced
    if end < len(lines) and not lines[end].strip():
        end += 1
    elif start > 0 and not lines[start - 1].strip():
        start -= 1
    return renumber(lines[:start] + lines[end:])


def to_dict(path: str, ordinal: int, comment: ReviewComment) -> dict[str, Any]:
    """A comment as ``calkit list comments --json`` reports a thread, plus
    where in the PDF it's about."""
    return {
        "id": str(ordinal),
        "path": path,
        "line": comment.lineno,
        "nlines": comment.nlines,
        "resolved": False,
        "issue": None,
        "highlight": (
            {"text": comment.quote, "occ": 0} if comment.quote else None
        ),
        "anchor": None,
        "messages": [
            {"author": "", "email": None, "date": None, "text": comment.text}
        ],
        "attrs": {},
        "review": True,
        "page": comment.page,
        "pdf_line": comment.line,
        "pdf_end_line": comment.end_line,
    }


def review_path(pdf: str, ck_info: dict) -> str | None:
    """The first review file the publication at this path lists, if any."""
    want = posixpath.normpath(pdf)
    for pub in ck_info.get("publications") or []:
        if not isinstance(pub, dict) or not pub.get("path"):
            continue
        if posixpath.normpath(str(pub["path"])) != want:
            continue
        for review in pub.get("reviews") or []:
            if isinstance(review, dict) and review.get("path"):
                return str(review["path"])
    return None


def ensure_review(pdf: str, wdir: str | None = None) -> str:
    """The review file for a PDF, listing it in ``calkit.yaml`` and making
    it beside the PDF if it isn't yet.

    Parameters
    ----------
    pdf : str
        Project-relative path of the PDF.
    wdir : str, optional
        Project working directory, defaulting to the current one.

    Returns
    -------
    str
        Project-relative path of the review file.
    """
    import calkit

    ck_info = calkit.load_calkit_info(wdir=wdir)
    path = review_path(pdf, ck_info)
    if path is None:
        path = posixpath.join(posixpath.dirname(pdf), "review.md")
        pubs = ck_info.setdefault("publications", [])
        want = posixpath.normpath(pdf)
        pub = next(
            (
                p
                for p in pubs
                if isinstance(p, dict)
                and posixpath.normpath(str(p.get("path", ""))) == want
            ),
            None,
        )
        if pub is None:
            pub = {"path": pdf}
            pubs.append(pub)
        pub.setdefault("reviews", []).append({"path": path})
        calkit.save_calkit_info(ck_info, wdir=wdir)
    full = os.path.join(wdir or ".", path)
    if not os.path.isfile(full):
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("## Comments\n")
    return path
