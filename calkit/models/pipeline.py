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
        "python-script",
        "latex",
        "bash-script",
        "sh-script",
        "matlab-script",
        "sh-command",
        "bash-command",
        "jupyter-notebook",
    ]
    environment: str
    wdir: str | None = None
    inputs: list[str] = []  # TODO: Support other input types
    outputs: (
        list[str] | list[PathOutput]
    ) = []  # TODO: Support database outputs
    always_run: bool = False


class PythonScriptStage(Stage):
    kind: Literal["python-script"]
    script_path: str
    args: list[str] = []

    def to_dvc(self) -> dict:
        """Convert to a DVC stage."""
        cmd = f"calkit xenv -n {self.environment} -- python {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        deps = [self.script_path]
        for i in self.inputs:
            if i not in deps:
                deps.append(i)
        outs = []
        for out in self.outputs:
            if isinstance(out, str):
                outs += out
            elif isinstance(out, PathOutput):
                pass
        stage = {"cmd": cmd, "deps": deps, "outs": outs}
        if self.wdir is not None:
            stage["wdir"] = self.wdir
        if self.always_run:
            stage["always_changed"] = True
        return stage


class LatexStage(Stage):
    kind: Literal["latex"]
    target_path: str


class MatlabScriptStage(Stage):
    kind: Literal["matlab-script"]
    script_path: str


class Pipeline(BaseModel):
    stages: dict[str, PythonScriptStage | LatexStage | MatlabScriptStage]
