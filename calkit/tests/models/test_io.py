"""Tests for ``calkit.models.io``."""

import pydantic
import pytest

from calkit.models.io import ScheduleInput


def test_schedule_input(monkeypatch, tmp_path):
    day = ScheduleInput(kind="schedule", period="day")
    assert day.timezone == "UTC"
    assert day.period_file_path == ".calkit/local/current-periods/day-UTC.txt"
    # Each period, from the same time
    monkeypatch.setenv("CALKIT_NOW", "2026-10-20T02:30:00+00:00")
    expected = {
        "hour": "2026-10-20T02",
        "day": "2026-10-20",
        "week": "2026-W43",
        "month": "2026-10",
        "year": "2026",
    }
    for period, value in expected.items():
        schedule = ScheduleInput(kind="schedule", period=period)
        assert schedule.get_current_period() == value
    # Periods start in the schedule's time zone, where it's still yesterday
    la = ScheduleInput(
        kind="schedule", period="day", timezone="America/Los_Angeles"
    )
    assert la.get_current_period() == "2026-10-19"
    assert la.period_file_path.endswith("/day-America_Los_Angeles.txt")
    # A time without a zone is taken to be in the schedule's
    monkeypatch.setenv("CALKIT_NOW", "2026-10-19T23:00:00")
    assert la.get_current_period() == "2026-10-19"
    assert day.get_current_period() == "2026-10-19"
    # The year of a week is the ISO one, e.g., Jan 1 can be in last year's
    monkeypatch.setenv("CALKIT_NOW", "2027-01-01T12:00:00")
    week = ScheduleInput(kind="schedule", period="week")
    assert week.get_current_period() == "2026-W53"
    # The file is only rewritten when the period changes
    path = day.write_period_file(wdir=str(tmp_path))
    fpath = tmp_path / path
    assert fpath.read_text() == "2027-01-01\n"
    mtime = fpath.stat().st_mtime_ns
    day.write_period_file(wdir=str(tmp_path))
    assert fpath.stat().st_mtime_ns == mtime
    monkeypatch.setenv("CALKIT_NOW", "2027-01-02T12:00:00")
    day.write_period_file(wdir=str(tmp_path))
    assert fpath.read_text() == "2027-01-02\n"
    # Everything under .calkit/local stays out of Git
    gitignore = tmp_path / ".calkit" / "local" / ".gitignore"
    assert gitignore.read_text() == "*\n"
    # Bad values are caught when calkit.yaml is read
    with pytest.raises(pydantic.ValidationError):
        ScheduleInput(kind="schedule", period="day", timezone="Mars/Olympus")
    with pytest.raises(pydantic.ValidationError):
        ScheduleInput(kind="schedule", period="fortnight")  # type: ignore
    with pytest.raises(pydantic.ValidationError):
        ScheduleInput(kind="schedule", period="day", start="2026-01-01")
