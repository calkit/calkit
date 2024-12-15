"""Functionality for building DVC pipelines with Python."""

from pydantic import BaseModel


class Dependency(BaseModel):
    path: str


class Output(BaseModel):
    path: str


class Figure(Output):
    title: str
    description: str | None = None


class Dataset(Output):
    title: str
    description: str | None = None


class Pipeline(BaseModel):
    deps: list[Dependency] | None = None

    def stage(self, func):
        """A decorator that creates a pipeline stage."""
        print("Stage being created from", func)

    def run(self):
        """Run the pipeline."""
        print("Running")
        pass
