"""Tests for ``calkit.models.io``."""

import pydantic
import pytest

from calkit.models.io import ScheduleInput, parse_period


def test_schedule_input(monkeypatch, tmp_path):
    # Periods can be written loosely, like pandas timedeltas
    for text, parsed in {
        "1 day": (1, "day"),
        "1d": (1, "day"),
        "day": (1, "day"),
        "daily": (1, "day"),
        "3 Days": (3, "day"),
        "15min": (15, "minute"),
        "15m": (15, "minute"),
        "6 hours": (6, "hour"),
        "2w": (2, "week"),
        "weekly": (1, "week"),
        "1mo": (1, "month"),
        "3 months": (3, "month"),
        "1y": (1, "year"),
        "annually": (1, "year"),
    }.items():
        assert parse_period(text) == parsed
    for text in ["0 days", "2 daily", "fortnight", "1.5 days", "", "d1"]:
        with pytest.raises(ValueError):
            parse_period(text)
    day = ScheduleInput(kind="schedule", period="1 day")
    assert day.timezone == "UTC"
    assert day.period_file_path == (
        ".calkit/local/current-periods/1-day-utc.txt"
    )
    # The same period written differently shares a file
    assert ScheduleInput(kind="schedule", period="daily").period_file_path == (
        day.period_file_path
    )
    # Each period, from the same time, is written as when it started
    monkeypatch.setenv("CALKIT_NOW", "2026-10-20T14:37:00+00:00")
    expected = {
        "15min": "2026-10-20T14:30",
        "1 hour": "2026-10-20T14:00",
        "6h": "2026-10-20T12:00",
        "1d": "2026-10-20",
        "1w": "2026-W43",
        "1mo": "2026-10",
        "3 months": "2026-10",
        "2 months": "2026-09",
        "1y": "2026",
        "5y": "2025",
    }
    for period, value in expected.items():
        schedule = ScheduleInput(kind="schedule", period=period)
        assert schedule.get_current_period() == value, period
    # Multi-day periods are counted from 1970, so they don't depend on when
    # or where they're computed; 2026-10-20 is day 20,746
    three_days = ScheduleInput(kind="schedule", period="3 days")
    assert three_days.get_current_period() == "2026-10-19"
    monkeypatch.setenv("CALKIT_NOW", "2026-10-21T23:59:00+00:00")
    assert three_days.get_current_period() == "2026-10-19"
    monkeypatch.setenv("CALKIT_NOW", "2026-10-22T00:00:00+00:00")
    assert three_days.get_current_period() == "2026-10-22"
    # Weeks start on Mondays
    monkeypatch.setenv("CALKIT_NOW", "2026-10-25T12:00:00+00:00")
    assert ScheduleInput(
        kind="schedule", period="1w"
    ).get_current_period() == ("2026-W43")
    monkeypatch.setenv("CALKIT_NOW", "2026-10-26T00:00:00+00:00")
    assert ScheduleInput(
        kind="schedule", period="1w"
    ).get_current_period() == ("2026-W44")
    # Periods start in the schedule's time zone, where it's still yesterday
    monkeypatch.setenv("CALKIT_NOW", "2026-10-20T02:30:00+00:00")
    la = ScheduleInput(
        kind="schedule", period="1 day", timezone="America/Los_Angeles"
    )
    assert la.get_current_period() == "2026-10-19"
    assert la.period_file_path.endswith("/1-day-america_los_angeles.txt")
    # A time without a zone is taken to be in the schedule's
    monkeypatch.setenv("CALKIT_NOW", "2026-10-19T23:00:00")
    assert la.get_current_period() == "2026-10-19"
    assert day.get_current_period() == "2026-10-19"
    # The year of a week is the ISO one, e.g., Jan 1 can be in last year's
    monkeypatch.setenv("CALKIT_NOW", "2027-01-01T12:00:00")
    week = ScheduleInput(kind="schedule", period="1 week")
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
        ScheduleInput(kind="schedule", period="1d", timezone="Mars/Olympus")
    with pytest.raises(pydantic.ValidationError):
        ScheduleInput(kind="schedule", period="fortnight")
    with pytest.raises(pydantic.ValidationError):
        ScheduleInput(kind="schedule", period="1d", start="2026-01-01")
