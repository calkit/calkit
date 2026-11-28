"""Tests for ``cli.describe``."""

import json
import os
import subprocess
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

import calkit
from calkit.cli.main import app


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
    # Apps beyond the ones always reported can be asked about
    out = subprocess.check_output(
        [
            "calkit",
            "describe",
            "system",
            "--json",
            "--app",
            "calkit",
            "--app",
            "calkit-test-no-such-app",
        ],
        text=True,
    )
    info = json.loads(out)
    assert info["calkit_version"]
    assert info["calkit-test-no-such-app_version"] is None


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


def test_describe_subprojects(tmp_dir):
    os.makedirs("sub/nested")
    os.makedirs("iso/.dvc")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "subprojects": [
                    {"path": "sub", "description": "Sub."},
                    {"path": "iso"},
                ]
            },
            f,
        )
    with open("sub/calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "name": "sub",
                "title": "Sub",
                "subprojects": [{"path": "nested"}],
                "environments": {
                    "py": {"kind": "uv", "path": "pyproject.toml"}
                },
                "pipeline": {"stages": {"a": {}, "b": {}}},
            },
            f,
        )
    for path in ["sub/nested", "iso"]:
        with open(f"{path}/calkit.yaml", "w") as f:
            calkit.ryaml.dump({}, f)
    out = subprocess.check_output(
        ["calkit", "describe", "subprojects", "--json"], text=True
    )
    assert json.loads(out) == {
        "sub": {
            "parent": ".",
            "description": "Sub.",
            "name": "sub",
            "title": "Sub",
            "isolated": False,
            "environments": ["py"],
            "stages": ["a", "b"],
            "subprojects": ["sub/nested"],
        },
        "sub/nested": {
            "parent": "sub",
            "description": None,
            "name": None,
            "title": None,
            "isolated": False,
            "environments": [],
            "stages": [],
            "subprojects": [],
        },
        "iso": {
            "parent": ".",
            "description": None,
            "name": None,
            "title": None,
            "isolated": True,
            "environments": [],
            "stages": [],
            "subprojects": [],
        },
    }
    # Human-readable output drops what's null
    out = subprocess.check_output(
        ["calkit", "describe", "subprojects"], text=True
    )
    assert "sub/nested:\n    parent: sub\n" in out
    assert "title" not in out.split("sub/nested:")[1]


def test_describe_storage():
    runner = CliRunner()
    hf = {"kind": "hf-bucket", "bucket": "someone/proj"}
    responses = {
        "/projects/someone/proj/storage": {"dvc": hf, "previous": []},
        "/projects/someone/proj/storage/usage": {
            "project_used_gb": 0.25,
            "account": {"used_gb": 3.0, "limit_gb": 10},
        },
    }
    repo = MagicMock()
    repo.remote.return_value.url = "git@github.com:someone/proj.git"
    with (
        patch.object(
            calkit, "detect_project_name", return_value="someone/proj"
        ),
        patch.object(calkit.git, "get_repo", return_value=repo),
        patch.object(calkit.hub, "get", side_effect=responses.get),
    ):
        result = runner.invoke(app, ["describe", "storage", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {
            "project": "someone/proj",
            "git": {
                "storage": "GitHub repo someone/proj",
                "url": "git@github.com:someone/proj.git",
            },
            "dvc": {
                "storage": "Hugging Face bucket someone/proj",
                "previous_storage": ["Calkit Hub storage"],
                "hub_used_gb": 0.25,
                "account_hub_used_gb": 3.0,
                "account_hub_limit_gb": 10,
            },
        }
        result = runner.invoke(app, ["describe", "storage"])
        assert "git storage: GitHub repo someone/proj" in result.output
        assert "dvc storage: Hugging Face bucket someone/proj" in result.output
        assert "dvc also read from: Calkit Hub storage" in result.output
        assert "hub storage used: 250.0 MB" in result.output
        # Box storage is one folder for all of an account's projects, named
        # by who connected it
        box = {"kind": "box-folder", "bucket": "123", "connected_by": "pete"}
        responses["/projects/someone/proj/storage"] = {
            "dvc": box,
            "previous": [hf],
        }
        result = runner.invoke(app, ["describe", "storage"])
        assert "dvc storage: Box, connected by pete" in result.output
        assert (
            "dvc also read from: Hugging Face bucket someone/proj, "
            "Calkit Hub storage"
        ) in result.output
        assert "account hub storage used: 3.00 GB of 10 GB" in result.output
        # S3 storage is shown by its URL, and read-only storage says so
        responses["/projects/someone/proj/storage"] = {
            "dvc": {"kind": "s3-bucket", "bucket": "lab/calkit"},
            "previous": [
                {"kind": "s3-bucket", "bucket": "shared", "read_only": True}
            ],
        }
        result = runner.invoke(app, ["describe", "storage"])
        assert "dvc storage: S3 bucket s3://lab/calkit" in result.output
        assert (
            "dvc also read from: S3 bucket s3://shared (read-only), "
            "Calkit Hub storage"
        ) in result.output
        # Someone who doesn't manage the account only sees the project's,
        # a project on the hub's own storage reads from nothing else, and a
        # remote elsewhere is shown as its URL, without credentials
        responses["/projects/someone/proj/storage"] = {
            "dvc": None,
            "previous": [],
        }
        responses["/projects/someone/proj/storage/usage"] = {
            "project_used_gb": 1.5,
            "account": None,
        }
        repo.remote.return_value.url = (
            "https://someone:secret@gitlab.com/someone/proj"
        )
        result = runner.invoke(app, ["describe", "storage"])
        assert "git storage: https://gitlab.com/someone/proj" in result.output
        assert "secret" not in result.output
        assert "dvc storage: Calkit Hub storage" in result.output
        assert "also read from" not in result.output
        assert "hub storage used: 1.50 GB" in result.output
        assert "account hub storage used" not in result.output


def test_describe_artifact(kit_project, tmp_path):
    import calkit.hub
    import calkit.kits

    runner = CliRunner()
    hub_url = calkit.hub.get_hub_url().rstrip("/")
    kit_path = str(tmp_path / "fig.png")
    calkit.kits.write_copy(
        "figures/fig.png", kit_path, up_to_date=True, max_size=1000
    )
    # A file with a kit is described by it, from anywhere, and the
    # subcommand name can be left out
    for args in [["describe", kit_path], ["describe", "artifact", kit_path]]:
        res = runner.invoke(app, args)
        assert res.exit_code == 0, res.stdout
        assert "figures/fig.png from kit-test at" in res.stdout
        assert "https://github.com/someone/kit-test.git" in res.stdout
        assert f"On hub: {hub_url}/someone/kit-test/files" in res.stdout
        assert "Made by stage: make" in res.stdout
        assert "Unchanged since calkit was created" in res.stdout
        assert "origin not defined for data/raw.csv" in res.stdout
        assert "  - data/raw.csv" in res.stdout
        assert "    scripts/make.py" in res.stdout
        # Here in its source project, it says what's changed since
        assert "From this project, at HEAD" in res.stdout
        assert "No newer figures/fig.png here" in res.stdout
    res = runner.invoke(app, ["describe", kit_path, "--json"])
    assert res.exit_code == 0, res.stdout
    info = json.loads(res.stdout)
    assert info["this_project"]["commit_found"] is True
    assert info["artifact_unchanged"] is True
    assert info["matches_pipeline"] is True
    assert info["calkit"]["artifact"]["stage"] == "make"
    assert info["calkit"]["provenance_gaps"][0]["path"] == "data/raw.csv"
    # A file in the project is described as part of it
    res = runner.invoke(app, ["describe", "figures/fig.png"])
    assert res.exit_code == 0, res.stdout
    assert "figures/fig.png: not declared in calkit.yaml" in res.stdout
    assert "Made by stage: make" in res.stdout
    assert "Up to date" in res.stdout
    assert "origin not defined for data/raw.csv" in res.stdout
    assert "calkit kit bundle figures/fig.png" in res.stdout
    # Defining the input's origin and declaring the figure fills the gaps
    ck_info = calkit.load_calkit_info()
    ck_info["figures"] = [{"path": "figures/fig.png", "title": "Squares"}]
    ck_info["datasets"] = [
        {"path": "data/raw.csv", "imported_from": {"url": "https://x.org/a"}}
    ]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = runner.invoke(app, ["describe", "figures/fig.png", "--json"])
    assert res.exit_code == 0, res.stdout
    info = json.loads(res.stdout)
    assert info["kind"] == "figures"
    assert info["title"] == "Squares"
    assert info["provenance_gaps"] == []
    res = runner.invoke(app, ["describe", "data/raw.csv"])
    assert "data/raw.csv: dataset" in res.stdout
    assert "Imported from:" in res.stdout
    assert "Provenance defined for all inputs" in res.stdout
    # Subcommands still win, and missing files are errors
    res = runner.invoke(app, ["describe", "system"])
    assert res.exit_code == 0, res.stdout
    res = runner.invoke(app, ["describe", "nope.png"])
    assert res.exit_code != 0
    assert "doesn't exist" in res.stdout + str(res.stderr)
