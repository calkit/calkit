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
    # The top level tolerates unknown keys while the schema evolves, so a
    # project using a newer or experimental feature isn't flagged as invalid
    assert schema.get("additionalProperties") is not False
    assert "$schema" in schema["properties"]
    # Pipeline stages stay strict, since a typo'd key there silently changes
    # what runs
    stage = schema["$defs"]["PythonScriptStage"]
    assert stage["additionalProperties"] is False
    # Check the checked-in copies are up-to-date, since they're what get
    # published and bundled into the VS Code extension
    for relpath in calkit.schema.SCHEMA_REPO_PATHS:
        with open(os.path.join(REPO_ROOT, relpath), encoding="utf-8") as f:
            checked_in = f.read()
        assert checked_in == calkit.schema.generate_json(), (
            f"{relpath} is out-of-date; regenerate it with 'make schema'"
        )


@pytest.mark.parametrize("relpath", ["examples/basic/calkit.yaml"])
def test_validate_example_projects(relpath: str) -> None:
    fpath = os.path.join(REPO_ROOT, relpath)
    # The examples live in Git submodules, which aren't necessarily checked
    # out; CI clones them so this actually runs there
    if not os.path.isfile(fpath):
        pytest.skip(f"{relpath} is not checked out")
    schema = calkit.schema.generate()
    with open(fpath, encoding="utf-8") as f:
        data = calkit.ryaml.load(f)
    jsonschema.validate(data, schema)


def test_validate_bad_projects() -> None:
    schema = calkit.schema.generate()
    validator = jsonschema.Draft202012Validator(schema)

    def errors(data: dict) -> list[str]:
        return [e.message for e in validator.iter_errors(data)]

    # An environment missing a required field for its kind
    assert errors({"environments": {"e": {"kind": "docker"}}})
    # An environment with an unknown kind, since the kinds are a closed set
    # even though their properties are not
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
    # Results as a list, which is the pre-name-keyed shape
    assert errors({"results": [{"path": "r.csv", "title": "Summary"}]})
    # Outside the pipeline, unknown keys are tolerated rather than rejected:
    # a misspelled top-level key, an unknown environment property, and the
    # removed _include and metrics keys all still validate
    assert not errors({"descrption": "Oops"})
    assert not errors(
        {"environments": {"e": {"kind": "uv-venv", "path": "r.txt", "x": 1}}}
    )
    assert not errors({"environments": {"e": {"_include": "env.yaml"}}})
    assert not errors({"metrics": {"mean": {"value": 3.14}}})
    # Valid documents, including ones using the features above correctly
    assert not errors({})
    assert not errors({"$schema": calkit.schema.SCHEMA_URL})
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
    # Shapes the CLI itself writes, which must not be rejected: a notebook
    # entry recording only its environment, a publication with no kind, and
    # every showcase element kind
    assert not errors(
        {"notebooks": [{"path": "nb.ipynb", "environment": "py"}]}
    )
    assert not errors(
        {"publications": [{"path": "paper.pdf", "title": "The paper"}]}
    )
    # Results are keyed by name; two can share a file with different keys,
    # and the title is optional since the name identifies it
    assert not errors(
        {
            "results": {
                "summary": {"path": "r.csv", "title": "Summary"},
                "mean": {"path": "s.json", "key": "metrics.mean"},
                "std": {"path": "s.json", "key": "metrics.std"},
            }
        }
    )
    assert not errors(
        {
            "showcase": [
                {"text": "Some text"},
                {"markdown": "### A heading"},
                {"figure": "figures/f.png"},
                {"publication": "paper/paper.pdf"},
            ]
        }
    )


def test_json_is_stable() -> None:
    # The generated text must be deterministic, else the drift check above
    # would fail spuriously
    assert calkit.schema.generate_json() == calkit.schema.generate_json()
    json.loads(calkit.schema.generate_json())
