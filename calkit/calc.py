"""Functionality for calculations."""

from __future__ import annotations

from typing import Literal

import arithmetic_eval
import requests
from pydantic import BaseModel, model_validator

DTYPES = {"int": int, "float": float, "str": str}
DEFAULT_IN_TYPE = "float"
DEFAULT_OUT_TYPE = "float"


class Input(BaseModel):
    name: str
    description: str | None = None
    dtype: Literal["int", "float", "str"] = DEFAULT_IN_TYPE
    min: int | float | None = None
    max: int | float | None = None


class Output(BaseModel):
    name: str
    description: str | None = None
    dtype: Literal["int", "float", "str"] = DEFAULT_OUT_TYPE
    template: str | None = None


class Calculation(BaseModel):
    kind: str
    params: dict = {}
    name: str | None = None
    description: str | None = None
    inputs: list[Input] | list[str]
    output: Output | str

    @model_validator(mode="after")
    def validate_model(self) -> Calculation:
        input_names = self.input_names
        if self.output_name in input_names:
            raise ValueError("Output name must not overlap with input names")
        if len(set(input_names)) != len(input_names):
            raise ValueError("Input names must be unique")
        return self

    @property
    def input_names(self) -> list[str]:
        input_names = []
        for i in self.inputs:
            if isinstance(i, Input):
                input_names.append(i.name)
            else:
                input_names.append(i)
        return input_names

    @property
    def inputs_dict(self) -> dict[str, Input]:
        res = {}
        for i in self.inputs:
            if isinstance(i, str):
                res[i] = Input(name=i)
            else:
                res[i.name] = i
        return res

    @property
    def output_name(self) -> str:
        if isinstance(self.output, Output):
            return self.output.name
        return self.output

    def check_inputs(self, **inputs) -> dict:
        """Check that the supplied inputs match those declared and do type
        coercion.
        """
        inputs_dict = self.inputs_dict
        for k in inputs_dict:
            if k not in inputs:
                raise ValueError(f"Missing input {k}")
        for k, v in inputs.items():
            if k not in inputs_dict:
                raise ValueError(f"{k} is not in declared inputs")
            input_def = inputs_dict[k]
            v = DTYPES[input_def.dtype](v)
            inputs[k] = v
            if input_def.min is not None and v < input_def.min:
                raise ValueError(f"Input value {k} = {v} it too small")
            if input_def.max is not None and v > input_def.max:
                raise ValueError(f"Input value {k} = {v} is too large")
        return inputs

    def calculate(self, **inputs):
        """This is the method to override to implement custom logic.

        Input and output type coercion will be handled outside.
        """
        raise NotImplementedError

    def evaluate(self, **inputs):
        inputs = self.check_inputs(**inputs)
        out = self.calculate(**inputs)
        return self.coerce_output(out)

    def coerce_output(self, val):
        if isinstance(self.output, Output):
            return DTYPES[self.output.dtype](val)
        else:
            return DTYPES[DEFAULT_OUT_TYPE](val)

    def evaluate_and_format(self, **inputs) -> str:
        res = self.evaluate(**inputs)
        if isinstance(self.output, Output):
            out_name = self.output.name
            template = self.output.template
        else:
            out_name = self.output
            template = None
        if template is None:
            template = "For input "
            for input_name in inputs:
                template += input_name + "={" + input_name + "}, "
            template += "the output is "
            template += out_name + "={" + out_name + "}."
        return template.format(**(inputs | {out_name: res}))


class FormulaParams(BaseModel):
    formula: str


class Formula(Calculation):
    kind: str = "formula"
    params: FormulaParams

    def calculate(self, **inputs):
        inputs = self.check_inputs(**inputs)
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
        if set(self.input_names) != set(self.params.coeffs.keys()):
            raise ValueError("Coefficients must have same keys as input names")
        return self

    def calculate(self, **inputs):
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


class HttpRequestParams(BaseModel):
    url: str
    inputs_as_params: bool = True  # Otherwise, use body
    method: Literal["get", "post", "put"] = "get"
    as_json: bool = True  # Otherwise, return raw text


class HttpRequest(Calculation):
    """Make an HTTP request and return the result.

    This should not be run on a web server since it can be insecure.
    For example, it could make requests to private services and return
    sensitive data.
    """

    kind: str = "http"
    params: HttpRequestParams

    def calculate(self, **inputs):
        func = getattr(requests, self.params.method)
        if self.params.inputs_as_params:
            kws = {"params": inputs}
        else:
            kws = {"json", inputs}
        resp: requests.Response = func(url=self.params.url, **kws)
        resp.raise_for_status()
        if self.params.as_json:
            return resp.json()
        else:
            return resp.text


class XGBoostModelParams(BaseModel):
    path: str
    type: Literal["classifier", "regressor"]


class XGBoostModel(Calculation):
    """Make predictions with an XGBoost model saved as JSON.

    This is currently just a prototype and should not be expected to work.

    One input, ``data``, should be defined to be passed to the model's
    ``predict`` method.
    """

    kind: str = "xgboost"
    params: XGBoostModelParams

    def calculate(self, **inputs):
        # Load model from JSON
        import xgboost

        # Convert model path to something that can be loaded if running on the
        # Calkit Cloud
        types = {
            "classifier": xgboost.XGBClassifier,
            "regressor": xgboost.XGBRegressor,
        }
        model = types[self.params.type]().load_model(self.params.path)
        return model.predict(**inputs)


def parse(data: dict) -> Calculation:
    if isinstance(data, BaseModel):
        data = data.model_dump()
    # Automatically take keys not in the `kind` and move them into `params`?
    kinds = {"formula": Formula, "lookup-table": LookupTable, "linear": Linear}
    return kinds[data["kind"]].model_validate(data)


def evaluate(calc_def: dict | Calculation, **inputs) -> dict:
    return parse(calc_def).evaluate(**inputs)


def evaluate_and_format(calc_def: dict | Calculation, **inputs) -> str:
    return parse(calc_def).evaluate_and_format(**inputs)
