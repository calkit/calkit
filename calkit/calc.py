"""Functionality for calculations."""

from __future__ import annotations

from typing import Literal

import arithmetic_eval
from pydantic import BaseModel, model_validator


class Input(BaseModel):
    dtype: Literal["int", "float"] = "float"
    min: int | float | None = None
    max: int | float | None = None


class Output(BaseModel):
    dtype: Literal["int", "float"] = "float"


class Calculation(BaseModel):
    kind: Literal["formula"]
    params: dict = {}
    title: str | None = None
    description: str | None = None
    inputs: dict[str, Input] | list[str]
    outputs: dict[str, Output] | list[str]

    def check_inputs(self, **inputs) -> None:
        """Check that the supplied inputs match those declared."""
        for k in self.inputs:
            if k not in inputs:
                raise ValueError(f"Missing input {k}")
        for k, v in inputs.items():
            if k not in self.inputs:
                raise ValueError(f"{k} is not in declared inputs")
            if isinstance(self.inputs, dict):
                input_def = self.inputs[k]
                if input_def.min is not None and v < input_def.min:
                    raise ValueError(f"Input value {k} = {v} it too small")
                if input_def.max is not None and v > input_def.max:
                    raise ValueError(f"Input value {k} = {v} is too large")

    def evaluate(self, **inputs) -> dict:
        self.check_inputs(**inputs)
        raise NotImplementedError


class FormulaParams(BaseModel):
    formula: str


class Formula(Calculation):
    kind: str = "formula"
    params: FormulaParams

    def evaluate(self, **inputs):
        self.check_inputs(**inputs)
        return arithmetic_eval.evaluate(self.params.formula, inputs)


class LinearParams(BaseModel):
    coeffs: dict[str, float]
    offset: float = 0.0


class Linear(Calculation):
    """Calculation for a simple linear relationship."""

    kind: str = "linear"
    params: LinearParams

    @model_validator(mode="after")
    def validate_model(self) -> Linear:
        input_names = (
            self.inputs
            if isinstance(self.inputs, list)
            else list(self.inputs.keys())
        )
        if set(input_names) != set(self.params.coeffs.keys()):
            raise ValueError("Coefficients must have same keys as input names")
        return self

    def evaluate(self, **inputs):
        super().check_inputs(**inputs)
        val = self.params.offset
        for input_name, input_val in inputs.items():
            val += self.params.coeffs[input_name] * input_val
        return val


class LookupTableParams(BaseModel):
    x_values: list[float]
    y_values: list[float]
    method: Literal["floor", "ceil", "round", "interpolate"] = "interpolate"


class LookupTable(Calculation):
    """A 1-D lookup table."""

    kind: str = "lookup-table"
    params: LookupTableParams

    def check_inputs(self, **inputs):
        if len(inputs) > 1:
            raise ValueError("Only one input can be provided")
        super().check_inputs(**inputs)

    def evaluate(self, **inputs):
        self.check_inputs(**inputs)
        return super().evaluate(**inputs)


def parse(data: dict) -> Calculation:
    if isinstance(data, BaseModel):
        data = data.model_dump()
    # Automatically take keys not in the `kind` and move them into `params`?
    kinds = {"formula": Formula, "lookup-table": LookupTable, "linear": Linear}
    return kinds[data["kind"]].model_validate(data)


def evaluate(calc_def: dict | Calculation, **inputs) -> dict:
    return parse(calc_def).evaluate(**inputs)
