"""Records of LaTeX review round trips through Word.

Written to ``.calkit/latex/docx-exports`` and ``.calkit/latex/docx-merges``,
one JSON file per run, named by export ID (plus a timestamp for merges).
Committing them is optional; they're a history of what the CLI did, and
what a hub would index if it wanted to track reviews.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DocxExport(BaseModel):
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


class DocxMergeChange(BaseModel):
    path: str
    lineno: int
    status: str = Field(
        description="'applied', 'already-applied', 'pending', 'unplaced'."
    )
    author: str | None = Field(
        default=None,
        description=(
            "Who made the change, known only while it's still tracked; "
            "Word drops the author when a change is accepted."
        ),
    )


class DocxMerge(BaseModel):
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
    changes: list[DocxMergeChange] = []
    comments_added: int = 0
    comments_updated: int = 0
    files: dict[str, str] = Field(
        default={},
        description=(
            "Hash of the .docx and every .tex file after merging, as "
            "'md5:<hex>'."
        ),
    )
