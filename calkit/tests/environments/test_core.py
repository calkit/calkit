"""Tests for ``calkit.environments.core``."""

import os
import subprocess

import pytest
import typer

import calkit.cli.check
import calkit.environments.core
from calkit.environments.core import relock


def test_relock(tmp_dir, monkeypatch):
    seen = {}

    def fake_check(env_name, verbose=False, force=False):
        seen[env_name] = {
            "force": force,
            "exist": sorted(
                p
                for p in ["Manifest.toml", "Manifest-v1.11.toml"]
                if os.path.isfile(p)
            ),
        }

    monkeypatch.setattr(calkit.cli.check, "check_environment", fake_check)
    # Julia removes the fallback manifest along with its versioned one
    for fname in ["Project.toml", "Manifest.toml", "Manifest-v1.11.toml"]:
        with open(fname, "w") as f:
            f.write("old\n")
    relock("jl", {"kind": "julia", "path": "Project.toml", "julia": "1.11"})
    assert seen["jl"] == {"force": True, "exist": []}
    # Pixi names the manifest it was given, not whichever it finds
    ran = []

    def fake_run(cmd, cwd=None):
        ran.append((cmd, cwd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(calkit.environments.core.subprocess, "run", fake_run)
    os.makedirs("env")
    relock("px", {"kind": "pixi", "path": "env/pyproject.toml"})
    assert ran[-1] == (
        [
            "pixi",
            "update",
            "--manifest-path",
            os.path.abspath("env/pyproject.toml"),
        ],
        "env",
    )
    assert seen["px"]["force"] is False
    # A failed rebuild puts back every old lock and removes any it wrote
    lock_dir = os.path.join(".calkit", "env-locks")
    os.makedirs(os.path.join(lock_dir, "img"))
    old_locks = {
        os.path.join(lock_dir, "img", "arm64.json"): b'{"arch": "arm64"}',
        os.path.join(lock_dir, "img.json"): b'{"legacy": true}',
    }
    for fpath, content in old_locks.items():
        with open(fpath, "wb") as fb:
            fb.write(content)
    new_lock = os.path.join(lock_dir, "img", "amd64.json")

    def failing_check(env_name, verbose=False, force=False):
        assert not any(os.path.isfile(p) for p in old_locks)
        with open(new_lock, "w") as f:
            f.write("{}")
        raise typer.Exit(1)

    monkeypatch.setattr(calkit.cli.check, "check_environment", failing_check)
    with pytest.raises(typer.Exit):
        relock("img", {"kind": "docker", "image": "alpine:3.19"})
    for fpath, content in old_locks.items():
        with open(fpath, "rb") as fr:
            assert fr.read() == content
    assert not os.path.exists(new_lock)
    # So does a failed upgrade command that rewrote the lock first
    os.makedirs("uvenv")
    with open(os.path.join("uvenv", "uv.lock"), "w") as f:
        f.write("old\n")

    def failing_upgrade(cmd, cwd=None):
        with open(os.path.join(cwd, "uv.lock"), "w") as f:
            f.write("new\n")
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(
        calkit.environments.core.subprocess, "run", failing_upgrade
    )
    with pytest.raises(typer.Exit):
        relock("uv", {"kind": "uv", "path": "uvenv/pyproject.toml"})
    with open(os.path.join("uvenv", "uv.lock")) as f:
        assert f.read() == "old\n"
