"""Pipeline models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class PipelineStep(BaseModel):
    """A step in the pipeline, analogous to a stage in DVC syntax."""

    kind: Literal[
        "dvc",
        "python-script",
        "bash-script",
        "sh-script",
        "matlab-script",
        "sh-command",
        "bash-command",
    ]
    environment: str | None = None
    wdir: str | None = None
    inputs: list[str]
    outputs: list[str, dict]
    always_run: bool = False


class Pipeline(BaseModel):
    """A computational pipeline, which will typically be transpiled to a DVC
    pipeline.
    """

    kind: Literal["dvc"] = "dvc"
    steps: dict[str, PipelineStep] = {}
