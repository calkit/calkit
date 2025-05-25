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
    outputs: list[str | PathOutput] = []  # TODO: Support database outputs
    always_run: bool = False

    @property
    def dvc_cmd(self) -> str:
        raise NotImplementedError

    @property
    def dvc_deps(self) -> list[str]:
        deps = []
        for i in self.inputs:
            if i not in deps:
                deps.append(i)
        return deps

    @property
    def dvc_outs(self) -> list[str | dict]:
        outs = []
        for out in self.outputs:
            if isinstance(out, str):
                outs.append(out)
            elif isinstance(out, PathOutput):
                outs.append(
                    {
                        out.path: dict(
                            cache=True if out.storage == "dvc" else False,
                            persist=not out.delete_before_run,
                        )
                    }
                )
        return outs

    @property
    def xenv_cmd(self) -> str:
        return f"calkit xenv -n {self.environment} --no-check"

    def to_dvc(self) -> dict:
        """Convert to a DVC stage."""
        cmd = self.dvc_cmd
        deps = self.dvc_deps
        for i in self.inputs:
            if i not in deps:
                deps.append(i)
        outs = self.dvc_outs
        stage = {"cmd": cmd, "deps": deps, "outs": outs}
        if self.wdir is not None:
            stage["wdir"] = self.wdir
        if self.always_run:
            stage["always_changed"] = True
        return stage


class PythonScriptStage(Stage):
    kind: Literal["python-script"]
    script_path: str
    args: list[str] = []

    @property
    def dvc_cmd(self) -> str:
        cmd = f"{self.xenv_cmd} -- python {self.script_path}"
        for arg in self.args:
            cmd += f" {arg}"
        return cmd

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps


class LatexStage(Stage):
    kind: Literal["latex"]
    target_path: str

    @property
    def dvc_cmd(self) -> str:
        return (
            f"{self.xenv_cmd} -- "
            f"latexmk -cd -interaction=nonstopmode -pdf {self.target_path}"
        )

    @property
    def dvc_deps(self) -> list[str]:
        return [self.target_path] + super().dvc_deps


class MatlabScriptStage(Stage):
    kind: Literal["matlab-script"]
    script_path: str

    @property
    def dvc_deps(self) -> list[str]:
        return [self.script_path] + super().dvc_deps

    @property
    def dvc_cmd(self) -> str:
        return f"matlab -noFigureWindows -batch \"run('{self.script_path}');\""


class Pipeline(BaseModel):
    stages: dict[str, PythonScriptStage | LatexStage | MatlabScriptStage]
