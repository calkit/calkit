"""Tests for ``calkit.calc``."""

import pytest

import calkit


def test_formula():
    calc = calkit.calc.Formula(
        params=dict(formula="0.2151 * x + y**2"),
        inputs=["x", "y"],
        output=calkit.calc.Output(
            name="z", description="The value", template="The value is {z:.1f}."
        ),
    )
    assert calc.evaluate(x=10.2, y=0.1) == 2.20402
    res = calkit.calc.evaluate_and_format(calc, x=5, y=1)
    assert res == "The value is 2.1."
    with pytest.raises(ValueError):
        calc.evaluate(x=5)
    with pytest.raises(ValueError):
        calc.evaluate(z=5)
    with pytest.raises(ValueError):
        calc = calkit.calc.Formula(
            params=dict(formula="0.2151 * x + y**2"),
            inputs=["x", "x"],
            output=calkit.calc.Output(
                name="z",
                description="The value",
                template="The value is {z:.1f}.",
            ),
        )
    with pytest.raises(ValueError):
        calc = calkit.calc.Formula(
            params=dict(formula="0.2151 * x + y**2"),
            inputs=["x", "y"],
            output=calkit.calc.Output(
                name="x",
                description="The value",
                template="The value is {z:.1f}.",
            ),
        )


def test_lookuptable():
    calc = calkit.calc.LookupTable(
        inputs=["x"],
        output="something",
        params=calkit.calc.LookupTableParams(
            x_values=[1, 2, 3], y_values=[4, 5, 6]
        ),
    )
    # TODO: Implement this


def test_linear():
    calc = calkit.calc.Linear(
        params=calkit.calc.LinearParams(
            coeffs=dict(input_voltage=1.1), offset=0.01
        ),
        inputs=[{"name": "input_voltage", "dtype": "float"}],
        output="load_lbf",
    )
    res = calc.evaluate(input_voltage=1.534)
    assert round(res, ndigits=3) == 1.697
    res2 = calkit.calc.evaluate_and_format(calc, input_voltage=-0.5)
    assert (
        res2 == "For input input_voltage=-0.5, the output is load_lbf=-0.54."
    )
