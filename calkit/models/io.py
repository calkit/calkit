"""Models for inputs and outputs."""

import os
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

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


def _get_tzinfo(name: str) -> Any:
    """The time zone named, without needing tzdata for UTC, e.g., on Windows."""
    import datetime
    import zoneinfo

    if name.upper() == "UTC":
        return datetime.timezone.utc
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown time zone '{name}'") from e


class ScheduleInput(Model):
    """A schedule a stage runs on, e.g., once a day.

    Every compile writes the current period, e.g., today's date, to a file
    the stage depends on, so the stage reruns once each period and is
    skipped until the next one starts. The stage can read the file to learn
    which period it's running for, e.g.,
    ``.calkit/local/current-periods/day-UTC.txt`` holds ``2026-10-20`` on
    that day. Set ``CALKIT_NOW`` to an ISO 8601 time to compile as if it
    were then, e.g., to redo a past day.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["schedule"] = Field(description="Always 'schedule'.")
    period: Literal["hour", "day", "week", "month", "year"] = Field(
        description="How often the stage runs, i.e., once per this period. "
        "Weeks start on Monday."
    )
    timezone: str = Field(
        default="UTC",
        description="Time zone periods start in, e.g., 'America/New_York'.",
    )

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        _get_tzinfo(value)
        return value

    @property
    def period_file_path(self) -> str:
        """Where the current period is written, relative to the project."""
        name = f"{self.period}-{self.timezone.replace('/', '_')}.txt"
        return "/".join([".calkit", "local", "current-periods", name])

    def get_current_period(self) -> str:
        """The current period, e.g., '2026-10-20' for a day."""
        import datetime

        tz = _get_tzinfo(self.timezone)
        override = os.environ.get("CALKIT_NOW")
        if override:
            now = datetime.datetime.fromisoformat(override)
            now = now.replace(tzinfo=tz) if now.tzinfo is None else now
            now = now.astimezone(tz)
        else:
            now = datetime.datetime.now(tz)
        formats = {
            "hour": "%Y-%m-%dT%H",
            "day": "%Y-%m-%d",
            "week": "%G-W%V",
            "month": "%Y-%m",
            "year": "%Y",
        }
        return now.strftime(formats[self.period])

    def write_period_file(self, wdir: str | None = None) -> str:
        """Write the current period, if it changed, and return the path."""
        from calkit.core import ensure_local_dir

        ensure_local_dir(wdir=wdir)
        fpath = os.path.join(wdir or ".", self.period_file_path)
        content = self.get_current_period() + "\n"
        try:
            with open(fpath) as f:
                if f.read() == content:
                    return self.period_file_path
        except OSError:
            pass
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", newline="\n") as f:
            f.write(content)
        return self.period_file_path


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
        # A malformed env-var input would otherwise be read as a path
        if isinstance(data, dict) and data.get("kind") == "env-var":
            raise ValueError("an 'env-var' input is not a path")
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
