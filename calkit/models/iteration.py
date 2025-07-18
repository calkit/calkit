"""Models for iteration."""

from __future__ import annotations

from pydantic import BaseModel


class RangeIterationParams(BaseModel):
    start: int | float
    stop: int | float
    step: int | float = 1


class RangeIteration(BaseModel):
    range: RangeIterationParams

    @property
    def values(self) -> list[int | float]:
        vals = []
        current = self.range.start
        while current < self.range.stop:
            vals.append(current)
            current += self.range.step
        return vals


class ValueInFile(BaseModel):
    """A value in a file.

    If ``key`` is None, we assume the value is all that's written in the file.
    """

    path: str
    key: str | None = None


class Parameter(BaseModel):
    value: int | float | str
    write_to: ValueInFile | None = None
    description: str | None = None


class Metric(BaseModel):
    value: int | float | str
    read_from: ValueInFile | None = None
    description: str | None = None


ParametersType = dict[
    str,
    int | float | str | list[int | float | str | RangeIteration],
]


class ParameterIteration(BaseModel):
    parameter: str

    def values_from_params(self, params: ParametersType) -> list:
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
