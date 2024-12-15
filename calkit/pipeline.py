"""Functionality for building DVC pipelines with Python."""

from pydantic import BaseModel

from typing import Callable


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

    def stage(self, *args, other_arg=None):
        """A decorator that creates a pipeline stage."""

        def decorator(func):

            print("Stage being created from", func)
            print("Other arg:", other_arg)

            def wrapper(*args, **kwargs):
                print(f"Calling {func.__name__} with instance {self}...")
                result = func(*args, **kwargs)
                print(f"{func.__name__} finished. Result: {result}")
                return result

            return wrapper

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])

        return decorator

    def run(self):
        """Run the pipeline."""
        print("Running")
        pass
