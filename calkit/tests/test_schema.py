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
    # 'image' and 'path' are both nullable, so requiring the key alone lets
    # 'image: null' through, which says no more about what to run in than
    # leaving it out does
    assert errors({"environments": {"e": {"kind": "docker", "image": None}}})
    assert errors({"environments": {"e": {"kind": "docker", "path": None}}})
    assert not errors(
        {"environments": {"e": {"kind": "docker", "image": "alpine:3.18"}}}
    )
    # An environment with an unknown kind, since the kinds are a closed set
    # even though their properties are not
    assert errors({"environments": {"e": {"kind": "not-a-kind"}}})
    # An environment with no kind at all, or whose 'kind' key is misspelled.
    # The union is discriminated on kind, so these are reported rather than
    # resolving to whichever kind happens to fit the remaining keys
    assert errors({"environments": {"e": {"image": "ubuntu"}}})
    assert errors({"environments": {"e": {"knid": "docker", "image": "u"}}})
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
    # An environment using the removed _include key, which no longer names a
    # kind and so can't be resolved
    assert errors({"environments": {"e": {"_include": "env.yaml"}}})
    # Outside the pipeline, unknown keys are tolerated rather than rejected:
    # a misspelled top-level key, an unknown environment property, and the
    # removed metrics key all still validate
    assert not errors({"descrption": "Oops"})
    assert not errors(
        {"environments": {"e": {"kind": "uv-venv", "path": "r.txt", "x": 1}}}
    )
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
    # Results are a list like the other artifacts, identified by path, but
    # two can share a file when each names a different key inside it. Both
    # title and name are optional
    assert not errors(
        {
            "results": [
                {"path": "r.csv", "title": "Summary"},
                {"path": "s.json", "key": "metrics.mean", "name": "mean"},
                {"path": "s.json", "key": "metrics.std"},
            ]
        }
    )
    # A system environment, which has nothing to build or verify
    assert not errors({"environments": {"sassy": {"kind": "system"}}})
    # An environment's files are written as 'inputs'. 'deps' is the name
    # Docker envs were published with, still accepted but no longer
    # documented, so it must keep validating on every kind that takes one
    for key in ["inputs", "deps"]:
        assert not errors(
            {
                "environments": {
                    "sys": {"kind": "system", key: ["scripts/setup.sh"]},
                    "img": {
                        "kind": "docker",
                        "image": "img",
                        key: ["src/solver.C"],
                    },
                    "hpc": {"kind": "slurm", key: ["scripts/setup.sh"]},
                }
            }
        )
    # Evidence defines what it points at inline, discriminated by kind, so
    # none of these need a matching top-level declaration
    assert not errors(
        {
            "questions": [
                {
                    "question": "Did it get faster?",
                    "evidence": [
                        {"kind": "figure", "path": "figures/f.png"},
                        {"kind": "result", "path": "r.json", "key": "pct"},
                        {"kind": "table", "path": "t.csv", "explanation": "x"},
                        {"kind": "publication", "path": "p.pdf"},
                    ],
                }
            ]
        }
    )
    # An unknown evidence kind is still reported, since kind is the
    # discriminator that says how to read the rest of the entry
    assert errors(
        {"questions": [{"question": "q?", "evidence": [{"kind": "nope"}]}]}
    )
    # Tables are a list identified by path, like the other artifacts
    assert not errors(
        {"tables": [{"path": "results/top-kernels.csv", "title": "Top"}]}
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
