"""Models for inputs and outputs."""

from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from calkit.models.base import Model


class InputsFromStageOutputs(Model):
    from_stage_outputs: str = Field(
        description="Name of a stage whose outputs are inputs to this one."
    )


class EnvVarInput(Model):
    """An environment variable whose value a stage's results depend on.

    The value is hashed, not stored, into a file the stage depends on, so
    changing it reruns the stage. A short or guessable value could be
    recovered from its hash, so this isn't a way to keep one secret.
    It is read where ``calkit run`` runs, from the project's ``env_vars``,
    the environment or ``.env``, even for a stage that runs on another
    machine.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["env-var"] = Field(description="Always 'env-var'.")
    name: str = Field(description="Name of the environment variable.")


class ParamsInput(Model):
    """Keys of a parameters file whose values a stage's results depend on.

    DVC records the keys' values rather than the file's hash, so changing a
    key this stage doesn't read leaves it alone. The file itself is kept out
    of the stage's dependencies for that reason: named there too, its hash
    would invalidate the stage whichever key moved.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["params"] = Field(description="Always 'params'.")
    path: str = Field(
        default="params.yaml",
        description="File the keys are read from. DVC parses it, so it must "
        "be YAML, JSON, TOML or Python.",
    )
    keys: list[str] = Field(
        description="Keys this stage depends on, a nested one written like "
        "'sample.turbine_id'.",
        min_length=1,
    )


class PathInput(Model):
    """An input written as an object carrying a path.

    Prefer a plain path string. This exists so a stage keeps working when an
    output is copied verbatim into another stage's ``inputs``, which is how
    entries like ``{path: ..., storage: ...}`` show up in the wild. Only
    ``path`` is used: an input is a dependency wherever it happens to be
    stored, so the other keys are carried along and ignored.

    Extra keys are allowed deliberately, both to tolerate whatever came along
    with a copied output and to leave room for object inputs that aren't
    paths at all, e.g., a database table. They are kept rather than dropped,
    since a stage rewritten back to calkit.yaml (see
    ``Pipeline.convert_sbatch_stages``) would otherwise silently lose them.
    """

    model_config = ConfigDict(extra="allow")
    path: str = Field(description="Path to the input file or directory.")

    @model_validator(mode="before")
    @classmethod
    def _not_env_var(cls, data: Any) -> Any:
        # A malformed env-var or params input would otherwise read as a path
        if isinstance(data, dict) and data.get("kind") in (
            "env-var",
            "params",
        ):
            raise ValueError(f"a '{data['kind']}' input is not a path")
        return data


class Input(Model):
    kind: Literal["path", "python-object", "file-segment", "database-table"]


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


class PathOutput(Model):
    path: str = Field(description="Path to the output file or directory.")
    storage: Literal["git", "dvc", "dvc-zip"] | None = Field(
        default="dvc",
        description="Where to store this output. Use null to leave it "
        "untracked.",
    )
    delete_before_run: bool = Field(
        default=True,
        description="Delete this output before the stage runs.",
    )
    # Do not allow extra keys
    model_config = ConfigDict(extra="forbid")


class DatabaseTableOutput(Model):
    kind: Literal["database-table"]
    uri: str
    database_name: str | None = None
    table_name: str
