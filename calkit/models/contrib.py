"""Contribution requests as recorded in a project.

A request is an ask for a specific contribution to a specific artifact,
sent to a specific person: "please review this manuscript," with a Word
copy attached, at a pinned revision. What the lead decided about it
lives here, in the repo, one file per request under
``.calkit/requests``; the hub keeps only what delivery needs (the link's
token, whether the email went out) and points at the file.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ContribRequestStatus = Literal["open", "closed", "revoked"]


class ContribRequestTarget(BaseModel):
    kind: Literal[
        "project",
        "publication",
        "figure",
        "figures",
        "presentation",
        "dataset",
        "notebook",
        "stage",
        "path",
    ] = "publication"
    path: str | None = None


class ContribRequestRecipient(BaseModel):
    name: str | None = None
    email: str | None = None


class ContribResponseRecord(BaseModel):
    """Something that came back: for a Word review, the reviewed copy."""

    path: str = Field(description="Where the response was saved in the repo.")
    name: str | None = None
    email: str | None = None
    message: str | None = None
    received: datetime


class ContribRequestRecord(BaseModel):
    id: str
    title: str
    message: str | None = None
    target: ContribRequestTarget = ContribRequestTarget()
    document: str | None = Field(
        default=None,
        description=(
            "A copy of the target sent with the request, e.g., the Word "
            "export of a manuscript, as a path in the repo."
        ),
    )
    permission: Literal["view", "comment", "suggest", "edit"] = "suggest"
    identity: Literal["anonymous", "email", "account"] = "anonymous"
    to: ContribRequestRecipient | None = None
    public: bool = False
    created: datetime
    created_by: str | None = Field(
        default=None, description="Email of whoever sent it."
    )
    rev: str | None = Field(
        default=None, description="Commit the request was created at."
    )
    due: datetime | None = None
    expires: datetime | None = None
    status: ContribRequestStatus = "open"
    responses: list[ContribResponseRecord] = []
