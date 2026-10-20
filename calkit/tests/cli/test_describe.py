"""Tests for ``cli.describe``."""

import json
import os
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
