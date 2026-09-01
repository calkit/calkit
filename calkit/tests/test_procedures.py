"""Tests for ``calkit.procedures``."""

import json
import os

import pytest
import typer
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


def _project(in_file: bool = False) -> dict:
    # A committed project with one procedure, inline or in its own file
    import subprocess

    subprocess.check_call(["git", "init", "-q"])
    subprocess.check_call(["git", "config", "user.email", "t@example.com"])
    subprocess.check_call(["git", "config", "user.name", "Tester"])
    proc = {
        "title": "Measure the rig",
        "description": "Read the temperature off the display.",
        "steps": [
            {"summary": "Turn on the machine"},
            {
                "summary": "Record the temperature",
                "inputs": {
                    "temperature": {"units": "C", "dtype": "float"},
                    "ok": {"dtype": "str"},
                },
            },
        ],
    }
    if in_file:
        os.makedirs("procedures", exist_ok=True)
        with open("procedures/measure-rig.yaml", "w") as f:
            calkit.ryaml.dump(proc, f)
        entry: dict = {"path": "procedures/measure-rig.yaml"}
    else:
        entry = proc
    ck_info = {"procedures": {"measure-rig": entry}}
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(["git", "commit", "-q", "-m", "Add procedure"])
    return ck_info


def _run(monkeypatch, answers: list[str], **kwargs) -> None:
    # Run the procedure, answering each prompt in turn
    from calkit.cli.main.core import run_procedure

    remaining = list(answers)
    monkeypatch.setattr("builtins.input", lambda *_: remaining.pop(0))
    run_procedure("measure-rig", **kwargs)


def _log_paths(name: str = "measure-rig") -> list[str]:
    import glob

    return sorted(glob.glob(f".calkit/procedure-runs/{name}/*.csv"))


def _log_rows(name: str = "measure-rig") -> list[dict]:
    import csv

    rows: list[dict] = []
    for path in _log_paths(name):
        with open(path) as f:
            rows += list(csv.DictReader(f))
    return rows


@pytest.mark.parametrize("in_file", [False, True])
def test_run_procedure(tmp_dir, monkeypatch, in_file):
    import subprocess

    # Whether the procedure is written inline or kept in its own file makes
    # no difference to carrying it out
    _project(in_file=in_file)
    _run(monkeypatch, ["", "21.5", "yes"])
    rows = _log_rows()
    assert [r["step"] for r in rows] == ["0", "1"]
    assert [r["procedure_name"] for r in rows] == ["measure-rig"] * 2
    # Inputs are columns, empty for the steps that don't ask for them
    assert rows[0]["temperature"] == ""
    assert rows[1]["temperature"] == "21.5"
    assert rows[1]["ok"] == "yes"
    # Every step is timed, and the version that ran is recorded
    assert rows[0]["start"] and rows[0]["end"]
    assert rows[1]["calkit_version"] == calkit.__version__
    # A run log is named for when the run started, and Windows has no
    # colon in a filename. Asserted here rather than left to Windows CI,
    # which is where this last went wrong.
    illegal = set(':*?"<>|')
    for path in _log_paths():
        assert not set(os.path.basename(path)) & illegal, path
    # Each step is committed on its own as it is completed
    log = subprocess.check_output(
        ["git", "log", "--format=%s"], text=True
    ).split("\n")
    assert "Execute procedure measure-rig step 1" in log
    assert "Execute procedure measure-rig step 0" in log
    # A float input that isn't one is a typo at the bench, not a reason to
    # lose the run: it asks again
    _run(monkeypatch, ["", "not-a-number", "22.5", "yes"])
    assert _log_rows()[3]["temperature"] == "22.5"
    # The log is still written with --no-commit; only the commits stop
    before = subprocess.check_output(
        ["git", "log", "--format=%s"], text=True
    ).count("Execute procedure")
    _run(monkeypatch, ["", "23.5", "yes"], no_commit=True)
    assert len(_log_rows()) == 6
    assert (
        subprocess.check_output(
            ["git", "log", "--format=%s"], text=True
        ).count("Execute procedure")
        == before
    )
    # A name the project doesn't have is an error, not an empty run
    from calkit.cli.main.core import run_procedure

    with pytest.raises(typer.Exit):
        run_procedure("no-such-procedure")


def test_run_procedure_definition_must_be_committed(tmp_dir, monkeypatch):
    import subprocess

    from calkit.cli.main.core import run_procedure
    from calkit.procedures import definition_paths

    ck_info = _project()
    # Something else in the tree, uncommitted, is not this procedure's
    # business: a procedure that is a pipeline stage runs after earlier
    # stages have written their outputs, so a whole-tree check could never
    # hold there
    with open("notes.txt", "w") as f:
        f.write("still thinking\n")
    _run(monkeypatch, ["", "21.5", "yes"])
    assert len(_log_rows()) == 2
    # The procedure's own definition, edited and not committed, is
    ck_info["procedures"]["measure-rig"]["steps"].append(
        {"summary": "Put the kettle on"}
    )
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    with pytest.raises(typer.Exit):
        run_procedure("measure-rig")
    subprocess.check_call(["git", "commit", "-q", "-am", "Edit procedure"])
    # Three steps now, so: step 0, the two inputs of step 1, then step 2
    _run(monkeypatch, ["", "22.0", "ok", ""])
    assert len(_log_rows()) == 5
    # calkit.yaml names the procedure, and the file holds it when it is
    # kept in one; both have to be committed
    assert definition_paths("measure-rig", ck_info=ck_info) == ["calkit.yaml"]
    in_file = {
        "procedures": {"measure-rig": {"path": "procedures/measure-rig.yaml"}}
    }
    assert definition_paths("measure-rig", ck_info=in_file) == [
        "calkit.yaml",
        "procedures/measure-rig.yaml",
    ]
    # A name the project doesn't have, and an entry that doesn't validate,
    # still have calkit.yaml behind them
    assert definition_paths("nope", ck_info=in_file) == ["calkit.yaml"]
    assert definition_paths(
        "bad", ck_info={"procedures": {"bad": "not an entry"}}
    ) == ["calkit.yaml"]


def test_procedure_pipeline_stage(tmp_dir):
    from calkit.models.pipeline import Pipeline

    pipeline = Pipeline.model_validate(
        {
            "stages": {
                "collect": {
                    "kind": "procedure",
                    "procedure_name": "measure-rig",
                    "outputs": [{"path": "data/raw.csv", "storage": "dvc"}],
                },
                "plot": {
                    "kind": "python-script",
                    "environment": "py",
                    "script_path": "plot.py",
                    "inputs": [{"from_stage_outputs": "collect"}],
                    "outputs": ["figures/plot.png"],
                },
            }
        }
    )
    stage = pipeline.stages["collect"]
    # A person in a room, not a runtime: nothing to activate, so the
    # command is not wrapped in an environment
    assert stage.dvc_cmd == "calkit xproc measure-rig"
    dvc = stage.to_dvc()
    # The run log is an output like any other, so the next stage can read
    # it and the pipeline knows whether the step has happened. Kept in Git
    # and never cleared: earlier runs are data, not stale output.
    assert dvc["outs"][0] == {
        ".calkit/procedure-runs/measure-rig": {"cache": False, "persist": True}
    }
    assert dvc["outs"][1] == {
        "data/raw.csv": {"cache": True, "persist": False}
    }
    # A change to what the person is asked to do means the old run no
    # longer stands for it
    assert dvc["deps"] == ["calkit.yaml"]
    pipeline.resolve_procedure_paths(
        {"measure-rig": {"path": "procedures/measure-rig.yaml"}}
    )
    assert stage.to_dvc()["deps"] == [
        "calkit.yaml",
        "procedures/measure-rig.yaml",
    ]
    # A procedure moved back inline has nothing extra to depend on, and
    # must not leave the stage depending on a file that is no longer there
    pipeline.resolve_procedure_paths({"measure-rig": {"title": "x"}})
    assert stage.to_dvc()["deps"] == ["calkit.yaml"]
    # Declaring the log directory as an output is redundant but harmless;
    # it must not end up in the compiled stage twice
    declared = Pipeline.model_validate(
        {
            "stages": {
                "collect": {
                    "kind": "procedure",
                    "procedure_name": "measure-rig",
                    "outputs": [".calkit/procedure-runs/measure-rig"],
                }
            }
        }
    )
    assert declared.stages["collect"].to_dvc()["outs"] == [
        {
            ".calkit/procedure-runs/measure-rig": {
                "cache": False,
                "persist": True,
            }
        }
    ]
