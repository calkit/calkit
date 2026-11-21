"""Models for iteration."""

from __future__ import annotations

import datetime
from functools import cached_property
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from calkit.models.base import Model


class RangeIteration(Model):
    kind: Literal["range"] = Field(description="A range of numbers.")
    start: int | float = Field(
        description="First value in the range, which is included."
    )
    stop: int | float = Field(
        description="Value at which to stop, which is not included."
    )
    step: int | float = Field(
        default=1, description="Amount by which to increment each value."
    )

    @model_validator(mode="before")
    @classmethod
    def _unnest_range(cls, data: Any) -> Any:
        # Ranges were written nested under 'range' before they had a kind
        if (
            isinstance(data, dict)
            and "kind" not in data
            and isinstance(data.get("range"), dict)
        ):
            return {"kind": "range"} | data["range"]
        return data

    @property
    def values(self) -> list[int | float]:
        # Determine precision from inputs
        def get_decimal_places(num):
            return len(str(num).split(".")[-1]) if "." in str(num) else 0

        max_precision = max(
            get_decimal_places(self.start),
            get_decimal_places(self.stop),
            get_decimal_places(self.step),
        )
        vals = []
        current = self.start
        while current < self.stop:
            vals.append(round(current, max_precision))
            current += self.step
        return vals


# A date range is named in days or longer, so every name is a valid path
_DATE_RANGE_UNITS = ["day", "week", "month", "quarter", "year"]


def _parse_date_bound(value: str | int | datetime.date) -> datetime.datetime:
    """Read a day, e.g., '2024-03-22', or a period, e.g., '2024-03',
    '2024Q1', '2024-W12', or 2024, as the time it starts.
    """
    import re

    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, datetime.date):
        return datetime.datetime(value.year, value.month, value.day)
    text = str(value).strip()
    if m := re.fullmatch(r"(\d{4})", text):
        return datetime.datetime(int(m[1]), 1, 1)
    if m := re.fullmatch(r"(\d{4})[Qq]([1-4])", text):
        return datetime.datetime(int(m[1]), 3 * int(m[2]) - 2, 1)
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", text):
        return datetime.datetime(int(m[1]), int(m[2]), 1)
    if m := re.fullmatch(r"(\d{4})-W(\d{2})", text):
        day = datetime.date.fromisocalendar(int(m[1]), int(m[2]), 1)
        return datetime.datetime(day.year, day.month, day.day)
    try:
        return datetime.datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        raise ValueError(
            f"can't read '{value}' as a date; use, e.g., '2024-03-22', "
            "'2024-03', '2024Q1', '2024-W12', or '2024'"
        )


def get_date_range_state_dir(stage_name: str, storage: str) -> str:
    """Where a stage's date-range periods keep their state, relative to the
    project.
    """
    # The name becomes a path, which mustn't leave the state directory
    parts = stage_name.split("/")
    if any(c in stage_name for c in "\\:") or any(
        part in ("", ".", "..") for part in parts
    ):
        raise ValueError(
            f"Stage '{stage_name}' can't keep date-range state, since its "
            "name isn't a relative path within the project"
        )
    if storage == "local":
        return f".calkit/local/date-ranges/{stage_name}"
    return f".calkit/date-ranges/{stage_name}"


class DateRangeIteration(Model):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["date-range"] = Field(
        description="A range of dates, iterated over one period at a time."
    )
    start: str | int | datetime.date = Field(
        description="When the range starts, either a day, e.g., "
        "'2024-03-22', or a period, e.g., '2024-03', '2024Q1', or 2024; "
        "the first item is the period containing it."
    )
    stop: str | int | datetime.date = Field(
        default="today",
        description="When the range stops, which is not included, written "
        "like 'start'. The default, 'today', runs to the last full day, so "
        "an item is added once a new period has one, as are items for a "
        "later date when it comes.",
    )
    step: str = Field(
        default="1 month",
        description="The length of each period, e.g., '1 day', '1 week', "
        "'1 month', '1 quarter', or '1 year', which names it as it starts, "
        "e.g., '2026-11-10', '2026-W46', '2026-11', '2026Q4', or '2026'. "
        "Multiples are counted from 1970, so '2 months' always start in an "
        "odd month.",
    )
    timezone: str = Field(
        default="UTC",
        description="Time zone days start in, e.g., 'America/New_York'.",
    )
    state_storage: Literal["git", "local"] | None = Field(
        default=None,
        description="Keep a directory for each period that its item "
        "depends on, holding the period's window and last full day in "
        "'period.json', so an item whose period is still open reruns daily "
        "and once more when it closes. Anything else written there, e.g., "
        "a fingerprint of a source's data for the period, reruns the item "
        "when it changes. 'git' keeps the directories in "
        "'.calkit/date-ranges/<stage>/<period>', 'local' in "
        "'.calkit/local/date-ranges/<stage>/<period>'.",
    )

    @field_validator("step")
    @classmethod
    def _readable_step(cls, value: str) -> str:
        from calkit.models.io import parse_period

        _, unit = parse_period(value)
        if unit not in _DATE_RANGE_UNITS:
            raise ValueError(
                f"a date range steps by days or longer, not '{value}'"
            )
        return value

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        from calkit.models.io import get_tzinfo

        get_tzinfo(value)
        return value

    @model_validator(mode="after")
    def _readable_bounds(self) -> DateRangeIteration:
        start = _parse_date_bound(self.start)
        if self.stop == "today":
            return self
        if _parse_date_bound(self.stop) <= start:
            raise ValueError(
                f"date range stop '{self.stop}' isn't after its start "
                f"'{self.start}'"
            )
        return self

    @property
    def span(self) -> tuple[str, datetime.datetime, datetime.datetime | None]:
        """The step's unit, and when the first period starts and the last
        ends, which is ``None`` for a range that runs to today.
        """
        from calkit.models.io import floor_period, next_period, parse_period

        count, unit = parse_period(self.step)
        first = floor_period(_parse_date_bound(self.start), count, unit)
        if self.stop == "today":
            return unit, first, None
        last_day = _parse_date_bound(self.stop) - datetime.timedelta(days=1)
        last = floor_period(last_day, count, unit)
        return unit, first, next_period(last, count, unit)

    @cached_property
    def periods(self) -> list[dict[str, str]]:
        """Each period with at least one full day, as its name, its window
        within the range, and its last full day.

        ``start`` is included and ``end`` is not, while ``through`` is the
        window's last day that is over, so a period still open has a
        ``through`` before its last day. Worked out once, so everything a
        compile writes agrees on what day it is. Empty before the range has
        a full day, which leaves its stage out of the pipeline until then.
        """
        from calkit.models.io import (
            floor_period,
            format_period,
            get_now,
            next_period,
            parse_period,
        )

        count, unit = parse_period(self.step)
        now = get_now(self.timezone)
        today = datetime.datetime(now.year, now.month, now.day)
        start = _parse_date_bound(self.start)
        end = None if self.stop == "today" else _parse_date_bound(self.stop)
        limit = today if end is None else min(end, today)
        one_day = datetime.timedelta(days=1)
        periods = []
        current = floor_period(start, count, unit)
        while current < limit:
            # Only the first window can start after its period does
            window_start = max(current, start)
            if window_start >= limit:
                break
            following = next_period(current, count, unit)
            window_end = following if end is None else min(following, end)
            periods.append(
                {
                    "period": format_period(current, unit),
                    "start": window_start.date().isoformat(),
                    "end": window_end.date().isoformat(),
                    "through": (min(window_end, today) - one_day)
                    .date()
                    .isoformat(),
                }
            )
            current = following
        return periods

    @property
    def values(self) -> list[str]:
        return [p["period"] for p in self.periods]


ParametersType = dict[
    str,
    int | float | str | list[int | float | str | RangeIteration],
]

ExpandedParametersType = dict[str, int | float | str | list[int | float | str]]


class ParameterIteration(Model):
    parameter: str = Field(
        description="Name of a project parameter whose list of values to "
        "iterate over."
    )

    def values_from_params(
        self, params: ParametersType | ExpandedParametersType
    ) -> list:
        """Convert parameters from calkit.yaml into a list of values."""
        if self.parameter not in params:
            raise ValueError(f"'{self.parameter}' not found in parameters")
        param_value = params[self.parameter]
        if not isinstance(param_value, list):
            raise ValueError("Parameter iteration must be over a list")
        vals = []
        for val in param_value:
            if isinstance(val, dict):
                range_iter = RangeIteration.model_validate(val)
                vals += range_iter.values
            else:
                vals.append(val)
        return vals


def expand_project_parameters(
    params: ParametersType,
) -> ExpandedParametersType:
    """Expand any range iterations in project parameters."""
    expanded = {}
    for key, value in params.items():
        if isinstance(value, list):
            expanded_list = []
            for item in value:
                try:
                    range_iter = RangeIteration.model_validate(item)
                    expanded_list.extend(range_iter.values)
                except Exception:
                    expanded_list.append(item)
            expanded[key] = expanded_list
        else:
            expanded[key] = value
    return expanded
