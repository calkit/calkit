"""Tests for ``cli.describe``."""

import json
import subprocess

import calkit


def test_describe_system():
    out = subprocess.check_output(
        ["calkit", "describe", "system", "--json"], text=True
    )
    info = json.loads(out)
    assert info["calkit_version"] == calkit.__version__
    # Without --json, output is human-readable key: value lines
    out = subprocess.check_output(["calkit", "describe", "system"], text=True)
    assert not out.startswith("{")
    assert f"calkit_version: {calkit.__version__}" in out


def test_describe_environments(tmp_dir):
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.13",
            },
            "img": {"kind": "docker", "path": "Dockerfile", "image": "img"},
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    # A single environment, by both the long and short command names
    for cmd in ["environment", "env"]:
        out = subprocess.check_output(
            ["calkit", "describe", cmd, "-n", "py", "--json"], text=True
        )
        desc = json.loads(out)
        assert desc == {
            "kind": "uv-venv",
            "spec_path": "requirements.txt",
            "lock_path": calkit.environments.get_env_lock_fpath(
                env=ck_info["environments"]["py"], env_name="py"
            ),
            "prefix": None,
            "python": "3.13",
        }
    # Human-readable output keeps the same fields, minus the null ones
    out = subprocess.check_output(
        ["calkit", "describe", "environment", "-n", "py"], text=True
    )
    assert "kind: uv-venv" in out
    assert "spec_path: requirements.txt" in out
    assert "prefix" not in out
    # All environments, keyed by name
    for cmd in ["environments", "envs"]:
        out = subprocess.check_output(
            ["calkit", "describe", cmd, "--json"], text=True
        )
        descs = json.loads(out)
        assert set(descs) == {"py", "img"}
        assert descs["img"]["kind"] == "docker"
        assert descs["img"]["spec_path"] == "Dockerfile"
        assert descs["img"]["lock_path"] is not None
    out = subprocess.check_output(
        ["calkit", "describe", "environments"], text=True
    )
    assert "py:" in out
    assert "    kind: uv-venv" in out
    # Describing a nonexistent environment is an error
    proc = subprocess.run(
        ["calkit", "describe", "env", "-n", "nope", "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "not found" in proc.stderr


def test_describe_components(tmp_dir):
    import os

    import calkit

    subprocess.check_call(["calkit", "init"])
    os.makedirs("results")
    os.makedirs("paper")
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 8}, f)
    ck_info = calkit.load_calkit_info()
    ck_info["environments"] = {
        "py": {"kind": "uv-venv", "path": "reqs.txt", "python": "3.13"}
    }
    ck_info["pipeline"] = {
        "stages": {
            "summarize": {
                "kind": "python-script",
                "environment": "py",
                "script_path": "s.py",
                "inputs": ["data.csv"],
                "outputs": [{"path": "results/findings.json"}],
            }
        }
    }
    ck_info["questions"] = [
        {
            "question": "Do the top structures use the rectifier?",
            "answer": "{n_top} of eight do.",
            "evidence": [
                {
                    "kind": "value",
                    "path": "results/findings.json",
                    "key": "n_top",
                }
            ],
        }
    ]
    with open("s.py", "w") as f:
        f.write("print(1)\n")
    with open("reqs.txt", "w") as f:
        f.write("polars\n")
    with open("data.csv", "w") as f:
        f.write("a\n1\n")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    subprocess.check_call(
        [
            "calkit",
            "latex",
            "from-json",
            "results/findings.json",
            "-o",
            "paper/numbers.tex",
            "--command",
            "result",
        ]
    )
    subprocess.check_call(
        ["calkit", "latex", "from-questions", "-o", "paper/gq.tex"]
    )
    with open("paper/main.tex", "w") as f:
        f.write(
            "\\documentclass{article}\n"
            "\\usepackage[provenance]{calkit}\n"
            "\\input{numbers}\n"
            "\\input{gq}\n"
            "\\begin{document}\n"
            "We saw \\result[n_top] of them.\n"
            "\\ckfindings\n"
            "\\end{document}\n"
        )
    subprocess.check_call(["git", "add", "-A"])
    subprocess.check_call(["git", "commit", "-q", "-m", "Answer"])
    out = subprocess.check_output(
        [
            "calkit",
            "describe",
            "components",
            "paper/main.tex",
            "--no-stage-check",
            "--json",
        ],
        text=True,
    )
    result = json.loads(out)
    assert result["built"] is False
    by = {(c["kind"], c["key"]): c for c in result["components"]}
    value = by[("value", "n_top")]
    assert value["path"] == "results/findings.json"
    assert value["stage"] == "summarize"
    assert value["script"] == "s.py"
    assert value["current_value"] == 8
    assert by[("block", "1")]["status"] == "ok"
    # A position resolves to what is under the cursor, which is what an
    # editor asks on hover
    out = subprocess.check_output(
        [
            "calkit",
            "describe",
            "components",
            "paper/main.tex",
            "--line",
            "6",
            "--no-stage-check",
            "--json",
        ],
        text=True,
    )
    at_cursor = json.loads(out)["components"]
    assert len(at_cursor) == 1
    assert at_cursor[0]["key"] == "n_top"
    assert at_cursor[0]["document_value"] == "8"
    # The pipeline moves the number on without the answer being reread:
    # the block that typesets that answer is stale
    with open("results/findings.json", "w") as f:
        json.dump({"n_top": 0}, f)
    subprocess.check_call(["git", "commit", "-q", "-am", "Re-run"])
    out = subprocess.check_output(
        [
            "calkit",
            "describe",
            "components",
            "paper/main.tex",
            "--no-stage-check",
            "--json",
        ],
        text=True,
    )
    by = {(c["kind"], c["key"]): c for c in json.loads(out)["components"]}
    assert by[("block", "1")]["status"] == "stale"
    assert by[("block", "1")]["stale_reasons"] == ["answer-stale"]
    # A stage needing a rerun is a different kind of out of date, and it
    # shows on everything that stage produces. This one has never run.
    out = subprocess.check_output(
        ["calkit", "describe", "components", "paper/main.tex", "--json"],
        text=True,
    )
    by = {(c["kind"], c["key"]): c for c in json.loads(out)["components"]}
    assert by[("value", "n_top")]["stale_reasons"] == ["stage-out-of-date"]
    assert by[("value", "n_top")]["status"] == "stale"
    # Human-readable output names the file, the stage and the script
    out = subprocess.check_output(
        [
            "calkit",
            "describe",
            "components",
            "paper/main.tex",
            "--stale",
            "--no-stage-check",
        ],
        text=True,
    )
    assert "block calkit.yaml:1" in out
    assert "answer-stale" in out
    assert "value results/findings.json:n_top" not in out
