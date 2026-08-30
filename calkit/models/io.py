"""Models for inputs and outputs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InputsFromStageOutputs(BaseModel):
    from_stage_outputs: str = Field(
        description="Name of a stage whose outputs are inputs to this one."
    )


class PathInput(BaseModel):
    """An input written as an object carrying a path.

    Prefer a plain path string. This exists so a stage keeps working when an
    output is copied verbatim into another stage's ``inputs``, which is how
    entries like ``{path: ..., storage: ...}`` show up in the wild. Only
    ``path`` is used: an input is a dependency wherever it happens to be
    stored, so the other keys are carried along and ignored.

    Extra keys are allowed deliberately, both to tolerate whatever came along
    with a copied output and to leave room for object inputs that aren't
    paths at all, e.g., a database table. They are kept rather than dropped,
    since a stage rewritten back to calkit.yaml (see
    ``Pipeline.convert_sbatch_stages``) would otherwise silently lose them.
    """

    model_config = ConfigDict(extra="allow")
    path: str = Field(description="Path to the input file or directory.")


class Input(BaseModel):
    kind: Literal["path", "python-object", "file-segment", "database-table"]


class PythonObjectInput(Input):
    kind: Literal["python-object"]
    module: str
    object_name: str


class FileSegmentInput(Input):
    kind: Literal["file-segment"]
    path: str
    start_line: int
    end_line: int


class DatabaseTableInput(Input):
    kind: Literal["database-table"]
    database_uri: str
    database_name: str | None = None
    table_name: str


class PathOutput(BaseModel):
    path: str = Field(description="Path to the output file or directory.")
    storage: Literal["git", "dvc", "dvc-zip"] | None = Field(
        default="dvc",
        description="Where to store this output. Use null to leave it "
        "untracked.",
    )
    delete_before_run: bool = Field(
        default=True,
        description="Delete this output before the stage runs.",
    )
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")


class DatabaseTableOutput(BaseModel):
    kind: Literal["database-table"]
    uri: str
    database_name: str | None = None
    table_name: str
