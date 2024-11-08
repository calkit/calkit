"""Data models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class _ImportedFromProject(BaseModel):
    project: str
    path: str | None = None
    git_rev: str | None = None


class _ImportedFromUrl(BaseModel):
    url: str


class _CalkitObject(BaseModel):
    path: str
    title: str
    description: str
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
        "poster",
        "report",
        "blog",
    ]
    is_published: bool = False
    doi: str = None


class ReferenceFile(BaseModel):
    path: str
    key: str


class ReferenceCollection(BaseModel):
    path: str
    files: list[ReferenceFile] = []


class Environment(BaseModel):
    kind: Literal[
        "conda", "docker", "pip", "poetry", "npm", "yarn", "remote-ssh"
    ]
    path: str | None = None
    description: str | None = None
    stage: str | None = None
    default: bool | None = None


class DockerEnvironment(Environment):
    kind: str = "docker"
    image: str
    layers: list[str] | None = None


class Software(BaseModel):
    title: str
    path: str
    description: str


class Notebook(_CalkitObject):
    """A Jupyter notebook."""

    pass


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
    parent: str | None = None
    questions: list[str] = []
    datasets: list[Dataset] = []
    figures: list[Figure] = []
    publications: list[Publication] = []
    references: list[ReferenceCollection] = []
    environments: dict[str, Environment | DockerEnvironment] = {}
    software: list[Software] = []
    notebooks: list[Notebook] = []
