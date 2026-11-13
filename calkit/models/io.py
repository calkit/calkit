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


def get_tzinfo(name: str) -> Any:
    """The time zone named, without needing tzdata for UTC, e.g., on Windows."""
    import datetime
    import zoneinfo

    if name.upper() == "UTC":
        return datetime.timezone.utc
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown time zone '{name}'") from e


# Unit names a period can be written with, e.g., '1d', '2 hours', or 'daily'
_PERIOD_UNITS = {
    "minute": ["m", "min", "mins", "minute", "minutes"],
    "hour": ["h", "hr", "hrs", "hour", "hours", "hourly"],
    "day": ["d", "day", "days", "daily"],
    "week": ["w", "wk", "wks", "week", "weeks", "weekly"],
    "month": ["mo", "mon", "mos", "month", "months", "monthly"],
    "quarter": ["q", "qtr", "qtrs", "quarter", "quarters", "quarterly"],
    "year": ["y", "yr", "yrs", "year", "years", "yearly", "annually"],
}


def parse_period(value: str) -> tuple[int, str]:
    """Parse a period like '1 day', '1d', or 'daily' into a count and unit.

    As with pandas' timedeltas, 'm' is a minute, so a month is 'mo'.
    """
    import re

    m = re.fullmatch(r"\s*(\d+)?\s*([A-Za-z]+)\s*", value)
    if m is not None:
        count = int(m.group(1) or 1)
        word = m.group(2).lower()
        adjective = word.endswith("ly")
        for unit, names in _PERIOD_UNITS.items():
            if word in names and count > 0 and not (adjective and m.group(1)):
                return count, unit
    raise ValueError(
        f"can't read period '{value}'; use, e.g., '1 day', '6h', or 'weekly'"
    )


# How many months each period counted in months spans
_MONTHS_PER_UNIT = {"month": 1, "quarter": 3, "year": 12}


def get_now(timezone: str) -> Any:
    """The time now in a time zone, or the time ``CALKIT_NOW`` names."""
    import datetime

    tz = get_tzinfo(timezone)
    override = os.environ.get("CALKIT_NOW")
    if not override:
        return datetime.datetime.now(tz)
    # Python 3.10 can't read a trailing 'Z' for UTC
    if override.endswith(("Z", "z")):
        override = override[:-1] + "+00:00"
    now = datetime.datetime.fromisoformat(override)
    now = now.replace(tzinfo=tz) if now.tzinfo is None else now
    return now.astimezone(tz)


def floor_period(when: Any, count: int, unit: str) -> Any:
    """The start of the period a time falls in, as a wall time without a
    time zone.

    Periods are counted in the time's own zone, so a day starts at midnight
    there, and multiples are counted from the start of 1970 (or for weeks,
    its first Monday), so every machine agrees where one starts.
    """
    import datetime

    wall = when.replace(tzinfo=None)
    if unit in _MONTHS_PER_UNIT:
        months = (wall.year - 1970) * 12 + wall.month - 1
        months -= months % (count * _MONTHS_PER_UNIT[unit])
        return datetime.datetime(1970 + months // 12, months % 12 + 1, 1)
    step = _period_timedelta(count, unit)
    # The first Monday of 1970, so weeks start on Mondays
    epoch = datetime.datetime(1970, 1, 5 if unit == "week" else 1)
    return epoch + (wall - epoch) // step * step


def next_period(start: Any, count: int, unit: str) -> Any:
    """The start of the period after the one starting at ``start``."""
    import datetime

    if unit in _MONTHS_PER_UNIT:
        months = start.year * 12 + start.month - 1
        months += count * _MONTHS_PER_UNIT[unit]
        return datetime.datetime(months // 12, months % 12 + 1, 1)
    return start + _period_timedelta(count, unit)


def _period_timedelta(count: int, unit: str) -> Any:
    import datetime

    return (
        count
        * {
            "minute": datetime.timedelta(minutes=1),
            "hour": datetime.timedelta(hours=1),
            "day": datetime.timedelta(days=1),
            "week": datetime.timedelta(weeks=1),
        }[unit]
    )


def format_period(start: Any, unit: str) -> str:
    """Name a period by its start, e.g., '2026-10-20', '2026-W43', '2026-10',
    '2026Q4', or '2026'.
    """
    if unit == "year":
        return f"{start.year:04d}"
    if unit == "quarter":
        return f"{start.year:04d}Q{(start.month - 1) // 3 + 1}"
    if unit == "month":
        return f"{start.year:04d}-{start.month:02d}"
    formats = {
        "minute": "%Y-%m-%dT%H:%M",
        "hour": "%Y-%m-%dT%H:%M",
        "day": "%Y-%m-%d",
        "week": "%G-W%V",
    }
    return str(start.strftime(formats[unit]))


class ScheduleInput(Model):
    """A schedule a stage runs on, e.g., once a day.

    Every compile writes the current period, e.g., today's date, to a file
    the stage depends on, so the stage reruns once each period and is
    skipped until the next one starts. The stage can read the file to learn
    which period it's running for, e.g.,
    ``.calkit/local/current-periods/1-day-utc.txt`` holds ``2026-10-20`` on
    that day. A period of more than one unit, e.g., '3 days', is counted
    from the start of 1970 (or for weeks, its first Monday), so every machine
    agrees where one starts, and is written as its first unit, e.g., the day
    it starts. Set ``CALKIT_NOW`` to an ISO 8601 time to compile as if it
    were then, e.g., to redo a past day.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["schedule"] = Field(description="Always 'schedule'.")
    period: str = Field(
        description="How often the stage runs, i.e., once per this period, "
        "e.g., '1 day', '1d', '6 hours', '2w', or 'monthly'. Units are "
        "minutes, hours, days, weeks (starting on Monday), months, quarters, "
        "and years; 'm' is a minute and 'mo' a month."
    )
    timezone: str = Field(
        default="UTC",
        description="Time zone periods start in, e.g., 'America/New_York'.",
    )

    @field_validator("period")
    @classmethod
    def _readable_period(cls, value: str) -> str:
        parse_period(value)
        return value

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        get_tzinfo(value)
        return value

    @property
    def period_file_path(self) -> str:
        """Where the current period is written, relative to the project."""
        count, unit = parse_period(self.period)
        tz = self.timezone.replace("/", "_")
        name = f"{count}-{unit}-{tz}.txt".lower()
        return "/".join([".calkit", "local", "current-periods", name])

    def get_current_period(self) -> str:
        """The start of the current period, e.g., '2026-10-20' for a day."""
        count, unit = parse_period(self.period)
        now = get_now(self.timezone)
        return format_period(floor_period(now, count, unit), unit)

    def write_period_file(self, wdir: str | None = None) -> str:
        """Write the current period, if it changed, and return the path."""
        from calkit.core import ensure_local_dir, write_if_changed

        ensure_local_dir(wdir=wdir)
        fpath = os.path.join(wdir or ".", self.period_file_path)
        write_if_changed(fpath, self.get_current_period() + "\n")
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
