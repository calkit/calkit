"""Functionality for calculations."""

from typing import Literal

import arithmetic_eval
from pydantic import BaseModel


class Input(BaseModel):
    dtype: Literal["int", "float"] = "float"
    min: int | float | None = None
    max: int | float | None = None


class Output(BaseModel):
    dtype: Literal["int", "float"] = "float"


class Calculation(BaseModel):
    kind: Literal["formula"]
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
        raise NotImplementedError


class Formula(Calculation):
    kind: str = "formula"
    formula: str

    def evaluate(self, **inputs):
        self.check_inputs(**inputs)
        return arithmetic_eval.evaluate(self.formula, inputs)


def parse(data: dict) -> Calculation:
    if isinstance(data, BaseModel):
        data = data.model_dump()
    kinds = {"formula": Formula}
    return kinds[data["kind"]].model_validate(data)


def evaluate(calc_def: dict | Calculation, **inputs) -> dict:
    return parse(calc_def).evaluate(**inputs)
