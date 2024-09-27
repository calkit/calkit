"""Data models."""

from typing import Literal

from pydantic import BaseModel


class _ImportedFrom(BaseModel):
    project: str
    path: str = None


class _CalkitObject(BaseModel):
    path: str
    title: str
    description: str
    stage: str | None = None


class Dataset(_CalkitObject):
    pass


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
    name: str
    kind: Literal["conda", "docker", "pip", "poetry", "npm", "yarn"]
    path: str


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
    """

    questions: list[str] = []
    datasets: list[Dataset] = []
    figures: list[Figure] = []
    publications: list[Publication] = []
    references: list[ReferenceCollection] = []
    environments: list[Environment] = []
    software: list[Software] = []
    notebooks: list[Notebook] = []
