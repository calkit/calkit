"""Tests for the untraceable-literal half of ``calkit check repro``."""

import json
import subprocess

import calkit


def _project() -> None:
    """A project whose paper cites one computed value and types another."""
    subprocess.check_call(["calkit", "init"])
    with open("results.json", "w") as f:
        json.dump({"DragCoefficient": 0.42, "LiftCoefficient": 1.23}, f)
    with open("compute.py", "w") as f:
        f.write("print(1)\n")
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "py": {"kind": "uv-venv", "path": "reqs.txt", "python": "3.13"}
    }
    with open("reqs.txt", "w") as f:
        f.write("polars\n")
    # The Calkit-native way to get a value onto the page: a stage computes
    # it, a json-to-latex stage turns the results file into commands, and
    # the document refers to it by key
    ck_info["pipeline"] = {
        "stages": {
            "compute": {
                "kind": "python-script",
                "environment": "py",
                "script_path": "compute.py",
                "outputs": [{"path": "results.json", "storage": "git"}],
            },
            "results-latex": {
                "kind": "json-to-latex",
                "command_name": "result",
                "inputs": ["results.json"],
                "outputs": [{"path": "results.tex", "storage": "git"}],
            },
            "build-paper": {
                "kind": "latex",
                "environment": "py",
                "target_path": "main.tex",
            },
        }
    }
    ck_info["publications"] = [
        {"title": "My Paper", "path": "main.tex", "kind": "journal-article"}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\input{results}\n"
            "A value read from the pipeline: \\result[DragCoefficient].\n"
            "The same value typed by hand: 0.42.\n"
            "A value with nothing behind it: 3.14.\n"
            "\\end{document}\n"
        )
    # The check reads the compiled pipeline, which is where the commands
    # that identify a from-json stage live
    calkit.pipeline.to_dvc(ck_info=ck_info, write=True)


def test_check_repro_literals(tmp_dir):
    _project()
    result = subprocess.run(
        ["calkit", "check", "repro"],
        capture_output=True,
        text=True,
        check=True,
    )
    # 3.14 is not in any results file, so nothing accounts for it
    assert "Untraceable literals: 1" in result.stdout
    assert "Untraceable Literals" in result.stdout
    assert "3.14" in result.stdout
    # 0.42 is in the results file, so it reads as traceable even though it
    # was typed here. The check under-flags on purpose: a value the project
    # computes is not evidence of a mistake, and a false positive on a real
    # number costs more than a missed one.
    assert "0.42" not in result.stdout.split("Untraceable Literals")[1]
    result_json = subprocess.run(
        ["calkit", "check", "repro", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    parsed = json.loads(result_json.stdout)
    assert len(parsed["untraceable_literals"]) == 1
    finding = parsed["untraceable_literals"][0]
    assert finding["value"] == "3.14"
    assert finding["file"] == "main.tex"
    assert finding["line"] == 6
    # The fix points at the stage kind, not at a hand-written DVC command
    assert "json-to-latex" in finding["suggestion"]


def test_generated_tex_is_not_scanned(tmp_dir):
    # The file a json-to-latex stage writes is full of the very numbers the
    # check is looking for, and reporting them would flag the fix itself
    _project()
    with open("results.tex", "w") as f:
        f.write("\\newcommand\\result[1][all]{0.42 1.23 9.99}\n")
    result = subprocess.run(
        ["calkit", "check", "repro", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    values = [
        f["value"] for f in json.loads(result.stdout)["untraceable_literals"]
    ]
    assert values == ["3.14"]
