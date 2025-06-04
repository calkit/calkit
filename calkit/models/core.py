"""Data models."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from calkit.models.iteration import ParametersType
from calkit.models.pipeline import Pipeline


class _ImportedFromProject(BaseModel):
    project: str
    path: str | None = None
    git_rev: str | None = None
    filter_paths: list[str] | None = None


class _ImportedFromUrl(BaseModel):
    url: str


class _CalkitObject(BaseModel):
    path: str
    title: str
    description: str | None = None
    stage: str | None = None


class Dataset(_CalkitObject):
    pass


class ImportedDataset(Dataset):
    imported_from: _ImportedFromProject | _ImportedFromUrl


class Figure(_CalkitObject):
    pass


class Publication(_CalkitObject):
    kind: Literal[
        "journal-article",
        "conference-paper",
        "presentation",
        "proposal",
        "poster",
        "report",
        "blog",
    ]
    is_published: bool = False
    doi: str | None = None


class ReferenceFile(BaseModel):
    path: str
    key: str


class ReferenceCollection(BaseModel):
    path: str
    files: list[ReferenceFile] = []


class Environment(BaseModel):
    kind: Literal[
        "conda",
        "docker",
        "poetry",
        "npm",
        "yarn",
        "remote-ssh",
        "uv",
        "pixi",
        "venv",
        "uv-venv",
        "renv",
    ]
    path: str | None = None
    description: str | None = None
    stage: str | None = None
    default: bool | None = None


class VenvEnvironment(Environment):
    kind: Literal["venv"]
    prefix: str


class UvVenvEnvironment(Environment):
    kind: Literal["uv-venv"]
    prefix: str


class PixiEnvironment(Environment):
    kind: Literal["pixi"]
    name: str | None = None


class DockerEnvironment(Environment):
    kind: Literal["docker"]
    image: str
    layers: list[str] | None = None
    shell: Literal["bash", "sh"] = "sh"
    platform: str | None = None


class REnvironment(Environment):
    kind: Literal["renv"]
    prefix: str


class SSHEnvironment(BaseModel):
    kind: Literal["ssh"]
    host: str
    user: str
    wdir: str
    key: str | None = None
    send_paths: list[str] = ["./*"]
    get_paths: list[str] = ["*"]


class Software(BaseModel):
    title: str
    path: str
    description: str


class Notebook(_CalkitObject):
    """A Jupyter notebook."""

    pass


class ProcedureInput(BaseModel):
    """An input that might be entered while running a procedure.

    Attributes
    ----------
    name : str
        The name of the input. This will be displayed to the user at the
        prompt like 'Enter {name}:'. Note the column name for the log is the
        key used to identify this input, and they can be different.
    dtype : 'int', 'bool', 'str', or 'float'
        The datatype of the input.
    units : str
        Units of the input value.
    description : str
        Optional longer description of the input.
    """

    name: str | None = None
    dtype: Literal["int", "bool", "str", "float"] | None = None
    units: str | None = None
    description: str | None = None


class ProcedureStep(BaseModel):
    summary: str
    details: str | None = None
    cmd: str | None = None
    wait_before_s: float | None = None
    wait_after_s: float | None = None
    inputs: dict[str, ProcedureInput] | None = None


class Timedelta(BaseModel):
    days: float | None = None
    seconds: float | None = None
    microseconds: float | None = None
    milliseconds: float | None = None
    minutes: float | None = None
    hours: float | None = None
    weeks: float | None = None

    def to_py_timedelta(self) -> timedelta:
        return timedelta(**self.model_dump())


class Procedure(BaseModel):
    """A procedure, typically executed by a human."""

    title: str
    description: str
    steps: list[ProcedureStep]
    imported_from: str | None = None


class Release(BaseModel):
    kind: Literal["project", "publication", "dataset", "model", "figure"]
    url: str | None = None
    doi: str | None = None
    has_suffix: bool = False


class ProjectRelease(Release):
    kind: Literal["project"]


class PublicationRelease(Release):
    kind: Literal["publication"]
    path: str


class DatasetRelease(Release):
    kind: Literal["dataset"]
    path: str


class ModelRelease(Release):
    kind: Literal["model"]
    path: str


class ShowcaseFigure(BaseModel):
    figure: str


class ShowcaseText(BaseModel):
    text: str


class DerivedFromProject(BaseModel):
    project: str
    git_repo_url: str
    git_rev: str


class ProjectStatus(BaseModel):
    timestamp: datetime
    status: Literal["in-progress", "on-hold", "completed"]
    message: str | None = None


class ProjectInfo(BaseModel):
    """All of the project's information or metadata, written to the
    ``calkit.yaml`` file.

    Attributes
    ----------
    parent : str
        The project's parent project, if applicable. This should be set if
        the project was created as a copy of another. This is similar to the
        concept of forking, but unlike a fork, a child project's changes
        are not meant to be merged back into the parent.
        The format of this field should be something like
        {owner_name}/{project_name}, e.g., 'someuser/some-project-name'.
        Note that individual objects can be imported from other projects, but
        that doesn't necessarily make them parent projects.
        This is probably not that important of a distinction.
        The real use case is being able to trace where things came from and
        distinguish what has been newly created here.
    """

    title: str | None = None
    owner: str | None = None
    description: str | None = None
    name: str | None = None
    git_repo_url: str | None = None
    derived_from: DerivedFromProject | None = None
    questions: list[str] = []
    dependencies: list = []
    parameters: ParametersType | None = None
    pipeline: Pipeline | None = None
    datasets: list[Dataset] = []
    figures: list[Figure] = []
    publications: list[Publication] = []
    references: list[ReferenceCollection] = []
    environments: dict[
        str,
        Environment
        | DockerEnvironment
        | VenvEnvironment
        | UvVenvEnvironment
        | SSHEnvironment,
    ] = {}
    software: list[Software] = []
    notebooks: list[Notebook] = []
    procedures: dict[str, Procedure] = {}
    releases: dict[
        str,
        ProjectRelease | PublicationRelease | DatasetRelease | ModelRelease,
    ] = {}
    showcase: list[ShowcaseFigure | ShowcaseText] | None = None
