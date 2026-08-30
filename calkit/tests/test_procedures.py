"""Tests for ``calkit.procedures``."""

import json
import os

import pytest
from pydantic import ValidationError

import calkit
from calkit.models.core import Procedure, ProjectInfo
from calkit.procedures import load


def test_load(tmp_dir):
    os.makedirs("procedures")
    proc = {
        "title": "Warm up",
        "description": "Get the rig ready.",
        "steps": [{"summary": "Turn it on", "wait_after_s": 1}],
    }
    with open("procedures/warm-up.yaml", "w") as f:
        calkit.ryaml.dump(proc, f)
    with open("procedures/cool-down.json", "w") as f:
        json.dump(proc | {"title": "Cool down"}, f)
    with open("procedures/list.yaml", "w") as f:
        calkit.ryaml.dump([proc], f)
    with open("procedures/notes.txt", "w") as f:
        f.write("title: Not a procedure file\n")
    ck_info = {
        "procedures": {
            "inline": proc,
            "from-yaml": {"path": "procedures/warm-up.yaml"},
            "from-json": {"path": "procedures/cool-down.json"},
            "missing": {"path": "procedures/nope.yaml"},
            "both": {"path": "procedures/warm-up.yaml", "steps": []},
            "a-list": {"path": "procedures/list.yaml"},
            "not-yaml": {"path": "procedures/notes.txt"},
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # Inline or from a file, what comes back is the same kind of thing
    assert load("inline") == Procedure.model_validate(proc)
    assert load("from-yaml") == Procedure.model_validate(proc)
    assert load("from-json").title == "Cool down"
    assert load("from-json", ck_info=ck_info).steps[0].wait_after_s == 1
    # Paths resolve against the project directory given, not the cwd
    assert load("from-yaml", wdir=os.getcwd()).title == "Warm up"
    with pytest.raises(KeyError):
        load("nope")
    with pytest.raises(FileNotFoundError):
        load("missing")
    with pytest.raises(ValidationError, match="not both"):
        load("both")
    with pytest.raises(ValueError, match="single procedure"):
        load("a-list")
    with pytest.raises(ValueError, match="YAML or JSON"):
        load("not-yaml")
    # The project as a whole refuses an entry that is both, so the mistake
    # is caught on validation rather than on the day the procedure is run
    with pytest.raises(ValidationError, match="not both"):
        ProjectInfo.model_validate(
            {"procedures": {"p": ck_info["procedures"]["both"]}}
        )
