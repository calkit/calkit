"""Tests for ``calkit.models.iteration``."""

import datetime

import pytest
from pydantic import ValidationError

from calkit.models.iteration import (
    DateRangeIteration,
    RangeIteration,
    RangeIterationParams,
)


def test_rangeiteration():
    r = RangeIteration(range=RangeIterationParams(start=0, stop=10, step=2))
    assert r.values == [0, 2, 4, 6, 8]
    r = RangeIteration(
        range=RangeIterationParams(start=0.05, stop=0.25, step=0.1)
    )
    assert r.values == [0.05, 0.15]
    r = RangeIteration(range=RangeIterationParams(start=0.5, stop=1, step=0.2))
    assert r.values == [0.5, 0.7, 0.9]
    r = RangeIteration(range=RangeIterationParams(start=0, stop=1, step=0.2))
    assert r.values == [0.0, 0.2, 0.4, 0.6, 0.8]


def test_daterangeiteration(monkeypatch):
    def periods(**params) -> list[dict]:
        return DateRangeIteration.model_validate(
            {"date_range": params}
        ).periods

    monkeypatch.setenv("CALKIT_NOW", "2026-11-10T08:00:00Z")
    # Runs to today by default, the open period through yesterday
    q = periods(start="2026Q2", step="1 quarter")
    assert [p["period"] for p in q] == ["2026Q2", "2026Q3", "2026Q4"]
    assert q[1] == {
        "period": "2026Q3",
        "start": "2026-07-01",
        "end": "2026-10-01",
        "through": "2026-09-30",
    }
    assert q[2]["end"] == "2027-01-01"
    assert q[2]["through"] == "2026-11-09"
    # The step defaults to a month, and a start or stop inside a period
    # names the period while clipping its window
    m = periods(start="2024-03-22", stop="2025-04-04")
    assert len(m) == 14
    assert m[0] == {
        "period": "2024-03",
        "start": "2024-03-22",
        "end": "2024-04-01",
        "through": "2024-03-31",
    }
    assert m[-1]["period"] == "2025-04"
    assert m[-1]["end"] == "2025-04-04"
    assert m[-1]["through"] == "2025-04-03"
    # YAML reads unquoted dates and years as dates and ints
    assert periods(start=datetime.date(2024, 3, 22), stop=2025) == periods(
        start="2024-03-22", stop="2025"
    )
    assert periods(start=2025, step="1y")[0]["period"] == "2025"
    # A period with no full day yet isn't included, nor is a later one
    # before a stop that hasn't come
    d = periods(start="2026-11-08", stop="2026-12-01", step="1 day")
    assert [p["period"] for p in d] == ["2026-11-08", "2026-11-09"]
    assert d[-1]["through"] == "2026-11-09"
    # Weeks start on Mondays and multiples are counted from 1970
    w = periods(start="2026-W45", step="1 week")
    assert [p["start"] for p in w] == ["2026-11-02", "2026-11-09"]
    assert periods(start="2026-08", step="2 months")[0]["period"] == "2026-07"
    # Days start in the range's time zone, where it can still be yesterday
    monkeypatch.setenv("CALKIT_NOW", "2026-11-10T02:00:00Z")
    la = periods(start="2026-11", timezone="America/Los_Angeles")
    assert la[0]["through"] == "2026-11-08"
    # A closed period no longer changes
    monkeypatch.setenv("CALKIT_NOW", "2027-03-01T00:00:00Z")
    assert periods(start="2026Q2", step="1 quarter")[2]["through"] == (
        "2026-12-31"
    )
    for bad in [
        {"start": "2026-11", "step": "6 hours"},
        {"start": "2026-11", "stop": "2026-10"},
        {"start": "last year"},
        {"start": "2026-11", "timezone": "Mars/Olympus"},
        {"start": "2026-11", "state_storage": "dvc"},
    ]:
        with pytest.raises(ValidationError):
            DateRangeIteration.model_validate({"date_range": bad})
    with pytest.raises(ValueError, match="no full day"):
        periods(start="2027-03-01")
