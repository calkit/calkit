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
