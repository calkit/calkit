"""Pipeline models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Input(BaseModel):
    kind: Literal["path", "python-object", "file-segment", "database-table"]


class PathInput(Input):
    kind: Literal["path"]
    path: str


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
    path: str
    storage: Literal["git", "dvc"] | None = "dvc"
    delete_before_run: bool = True


class DatabaseTableOutput(BaseModel):
    kind: Literal["database-table"]
    uri: str
    database_name: str | None = None
    table_name: str


class Stage(BaseModel):
    """A stage in the pipeline."""

    kind: Literal[
        "dvc",
        "python-script",
        "bash-script",
        "sh-script",
        "matlab-script",
        "sh-command",
        "bash-command",
        "jupyter-notebook",
    ]
    environment: str
    wdir: str | None = None
    inputs: list[str]  # TODO: Support other input types
    outputs: list[str] | list[PathOutput]  # TODO: Support database outputs
    always_run: bool = False


class PythonScriptStage(Stage):
    kind: Literal["python-script"]
    script_path: str
    args: list[str] = []


class MatlabScriptStage(Stage):
    kind: Literal["matlab-script"]
    script_path: str


class Pipeline(BaseModel):
    stages: dict[str, PythonScriptStage | MatlabScriptStage]
