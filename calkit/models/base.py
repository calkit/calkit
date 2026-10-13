"""The base for Calkit's models."""

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """A model whose schema is built when it's first used, rather than when
    it's defined, since most commands use few of them.

    What that saves is a question in decisions/calkit.yaml.
    """

    model_config = ConfigDict(defer_build=True)
