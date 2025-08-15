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
        # Determine precision from inputs
        def get_decimal_places(num):
            return len(str(num).split(".")[-1]) if "." in str(num) else 0

        max_precision = max(
            get_decimal_places(self.range.start),
            get_decimal_places(self.range.stop),
            get_decimal_places(self.range.step),
        )
        vals = []
        current = self.range.start
        while current < self.range.stop:
            vals.append(round(current, max_precision))
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

ExpandedParametersType = dict[str, int | float | str | list[int | float | str]]


class ParameterIteration(BaseModel):
    parameter: str

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
