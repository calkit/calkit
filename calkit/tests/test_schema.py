"""Tests for ``calkit.schema``."""

from __future__ import annotations

import json
import os

import jsonschema
import pytest

import calkit.schema

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def test_generate() -> None:
    schema = calkit.schema.generate()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == calkit.schema.SCHEMA_URL
    # Unknown top-level keys must be an error, else typos go unnoticed
    assert schema["additionalProperties"] is False
    # The modeline is a comment, but an inline $schema key is also valid, so
    # it must not trip the check above
    assert "$schema" in schema["properties"]
    # Check the checked-in copies are up-to-date, since they're what get
    # published and bundled into the VS Code extension
    for relpath in calkit.schema.SCHEMA_REPO_PATHS:
        with open(os.path.join(REPO_ROOT, relpath), encoding="utf-8") as f:
            checked_in = f.read()
        assert (
            checked_in == calkit.schema.generate_json()
        ), f"{relpath} is out-of-date; regenerate it with 'make schema'"


@pytest.mark.parametrize(
    "relpath",
    [
        "examples/basic/calkit.yaml",
        "jupyterlab-ext/ui-tests/test-project/calkit.yaml",
    ],
)
def test_validate_example_projects(relpath: str) -> None:
    schema = calkit.schema.generate()
    with open(os.path.join(REPO_ROOT, relpath), encoding="utf-8") as f:
        data = calkit.ryaml.load(f)
    jsonschema.validate(data, schema)


def test_validate_bad_projects() -> None:
    schema = calkit.schema.generate()
    validator = jsonschema.Draft202012Validator(schema)

    def errors(data: dict) -> list[str]:
        return [e.message for e in validator.iter_errors(data)]

    # A misspelled top-level key
    assert errors({"descrption": "Oops"})
    # An environment missing a required field for its kind
    assert errors({"environments": {"e": {"kind": "docker"}}})
    # An environment with a misspelled field
    assert errors(
        {"environments": {"e": {"kind": "uv-venv", "pathh": "reqs.txt"}}}
    )
    # An environment with an unknown kind
    assert errors({"environments": {"e": {"kind": "not-a-kind"}}})
    # A stage with an unknown kind, and one with a misspelled field
    assert errors({"pipeline": {"stages": {"s": {"kind": "nope"}}}})
    assert errors(
        {
            "pipeline": {
                "stages": {
                    "s": {
                        "kind": "python-script",
                        "script_path": "s.py",
                        "enviroment": "py",
                    }
                }
            }
        }
    )
    # Valid documents, including ones using the features above correctly
    assert not errors({})
    assert not errors({"$schema": calkit.schema.SCHEMA_URL})
    assert not errors({"environments": {"e": {"_include": "env.yaml"}}})
    assert not errors(
        {
            "environments": {"py": {"kind": "uv-venv", "path": "reqs.txt"}},
            "pipeline": {
                "stages": {
                    "s": {
                        "kind": "python-script",
                        "script_path": "s.py",
                        "environment": "py",
                    }
                }
            },
            "env_vars": {"MY_VAR": "value"},
            "subprojects": [{"path": "sub"}],
            "overleaf_sync": {"paper": {"url": "https://overleaf.com/1"}},
        }
    )


def test_json_is_stable() -> None:
    # The generated text must be deterministic, else the drift check above
    # would fail spuriously
    assert calkit.schema.generate_json() == calkit.schema.generate_json()
    json.loads(calkit.schema.generate_json())
