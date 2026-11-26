"""Tests for ``cli.describe``."""

import json
import os
import subprocess
from pathlib import Path
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


def test_describe_env_cache(tmp_dir: Path) -> None:
    ck_info = {
        "environments": {
            "py": {"kind": "uv-venv", "path": "requirements.txt"},
            "img": {"kind": "docker", "image": "alpine"},
        },
        "pipeline": {
            "stages": {
                "a": {
                    "kind": "shell-command",
                    "command": "echo",
                    "environment": "py",
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    # The pipeline's environments by default
    for cmd in ["environment-cache", "env-cache"]:
        out = subprocess.check_output(
            ["calkit", "describe", cmd, "--json"], text=True
        )
        spec = json.loads(out)
        assert set(spec["environments"]) == {"py"}
        assert spec["key"].startswith(spec["restore_key"])
        assert os.path.abspath(".venv") in spec["paths"]
        assert spec["ready"] is False
    # Or those named
    out = subprocess.check_output(
        ["calkit", "describe", "env-cache", "-n", "img", "--json"], text=True
    )
    spec = json.loads(out)
    assert spec["key"] is None
    assert spec["environments"]["img"]["cached"] is False
    out = subprocess.check_output(
        ["calkit", "describe", "env-cache"], text=True
    )
    assert "key: calkit-envs-" in out
    assert f"path: {os.path.abspath('.venv')}" in out
    assert "py:\n    kind: uv-venv" in out
    proc = subprocess.run(
        ["calkit", "describe", "env-cache", "-n", "nope"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "not defined" in proc.stderr


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
