"""Records of LaTeX review round trips through Word.

Written to ``.calkit/latex/docx-exports`` and ``.calkit/latex/docx-merges``,
one JSON file per run, named by export ID (plus a timestamp for merges).
Committing them is optional; they're a history of what the CLI did, and
what a hub would index if it wanted to track reviews.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class LatexDocxExport(BaseModel):
    id: str = Field(description="Identifier carried inside the .docx.")
    created: datetime
    source: str = Field(description="Main .tex file the PDF came from.")
    pdf: str
    docx: str
    rev: str | None = Field(
        default=None, description="Git commit at export, if in a repo."
    )
    dirty: bool = Field(
        default=False, description="Whether the source had uncommitted edits."
    )
    permission: str = Field(
        default="suggest", description="'suggest' or 'comment'."
    )
    paragraphs: int = Field(description="Paragraphs anchored to the source.")
    unanchored: int = Field(
        default=0, description="Paragraphs with no source location."
    )
    comments_exported: int = 0
    files: dict[str, str] = Field(
        default={},
        description=(
            "Hash of every file involved (.tex inputs, PDF, .docx), as "
            "'md5:<hex>'."
        ),
    )


class LatexDocxMergeChange(BaseModel):
    key: str | None = Field(
        default=None,
        description=(
            "Bookmark of the paragraph the change was made in, stable for "
            "the life of the export, so a decision can be remembered."
        ),
    )
    path: str
    lineno: int
    status: str = Field(
        description=(
            "'applied', 'already-applied', 'pending', 'unplaced', or "
            "'rejected'."
        )
    )
    author: str | None = Field(
        default=None,
        description=(
            "Who made the change, known only while it's still tracked; "
            "Word drops the author when a change is accepted."
        ),
    )


class LatexDocxMergeComment(BaseModel):
    key: str = Field(description="Word's paragraph ID for the thread root.")
    path: str
    lineno: int
    status: str = Field(
        description="'added', 'updated', 'unchanged', 'unplaced', 'dismissed'."
    )
    author: str | None = None


class LatexDocxEdit(BaseModel):
    """A paragraph the reviewer changed, as one decision for the lead.

    ``proposed`` is the paragraph as it reads with every tracked change
    accepted, which is what applying it writes. ``status`` says whether
    that can happen:

    - ``applicable``: accepted in Word or made with tracking off; applied
      by a merge unless rejected.
    - ``pending``: still a tracked change in Word; applied only when
      accepted explicitly.
    - ``already-applied``: the source already reads this way.
    - ``unplaced``: the paragraph or its edited words can't be found in
      the source; ``reason`` says which. Apply by hand.
    - ``rejected``: declined in an earlier merge of this document.
    """

    key: str
    path: str
    lineno: int
    status: str
    sent: str = Field(description="The paragraph as it was exported.")
    proposed: str
    authors: list[str] = []
    reason: str | None = None
    source: list[str] = Field(
        default=[], description="The source lines the paragraph came from."
    )
    result: list[str] | None = Field(
        default=None, description="Those lines after the edit, if placeable."
    )


class LatexDocxCommentEntry(BaseModel):
    author: str
    text: str
    date: str | None = None


class LatexDocxComment(BaseModel):
    """A comment thread from the document, and what merging does with it.

    ``status`` is ``new`` for a thread the source doesn't have, ``updated``
    when the source has it but replies or resolution changed, ``unchanged``
    when it's already there as is, ``unplaced`` when its paragraph can't be
    found, and ``dismissed`` when an earlier merge declined it.
    """

    key: str
    path: str
    lineno: int
    status: str
    entries: list[LatexDocxCommentEntry]
    highlight: str | None = None
    resolved: bool = False
    source: list[str] = []


class LatexDocxMerge(BaseModel):
    export_id: str = Field(description="Export the merged document came from.")
    created: datetime
    docx: str
    rev: str | None = Field(default=None, description="Git commit at merge.")
    authors: list[str] = Field(
        default=[],
        description="Everyone named on a tracked change or comment.",
    )
    last_modified_by: str | None = Field(
        default=None, description="Who last saved the document, per Word."
    )
    changes: list[LatexDocxMergeChange] = []
    comments: list[LatexDocxMergeComment] = []
    comments_added: int = 0
    comments_updated: int = 0
    files: dict[str, str] = Field(
        default={},
        description=(
            "Hash of the .docx and every .tex file after merging, as "
            "'md5:<hex>'."
        ),
    )
