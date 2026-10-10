"""Reading and comparing the text of a PDF.

A pull request that regenerates a paper shows only its ``.dvc`` pointer
changing, and looking at the two builds side by side answers "did the
figures move" better than "did the wording change". This reads the words
out of both and compares them.

Extraction is inherently lossy: a PDF stores glyphs at positions, not
sentences. Everything here is about getting from that back to something
worth diffing.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel

# Bounds on what will be read at all, so one enormous artifact can't tie
# up a worker.
MAX_PDF_BYTES = 50_000_000
MAX_PAGES = 300
# Words of unchanged text kept either side of a change. Enough to place
# the change in the document without returning the whole paper twice.
CONTEXT_WORDS = 12


class DiffSegment(BaseModel):
    kind: Literal["equal", "insert", "delete"]
    text: str
    # Set on an equal segment standing in for text that was left out
    elided: bool = False


class TextDiff(BaseModel):
    path: str
    base_ref: str
    head_ref: str
    identical: bool
    segments: list[DiffSegment]
    # Set when a document was too long to read in full
    truncated: bool = False


def extract_text(data: bytes) -> tuple[str, bool]:
    """Return a PDF's text, and whether it was cut short at MAX_PAGES."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = reader.pages
    truncated = len(pages) > MAX_PAGES
    return (
        "\n".join(page.extract_text() or "" for page in pages[:MAX_PAGES]),
        truncated,
    )


def normalize(text: str) -> str:
    """Reduce extracted text to what a reader would call the words.

    Without this, two builds of the same document differ in ways nobody
    means: LaTeX writes "fi" as a single ligature glyph and toolchains
    decompose it differently, a line break mid-word leaves a hyphen, and
    the spacing between glyphs comes back as whatever the layout put
    there.
    """
    text = unicodedata.normalize("NFKC", text)
    # A word broken across lines is one word
    text = re.sub(r"-\n(\w)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def diff(
    base: str, head: str, path: str, base_ref: str, head_ref: str
) -> TextDiff:
    """Compare two documents' text, word by word.

    Word level rather than line level because a PDF has no lines to speak
    of -- where text wraps depends on the layout, so inserting a sentence
    would otherwise mark every following line as changed.
    """
    base_words = normalize(base).split(" ")
    head_words = normalize(head).split(" ")
    matcher = difflib.SequenceMatcher(
        None, base_words, head_words, autojunk=False
    )
    segments: list[DiffSegment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            words = base_words[i1:i2]
            # Long runs of unchanged text are the bulk of any document;
            # only what surrounds a change is worth returning
            if len(words) > CONTEXT_WORDS * 2 + 1:
                head_context = " ".join(words[:CONTEXT_WORDS])
                tail_context = " ".join(words[-CONTEXT_WORDS:])
                if segments:
                    segments.append(
                        DiffSegment(kind="equal", text=head_context)
                    )
                segments.append(
                    DiffSegment(kind="equal", text="", elided=True)
                )
                segments.append(DiffSegment(kind="equal", text=tail_context))
            else:
                segments.append(
                    DiffSegment(kind="equal", text=" ".join(words))
                )
            continue
        if tag in ("delete", "replace"):
            segments.append(
                DiffSegment(kind="delete", text=" ".join(base_words[i1:i2]))
            )
        if tag in ("insert", "replace"):
            segments.append(
                DiffSegment(kind="insert", text=" ".join(head_words[j1:j2]))
            )
    identical = not any(s.kind != "equal" for s in segments)
    return TextDiff(
        path=path,
        base_ref=base_ref,
        head_ref=head_ref,
        identical=identical,
        # Nothing to show when the words are the same; the segments would
        # just be the document
        segments=[] if identical else segments,
    )


# Characters a PDF's layout adds or changes, and that the same text in the
# source wouldn't have, e.g., hyphens at line breaks and the spacing
# between glyphs
_SKIP_RE = re.compile(r"[\s\-­‐-―]")
_CHAR_MAP = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    # Math as typeset: a minus sign, and an increment for a capital delta
    "\u2212": "-",
    "\u2206": "\u0394",
}


def _norm_char(c: str) -> str:
    out = unicodedata.normalize("NFKC", _CHAR_MAP.get(c, c))
    return "".join(
        ch
        for ch in out
        if not _SKIP_RE.match(ch) and not unicodedata.category(ch)[0] == "C"
    )


def normalize_selection(text: str) -> str:
    """Text selected in a PDF as it reads in its paragraph, without the
    hyphenation and line breaks of the layout."""
    text = "".join(_CHAR_MAP.get(c, c) for c in text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(\w)[-­]\s*\n\s*(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


class _Page:
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height
        # Each character and its box: left, bottom, right, top
        self.chars: list[str] = []
        self.boxes: list[tuple[float, float, float, float]] = []
        # The text with what the layout adds left out, and the character
        # each of its characters came from
        self.norm = ""
        self.index: list[int] = []

    def mid(self, i: int) -> float:
        """How far down the page a character's middle is."""
        _, bottom, _, top = self.boxes[i]
        return self.height - (top + bottom) / 2


# A place in a document: page number from 1, and character on the page
Pos = tuple[int, int]


class PdfLayout:
    """Where a PDF's text is, for finding a source paragraph's place in it.

    A PDF built without SyncTeX, or built by someone else, carries nothing
    that maps it to its source, so paragraphs and the text selected in them
    are found by their words.
    """

    def __init__(self, data: bytes) -> None:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_c

        self.pages: list[_Page] = []
        pdf = pdfium.PdfDocument(data)
        try:
            for i in range(min(len(pdf), MAX_PAGES)):
                page = pdf[i]
                width, height = page.get_size()
                p = _Page(width, height)
                textpage = page.get_textpage()
                for j in range(textpage.count_chars()):
                    p.chars.append(
                        chr(pdfium_c.FPDFText_GetUnicode(textpage, j))
                    )
                    p.boxes.append(textpage.get_charbox(j))
                    for ch in _norm_char(p.chars[-1]):
                        p.norm += ch
                        p.index.append(j)
                textpage.close()
                page.close()
                self.pages.append(p)
        finally:
            pdf.close()

    def find(
        self, text: str, start: Pos = (1, 0), end: Pos | None = None
    ) -> list[tuple[int, int, int]]:
        """Where some text is, as page and first and last character, from
        one place to another, in reading order. Spacing and dashes don't
        count, since a PDF's line breaks and hyphenation rarely match."""
        needle = "".join(_norm_char(c) for c in text)
        out: list[tuple[int, int, int]] = []
        if not needle:
            return out
        last = end[0] if end else len(self.pages)
        for n in range(start[0], last + 1):
            p = self.pages[n - 1]
            i = p.norm.find(needle)
            while i >= 0:
                first = p.index[i]
                final = p.index[i + len(needle) - 1]
                if (n, first) >= start and (end is None or (n, final) <= end):
                    out.append((n, first, final))
                i = p.norm.find(needle, i + 1)
        return out

    def paragraph(self, text: str) -> tuple[Pos, Pos] | None:
        """Where a source paragraph, as rendered text, starts and ends.

        Text from the source loses its math, citations, and references, so
        runs of its words are looked for rather than all of it, from the
        start for where it starts and from the end for where it ends.
        """
        words = text.split()
        if not words:
            return None
        # Runs of fewer words for a short paragraph, e.g., an equation
        sizes = [s for s in (8, 5) if s <= len(words)] or [len(words)]
        start = fallback = None
        for size in sizes:
            for i in range(min(20, len(words) - size + 1)):
                hits = self.find(" ".join(words[i : i + size]))
                if len(hits) == 1:
                    start = hits[0]
                    break
                if hits and fallback is None:
                    fallback = hits[0]
            if start is not None:
                break
        start = start or fallback
        if start is None:
            return None
        begin = (start[0], start[1])
        for size in sizes:
            for i in range(
                len(words) - size, max(len(words) - size - 20, -1), -1
            ):
                hits = self.find(" ".join(words[i : i + size]), begin)
                if hits:
                    return begin, (hits[0][0], hits[0][2])
        return begin, (start[0], start[2])

    def position(self, n: int, first: int, last: int) -> dict:
        """A run of characters as react-pdf-highlighter's ScaledPosition,
        in points from the page's top-left, a rectangle per line."""
        p = self.pages[n - 1]
        rects: list[list[float]] = []
        prev = None
        for i in range(first, last + 1):
            left, bottom, right, top = p.boxes[i]
            if right <= left or p.chars[i].isspace():
                continue
            # A character starting left of the one before, or lower down,
            # starts a new line. Not left of where it ends: a ligature's
            # characters share one glyph's box.
            new_line = prev is None or (
                left < prev[0] - 1 or abs(bottom - prev[1]) > (top - bottom)
            )
            if new_line:
                rects.append([left, bottom, right, top])
            else:
                r = rects[-1]
                rects[-1] = [
                    min(r[0], left),
                    min(r[1], bottom),
                    max(r[2], right),
                    max(r[3], top),
                ]
            prev = (left, bottom, right, top)

        def scaled(r: list[float]) -> dict:
            return {
                "x1": r[0],
                "y1": p.height - r[3],
                "x2": r[2],
                "y2": p.height - r[1],
                "width": p.width,
                "height": p.height,
                "pageNumber": n,
            }

        out = [scaled(r) for r in rects] or [
            scaled([0, p.height, p.width, p.height])
        ]
        bound = [
            min(r["x1"] for r in out),
            min(r["y1"] for r in out),
            max(r["x2"] for r in out),
            max(r["y2"] for r in out),
        ]
        return {
            "boundingRect": {
                "x1": bound[0],
                "y1": bound[1],
                "x2": bound[2],
                "y2": bound[3],
                "width": p.width,
                "height": p.height,
                "pageNumber": n,
            },
            "rects": out,
            "pageNumber": n,
        }

    def place(
        self, paragraph: str, highlight: str | None, occ: int = 0
    ) -> dict | None:
        """Where a comment thread goes: its highlighted text, or without
        one, the first line of its paragraph."""
        span = self.paragraph(paragraph)
        if span is None:
            return None
        start, end = span
        if highlight:
            hits = self.find(highlight, start, end)
            if hits:
                n, first, last = hits[occ] if occ < len(hits) else hits[0]
                return self.position(n, first, last)
        n, first = start
        p = self.pages[n - 1]
        _, bottom0, _, top0 = p.boxes[first]
        last = first
        for i in range(first + 1, len(p.chars)):
            left, bottom, right, _ = p.boxes[i]
            # The line ends where the text moves down a line
            if p.chars[i] in "\r\n" or (
                right > left and abs(bottom - bottom0) > top0 - bottom0
            ):
                break
            if right > left:
                last = i
        return self.position(n, first, last)

    def selection(self, position: dict) -> tuple[Pos, str] | None:
        """Where a selection made in a viewer starts, and the text of the
        lines it's on, from its ScaledPosition."""
        rects = position.get("rects") or [position.get("boundingRect")]
        rects = [r for r in rects if r]
        if not rects:
            return None
        n = int(rects[0].get("pageNumber") or position.get("pageNumber") or 1)
        if not 1 <= n <= len(self.pages):
            return None
        p = self.pages[n - 1]

        def to_points(r: dict) -> tuple[float, float, float, float]:
            sx = p.width / float(r.get("width") or p.width)
            sy = p.height / float(r.get("height") or p.height)
            return (
                r["x1"] * sx,
                r["y1"] * sy,
                r["x2"] * sx,
                r["y2"] * sy,
            )

        boxes = [to_points(r) for r in rects if r.get("pageNumber", n) == n]
        top = min(b[1] for b in boxes)
        bottom = max(b[3] for b in boxes)
        on_lines = [
            i
            for i in range(len(p.chars))
            if p.boxes[i][2] > p.boxes[i][0] and top <= p.mid(i) <= bottom
        ]
        if not on_lines:
            return None
        x1, y1, _, y2 = boxes[0]
        first = min(
            (
                i
                for i in on_lines
                if y1 <= p.mid(i) <= y2 and p.boxes[i][2] > x1
            ),
            default=on_lines[0],
        )
        context = "".join(p.chars[on_lines[0] : on_lines[-1] + 1])
        return (n, first), context
