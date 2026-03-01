"""Tests for ``calkit.models.iteration``."""

from calkit.models.iteration import RangeIteration, RangeIterationParams


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
