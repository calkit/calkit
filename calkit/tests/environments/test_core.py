"""Tests for ``calkit.environments.core``."""

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from datetime import timedelta
from unittest import mock

import pytest
import typer

import calkit
import calkit.cli.check
import calkit.environments
import calkit.environments.core
import calkit.environments.texlive
import calkit.pipeline
import calkit.progress
from calkit.environments.core import relock


def test_check_all_in_pipeline(tmp_dir, capfd):
    ck_info: dict = {
        "environments": {
            "py1": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.13",
                "prefix": ".venv",
            },
        },
        "pipeline": {
            "stages": {
                "run-thing": {
                    "kind": "python-script",
                    "script_path": "scripts/run-thing.py",
                    "environment": "py1",
                }
            },
        },
    }
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert res["py1"]["cached"]
    res = calkit.environments.check_all_in_pipeline(force=True)
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    # Check that if we update requirements.txt, the environment check is no
    # longer cached
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
        f.write("polars\n")
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    # Check that if we delete the env lock file, the environment check is no
    # longer cached
    env_lock_fpath = calkit.environments.get_env_lock_fpath(
        env=ck_info["environments"]["py1"], env_name="py1"
    )
    assert env_lock_fpath is not None
    assert os.path.exists(env_lock_fpath)
    os.remove(env_lock_fpath)
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    # Now make sure the env is rechecked if we delete the prefix
    env_prefix = ck_info["environments"]["py1"].get("prefix")
    assert env_prefix is not None
    shutil.rmtree(env_prefix)
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert not res["py1"].get("cached")
    res = calkit.environments.check_all_in_pipeline()
    print(res)
    assert res["py1"]["success"]
    assert res["py1"]["cached"]
    # A frozen stage never runs, so its environment isn't checked or built
    shutil.rmtree(env_prefix)
    ck_info["pipeline"]["stages"]["run-thing"]["frozen"] = True
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    assert calkit.environments.check_all_in_pipeline() == {}
    assert (
        calkit.environments.check_all_in_pipeline(targets=["run-thing"]) == {}
    )
    assert not os.path.exists(env_prefix)
    # A Docker environment needs Docker ready, which is checked up front
    ck_info["environments"]["docker1"] = {"kind": "docker", "image": "alpine"}
    ck_info["pipeline"]["stages"]["run-docker"] = {
        "kind": "command",
        "command": "echo hi",
        "environment": "docker1",
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with mock.patch(
        "calkit.docker.ensure_ready",
        side_effect=ValueError("Docker is required, but is not installed"),
    ) as ensure_ready:
        with pytest.raises(ValueError, match="not installed"):
            calkit.environments.check_all_in_pipeline(interactive=True)
        ensure_ready.assert_called_once_with(interactive=True)
        # Only when a stage that will run uses it
        assert (
            calkit.environments.check_all_in_pipeline(targets=["run-thing"])
            == {}
        )
        # Not when it isn't known yet which stages will run, in which case
        # the environment's own check fails instead
        ensure_ready.reset_mock()
        with mock.patch(
            "calkit.cli.check.check_environment", side_effect=Exception
        ):
            res = calkit.environments.check_all_in_pipeline(
                docker_required=False
            )
        ensure_ready.assert_not_called()
        assert not res["docker1"]["success"]
        # Nor when it runs inside an environment on another machine or a
        # scheduler, which needs Docker there instead
        ck_info["environments"]["remote"] = {
            "kind": "system",
            "host": "some-other-machine.example.com",
        }
        ck_info["environments"]["cluster"] = {"kind": "slurm", "host": "hpc"}
        for outer in ["remote", "cluster"]:
            ck_info["pipeline"]["stages"]["run-docker"]["environment"] = (
                f"{outer}:docker1"
            )
            with open("calkit.yaml", "w") as f:
                calkit.ryaml.dump(ck_info, f)
            with mock.patch("calkit.cli.check.check_environment"):
                calkit.environments.check_all_in_pipeline(
                    targets=["run-docker"]
                )
            ensure_ready.assert_not_called()
        # But it does when that machine is this one
        ck_info["environments"]["remote"]["host"] = "localhost"
        ck_info["pipeline"]["stages"]["run-docker"]["environment"] = (
            "remote:docker1"
        )
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        with pytest.raises(ValueError, match="not installed"):
            calkit.environments.check_all_in_pipeline(targets=["run-docker"])
    del ck_info["pipeline"]["stages"]["run-docker"]
    del ck_info["pipeline"]["stages"]["run-thing"]["frozen"]
    # Editing an input's contents, not just its path, invalidates the cache
    with open("local.txt", "w") as f:
        f.write("one\n")
    ck_info["environments"]["py1"]["inputs"] = ["local.txt"]
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    assert not calkit.environments.check_all_in_pipeline()["py1"].get("cached")
    assert calkit.environments.check_all_in_pipeline()["py1"]["cached"]
    with open("local.txt", "w") as f:
        f.write("two\n")
    assert not calkit.environments.check_all_in_pipeline()["py1"].get("cached")
    # An inner env runs where its outer env does, so one behind another
    # machine isn't checked here; nor are the envs of stages that are
    # skipped, and an undefined env is a failure rather than a crash
    ck_info["environments"]["far"] = {
        "kind": "system",
        "host": "calkit-test.invalid",
    }
    ck_info["environments"]["py2"] = {
        "kind": "uv-venv",
        "path": "requirements.txt",
        "prefix": ".venv2",
    }
    stages = ck_info["pipeline"]["stages"]
    stages["remote"] = {
        "kind": "python-script",
        "script_path": "s.py",
        "environment": "far:py2",
    }
    stages["skipped"] = {
        "kind": "python-script",
        "script_path": "s.py",
        "environment": "py2",
    }
    stages["typo"] = {
        "kind": "python-script",
        "script_path": "s.py",
        "environment": "nope",
    }
    # A notebook stage runs here in its inner env whatever its outer one
    ck_info["environments"]["py3"] = dict(
        ck_info["environments"]["py2"], prefix=".venv3"
    )
    stages["nb"] = {
        "kind": "jupyter-notebook",
        "notebook_path": "nb.ipynb",
        "environment": "far:py3",
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    res = calkit.environments.check_all_in_pipeline(skip_stages=["skipped"])
    assert set(res) == {"py1", "far", "nope", "py3"}
    assert not res["nope"]["success"]
    assert not os.path.isdir(".venv2")
    # Nor that of a stage whose items are all skipped, unlike one with an
    # item left to run
    iterated = dict(
        stages["skipped"],
        iterate_over=[{"arg_name": "app", "values": ["a", "b"]}],
        requirements=["{app}"],
    )
    info = {**ck_info, "pipeline": {"stages": {"skipped": iterated}}}
    for skip, expected in [
        (["skipped@a", "skipped@b"], []),
        (["skipped@a"], ["py2"]),
    ]:
        names, _, _ = calkit.environments.get_pipeline_env_names(
            info, skip_stages=skip
        )
        assert names == expected

    # Quiet discards what the checks and their tools print, and leaves the
    # terminal's handles intact, since on Windows Click keeps its own. Nobody
    # can answer a prompt there either, so they get no input.
    def noisy_check(*args: object, **kwargs: object) -> None:
        print("from python")
        subprocess.run(["git", "--version"])
        with pytest.raises(EOFError):
            input("Continue? ")
        assert subprocess.run([sys.executable, "-c", "input()"]).returncode

    capfd.readouterr()
    if sys.platform == "win32":
        import msvcrt

        stderr_handle = msvcrt.get_osfhandle(2)
    with mock.patch(
        "calkit.cli.check.check_environment", side_effect=noisy_check
    ):
        res = calkit.environments.check_all_in_pipeline(
            skip_stages=["skipped"], force=True, quiet=True
        )
    assert res["py1"]["success"]
    assert capfd.readouterr() == ("", "")
    if sys.platform == "win32":
        assert msvcrt.get_osfhandle(2) == stderr_handle
    assert calkit.environments.check_inner_env_there(
        ["calkit", "xenv", "-n", "py2", "--no-check", "--", "a", "--no-check"]
    ) == ["calkit", "xenv", "-n", "py2", "--", "a", "--no-check"]
    assert calkit.environments.check_inner_env_there(["echo", "hi"]) == [
        "echo",
        "hi",
    ]
    # The inner env a job runs in is read from its command
    for argv, name in [
        (["--", "calkit", "xenv", "-n", "py", "--no-check", "--", "a"], "py"),
        (["calkit", "xenv", "--name=py", "--", "-n", "x"], "py"),
        (["calkit", "xenv", "--", "-n", "x"], None),
        (["echo", "-n", "hi"], None),
    ]:
        assert calkit.environments.inner_env_name(argv) == name


def test_cache_uses_dir_signature_for_conda_prefix(tmp_dir, monkeypatch):
    env = {
        "kind": "conda",
        "path": "environment.yml",
        "prefix": ".conda",
    }
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump({"name": "myenv", "dependencies": ["python"]}, f)
    os.makedirs(".conda", exist_ok=True)
    with open(".conda/marker.txt", "w") as f:
        f.write("one")
    lock_fpath = calkit.environments.get_env_lock_fpath(
        env=env, env_name="myenv", as_posix=False
    )
    assert lock_fpath is not None
    os.makedirs(os.path.dirname(lock_fpath), exist_ok=True)
    with open(lock_fpath, "w") as f:
        f.write("lock")
    calkit.environments.save_cache(env_name="myenv", env=env, success=True)
    assert calkit.environments.check_cache(env_name="myenv", env=env)
    real_getmtime = os.path.getmtime
    prefix_mtime = real_getmtime(".conda")

    def _fake_getmtime(path):
        if os.path.abspath(path) == os.path.abspath(".conda"):
            return prefix_mtime
        return real_getmtime(path)

    monkeypatch.setattr(os.path, "getmtime", _fake_getmtime)
    with open(".conda/marker.txt", "w") as f:
        f.write("three")
    assert not calkit.environments.check_cache(env_name="myenv", env=env)


def test_cache_tracks_julia_manifest(tmp_dir):
    os.makedirs("juliaenv", exist_ok=True)
    with open("juliaenv/Project.toml", "w") as f:
        f.write('name = "demo"\n')
    with open("juliaenv/Manifest.toml", "w") as f:
        f.write("# manifest v1\n")
    env = {
        "kind": "julia",
        "path": "juliaenv/Project.toml",
        "julia": "1.11",
    }
    calkit.environments.save_cache(env_name="jl", env=env, success=True)
    assert calkit.environments.check_cache(env_name="jl", env=env)
    # Unrelated file change should NOT invalidate the cache
    with open("juliaenv/extra.txt", "w") as f:
        f.write("irrelevant")
    assert calkit.environments.check_cache(env_name="jl", env=env)
    # Changing Manifest.toml SHOULD invalidate
    with open("juliaenv/Manifest.toml", "w") as f:
        f.write("# manifest v2\n")
    assert not calkit.environments.check_cache(env_name="jl", env=env)


def test_cache_prefers_versioned_manifest(tmp_dir):
    os.makedirs("juliaenv", exist_ok=True)
    with open("juliaenv/Project.toml", "w") as f:
        f.write('name = "demo"\n')
    # Both Manifest.toml and Manifest-v1.11.toml exist; the versioned one wins
    with open("juliaenv/Manifest.toml", "w") as f:
        f.write("# plain manifest\n")
    with open("juliaenv/Manifest-v1.11.toml", "w") as f:
        f.write("# versioned manifest v1\n")
    env = {
        "kind": "julia",
        "path": "juliaenv/Project.toml",
        "julia": "1.11",
    }
    lock_fpath = calkit.environments.get_env_lock_fpath(
        env=env, env_name="jl", as_posix=False
    )
    assert lock_fpath is not None
    assert os.path.basename(lock_fpath) == "Manifest-v1.11.toml"
    calkit.environments.save_cache(env_name="jl", env=env, success=True)
    assert calkit.environments.check_cache(env_name="jl", env=env)
    # Touching the plain Manifest should NOT invalidate (versioned is tracked)
    with open("juliaenv/Manifest.toml", "w") as f:
        f.write("# plain manifest changed\n")
    assert calkit.environments.check_cache(env_name="jl", env=env)
    # Touching the versioned Manifest SHOULD invalidate
    with open("juliaenv/Manifest-v1.11.toml", "w") as f:
        f.write("# versioned manifest v2\n")
    assert not calkit.environments.check_cache(env_name="jl", env=env)


def test_versioned_manifest_uses_major_minor_only(tmp_dir):
    os.makedirs("juliaenv", exist_ok=True)
    with open("juliaenv/Project.toml", "w") as f:
        f.write('name = "demo"\n')
    # julia = "1.11.7" should still look for Manifest-v1.11.toml
    with open("juliaenv/Manifest-v1.11.toml", "w") as f:
        f.write("# versioned manifest\n")
    env = {
        "kind": "julia",
        "path": "juliaenv/Project.toml",
        "julia": "1.11.7",
    }
    lock_fpath = calkit.environments.get_env_lock_fpath(
        env=env, env_name="jl", as_posix=False
    )
    assert lock_fpath is not None
    assert os.path.basename(lock_fpath) == "Manifest-v1.11.toml"


def test_cache_includes_julia_packages_directory_changes(tmp_dir, monkeypatch):
    os.makedirs("juliaenv", exist_ok=True)
    with open("juliaenv/Project.toml", "w") as f:
        f.write('name = "demo"\n')
    with open("juliaenv/Manifest.toml", "w") as f:
        f.write("# manifest\n")
    depot = os.path.abspath(".test-julia-depot")
    packages_dir = os.path.join(depot, "packages")
    os.makedirs(packages_dir, exist_ok=True)
    pkg_file = os.path.join(packages_dir, "Example.txt")
    with open(pkg_file, "w") as f:
        f.write("one")
    monkeypatch.setenv("JULIA_DEPOT_PATH", depot)
    env = {
        "kind": "julia",
        "path": "juliaenv/Project.toml",
        "julia": "1.11",
    }
    calkit.environments.save_cache(env_name="jl-pkgs", env=env, success=True)
    assert calkit.environments.check_cache(env_name="jl-pkgs", env=env)
    with open(pkg_file, "w") as f:
        f.write("three")
    assert not calkit.environments.check_cache(env_name="jl-pkgs", env=env)


def test_check_cache_can_bypass_ttl(tmp_dir):
    with open("pyproject.toml", "w") as f:
        f.write('[project]\nname = "demo"\nversion = "0.1.0"\n')
    with open("uv.lock", "w") as f:
        f.write("version = 1\n")
    env = {"kind": "uv", "path": "pyproject.toml"}
    env_name = "ttl-test"
    data = calkit.environments.save_cache(
        env_name=env_name, env=env, success=True
    )
    key = calkit.environments.make_cache_key(env_name=env_name)
    with calkit.environments.get_cache_db() as db:
        stale = dict(data)
        stale["checked_at"] = stale["checked_at"] - timedelta(hours=2)
        db[key] = stale
        db.commit()
    assert not calkit.environments.check_cache(env_name=env_name, env=env)
    assert calkit.environments.check_cache(
        env_name=env_name, env=env, respect_ttl=False
    )


def test_get_venv_activate_cmd():
    get_venv_activate_cmd = calkit.environments.get_venv_activate_cmd
    # POSIX activates by sourcing the script
    assert (
        get_venv_activate_cmd(".venv", system="Linux")
        == ". .venv/bin/activate"
    )
    assert (
        get_venv_activate_cmd(".calkit/envs/a/.venv", system="Darwin")
        == ". .calkit/envs/a/.venv/bin/activate"
    )
    # Windows needs native separators throughout; cmd reads a forward slash
    # as a switch and would take a nested prefix for a '.calkit' command
    assert (
        get_venv_activate_cmd(".venv", system="Windows")
        == ".venv\\Scripts\\activate"
    )
    assert (
        get_venv_activate_cmd(".calkit/envs/a/.venv", system="Windows")
        == ".calkit\\envs\\a\\.venv\\Scripts\\activate"
    )
    assert "/" not in get_venv_activate_cmd("sub/.venv", system="Windows")
    # Defaults to the running platform
    assert get_venv_activate_cmd(".venv") == get_venv_activate_cmd(
        ".venv", system=platform.system()
    )


def test_get_uv_extras(monkeypatch):
    from calkit.environments import get_uv_extras

    gpus = (
        {"name": "AMD Radeon RX 9070 XT", "vendor": "amd", "arch": "gfx1201"},
    )
    monkeypatch.setattr("calkit.core.get_gpus", lambda: gpus)
    env = {
        "kind": "uv",
        "path": "pyproject.toml",
        "extras": [
            "plots",
            {"name": "rocm", "when": [{"gpu_arch_is": "gfx1201"}]},
            {"name": "cuda", "when": [{"gpu_vendor_is": "nvidia"}]},
            # Every condition must hold, not just one
            {
                "name": "rocm-on-cluster",
                "when": [
                    {"gpu_vendor_is": "amd"},
                    {"env_var_set": "CK_TEST_UNSET"},
                ],
            },
        ],
    }
    monkeypatch.delenv("CK_TEST_UNSET", raising=False)
    assert get_uv_extras(env) == ["plots", "rocm"]
    # On a machine without that GPU, the extra is left out, not an error
    monkeypatch.setattr("calkit.core.get_gpus", lambda: ())
    assert get_uv_extras(env) == ["plots"]
    assert get_uv_extras({"kind": "uv", "path": "pyproject.toml"}) == []
    # A mistake is an error, rather than leaving the extra out
    for bad in [
        {"name": "rocm"},
        {"name": "rocm", "when": []},
        {"name": "rocm", "when": [{"kind": "gpu-arch", "equals": "gfx1201"}]},
        {"name": "rocm", "when": [{"gpu_arch_is": "gfx1201"}], "if": "x"},
    ]:
        with pytest.raises(ValueError, match="is invalid"):
            get_uv_extras({"kind": "uv", "path": "x", "extras": [bad]})


def test_get_default_venv_prefix():
    get_default_venv_prefix = calkit.environments.get_default_venv_prefix
    # With no existing environments, default to .venv next to the spec file
    assert get_default_venv_prefix({}, "requirements.txt", "main") == ".venv"
    assert (
        get_default_venv_prefix({}, "sub/requirements.txt", "myenv")
        == "sub/.venv"
    )
    # A uv environment in the same directory occupies .venv, so nest the new
    # virtualenv under .calkit/envs/{name}
    envs = {"main": {"kind": "uv", "path": "pyproject.toml"}}
    assert (
        get_default_venv_prefix(envs, "requirements.txt", "myenv")
        == ".calkit/envs/myenv/.venv"
    )
    # A uv environment in another directory does not collide
    envs = {"sub": {"kind": "uv", "path": "sub/pyproject.toml"}}
    assert get_default_venv_prefix(envs, "requirements.txt", "main") == ".venv"
    # An explicit prefix on an existing environment is respected
    envs = {"a": {"kind": "venv", "prefix": ".venv"}}
    assert (
        get_default_venv_prefix(envs, "requirements.txt", "myenv")
        == ".calkit/envs/myenv/.venv"
    )
    # An environment does not collide with itself, so a prefix-less venv that
    # is already in the dict still resolves to .venv
    envs = {"main": {"kind": "uv-venv", "path": "requirements.txt"}}
    assert get_default_venv_prefix(envs, "requirements.txt", "main") == ".venv"
    # Two prefix-less venvs in the same directory both nest under their own
    # name, which is collision-free
    envs = {
        "a": {"kind": "venv", "path": "requirements.txt"},
        "b": {"kind": "venv", "path": "requirements.txt"},
    }
    assert (
        get_default_venv_prefix(envs, "requirements.txt", "b")
        == ".calkit/envs/b/.venv"
    )


def test_env_from_name_or_path(tmp_dir):
    # Test with typical venvs
    with open("requirements.txt", "w") as f:
        f.write("requests")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="requirements.txt"
    )
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    assert not res.exists
    # The prefix is left unset and resolved on the fly
    assert "prefix" not in res.env
    res = calkit.environments.env_from_name_or_path(
        name_or_path="requirements.txt"
    )
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    assert not res.exists
    # Test a venv in a subdirectory
    os.makedirs("envs")
    os.makedirs("envs/myenv")
    with open("envs/myenv/requirements.txt", "w") as f:
        f.write("requests")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="envs/myenv/requirements.txt"
    )
    assert res.name == "myenv"
    assert "prefix" not in res.env
    # Test with a conda env
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump({"name": "myenv", "dependencies": ["pandas"]}, f)
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="environment.yml"
    )
    assert res.name == "myenv"
    assert res.env["path"] == "environment.yml"
    assert not res.exists
    # Test with a uv project env
    subprocess.check_call(["uv", "init", "--bare"])
    subprocess.check_call(["uv", "add", "requests"])
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="pyproject.toml"
    )
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert not res.exists
    # Test that we don't overwrite an existing name
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv-venv", "path": "requirements.txt"}
                }
            },
            f,
        )
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="pyproject.toml"
    )
    assert res.name == "uv1"
    assert res.env["path"] == "pyproject.toml"
    assert not res.exists
    # Now, what if we put the environment in a subdirectory
    os.makedirs("envs/uvsubdir")
    subprocess.check_call(
        [
            "uv",
            "init",
            "--bare",
            "--directory",
            "envs/uvsubdir",
            "--no-workspace",
        ]
    )
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="envs/uvsubdir/pyproject.toml"
    )
    assert res.name == "uvsubdir"
    assert res.env["path"] == "envs/uvsubdir/pyproject.toml"
    assert res.env["kind"] == "uv"
    assert not res.exists
    # Check when the subdirectory name conflicts with an existing name
    os.makedirs("envs/main")
    subprocess.check_call(
        [
            "uv",
            "init",
            "--bare",
            "--directory",
            "envs/main",
            "--no-workspace",
        ]
    )
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="envs/main/pyproject.toml"
    )
    assert res.name == "main-uv"
    assert res.env["path"] == "envs/main/pyproject.toml"
    assert res.env["kind"] == "uv"
    assert not res.exists
    # Test with a Julia env
    os.makedirs("juliaenv")
    with open("juliaenv/Project.toml", "w") as f:
        f.write("doesn't need to work")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="juliaenv/Project.toml"
    )
    assert res.name == "juliaenv"
    assert res.env["path"] == "juliaenv/Project.toml"
    assert res.env["kind"] == "julia"
    assert not res.exists
    # Test with a Dockerfile
    with open("Dockerfile", "w") as f:
        f.write("FROM python:3.9-slim")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="Dockerfile"
    )
    assert res.name == "docker1"
    assert res.env["path"] == "Dockerfile"
    assert res.env["kind"] == "docker"
    # Test with a pixi env
    with open("pixi.toml", "w") as f:
        f.write("doesn't need to work")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="pixi.toml"
    )
    assert res.name == "pixi1"
    assert res.env["path"] == "pixi.toml"


def test_env_from_name_or_path_composite():
    ck_info = {
        "environments": {
            "py1": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.13",
                "prefix": ".venv",
            },
            "mycluster": {
                "kind": "slurm",
                "host": "mycluster.something.edu",
            },
        },
    }
    res = calkit.environments.env_from_name_or_path(
        name_or_path="mycluster", ck_info=ck_info
    )
    assert res.name == "mycluster"
    assert res.env["kind"] == "slurm"
    assert res.env["host"] == "mycluster.something.edu"
    res = calkit.environments.env_from_name_or_path(
        name_or_path="mycluster:py1", ck_info=ck_info
    )
    assert res.name == "py1"
    assert res.env["path"] == "requirements.txt"
    assert res.env["kind"] == "uv-venv"
    assert res.outer is not None
    assert res.outer.name == "mycluster"
    assert res.outer.env["kind"] == "slurm"
    assert res.outer.env["host"] == "mycluster.something.edu"
    assert res.exists
    assert res.outer.exists
    # Make sure we fail with the uv-venv as the outer env
    with pytest.raises(ValueError):
        calkit.environments.env_from_name_or_path(
            name_or_path="py1:mycluster", ck_info=ck_info
        )
    # Make sure this works with name and/or path
    res = calkit.environments.env_from_name_and_or_path(
        name="mycluster:py1", path=None, ck_info=ck_info
    )
    assert res.name == "py1"
    assert res.env["path"] == "requirements.txt"
    assert res.env["kind"] == "uv-venv"
    assert res.outer is not None
    assert res.outer.name == "mycluster"
    assert res.outer.env["kind"] == "slurm"
    assert res.outer.env["host"] == "mycluster.something.edu"
    assert res.exists
    assert res.outer.exists


def test_detect_default_env(tmp_dir):
    # First start with only a single env spec file
    with open("requirements.txt", "w") as f:
        f.write("requests")
    res = calkit.environments.detect_default_env()
    assert res is not None
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    # Now add a second env spec file--should not detect a default env anymore
    with open("environment.yml", "w") as f:
        calkit.ryaml.dump({"name": "myenv", "dependencies": ["pandas"]}, f)
    res = calkit.environments.detect_default_env()
    assert res is None


def test_extract_dependencies_and_env_superset(tmp_dir):
    with open("requirements.txt", "w") as f:
        f.write("requests>=2\n")
        f.write("numpy\n")
    deps = calkit.environments.extract_dependencies_from_spec_file(
        "requirements.txt"
    )
    assert "requests" in deps
    assert "numpy" in deps
    with open("pyproject.toml", "w") as f:
        f.write("[project]\n")
        f.write('name = "demo"\n')
        f.write('version = "0.1.0"\n')
        f.write('requires-python = ">=3.11"\n')
        f.write("dependencies = [\n")
        f.write('  "pandas>=2",\n')
        f.write('  "matplotlib",\n')
        f.write("]\n")
    pyproject_deps = calkit.environments.extract_dependencies_from_spec_file(
        "pyproject.toml"
    )
    assert "pandas" in pyproject_deps
    assert "matplotlib" in pyproject_deps
    env = {"kind": "uv", "path": "requirements.txt"}
    assert calkit.environments.env_has_superset_dependencies(
        env, ["requests", "numpy"], strict=True
    )
    assert not calkit.environments.env_has_superset_dependencies(
        env, ["requests", "numpy", "pandas"], strict=True
    )
    assert calkit.environments.env_has_superset_dependencies(
        {"kind": "uv", "path": "missing.txt"}, ["requests"], strict=False
    )
    assert not calkit.environments.env_has_superset_dependencies(
        {"kind": "uv", "path": "missing.txt"}, ["requests"], strict=True
    )
    with open("Project.toml", "w") as f:
        f.write("[deps]\n")
        f.write('DataFrames = "a93c6f00-e57d-5684-b7b6-d8193f3e46c0"\n')
        f.write('CSV = "336ed68f-0bac-5ca0-87d4-7b16caf5d00b"\n')
    julia_deps = calkit.environments.extract_dependencies_from_spec_file(
        "Project.toml"
    )
    assert "DataFrames" in julia_deps
    assert "CSV" in julia_deps
    with open("DESCRIPTION", "w") as f:
        f.write("Package: Demo\n")
        f.write("Version: 0.1.0\n")
        f.write("Imports: dplyr,\n")
        f.write("    ggplot2\n")
    r_deps = calkit.environments.extract_dependencies_from_spec_file(
        "DESCRIPTION"
    )
    assert "dplyr" in r_deps
    assert "ggplot2" in r_deps
    with open("environment.yml", "w") as f:
        f.write("name: test-env\n")
        f.write("dependencies:\n")
        f.write("  - python=3.11\n")
        f.write("  - conda-forge::pandas=2.0\n")
        f.write("  - jupyter\n")
        f.write("  - pip\n")
        f.write("  - pip:\n")
        f.write("    - requests==2.0\n")
        f.write("    - scipy>=1.0\n")
    conda_deps = calkit.environments.extract_dependencies_from_spec_file(
        "environment.yml"
    )
    assert "pandas" in conda_deps
    assert "requests" in conda_deps
    assert "scipy" in conda_deps
    conda_env = {"kind": "conda", "path": "environment.yml"}
    assert calkit.environments.env_has_superset_dependencies(
        conda_env, ["ipykernel"], strict=True
    )
    assert calkit.environments.env_has_superset_dependencies(
        conda_env, ["numpy"], strict=True
    )


def test_detect_env_for_stage(tmp_dir):
    stage_py = {"kind": "python-script", "script_path": "script.py"}
    with open("script.py", "w") as f:
        f.write("import requests\n")
    with open("requirements.txt", "w") as f:
        f.write("requests\n")
    ck_info = {
        "environments": {
            "explicit": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment="explicit", ck_info=ck_info
    )
    assert res.name == "explicit"
    assert res.exists
    ck_info = {
        "environments": {
            "pyenv": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.name == "pyenv"
    assert res.exists
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.name == "main"
    assert res.env["path"] == "requirements.txt"
    assert not res.created_from_dependencies
    os.remove("requirements.txt")
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "pyproject.toml"
    ck_info = {
        "environments": {
            "jl": {"kind": "julia", "path": "Project.toml", "julia": "1.11"}
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_py, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path is not None
    # Since this is the first Python env, use pyproject.toml
    assert res.spec_path == "pyproject.toml"
    stage_r = {"kind": "r-script", "script_path": "analysis.R"}
    with open("analysis.R", "w") as f:
        f.write("library(dplyr)\n")
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_r, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "DESCRIPTION"
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_r, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path is not None
    assert res.spec_path == "DESCRIPTION"
    stage_jl = {"kind": "julia-script", "script_path": "analysis.jl"}
    with open("analysis.jl", "w") as f:
        f.write("using DataFrames\n")
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_jl, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "Project.toml"
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_jl, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "Project.toml"
    notebook_py = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["import pandas\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebook-py.ipynb", "w") as f:
        json.dump(notebook_py, f)
    stage_nb = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-py.ipynb",
    }
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_nb, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "pyproject.toml"
    assert res.spec_content is not None
    assert "ipykernel" in res.spec_content
    notebook_r = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["library(ggplot2)\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "R",
                "name": "ir",
            }
        },
    }
    with open("notebook-r.ipynb", "w") as f:
        json.dump(notebook_r, f)
    stage_nb_r = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-r.ipynb",
    }
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_r, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "DESCRIPTION"
    assert res.spec_content is not None
    assert "IRkernel" in res.spec_content
    notebook_jl = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["using DataFrames\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "julia",
                "name": "julia-1.9",
            }
        },
    }
    with open("notebook-jl.ipynb", "w") as f:
        json.dump(notebook_jl, f)
    stage_nb_jl = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-jl.ipynb",
    }
    ck_info = {
        "environments": {
            "py": {
                "kind": "uv-venv",
                "path": "requirements.txt",
                "python": "3.14",
                "prefix": ".venv",
            }
        }
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_jl, environment=None, ck_info=ck_info
    )
    assert res.created_from_dependencies
    assert res.spec_path == "Project.toml"
    assert res.spec_content is not None
    assert "IJulia" in res.spec_content
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "source": ["using DataFrames\n"],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "julia",
                "name": "julia-1.9",
            }
        },
    }
    with open("notebook.ipynb", "w") as f:
        json.dump(notebook, f)
    # Create Project.toml with DataFrames (so strict check passes)
    with open("Project.toml", "w") as f:
        f.write(
            '[deps]\nDataFrames = "a93c6f00-e57d-5684-b7b6-d8193f3e46c0"\n'
        )
    ck_info = {
        "environments": {
            "juliaenv": {
                "kind": "julia",
                "path": "Project.toml",
                "julia": "1.11",
            }
        }
    }
    stage_nb_exist = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook.ipynb",
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_exist, environment=None, ck_info=ck_info
    )
    assert res.name == "juliaenv"
    assert res.exists
    # Test that a notebook with additional dependencies does NOT reuse an
    # environment that doesn't have those dependencies
    notebook_scipy = {
        "cells": [
            {
                "cell_type": "code",
                "source": [
                    "import scipy\n",
                    "import matplotlib.pyplot as plt\n",
                ],
            }
        ],
        "metadata": {
            "kernelspec": {
                "language": "python",
                "name": "python3",
            }
        },
    }
    with open("notebook-scipy.ipynb", "w") as f:
        json.dump(notebook_scipy, f)
    # Create a pyproject.toml with only numpy (the "main"
    # environment)
    with open("pyproject.toml", "w") as f:
        f.write('[project]\nname = "main"\ndependencies = ["numpy"]\n')
    ck_info = {
        "environments": {
            "main": {
                "kind": "uv",
                "path": "pyproject.toml",
            }
        }
    }
    stage_nb_scipy = {
        "kind": "jupyter-notebook",
        "notebook_path": "notebook-scipy.ipynb",
    }
    res = calkit.environments.detect_env_for_stage(
        stage_nb_scipy, environment=None, ck_info=ck_info
    )
    # Should NOT reuse "main" since it doesn't have scipy/matplotlib
    assert res.name != "main"
    # Should create a new environment with the dependencies
    assert res.created_from_dependencies
    stage_matlab = {"kind": "matlab-script", "script_path": "calc.m"}
    ck_info = {"environments": {}}
    res = calkit.environments.detect_env_for_stage(
        stage_matlab, environment=None, ck_info=ck_info
    )
    assert res.name == "_system"
    assert res.env["kind"] == "system"
    stage_latex = {"kind": "latex", "script_path": "paper.tex"}
    res = calkit.environments.detect_env_for_stage(
        stage_latex, environment=None, ck_info={"environments": {}}
    )
    assert res.env == calkit.environments.texlive.DEFAULT_ENVIRONMENT
    # A TeX Live environment the project has is used
    tl_env = {"kind": "texlive", "release": 2025}
    res = calkit.environments.detect_env_for_stage(
        stage_latex, environment=None, ck_info={"environments": {"tl": tl_env}}
    )
    assert (res.name, res.env, res.exists) == ("tl", tl_env, True)


def test_env_from_notebook_path(tmp_dir):
    with open("pyproject.toml", "w") as f:
        f.write("doesn't need to work")
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert res.env["kind"] == "uv"
    assert not res.exists
    # Now add to calkit.yaml--should still work
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv", "path": "pyproject.toml"}
                }
            },
            f,
        )
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert res.env["kind"] == "uv"
    assert res.exists
    # Now add a new environment and associate it with the notebook in
    # calkit.yaml--should use that one instead
    with open("requirements.txt", "w") as f:
        f.write("requests")
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv", "path": "pyproject.toml"},
                    "notebook-env": {
                        "kind": "venv",
                        "path": "requirements.txt",
                    },
                },
                "notebooks": [
                    {
                        "path": "notebooks/main.ipynb",
                        "environment": "notebook-env",
                    }
                ],
            },
            f,
        )
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "notebook-env"
    assert res.env["path"] == "requirements.txt"
    assert res.env["kind"] == "venv"
    assert res.exists
    # Check that we can detect the environment from a notebook stage
    # TODO: Handle conflicts between notebook env and stage env
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(
            {
                "environments": {
                    "main": {"kind": "uv", "path": "pyproject.toml"},
                    "notebook-env": {
                        "kind": "venv",
                        "path": "requirements.txt",
                    },
                },
                "pipeline": {
                    "stages": {
                        "notebook-stage": {
                            "kind": "jupyter-notebook",
                            "notebook_path": "notebooks/main.ipynb",
                            "environment": "main",
                        }
                    }
                },
                "notebooks": [
                    {
                        "path": "notebooks/main.ipynb",
                        "environment": "notebook-env",
                    }
                ],
            },
            f,
        )
    res = calkit.environments.env_from_notebook_path("notebooks/main.ipynb")
    assert res.name == "main"
    assert res.env["path"] == "pyproject.toml"
    assert res.env["kind"] == "uv"
    assert res.exists


def test_scheduler_env_lock_files(tmp_dir, monkeypatch):
    """Cover scheduler env lock-file behavior (slurm and pbs).

    Scenarios:
    - ``get_env_lock_fpath`` returns the expected path,
    - ``write_scheduler_env_lock`` writes a deterministic JSON file,
    - re-running with unchanged content leaves the file untouched,
    - changing ``default_options`` produces different content (so DVC will
      treat dependent stages as stale),
    - a mocked scheduler records ``"mocked": true`` so mocked and real runs
      produce different lock content,
    - non-scheduler envs return ``None``.
    """
    slurm_env = {
        "kind": "slurm",
        "host": "localhost",
        "default_options": ["--time=01:00:00"],
        "default_setup": ["module purge"],
    }
    pbs_env = {
        "kind": "pbs",
        "host": "hpc.example.org",
        "default_options": ["-l", "walltime=01:00:00"],
    }
    slurm_lock = calkit.environments.get_env_lock_fpath(
        env=slurm_env, env_name="cluster", as_posix=True
    )
    assert slurm_lock == ".calkit/env-locks/cluster/info.json"
    pbs_lock_path = calkit.environments.get_env_lock_fpath(
        env=pbs_env, env_name="hpc", as_posix=True
    )
    assert pbs_lock_path == ".calkit/env-locks/hpc/info.json"
    written = calkit.environments.write_scheduler_env_lock(
        env_name="cluster", env=slurm_env
    )
    assert written == slurm_lock
    assert os.path.isfile(slurm_lock)
    with open(slurm_lock) as f:
        loaded = json.load(f)
    assert loaded == slurm_env
    mtime_before = os.path.getmtime(slurm_lock)
    calkit.environments.write_scheduler_env_lock(
        env_name="cluster", env=slurm_env
    )
    assert os.path.getmtime(slurm_lock) == mtime_before
    updated = dict(slurm_env)
    updated["default_options"] = ["--time=02:00:00"]
    calkit.environments.write_scheduler_env_lock(
        env_name="cluster", env=updated
    )
    with open(slurm_lock) as f:
        loaded = json.load(f)
    assert loaded["default_options"] == ["--time=02:00:00"]
    # When the scheduler is mocked, the lock records "mocked": true
    monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", "1")
    calkit.environments.write_scheduler_env_lock(
        env_name="cluster", env=slurm_env
    )
    with open(slurm_lock) as f:
        loaded = json.load(f)
    assert loaded["mocked"] is True
    assert {k: v for k, v in loaded.items() if k != "mocked"} == slurm_env
    # Without the mock, the key is absent again (so content differs)
    monkeypatch.delenv("CALKIT_MOCK_SCHEDULER")
    calkit.environments.write_scheduler_env_lock(
        env_name="cluster", env=slurm_env
    )
    with open(slurm_lock) as f:
        loaded = json.load(f)
    assert "mocked" not in loaded
    other = {"kind": "uv", "path": "pyproject.toml"}
    assert (
        calkit.environments.write_scheduler_env_lock(
            env_name="main", env=other
        )
        is None
    )


def test_nix_env(tmp_dir):
    # Flake at the repo root: flake.lock should live next to flake.nix.
    root_env = {"kind": "nix", "path": "flake.nix"}
    assert (
        calkit.environments.get_env_lock_fpath(
            env=root_env, env_name="main", as_posix=True
        )
        == "flake.lock"
    )
    # Flake in a subdirectory: lock follows the flake into the same dir.
    nested_env = {"kind": "nix", "path": "envs/myenv/flake.nix"}
    assert (
        calkit.environments.get_env_lock_fpath(
            env=nested_env, env_name="myenv", as_posix=True
        )
        == "envs/myenv/flake.lock"
    )
    # A path that doesn't end with flake.nix is a config error.
    with pytest.raises(ValueError):
        calkit.environments.get_env_lock_fpath(
            env={"kind": "nix", "path": "envs/myenv/shell.nix"},
            env_name="myenv",
        )
    # Detect from a flake.nix file. The detector keys off the filename,
    # so a placeholder body is enough.
    os.makedirs("envs/foo", exist_ok=True)
    with open("envs/foo/flake.nix", "w") as f:
        f.write("{}\n")
    res = calkit.environments.env_from_name_and_or_path(
        name=None, path="envs/foo/flake.nix"
    )
    assert res.env["kind"] == "nix"
    assert res.env["path"] == "envs/foo/flake.nix"
    assert not res.exists
    # The generated flake.nix template lists each requested package and
    # pins nixpkgs via the input URL we asked for.
    content = calkit.environments.create_nix_flake_content(
        packages=["python3", "uv"],
        description="dev shell",
        nixpkgs_url="github:NixOS/nixpkgs/nixos-24.05",
    )
    assert "python3" in content
    assert "uv" in content
    assert "nixos-24.05" in content
    assert "devShells" in content


def test_pixi_env_lock_fpath(tmp_dir):
    # Manifest at the repo root: pixi.lock lives next to pixi.toml.
    root_env = {"kind": "pixi", "path": "pixi.toml"}
    assert (
        calkit.environments.get_env_lock_fpath(
            env=root_env, env_name="main", as_posix=True
        )
        == "pixi.lock"
    )
    # Manifest in a subdirectory: lock follows the manifest.
    nested_env = {"kind": "pixi", "path": ".calkit/envs/my-env/pixi.toml"}
    assert (
        calkit.environments.get_env_lock_fpath(
            env=nested_env, env_name="my-env", as_posix=True
        )
        == ".calkit/envs/my-env/pixi.lock"
    )
    # path may be omitted/None without raising.
    assert (
        calkit.environments.get_env_lock_fpath(
            env={"kind": "pixi"}, env_name="main", as_posix=True
        )
        == "pixi.lock"
    )
    assert (
        calkit.environments.get_env_lock_fpath(
            env={"kind": "pixi", "path": None},
            env_name="main",
            as_posix=True,
        )
        == "pixi.lock"
    )


def test_add_packages_to_nix_flake(tmp_dir):
    # Round-trip: generate a flake, add some packages, verify they appear
    # in the packages list, that duplicates aren't re-inserted, and that
    # we error cleanly when the anchor is missing.
    initial = calkit.environments.create_nix_flake_content(
        packages=["python3"],
    )
    with open("flake.nix", "w") as f:
        f.write(initial)
    added = calkit.environments.add_packages_to_nix_flake(
        "flake.nix", ["R", "uv"]
    )
    assert added == ["R", "uv"]
    with open("flake.nix") as f:
        updated = f.read()
    # All three packages now live in the packages list, in declaration
    # order (existing first, then new).
    pkgs_section = updated.split("packages = with pkgs;", 1)[1]
    pkgs_section = pkgs_section.split("];", 1)[0]
    assert pkgs_section.index("python3") < pkgs_section.index("R")
    assert pkgs_section.index("R") < pkgs_section.index("uv")
    # Adding a package that's already there is a no-op, not a duplicate.
    again = calkit.environments.add_packages_to_nix_flake(
        "flake.nix", ["R", "polars"]
    )
    assert again == ["polars"]
    with open("flake.nix") as f:
        after = f.read()
    assert after.count("\n            R\n") == 1
    # Unknown structure: raise rather than silently mangle the file.
    with open("hand-rolled.nix", "w") as f:
        f.write("{ outputs = { self }: { devShells = {}; }; }\n")
    with pytest.raises(ValueError):
        calkit.environments.add_packages_to_nix_flake(
            "hand-rolled.nix", ["python3"]
        )


def test_system_env_lock(tmp_dir):
    from typing import get_args

    import calkit.environments.core as envs
    from calkit.models.core import SystemLockProperty

    # The literals offered in the schema and the table that resolves them
    # must not drift apart, and every one must name a key the system info
    # can actually produce
    assert set(get_args(SystemLockProperty)) == set(
        envs.SYSTEM_LOCK_PROPERTIES
    )
    system_info = calkit.get_system_info()
    for prop, key in envs.SYSTEM_LOCK_PROPERTIES.items():
        only_on = envs.SYSTEM_LOCK_PROPERTY_PLATFORMS.get(prop)
        if only_on is not None and platform.system() != only_on:
            # A package manager version this OS never collects. Absent by
            # design, and locking it raises rather than recording null.
            assert key not in system_info
            with pytest.raises(ValueError, match="not available"):
                envs.get_system_lock_data([prop])
            continue
        assert key in system_info, f"{key} is not in get_system_info()"
    # Locking nothing means no lock file, so nothing to depend on
    bare = {"kind": "system"}
    assert envs.get_env_lock_fpath(env=bare, env_name="sys") is None
    assert envs.write_system_env_lock(env_name="sys", env=bare) is None
    # 'default_setup' is compiled into the stage's command, where DVC
    # already watches it, so it isn't copied here -- an env that only has
    # setup commands needs no lock file at all
    setup_env = {"kind": "system", "default_setup": ["module load cuda"]}
    assert envs.get_env_lock_fpath(env=setup_env, env_name="setup") is None
    assert envs.write_system_env_lock(env_name="setup", env=setup_env) is None
    # The shell those commands run in isn't in the compiled command, so it
    # is recorded -- and sits alongside the locked properties
    both = {
        "kind": "system",
        "lock": ["os"],
        "default_setup": ["module load cuda"],
        "shell": "zsh",
    }
    with open(envs.write_system_env_lock(env_name="both", env=both)) as f:
        data = json.load(f)
    assert set(data) == {"os", "shell"}
    assert data["shell"] == "zsh"
    # A shell other than the default is recorded with no defaults set, for
    # the sake of a stage's own setup commands, which run in it
    shell_env = {"kind": "system", "shell": "zsh"}
    with open(envs.write_system_env_lock(env_name="zsh", env=shell_env)) as f:
        assert json.load(f) == {"shell": "zsh"}
    # Writing the default explicitly says exactly what leaving it out says,
    # so it must not be what decides whether there is a lock file at all --
    # otherwise 'shell: bash' would silently add a dependency to every
    # stage using the env and rerun them
    bash_env = {"kind": "system", "shell": "bash"}
    assert envs.get_env_lock_fpath(env=bash_env, env_name="b") is None
    assert envs.write_system_env_lock(env_name="b", env=bash_env) is None
    assert envs.get_env_lock_fpath(env=shell_env, env_name="z") is not None
    # Locking something writes it, and the file is what stages depend on
    env = {"kind": "system", "lock": ["os", "python-version"]}
    lock_fpath = envs.write_system_env_lock(env_name="sys", env=env)
    assert lock_fpath == envs.get_env_lock_fpath(env=env, env_name="sys")
    # There is exactly one lock file, so a stage depends on the file rather
    # than its directory, unlike the envs with per-platform lock files
    assert lock_fpath.endswith("info.json")
    assert (
        envs.get_env_lock_fpath(env=env, env_name="sys", for_dvc=True)
        == lock_fpath
    )
    with open(lock_fpath) as f:
        data = json.load(f)
    assert set(data) == {"os", "python-version"}
    assert data["os"] == system_info["os"]
    # Rewriting identical content leaves the file alone, so an unchanged
    # machine doesn't invalidate cached stage results
    mtime = os.path.getmtime(lock_fpath)
    envs.write_system_env_lock(env_name="sys", env=env)
    assert os.path.getmtime(lock_fpath) == mtime
    # Locking more changes the file, which is what triggers a rerun
    envs.write_system_env_lock(
        env_name="sys", env={"kind": "system", "lock": ["os", "machine"]}
    )
    with open(lock_fpath) as f:
        assert set(json.load(f)) == {"os", "machine"}
    # Total memory is a bare division of bytes, so it's recorded rounded:
    # a firmware or kernel update that reserves a little differently must
    # not read as the machine having changed
    assert envs.get_system_lock_data(
        ["memory-gb"], system_info={"memory_gb": 15.492069244384766}
    ) == {"memory-gb": 15.5}
    # Everything else is recorded exactly as reported
    assert envs.get_system_lock_data(
        ["cpu-count", "os-version"],
        system_info={"cpu_count": 10, "os_version": "24.5.0"},
    ) == {"cpu-count": 10, "os-version": "24.5.0"}
    # A property that doesn't exist, and one this machine can't supply,
    # both raise rather than quietly recording nothing
    with pytest.raises(ValueError, match="Unknown system property"):
        envs.get_system_lock_data(["not-a-thing"])
    with mock.patch.object(calkit, "get_system_info", return_value={}):
        with pytest.raises(ValueError, match="not available on this machine"):
            envs.get_system_lock_data(["os"])
    # Only the versions a lock names are read, since each is a subprocess
    probed: list[str] = []

    def fake_version(app: str) -> str:
        probed.append(app)
        return f"{app} 1.2.3"

    with mock.patch.object(calkit.core, "get_dep_version", fake_version):
        envs.get_system_lock_data(["cpu-count", "os-version"])
        assert envs.gate_system_env_lock("zsh", shell_env) == {}
        assert probed == []
        assert envs.get_system_lock_data(
            ["rscript-version", "git-version-minor"]
        ) == {"rscript-version": "1.2.3", "git-version-minor": "1.2"}
        assert sorted(probed) == ["Rscript", "git"]


def test_host_is_local_by_address(monkeypatch):
    import calkit.environments.core as envs

    # A project commonly writes a machine down as an IP, which never
    # matches a hostname however the machine reports itself -- so running
    # on that very machine would otherwise mean connecting to itself
    envs._host_addresses.cache_clear()
    assert envs.host_is_local("127.0.0.1")
    assert envs.host_is_local("::1")
    own = socket.gethostbyname(socket.gethostname())
    assert envs.host_is_local(own)
    # An address that isn't ours stays not ours, whatever we're called
    assert not envs.host_is_local("192.0.2.1")  # TEST-NET-1, unroutable
    # A name that doesn't resolve is not this machine either
    assert not envs.host_is_local("definitely-not-a-host.invalid")
    # Names still decide it when they match, without a lookup
    gh = mock.patch.object(socket, "gethostname", return_value="cluster01")
    gf = mock.patch.object(socket, "getfqdn", return_value="cluster01")

    def no_lookup(*a, **kw):
        raise AssertionError("resolved a host that matched by name")

    with gh, gf:
        envs._host_addresses.cache_clear()
        monkeypatch.setattr(socket, "getaddrinfo", no_lookup)
        assert envs.host_is_local("cluster01")
    envs._host_addresses.cache_clear()


def test_host_is_local():
    import calkit.environments.core as envs

    # An env with no host, or localhost, is this machine by definition
    assert envs.host_is_local(None)
    assert envs.host_is_local("")
    assert envs.host_is_local("localhost")
    # So is one naming this machine, however either side spells it
    assert envs.host_is_local(socket.gethostname())
    assert envs.host_is_local(socket.getfqdn())
    assert envs.host_is_local(socket.gethostname().split(".")[0])
    assert envs.host_is_local(socket.getfqdn().split(".")[0])
    # A machine that isn't this one has to be reached
    assert not envs.host_is_local("not-this-box.invalid")

    def _with_names(hostname, fqdn):
        return mock.patch.object(
            socket, "gethostname", return_value=hostname
        ), mock.patch.object(socket, "getfqdn", return_value=fqdn)

    # A machine that reports itself qualified still answers to its bare name
    gh, gf = _with_names("macbookpro.local", "macbookpro.local")
    with gh, gf:
        assert envs.host_is_local("macbookpro")
        assert envs.host_is_local("macbookpro.local")
    # One that only knows its short name answers to a qualified one
    gh, gf = _with_names("box", "box")
    with gh, gf:
        assert envs.host_is_local("box.example.org")
    # But two machines sharing a short name under different domains are not
    # the same machine, so the domain has to be believed
    gh, gf = _with_names("web01.dev.example.com", "web01.dev.example.com")
    with gh, gf:
        assert envs.host_is_local("web01.dev.example.com")
        assert not envs.host_is_local("web01.prod.example.com")


def test_host_is_local_by_mdns_name(monkeypatch):
    import calkit.environments.core as envs

    # The name macOS shows the user as theirs -- in Sharing, and from
    # 'scutil --get LocalHostName' -- is an mDNS name, which is not in the
    # resolver's search list the way a DNS domain is. It resolves under
    # '.local' and nowhere else, so the name a user is most likely to write
    # down would otherwise be the one name for their machine that fails to
    # match it, sending them off to SSH into the box they're sitting at.
    own = socket.gethostbyname(socket.gethostname())

    def resolve(host, *a, **kw):
        if host == "petes-laptop.local":
            return [(socket.AF_INET, None, None, "", (own, 0))]
        raise socket.gaierror(-2, "Name or service not known")

    gh = mock.patch.object(socket, "gethostname", return_value="somethingelse")
    gf = mock.patch.object(socket, "getfqdn", return_value="somethingelse")
    with gh, gf:
        envs._host_addresses.cache_clear()
        monkeypatch.setattr(socket, "getaddrinfo", resolve)
        assert envs.host_is_local("petes-laptop")
        # A qualified name is not retried under '.local': the domain it
        # already carries is an answer, and appending another would let a
        # machine in one domain match a different one in another
        envs._host_addresses.cache_clear()
        assert not envs.host_is_local("petes-laptop.example.org")
    envs._host_addresses.cache_clear()


def test_machine_ids_match_ignores_how_the_id_was_written():
    # Platforms write the same kind of ID differently -- macOS uppercase
    # with dashes, systemd lowercase without -- and users paste back
    # whichever form they were shown
    assert calkit.machine_ids_match(
        "0F1E2D3C-4B5A-6978-8796-A5B4C3D2E1F0",
        "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
    )
    assert calkit.machine_ids_match(" 0f1e2d3c ", "0F1E2D3C")
    assert not calkit.machine_ids_match("0f1e2d3c", "0000ffff")
    # Not knowing which machine this is is never evidence that it's the one
    # being asked about, so an unknown ID matches nothing -- not even
    # another unknown one
    assert not calkit.machine_ids_match(None, None)
    assert not calkit.machine_ids_match("0f1e2d3c", None)
    assert not calkit.machine_ids_match(None, "0f1e2d3c")
    assert not calkit.machine_ids_match("", "")
    # What's recorded is a hash of the normalized ID, so either way of
    # writing it hashes the same, and a hash matches the ID it came from
    hashed = calkit.hash_machine_id("0F1E2D3C-4B5A-6978-8796-A5B4C3D2E1F0")
    assert hashed == calkit.hash_machine_id("0f1e2d3c4b5a69788796a5b4c3d2e1f0")
    assert hashed is not None and hashed.startswith("sha256:")
    assert len(hashed) == len("sha256:") + 64
    assert "0f1e2d3c" not in hashed
    assert calkit.machine_ids_match(hashed, "0f1e2d3c4b5a69788796a5b4c3d2e1f0")
    assert calkit.machine_ids_match(hashed.upper(), hashed)
    assert calkit.hash_machine_id(hashed) == hashed
    assert not calkit.machine_ids_match(hashed, "0000ffff")
    assert calkit.hash_machine_id(None) is None
    assert calkit.hash_machine_id("  ") is None
    # Keyed to Calkit, so it can't be matched against another program's
    # plain hash of the same ID
    plain = hashlib.sha256(b"0f1e2d3c4b5a69788796a5b4c3d2e1f0").hexdigest()
    assert plain not in hashed


def test_env_is_local_prefers_the_machine_id_over_the_name():
    import calkit.environments.core as envs

    with mock.patch.object(calkit, "get_machine_id", return_value="abc-123"):
        # A machine ID is a stronger claim than a name, so it decides even
        # when the host names somewhere unreachable
        assert envs.env_is_local(
            {"kind": "system", "machine_id": "ABC123", "host": "nope.invalid"}
        )
        # ...and even when the host resolves here. A name that has come to
        # point at a different box is exactly what an ID exists to catch,
        # so matching it is not enough to run here.
        assert not envs.env_is_local(
            {"kind": "system", "machine_id": "def-456", "host": "localhost"}
        )
    # Where no ID can be read, a declared one could never match, and taking
    # that as "not this machine" would send the user off to SSH into the
    # machine they're on. The name is what's left to go on.
    with mock.patch.object(calkit, "get_machine_id", return_value=None):
        assert envs.env_is_local(
            {"kind": "system", "machine_id": "abc-123", "host": "localhost"}
        )
        assert not envs.env_is_local(
            {"kind": "system", "machine_id": "abc-123", "host": "box.invalid"}
        )
    # An env that declares no ID is decided by its host, as before
    with mock.patch.object(calkit, "get_machine_id", return_value="abc-123"):
        assert envs.env_is_local({"kind": "system", "host": "localhost"})
        assert envs.env_is_local({"kind": "system"})
        assert not envs.env_is_local({"kind": "system", "host": "no.invalid"})


def test_env_is_local_expands_variables_in_the_machine_id(monkeypatch):
    import calkit.environments.core as envs

    # A machine ID can be kept out of a shared calkit.yaml the same way a
    # host can, since it names one particular person's machine
    monkeypatch.setenv("CK_MACHINE_ID", "abc-123")
    with mock.patch.object(calkit, "get_machine_id", return_value="ABC123"):
        assert envs.env_is_local(
            {"kind": "system", "machine_id": "${CK_MACHINE_ID}"}
        )


def test_machine_id_can_be_overridden_in_config(monkeypatch):
    import calkit.config

    # Settable, so 'calkit config set machine_id' reaches it
    assert "machine_id" in calkit.config.Settings.model_fields

    def _configured(value):
        return mock.patch.object(
            calkit.config,
            "read",
            return_value=calkit.config.Settings(machine_id=value),
        )

    platform_says = mock.patch.object(
        calkit.core, "_read_platform_machine_id", return_value="from-platform"
    )
    # A machine that was rebuilt can be told to still count as the same one,
    # and a platform that supplies no ID of its own can be given one
    with _configured("  chosen-id  "), platform_says:
        assert calkit.get_machine_id() == "chosen-id"
    # An override that is absent or only whitespace is not an ID, so the
    # platform still gets to answer
    with _configured("   "), platform_says:
        assert calkit.get_machine_id() == "from-platform"
    with _configured(None), platform_says:
        assert calkit.get_machine_id() == "from-platform"
    # A config too broken to read shouldn't make the machine unidentifiable
    with (
        mock.patch.object(
            calkit.config, "read", side_effect=ValueError("bad config")
        ),
        platform_says,
    ):
        assert calkit.get_machine_id() == "from-platform"


def test_machine_id_is_reported_and_lockable(tmp_dir: str) -> None:
    import calkit.environments.core as envs

    # Pinning results to one machine is what 'hostname' was being used for,
    # badly: renaming the machine breaks that pin, and a machine elsewhere
    # with the same name satisfies it
    assert envs.SYSTEM_LOCK_PROPERTIES["machine-id"] == "machine_id_hash"
    # Reported hashed, since what's locked is committed and often public
    with mock.patch.object(
        calkit.core, "get_machine_id", return_value="AB-CD"
    ):
        props = calkit.get_machine_properties()
    assert props["machine_id_hash"] == calkit.hash_machine_id("abcd")
    assert "machine_id" not in props
    hashed = calkit.hash_machine_id("abc-123")
    # A null in a lock file is no ID, not a hash of the word 'None'
    assert envs.lock_value("machine-id", None) is None
    env = {"kind": "system", "lock": ["machine-id"]}
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id_hash": hashed}
    ):
        assert envs.get_system_lock_data(["machine-id"]) == {
            "machine-id": hashed
        }
        # A lock from before IDs were hashed holds the raw one, which still
        # matches this machine, and is kept as written until it's relocked,
        # so the stages depending on it don't rerun for nothing
        lock_fpath = envs.get_env_lock_fpath(env=env, env_name="laptop")
        assert lock_fpath is not None
        os.makedirs(os.path.dirname(lock_fpath), exist_ok=True)
        with open(lock_fpath, "w") as f:
            json.dump({"machine-id": "ABC123"}, f)
        assert not envs.system_env_lock_mismatch(env_name="laptop", env=env)
        envs.write_system_env_lock(env_name="laptop", env=env)
        assert envs.read_system_env_lock("laptop", env) == {
            "machine-id": "ABC123"
        }
        # unless it follows the machine, which takes the hash, leaving
        # anything else that matches as written
        auto = {"kind": "system", "lock": ["machine-id", "memory-gb"]} | {
            "relock": "auto"
        }
        auto_fpath = envs.get_env_lock_fpath(env=auto, env_name="auto")
        assert auto_fpath is not None
        os.makedirs(os.path.dirname(auto_fpath), exist_ok=True)
        with open(auto_fpath, "w") as f:
            json.dump({"machine-id": "ABC123", "memory-gb": 15.49}, f)
        envs.write_system_env_lock(
            env_name="auto",
            env=auto,
            system_info={"machine_id_hash": hashed, "memory_gb": 15.4921},
        )
        assert envs.read_system_env_lock("auto", auto) == {
            "machine-id": hashed,
            "memory-gb": 15.49,
        }
        envs.write_system_env_lock(env_name="laptop", env=env, relock=True)
        assert envs.read_system_env_lock("laptop", env) == {
            "machine-id": hashed
        }
        # Another machine's is a mismatch, and both are shown hashed
        with open(lock_fpath, "w") as f:
            json.dump({"machine-id": "def-456"}, f)
        mismatch = envs.system_env_lock_mismatch(env_name="laptop", env=env)
    assert mismatch == {
        "machine-id": {
            "locked": calkit.hash_machine_id("def-456"),
            "actual": hashed,
        }
    }
    # A machine that can't report one can't pin to one either, rather than
    # recording null and claiming a pin that isn't there
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id_hash": None}
    ):
        with pytest.raises(ValueError, match="not available on this machine"):
            envs.get_system_lock_data(["machine-id"])


def test_declaring_a_machine_id_does_not_lock_it(tmp_dir):
    import calkit.environments.core as envs

    # Naming a machine says where to run, which is a separate question from
    # whether results depend on it: moving a project to a new machine and
    # updating 'machine_id' need not invalidate everything computed on the
    # old one. Whether it does is the project's call, made through 'lock'.
    env = {"kind": "system", "machine_id": "abc-123"}
    hashed = calkit.hash_machine_id("abc-123")
    assert envs.get_env_lock_fpath(env=env, env_name="laptop") is None
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id_hash": hashed}
    ):
        assert envs.write_system_env_lock(env_name="laptop", env=env) is None
        # Saying so explicitly is what pins it
        env_locked = env | {"lock": ["machine-id"]}
        lock_fpath = envs.write_system_env_lock(
            env_name="laptop", env=env_locked
        )
    assert lock_fpath is not None
    with open(lock_fpath) as f:
        assert json.load(f) == {"machine-id": hashed}


def test_locking_an_unreadable_machine_id_says_how_to_supply_one(tmp_dir):
    import calkit.environments.core as envs

    # Recording null would claim a pin that isn't there, so this raises --
    # but this is the one lockable property a user can supply by hand, and
    # the way to is a config setting they have no reason to know about
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id_hash": None}
    ):
        with pytest.raises(ValueError, match="calkit config set machine_id"):
            envs.write_system_env_lock(
                env_name="laptop",
                env={"kind": "system", "lock": ["machine-id"]},
            )


def test_system_lock_can_describe_another_machine(tmp_dir):
    import calkit.environments.core as envs

    # What a stage's results depend on is the machine it runs on, so a lock
    # for a remote host is written from that host's properties rather than
    # from this one's
    remote = {"cpu_count": 64, "os": "Linux", "python_version": "3.12.7"}
    data = envs.get_system_lock_data(["cpu-count", "os"], system_info=remote)
    assert data == {"cpu-count": 64, "os": "Linux"}
    assert data != envs.get_system_lock_data(["cpu-count", "os"])
    # A property that machine can't supply is still an error, not a null
    with pytest.raises(ValueError, match="not available"):
        envs.get_system_lock_data(["docker-version"], system_info=remote)
    env = {"kind": "system", "host": "box", "lock": ["cpu-count"]}
    lock_fpath = envs.write_system_env_lock(
        env_name="remote", env=env, system_info=remote
    )
    assert lock_fpath is not None
    with open(lock_fpath) as f:
        assert json.load(f) == {"cpu-count": 64}


def test_system_env_lock_survives_a_move_to_another_machine(tmp_dir):
    import calkit.environments.core as envs

    env = {"kind": "system", "lock": ["cpu-count", "os"]}
    lock_fpath = envs.write_system_env_lock(env_name="bench", env=env)
    assert lock_fpath is not None
    with open(lock_fpath) as f:
        locked = json.load(f)
    # A machine that disagrees keeps the lock and reports the mismatch
    elsewhere = {
        "cpu_count": locked["cpu-count"] + 1,
        "os": "SomeOtherOS",
    }
    envs.write_system_env_lock(
        env_name="bench", env=env, system_info=elsewhere
    )
    with open(lock_fpath) as f:
        assert json.load(f) == locked
    mismatch = envs.system_env_lock_mismatch(
        env_name="bench", env=env, system_info=elsewhere
    )
    assert set(mismatch) == {"cpu-count", "os"}
    assert mismatch["os"] == {
        "locked": locked["os"],
        "actual": "SomeOtherOS",
    }
    described = envs.describe_system_env_lock_mismatch("bench", mismatch)
    assert "calkit update env -n bench --lock" in described
    assert "SomeOtherOS" in described
    # Only relocking moves the recorded properties
    envs.write_system_env_lock(
        env_name="bench", env=env, system_info=elsewhere, relock=True
    )
    with open(lock_fpath) as f:
        assert json.load(f) == {
            "cpu-count": elsewhere["cpu_count"],
            "os": "SomeOtherOS",
        }
    assert not envs.system_env_lock_mismatch(
        env_name="bench", env=env, system_info=elsewhere
    )
    # Locking another property adds it from a machine matching the rest
    added = env | {"lock": ["cpu-count", "os", "machine"]}
    there = elsewhere | {"machine": "riscv64"}
    assert not envs.system_env_lock_mismatch(
        env_name="bench", env=added, system_info=there
    )
    envs.write_system_env_lock(env_name="bench", env=added, system_info=there)
    with_machine = {
        "cpu-count": elsewhere["cpu_count"],
        "os": "SomeOtherOS",
        "machine": "riscv64",
    }
    assert envs.read_system_env_lock("bench", added) == with_machine
    # but not from one that doesn't, where it's a mismatch until relocked
    more = env | {"lock": ["cpu-count", "os", "machine", "processor"]}
    assert "os" in envs.system_env_lock_mismatch(env_name="bench", env=more)
    envs.write_system_env_lock(env_name="bench", env=more)
    assert envs.read_system_env_lock("bench", more) == with_machine
    envs.write_system_env_lock(env_name="bench", env=more, relock=True)
    assert envs.read_system_env_lock(
        env_name="bench", env=more
    ) == envs.get_system_lock_data(more["lock"])
    # Locking fewer keeps the rest
    envs.write_system_env_lock(
        env_name="bench", env=env, system_info=elsewhere
    )
    assert envs.read_system_env_lock(
        env_name="bench", env=env
    ) == envs.get_system_lock_data(["cpu-count", "os"])
    # No lock yet is not a mismatch
    assert not envs.system_env_lock_mismatch(env_name="never-locked", env=env)
    # An unreadable lock is an error rather than treated as missing
    with open(lock_fpath, "w") as f:
        f.write("{not json")
    with pytest.raises(ValueError, match="cannot be read"):
        envs.read_system_env_lock(env_name="bench", env=env)
    with pytest.raises(ValueError, match="cannot be read"):
        envs.write_system_env_lock(env_name="bench", env=env)
    with open(lock_fpath, "w") as f:
        f.write("[1, 2]")
    with pytest.raises(ValueError, match="does not contain an object"):
        envs.system_env_lock_mismatch(env_name="bench", env=env)
    # Relocking doesn't read the broken file
    envs.write_system_env_lock(env_name="bench", env=env, relock=True)
    assert envs.read_system_env_lock(
        env_name="bench", env=env
    ) == envs.get_system_lock_data(["cpu-count", "os"])
    # With 'relock: auto' the lock follows the machine instead
    auto = env | {"relock": "auto"}
    envs.write_system_env_lock(
        env_name="bench", env=auto, system_info=elsewhere
    )
    assert envs.read_system_env_lock(env_name="bench", env=auto) == {
        "cpu-count": elsewhere["cpu_count"],
        "os": "SomeOtherOS",
    }
    # and a broken lock is just replaced, since it would be rewritten anyway
    for broken in ["{not json", "[1, 2]"]:
        with open(lock_fpath, "w") as f:
            f.write(broken)
        envs.write_system_env_lock(
            env_name="bench", env=auto, system_info=elsewhere
        )
        assert envs.read_system_env_lock(env_name="bench", env=auto) == {
            "cpu-count": elsewhere["cpu_count"],
            "os": "SomeOtherOS",
        }
    assert (
        envs.switch_machine_lock_env({"lock": ["os"], "relock": "auto"})[
            "relock"
        ]
        == "auto"
    )


def test_lock_any_app_version(tmp_dir):
    import calkit.environments.core as envs

    assert envs.lock_app_names(
        ["os", "git-version", "jq-version", "cc-version-minor"]
    ) == ["jq", "cc"]
    # Any app's version can be locked, read from the machine like the rest,
    # and recorded as its number up to the patch part
    clang = (
        "Apple clang version 21.0.0 (clang-2100.3.34.2)\n"
        "InstalledDir: /Library/Developer/CommandLineTools/usr/bin"
    )
    nvcc = (
        "nvcc: NVIDIA (R) Cuda compiler driver\n"
        "Copyright (c) 2005-2024 NVIDIA Corporation\n"
        "Cuda compilation tools, release 12.4, V12.4.131"
    )
    info = {
        "jq_version": "jq-1.7.1",
        "cc_version": clang,
        "nvcc_version": nvcc,
        "perl_version": "This is perl 5, version 34, subversion 1 (v5.34.1)",
        "gcc_version": "gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0",
        "mingw_version": "gcc.exe (x86_64-posix-seh-rev0, MinGW-W64) 8.1.0",
        "git_version": "git version 2.39.5.windows.1",
        "docker_version": "Docker version 27.3.1, build ce12230",
        "python_version": "3.12.10rc1",
        "os_version": "6.8.0-45-generic",
        "rscript_version": "Rscript (R) version 4.3.2 (2023-10-31)",
    }
    lock = [
        "jq-version",
        "cc-version",
        "nvcc-version",
        "perl-version",
        "gcc-version",
        "gcc-version-patch",
        "gcc-version-full",
        "mingw-version",
        "git-version",
        "git-version-full",
        "docker-version-major",
        "python-version-minor",
        "python-version-full",
        "os-version",
        "os-version-full",
        "rscript-version",
        "Rscript-version",
    ]
    assert envs.get_system_lock_data(lock, system_info=info) == {
        "jq-version": "1.7.1",
        "cc-version": "21.0.0",
        "nvcc-version": "12.4",
        "perl-version": "5.34.1",
        "gcc-version": "11.4.0",
        "gcc-version-patch": "11.4.0",
        "gcc-version-full": "11.4.0-1ubuntu1~22.04",
        "mingw-version": "8.1.0",
        "git-version": "2.39.5",
        "git-version-full": "2.39.5.windows.1",
        "docker-version-major": "27",
        "python-version-minor": "3.12",
        "python-version-full": "3.12.10rc1",
        "os-version": "6.8.0",
        "os-version-full": "6.8.0-45-generic",
        "rscript-version": "4.3.2",
        "Rscript-version": "4.3.2",
    }
    # The Python stages run isn't necessarily the one running Calkit, and
    # where there's only 'python3', that's the one to lock
    pythons = {"python_version": "3.12.8", "calkit_python_version": "3.14.2"}
    assert envs.get_system_lock_data(
        ["python-version", "calkit-python-version"], system_info=pythons
    ) == {"python-version": "3.12.8", "calkit-python-version": "3.14.2"}
    with pytest.raises(ValueError, match="lock 'python3-version'"):
        envs.get_system_lock_data(["python-version-minor"], system_info={})
    # A version that can't be read would match any other, so isn't locked,
    # whether nothing was printed or nothing in it is a version
    for printed in ["", "a version with no number"]:
        with pytest.raises(ValueError, match="has no version"):
            envs.get_system_lock_data(
                ["pandoc-version"], system_info={"pandoc_version": printed}
            )
    # A lock recorded in full before versions were trimmed still matches
    env = {"kind": "system", "lock": ["docker-version"]}
    os.makedirs(".calkit/env-locks/old")
    with open(".calkit/env-locks/old/info.json", "w") as f:
        json.dump({"docker-version": "Docker version 27.3.1, build abc"}, f)
    rebuilt = {"docker_version": "Docker version 27.3.1, build def"}
    assert not envs.system_env_lock_mismatch("old", env, system_info=rebuilt)
    upgraded = {"docker_version": "Docker version 28.0.0, build def"}
    assert envs.system_env_lock_mismatch("old", env, system_info=upgraded) == {
        "docker-version": {"locked": "27.3.1", "actual": "28.0.0"}
    }
    # Only the versions locked to fewer parts move with them, and a
    # pre-release only counts in full
    minor = {"kind": "system", "lock": ["python-version-minor"]}
    envs.write_system_env_lock("minor", minor, system_info=info)
    patched = info | {"python_version": "3.12.9"}
    assert not envs.system_env_lock_mismatch(
        "minor", minor, system_info=patched
    )
    newer = info | {"python_version": "3.13.0"}
    assert envs.system_env_lock_mismatch("minor", minor, system_info=newer)
    released = info | {"python_version": "3.12.10"}
    for name, expected in [("patch", False), ("full", True)]:
        env = {"kind": "system", "lock": [f"python-version-{name}"]}
        envs.write_system_env_lock(name, env, system_info=info)
        mismatch = envs.system_env_lock_mismatch(
            name, env, system_info=released
        )
        assert bool(mismatch) is expected, name
    data = envs.get_system_lock_data(["calkit-version"])
    assert data["calkit-version"]
    with pytest.raises(ValueError, match="not available"):
        envs.get_system_lock_data(["calkit-test-no-such-app-version"])
    with pytest.raises(ValueError, match="'<app>-version' for any app"):
        envs.get_system_lock_data(["bogus"])
    with pytest.raises(ValueError, match="'-patch', or '-full'"):
        envs.get_system_lock_data(["python-version-micro"])


def test_system_env_lock_still_tracks_project_controlled_fields(tmp_dir):
    import calkit.environments.core as envs

    # The shell is a project setting, so changing it still updates the lock
    env = {"kind": "system", "lock": ["os"], "shell": "zsh"}
    lock_fpath = envs.write_system_env_lock(env_name="shell", env=env)
    assert lock_fpath is not None
    with open(lock_fpath) as f:
        assert json.load(f)["shell"] == "zsh"
    env["shell"] = "fish"
    envs.write_system_env_lock(env_name="shell", env=env)
    with open(lock_fpath) as f:
        data = json.load(f)
    assert data["shell"] == "fish"


def test_system_env_checks_are_not_cached():
    import calkit.environments.core as envs

    # Caching exists to skip rebuilding something expensive. Checking a
    # system env *is* reading the machine, so there is nothing to skip --
    # and caching it means a locked property can change and be missed,
    # which is exactly the drift 'lock' exists to catch.
    assert not envs.cacheable({"kind": "system", "lock": ["cpu-count"]})
    assert not envs.cacheable({"kind": "system"})
    for kind in ["uv", "conda", "docker", "slurm", "renv"]:
        assert envs.cacheable({"kind": kind}), kind


def test_get_env_input_paths(capsys):
    # An environment's files are read from 'inputs', with the older 'deps'
    # spelling still accepted so a project that predates the rename doesn't
    # have its files go silently untracked
    import calkit.environments.core as envs

    assert envs.get_env_input_paths({}) == []
    assert envs.get_env_input_paths({"inputs": ["a.sh"]}) == ["a.sh"]
    # Reset, since the warning is deliberately only issued once per process
    envs._warned_deprecated_deps_key = False
    assert envs.get_env_input_paths({"deps": ["b.sh"]}, "old") == ["b.sh"]
    captured = capsys.readouterr()
    assert "deprecated" in captured.out + captured.err
    assert "old" in captured.out + captured.err
    # Only once, however many readers ask
    envs.get_env_input_paths({"deps": ["c.sh"]}, "old")
    assert "deprecated" not in capsys.readouterr().out
    # Saying the same thing twice in two places that can drift apart is
    # reported rather than silently resolved one way
    with pytest.raises(ValueError, match="merge them into 'inputs'"):
        envs.get_env_input_paths({"inputs": ["a"], "deps": ["b"]}, "both")


def test_env_inputs_must_be_inside_the_project():
    # A stage can't depend on something the repo doesn't carry, so the
    # inputs this PR adds are constrained the way a stage's wdir is. Note
    # this is a pydantic constraint, not a JSON-schema one, so it catches a
    # file being loaded as a model rather than one being linted in an
    # editor -- same as every other RelativeChildPathString field.
    from pydantic import ValidationError

    import calkit.environments.core as envs
    from calkit.models.core import (
        DockerEnvironment,
        PBSEnvironment,
        SlurmEnvironment,
        SystemEnvironment,
    )

    for model in (SystemEnvironment, SlurmEnvironment, PBSEnvironment):
        assert model(inputs=["scripts/setup.sh"]).inputs == [
            "scripts/setup.sh"
        ]
        for bad in ["../outside.sh", "/etc/hosts"]:
            with pytest.raises(ValidationError):
                model(inputs=[bad])
    # The models are not what production reads: every caller goes through
    # get_env_input_paths with a raw dict, so the check has to be there
    # too or the guarantee only holds in tests
    for kind in ("system", "slurm", "pbs"):
        assert envs.get_env_input_paths(
            {"kind": kind, "inputs": ["scripts/setup.sh"]}
        ) == ["scripts/setup.sh"]
        for bad in ["../outside.sh", "/etc/hosts"]:
            with pytest.raises(ValueError, match="outside|absolute"):
                envs.get_env_input_paths({"kind": kind, "inputs": [bad]})
    # Docker's is a rename of a field that has been published for a while,
    # so tightening it would retroactively invalidate existing projects
    assert DockerEnvironment(image="x", inputs=["../outside.C"]).inputs == [
        "../outside.C"
    ]
    assert envs.get_env_input_paths(
        {"kind": "docker", "inputs": ["../outside.C"]}
    ) == ["../outside.C"]


def test_get_cached_env_states(tmp_dir):
    env = {"kind": "conda", "path": "environment.yml"}
    ck_info = {
        "environments": {"py": env, "other": env | {"path": "other.yml"}},
        "pipeline": {
            "stages": {
                "a": {
                    "kind": "shell-command",
                    "command": "echo",
                    "environment": "py",
                },
                "b": {
                    "kind": "shell-command",
                    "command": "echo",
                    "environment": "other",
                },
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    with open("environment.yml", "w") as f:
        f.write("dependencies:\n  - python\n")
    lock = calkit.environments.get_env_lock_fpath(env_name="py", env=env)
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    with open(lock, "w") as f:
        f.write("locked\n")
    # Never checked
    states = calkit.environments.get_cached_env_states()
    assert states["py"] == {
        "checked_at": None,
        "success": None,
        "changed": None,
    }
    # Checked and unchanged, which is reported without checking again
    calkit.environments.save_cache(env_name="py", env=env, success=True)
    calkit.environments.save_cache(
        env_name="other", env=ck_info["environments"]["other"], success=False
    )
    with mock.patch("calkit.cli.check.check_environment") as check:
        states = calkit.environments.get_cached_env_states()
    check.assert_not_called()
    assert states["py"]["success"] and states["py"]["checked_at"]
    assert states["py"]["changed"] is False
    # A failed check says so, rather than whether anything changed since
    assert states["other"]["success"] is False
    assert states["other"]["changed"] is None
    # Editing the spec shows up as a change since the last check
    with open("environment.yml", "w") as f:
        f.write("dependencies:\n  - python\n  - numpy\n")
    assert calkit.environments.get_cached_env_states()["py"]["changed"]
    # So does its lock file
    with open("environment.yml", "w") as f:
        f.write("dependencies:\n  - python\n")
    assert not calkit.environments.get_cached_env_states()["py"]["changed"]
    with open(lock, "w") as f:
        f.write("relocked\n")
    assert calkit.environments.get_cached_env_states()["py"]["changed"]
    # Status reports these instead of checking when told not to check
    status = calkit.pipeline.get_status(
        check_environments=False, compile_to_dvc=False, clean_notebooks=False
    )
    assert set(status.environment_states) == {"py", "other"}
    assert status.environment_checks == {}


def test_env_spec_hashes(tmp_dir):
    import json

    import calkit.environments.core as envs

    def write(fpath: str, text: str) -> None:
        with open(fpath, "w", newline="") as f:
            f.write(text)

    spec, lock = "requirements.txt", "requirements-lock.txt"
    write(spec, "idna\n")
    write(lock, "idna==3.10\n")
    # Recorded beside the lock, not in it
    assert envs.read_env_spec_hash(lock) is None
    envs.write_env_spec_hash(lock, envs.env_spec_hash(spec))
    assert envs.read_env_spec_hash(lock) == envs.env_spec_hash(spec)
    with open(lock) as f:
        assert f.read() == "idna==3.10\n"
    # Comments, blank lines, spacing and line endings aren't changes
    base = envs.env_spec_hash(spec)
    for text in ["# Deps\nidna  # For URLs\n\n", "idna\r\n", "  idna\n"]:
        write(spec, text)
        assert envs.env_spec_hash(spec) == base
    write(spec, "idna\ncertifi\n")
    assert envs.env_spec_hash(spec) != base
    assert envs.env_spec_hash(spec, python="3.11") != envs.env_spec_hash(spec)
    # A YAML spec is hashed as the data it holds, so channel order counts
    write("a.yml", "name: e\n# Note\nchannels: [conda-forge, bioconda]\n")
    write("b.yml", "channels:\n  - conda-forge\n  - bioconda\nname: 'e'\n")
    write("c.yml", "name: e\nchannels: [bioconda, conda-forge]\n")
    assert envs.env_spec_hash("a.yml") == envs.env_spec_hash("b.yml")
    assert envs.env_spec_hash("a.yml") != envs.env_spec_hash("c.yml")
    # Included files are part of the spec, relative to what includes them,
    # including from a conda spec's pip section
    os.makedirs("reqs")
    write(spec, "-r reqs/base.txt\n")
    write(os.path.join("reqs", "base.txt"), "-c pins.txt\nidna\n")
    write(os.path.join("reqs", "pins.txt"), "idna==3.7\n")
    write(
        "d.yml", "name: e\ndependencies:\n  - pip:\n    - -r reqs/base.txt\n"
    )
    included = envs.env_spec_hash(spec), envs.env_spec_hash("d.yml")
    write(os.path.join("reqs", "pins.txt"), "idna==3.10\n")
    assert envs.env_spec_hash(spec) != included[0]
    assert envs.env_spec_hash("d.yml") != included[1]
    write(os.path.join("reqs", "base.txt"), "-r ../requirements.txt\n")
    assert envs.env_spec_hash(spec)
    # Every platform's lock in a directory shares one entry, relative to the
    # project it's in
    os.makedirs(os.path.join("sub", ".calkit", "env-locks", "py"))
    write(os.path.join("sub", spec), "idna\n")
    envs.write_env_spec_hash(
        os.path.join(".calkit", "env-locks", "py", "linux-64.txt"),
        envs.env_spec_hash(os.path.join("sub", spec)),
        wdir="sub",
    )
    assert envs.read_env_spec_hash(
        os.path.join(".calkit", "env-locks", "py", "win-64.txt"), wdir="sub"
    ) == envs.env_spec_hash(os.path.join("sub", spec))
    with open(os.path.join("sub", envs.ENV_SPEC_HASHES_FPATH)) as f:
        assert json.load(f) == {
            ".calkit/env-locks/py": envs.env_spec_hash(
                os.path.join("sub", spec)
            )
        }
    assert envs.env_spec_hash(spec).startswith("sha256:")
    # Older md5 hashes aren't read, and are dropped on the next write
    write(envs.ENV_SPEC_HASHES_FPATH, json.dumps({"old": "md5:abc"}))
    assert envs.read_env_spec_hash("old") is None
    envs.write_env_spec_hash(lock, envs.env_spec_hash(spec))
    with open(envs.ENV_SPEC_HASHES_FPATH) as f:
        assert list(json.load(f)) == [lock]
    # An unreadable file records nothing, and is replaced on the next write
    write(envs.ENV_SPEC_HASHES_FPATH, "not json")
    assert envs.read_env_spec_hash(lock) is None
    envs.write_env_spec_hash(lock, envs.env_spec_hash(spec))
    assert envs.read_env_spec_hash(lock) == envs.env_spec_hash(spec)


def test_cross_platform_venv_locks(tmp_dir, monkeypatch):
    import calkit.environments.core as envs

    assert set(envs.UV_PLATFORM_TARGETS) <= set(envs.CONDA_VENV_ARCHS)
    spec = "requirements.txt"
    with open(spec, "w") as f:
        f.write("idna\n")
    # A lock that isn't one of a per-platform set gets no siblings
    with open("lock.txt", "w") as f:
        f.write("idna==3.7\n")
    assert not envs.write_cross_platform_venv_locks(
        spec_fpath=spec, lock_fpath="lock.txt", python_version="3.12"
    )
    assert not set(os.listdir()) & {a + ".txt" for a in envs.CONDA_VENV_ARCHS}
    # Other platforms are resolved to the versions locked here
    os.makedirs(os.path.join(".calkit", "env-locks", "py"), exist_ok=True)
    here = envs._conda_venv_platform()
    lock_fpath = os.path.join(".calkit", "env-locks", "py", here + ".txt")
    with open(lock_fpath, "w") as f:
        f.write("idna==3.7\n")
    written = envs.write_cross_platform_venv_locks(
        spec_fpath=spec, lock_fpath=lock_fpath, python_version="3.12"
    )
    assert lock_fpath not in written
    for fpath in written:
        with open(fpath) as f:
            assert "idna==3.7" in f.read()
    if not written:
        return
    # Without relocking, only missing platforms are added
    os.remove(written[0])
    again = envs.write_cross_platform_venv_locks(
        spec_fpath=spec,
        lock_fpath=lock_fpath,
        python_version="3.12",
        relock=False,
    )
    assert again == [written[0]]
    # Relocking removes a platform that can't be resolved, which is stale
    with open(spec, "w") as f:
        f.write("idna\ncalkit-no-such-package-anywhere\n")
    assert not envs.write_cross_platform_venv_locks(
        spec_fpath=spec, lock_fpath=lock_fpath, python_version="3.12"
    )
    assert not any(os.path.isfile(fpath) for fpath in written)
    # So does relocking without uv, or for a platform uv can't target, but
    # only missing platforms are left alone
    lock_dir = os.path.dirname(lock_fpath)
    siblings = [
        os.path.join(lock_dir, a + ".txt")
        for a in envs.CONDA_VENV_ARCHS
        if a != here
    ]
    for fpath in siblings:
        with open(fpath, "w") as f:
            f.write("idna==3.7\n")
    with monkeypatch.context() as m:
        m.setattr(envs.shutil, "which", lambda name: None)
        assert not envs.write_cross_platform_venv_locks(
            spec_fpath=spec, lock_fpath=lock_fpath, relock=False
        )
        assert all(os.path.isfile(fpath) for fpath in siblings)
        assert not envs.write_cross_platform_venv_locks(
            spec_fpath=spec, lock_fpath=lock_fpath
        )
    assert not any(os.path.isfile(fpath) for fpath in siblings)


def test_switch_env(tmp_dir, monkeypatch):
    import calkit.environments.core as envs

    def option(env: str, *when: dict) -> dict:
        return {"when": list(when), "use": env} if when else {"use": env}

    envs_def: dict[str, dict] = {
        "cluster": {
            "kind": "switch",
            "switch": [
                option("slurm-env", {"app_exists": "calkit-test-no-such-app"}),
                option(
                    "lab",
                    {"env_var_equals": ["CK_TEST_SITE=lab", "CK_TEST_SITE=b"]},
                ),
                option("here", {"hostname_matches": "*"}),
            ],
        },
        "slurm-env": {"kind": "slurm"},
        "lab": {"kind": "system", "host": "lab.invalid"},
        "here": {"kind": "system"},
        "py": {"kind": "uv-venv", "path": "requirements.txt"},
    }
    monkeypatch.delenv("CK_TEST_SITE", raising=False)
    assert envs.get_switch_options("cluster", envs_def) == [
        "slurm-env",
        "lab",
        "here",
    ]
    assert envs.switch_is_outer("cluster", envs_def)
    assert envs.env_can_be_outer("cluster", envs_def)
    assert not envs.env_can_be_outer("py", envs_def)
    # First match wins, and conditions see this machine and its env vars
    assert envs.resolve_switch("cluster", envs_def) == "here"
    monkeypatch.setenv("CK_TEST_SITE", "b")
    assert envs.resolve_switch("cluster", envs_def) == "lab"
    # Each condition, where a list of values means any one, and every
    # condition of an option must hold
    monkeypatch.setattr(envs.socket, "gethostname", lambda: "N1.Cluster.EDU")
    monkeypatch.setattr(envs.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(calkit, "get_machine_id", lambda: "AB-CD")
    monkeypatch.setenv("CK_TEST_EMPTY", "")
    cases: list[tuple[list[dict], bool]] = [
        ([{"app_exists": "git"}], True),
        ([{"app_exists": ["calkit-test-no-such-app", "git"]}], True),
        ([{"env_var_set": "CK_TEST_SITE"}], True),
        ([{"env_var_set": ["CK_TEST_UNSET", "CK_TEST_SITE"]}], True),
        ([{"env_var_set": "CK_TEST_UNSET"}], False),
        # The old name still works
        ([{"env_var_exists": "CK_TEST_SITE"}], True),
        ([{"env_var_exists": "CK_TEST_UNSET"}], False),
        ([{"env_var_equals": "CK_TEST_UNSET="}], False),
        ([{"env_var_equals": "CK_TEST_EMPTY="}], True),
        ([{"env_var_equals": "CK_TEST_SITE=b=c"}], False),
        ([{"hostname_matches": "*.cluster.edu"}], True),
        ([{"hostname_matches": ["x", "n?.*"]}], True),
        ([{"hostname_matches": "cluster.edu"}], False),
        ([{"os_is": "macos"}], True),
        ([{"os_is": ["linux", "windows"]}], False),
        ([{"machine_id_equals": "abcd"}], True),
        ([{"machine_id_equals": ["ef"]}], False),
        ([{"os_is": "macos"}, {"app_exists": "git"}], True),
        ([{"os_is": "macos"}, {"os_is": "linux"}], False),
        # A GPU condition holds when any of the machine's GPUs meets it
        ([{"gpu_vendor_is": "amd"}], True),
        ([{"gpu_vendor_is": ["nvidia", "apple"]}], False),
        ([{"gpu_arch_is": "GFX1201"}], True),
        ([{"gpu_arch_is": ["sm_89", "gfx1036"]}], True),
        ([{"gpu_arch_is": "gfx90a"}], False),
        ([{"gpu_name_matches": "*rx 9070*"}], True),
        ([{"gpu_name_matches": "*RTX*"}], False),
    ]
    gpus = (
        {
            "name": "AMD Radeon(TM) Graphics",
            "vendor": "amd",
            "arch": "gfx1036",
        },
        {"name": "AMD Radeon RX 9070 XT", "vendor": "amd", "arch": "gfx1201"},
    )
    monkeypatch.setattr(calkit.core, "get_gpus", lambda: gpus)
    for when, held in cases:
        envs_def["one"] = {"kind": "switch", "switch": [option("here", *when)]}
        picked = envs.resolve_switch("one", envs_def)
        assert picked == ("here" if held else None), when
    # A node that reports a short hostname still matches its qualified name
    monkeypatch.setattr(envs.socket, "gethostname", lambda: "login1")
    monkeypatch.setattr(envs.socket, "getfqdn", lambda: "login1.hpc.edu")
    envs_def["one"] = {
        "kind": "switch",
        "switch": [option("here", {"hostname_matches": "*.hpc.edu"})],
    }
    assert envs.resolve_switch("one", envs_def) == "here"
    # Nothing matching and no default picks nothing, rather than guessing,
    # and says which conditions failed
    envs_def["none"] = {
        "kind": "switch",
        "switch": [
            option("here", {"os_is": "linux"}, {"app_exists": "sbatch"}),
            option("here", {"env_var_equals": "CK_TEST_SITE=lab"}),
        ],
    }
    assert envs.resolve_switch("none", envs_def) is None
    reason = envs.describe_switch_no_match("none", envs_def["none"])
    assert reason.endswith(
        "none of these hold: os_is: linux and app_exists: sbatch; "
        "env_var_equals: CK_TEST_SITE=lab"
    )
    # Options must exist, not be switches, and not mix machines and
    # runtimes, and a definition that doesn't validate says so
    is_linux = {"os_is": "linux"}
    for options, match in [
        ([option("nope", is_linux), option("here")], "not defined"),
        ([option("cluster", is_linux), option("here")], "another switch"),
        ([option("py", is_linux), option("here")], "one or the other"),
        ([option("here"), option("py", is_linux)], "only the last option"),
        ([option("here", {"os_is": "Darwin"})], "is invalid"),
        ([option("_system", is_linux), option("here")], "kind: system"),
    ]:
        envs_def["bad"] = {"kind": "switch", "switch": options}
        with pytest.raises(ValueError, match=match):
            envs.get_switch_options("bad", envs_def)
    del envs_def["bad"]
    # A switch of runtimes can't wrap another env
    envs_def["rt"] = {"kind": "switch", "switch": [option("py")]}
    assert not envs.switch_is_outer("rt", envs_def)
    # An option only the switch uses can be defined in place, named after
    # the switch and its position, and is recorded by that name
    envs_def["inline"] = {
        "kind": "switch",
        "switch": [
            {
                "when": [is_linux],
                "use": {"kind": "slurm", "max_concurrent_jobs": 2},
            },
            {"use": {"kind": "system"}},
        ],
    }
    assert envs.get_switch_options("inline", envs_def) == [
        "inline.1",
        "inline.2",
    ]
    assert envs.switch_is_outer("inline", envs_def)
    assert envs.resolve_switch("inline", envs_def) == "inline.2"
    assert envs.get_env("inline.2", envs_def) == {"kind": "system"}
    assert envs.get_env("here", envs_def) == {"kind": "system"}
    for missing in ["inline.3", "inline.0", "inline.x", "here.1", "nope.1"]:
        assert envs.get_env(missing, envs_def) is None
    with open(envs.write_switch_env_lock("inline", envs_def)) as f:
        inline_lock = json.load(f)
    assert [o["use"] for o in inline_lock["switch"]] == [
        "inline.1",
        "inline.2",
    ]
    assert inline_lock["options"]["inline.1"] == {"kind": "slurm"}
    envs_def["inline.1"] = {"kind": "system"}
    with pytest.raises(ValueError, match="already has that name"):
        envs.get_switch_options("inline", envs_def)
    del envs_def["inline"], envs_def["inline.1"]
    # The definitions lock is the same on every machine, and changes when an
    # option's definition or spec does
    with open("requirements.txt", "w") as f:
        f.write("idna\n")
    lock_fpath = envs.write_switch_env_lock("rt", envs_def)
    assert lock_fpath == ".calkit/env-locks/rt/switch.json"
    assert envs.get_env_lock_fpath(
        env=envs_def["rt"], env_name="rt", for_dvc=True
    ) == os.path.dirname(lock_fpath)
    with open(lock_fpath) as f:
        locked = json.load(f)
    assert set(locked["options"]) == {"py"}
    assert "requirements.txt" in locked["specs"]
    monkeypatch.setenv("CK_TEST_SITE", "elsewhere")
    envs.write_switch_env_lock("rt", envs_def)
    with open(lock_fpath) as f:
        assert json.load(f) == locked
    with open("requirements.txt", "w") as f:
        f.write("idna\ncertifi\n")
    envs.write_switch_env_lock("rt", envs_def)
    with open(lock_fpath) as f:
        assert json.load(f)["specs"] != locked["specs"]
    # So does an option's lock, though not its line endings
    py_lock = envs.get_env_lock_fpath(
        env=envs_def["py"], env_name="py", for_dvc=True
    )
    assert py_lock is not None
    os.makedirs(py_lock, exist_ok=True)
    with open(os.path.join(py_lock, "linux-64.txt"), "w") as f:
        f.write("idna==3.10\n")
    envs.write_switch_env_lock("rt", envs_def)
    with open(lock_fpath) as f:
        with_lock = json.load(f)
    assert "py" in with_lock["locks"]
    with open(os.path.join(py_lock, "linux-64.txt"), "wb") as f:
        f.write(b"idna==3.10\r\n")
    envs.write_switch_env_lock("rt", envs_def)
    with open(lock_fpath) as f:
        assert json.load(f) == with_lock
    with open(os.path.join(py_lock, "linux-64.txt"), "w") as f:
        f.write("idna==3.11\n")
    envs.write_switch_env_lock("rt", envs_def)
    with open(lock_fpath) as f:
        assert json.load(f)["locks"] != with_lock["locks"]
    # A switch's machine lock is a system env lock beside the definitions
    machine_env = envs.switch_machine_lock_env({"lock": ["os"]})
    envs.write_system_env_lock(env_name="rt", env=machine_env)
    assert os.path.isfile(".calkit/env-locks/rt/info.json")
    # Locks an option's first check on a machine writes don't change it, so
    # moving to that machine doesn't rerun anything
    here = {"kind": "system", "lock": ["os"]}
    envs_def["here"] = here
    envs_def["mach"] = {
        "kind": "switch",
        "switch": [option("slurm-env", is_linux), option("here")],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"environments": envs_def}, f)
    mach_lock = envs.write_switch_env_lock("mach", envs_def)
    with open(mach_lock) as f:
        before = json.load(f)
    envs.write_scheduler_env_lock(
        env_name="slurm-env", env=envs_def["slurm-env"]
    )
    envs.write_system_env_lock(env_name="here", env=here)
    envs.write_switch_env_lock("mach", envs_def)
    with open(mach_lock) as f:
        assert json.load(f) == before
    # Rewriting one does, from then on, as it reruns the stages using that
    # option directly
    for os_name in ["Elsewhere", "Another"]:
        envs.write_system_env_lock(
            env_name="here", env=here, system_info={"os": os_name}, relock=True
        )
        with open(mach_lock) as f:
            relocked = json.load(f)
        assert set(relocked["machine_locks"]) == {"here"}
        assert relocked["machine_locks"] != before.get("machine_locks")
        before = relocked
        envs.write_switch_env_lock("mach", envs_def)
        with open(mach_lock) as f:
            assert json.load(f) == relocked
    # A switch's first lock records the machine locks there are, since
    # there are no results yet to rerun
    envs_def["mach2"] = {"kind": "switch", "switch": [option("here")]}
    with open(envs.write_switch_env_lock("mach2", envs_def)) as f:
        assert set(json.load(f)["machine_locks"]) == {"here"}
    del envs_def["mach2"]
    os.remove("calkit.yaml")
    # A runtime switch's lock gates its stages like a machine switch's
    envs_def["rt"]["lock"] = ["hostname"]
    with open(".calkit/env-locks/rt/info.json", "w") as f:
        json.dump({"hostname": "calkit-test.invalid"}, f)
    ck_info = {
        "environments": envs_def,
        "pipeline": {
            "stages": {
                "s": {
                    "kind": "shell-command",
                    "command": "true",
                    "environment": "rt",
                }
            }
        },
    }
    gated, errors = calkit.pipeline.get_gated_stages(
        ck_info, interactive=False
    )
    assert "locked to another machine" in gated["s"] and not errors
    del envs_def["rt"]["lock"]
    # A switch's check is current only while its pick and the picked env
    # are, and never when it picks a machine, which is read on each check
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"environments": envs_def}, f)
    envs.save_cache(env_name="rt", env=envs_def["rt"], success=True)
    assert envs.check_cache(env_name="rt", env=envs_def["rt"])
    with open("requirements.txt", "w") as f:
        f.write("idna\nsix\n")
    assert not envs.check_cache(env_name="rt", env=envs_def["rt"])
    envs.save_cache(env_name="rt", env=envs_def["rt"], success=True)
    envs_def["rt"]["switch"] = [
        option("py-b", {"env_var_set": "CK_TEST_PICK_B"}),
        option("py"),
    ]
    envs_def["py-b"] = {"kind": "uv-venv", "path": "requirements.txt"}
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"environments": envs_def}, f)
    envs.save_cache(env_name="rt", env=envs_def["rt"], success=True)
    assert envs.check_cache(env_name="rt", env=envs_def["rt"])
    monkeypatch.setenv("CK_TEST_PICK_B", "1")
    assert not envs.check_cache(env_name="rt", env=envs_def["rt"])
    envs.save_cache(env_name="mach", env=envs_def["mach"], success=True)
    assert not envs.check_cache(env_name="mach", env=envs_def["mach"])
    # Only machines have requirements, which compiling the pipeline enforces
    # even though the project isn't validated on load
    for kind, extra in [("conda", {"path": "env.yml"}), ("switch", {})]:
        bad_info = {
            "environments": {
                "e": {"kind": kind, "requirements": ["git"], **extra}
            },
            "pipeline": {"stages": {}},
        }
        with pytest.raises(ValueError, match="describe a machine"):
            calkit.pipeline.to_dvc(ck_info=bad_info, write=False)
    # A machine switch's stage setup goes in a file, which survives cmd.exe
    stages = calkit.pipeline.to_dvc(
        ck_info={
            "environments": envs_def,
            "pipeline": {
                "stages": {
                    "job": {
                        "kind": "shell-command",
                        "command": "true",
                        "environment": "mach",
                        "setup": ["module load x"],
                    }
                }
            },
        },
        write=False,
    )
    cmd = stages["job"]["cmd"]
    assert "--setup-file .calkit/stage-setup/job.json" in cmd
    assert "module load" not in cmd
    assert ".calkit/stage-setup/job.json" in stages["job"]["deps"]


def test_stage_calkit_files(tmp_dir):
    import git

    repo = git.Repo.init()
    os.makedirs(".dvc")
    with open(os.path.join(".dvc", "config"), "w") as f:
        f.write("[core]\n    autostage = true\n")
    os.makedirs(os.path.join(".calkit", "env-locks"))
    with open(os.path.join(".calkit", "env-locks", "py.json"), "w") as f:
        f.write("{}\n")
    with open(calkit.STAGE_RUNS_FPATH, "w") as f:
        f.write("{}\n")
    # Everything Calkit wrote is staged
    calkit.environments.stage_calkit_files()
    staged = repo.git.diff("--cached", "--name-only").split()
    assert ".calkit/env-locks/py.json" in staged
    assert ".calkit/stage-runs.json" in staged
    # A file the project ignores is left out, without a warning, and the
    # rest are still staged
    repo.git.reset()
    with open(".gitignore", "w") as f:
        f.write(".calkit/stage-runs.json\n")
    with mock.patch("calkit.cli.warn") as warn:
        calkit.environments.stage_calkit_files()
    warn.assert_not_called()
    staged = repo.git.diff("--cached", "--name-only").split()
    assert staged == [".calkit/env-locks/py.json"]


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


@pytest.mark.xdist_group("texlive")
def test_composed_envs(tmp_dir, texlive_user_home, monkeypatch):
    monkeypatch.setenv("CALKIT_USER_HOME", texlive_user_home)
    envs: dict = {
        "tex": {"kind": "texlive"},
        "tex2": {"kind": "texlive"},
        "py": {"kind": "uv", "path": "pyproject.toml", "with": ["tex"]},
        "plain": {"kind": "uv", "path": "pyproject.toml"},
        "twice": {"kind": "uv", "path": "x.toml", "with": ["tex", "tex"]},
        "img": {"kind": "docker", "image": "x", "with": ["tex"]},
        "nested": {"kind": "uv", "path": "pyproject.toml", "with": ["py"]},
        "missing": {"kind": "uv", "path": "pyproject.toml", "with": ["no"]},
        "two": {"kind": "uv", "path": "x.toml", "with": ["tex", "tex2"]},
        "word": {"kind": "uv", "path": "x.toml", "with": "tex"},
        "texwith": {"kind": "texlive", "with": ["tex"]},
        "deep": {"kind": "uv", "path": "x.toml", "with": ["texwith"]},
        "sw": {"kind": "switch", "switch": [{"use": "py"}]},
    }
    get_guest_envs = calkit.environments.get_guest_envs
    assert get_guest_envs("py", envs["py"], envs) == [("tex", envs["tex"])]
    assert get_guest_envs("plain", envs["plain"], envs) == []
    assert get_guest_envs("twice", envs["twice"], envs) == [
        ("tex", envs["tex"])
    ]
    # Only a runtime on this machine can host, only TeX Live can be a guest,
    # only one of those, and a guest can't have its own
    for name, message in [
        ("img", "can't have others composed into it"),
        ("nested", "only texlive environments can be composed"),
        ("missing", "isn't defined"),
        ("two", "more than one TeX Live environment"),
        ("word", "write it as a list"),
        ("texwith", "can't have others composed into it"),
        ("deep", "can't have a 'with' of its own"),
    ]:
        with pytest.raises(ValueError, match=message):
            get_guest_envs(name, envs[name], envs)
    # A guest is checked along with the environment it's composed into
    ck_info = {
        "environments": {k: envs[k] for k in ["tex", "py"]},
        "pipeline": {
            "stages": {
                "fig": {
                    "kind": "python-script",
                    "script_path": "fig.py",
                    "environment": "py",
                }
            }
        },
    }
    names, _, _ = calkit.environments.get_pipeline_env_names(ck_info)
    assert names == ["py", "tex"]
    # Its programs come first on PATH, nothing on the machine points TeX
    # elsewhere, fontconfig finds the system's fonts and its own, and
    # Matplotlib's caches are its own, unless the project says otherwise
    calkit.save_calkit_info(ck_info)
    monkeypatch.setenv("TEXINPUTS", "/elsewhere:")
    monkeypatch.setenv("MPLCONFIGDIR", "/elsewhere")
    monkeypatch.delenv("FONTCONFIG_FILE", raising=False)
    get_composed_env_vars = calkit.environments.get_composed_env_vars
    assert get_composed_env_vars("plain", envs["plain"], envs) is None
    env_vars = get_composed_env_vars("py", envs["py"], envs)
    assert env_vars is not None
    view_dir = calkit.environments.texlive.check("tex", envs["tex"])
    bin_dir = os.path.join(
        view_dir, "bin", calkit.environments.texlive.get_platform()
    )
    assert env_vars["PATH"].split(os.pathsep)[0] == bin_dir
    assert "TEXINPUTS" not in env_vars
    composed_dir = os.path.dirname(env_vars["FONTCONFIG_FILE"])
    assert composed_dir.startswith(
        os.path.join(texlive_user_home, ".calkit", "composed")
    )
    assert env_vars["MPLCONFIGDIR"] == os.path.join(composed_dir, "matplotlib")
    with open(env_vars["FONTCONFIG_FILE"]) as f:
        fonts_conf = f.read()
    assert "/etc/fonts/fonts.conf</include>" in fonts_conf
    assert "texmf-var/fonts/conf/fonts.conf</include>" in fonts_conf
    assert os.environ["MPLCONFIGDIR"] == "/elsewhere"
    assert "FONTCONFIG_FILE" not in os.environ
    env_vars = get_composed_env_vars(
        "py", envs["py"], envs, keep=["MPLCONFIGDIR", "TEXINPUTS"]
    )
    assert env_vars is not None
    assert env_vars["MPLCONFIGDIR"] == "/elsewhere"
    assert env_vars["TEXINPUTS"] == "/elsewhere:"
    # A fontconfig configuration the machine already uses is the one kept
    monkeypatch.setenv("FONTCONFIG_FILE", "/my/fonts.conf")
    env_vars = get_composed_env_vars("py", envs["py"], envs)
    assert env_vars is not None
    with open(env_vars["FONTCONFIG_FILE"]) as f:
        fonts_conf = f.read()
    assert "/my/fonts.conf</include>" in fonts_conf
    assert "/etc/fonts/fonts.conf" not in fonts_conf
    # A switch composes what it picks here
    env_vars = get_composed_env_vars("sw", envs["sw"], envs)
    assert env_vars is not None
    assert env_vars["PATH"].split(os.pathsep)[0] == bin_dir
    # Matplotlib's usetex packages are added to the TeX Live environment's
    # lock when the host has Matplotlib, but not just matplotlib-inline
    add_host_tex_packages = calkit.environments.add_host_tex_packages
    with open("pyproject.toml", "w") as f:
        f.write('[project]\nname = "x"\ndependencies = ["ipykernel"]\n')
    with open("uv.lock", "w") as f:
        f.write('[[package]]\nname = "matplotlib-inline"\n')
    assert add_host_tex_packages("py", envs["py"], "tex", envs["tex"]) == []
    with open("uv.lock", "a") as f:
        f.write('[[package]]\nname = "matplotlib"\n')
    added = add_host_tex_packages("py", envs["py"], "tex", envs["tex"])
    assert added == calkit.environments.MATPLOTLIB_TEX_PACKAGES
    lock = calkit.environments.texlive.read_lock(
        calkit.environments.texlive.get_lock_fpath("tex", envs["tex"])
    )
    assert lock is not None
    assert lock["added"] == calkit.environments.MATPLOTLIB_TEX_PACKAGES
    assert add_host_tex_packages("py", envs["py"], "tex", envs["tex"]) == []


@pytest.mark.skipif(sys.platform == "win32", reason="Uses shell scripts")
def test_check_app_in_env(tmp_path, monkeypatch):
    from calkit.environments.core import check_app_in_env, is_app_required

    monkeypatch.chdir(tmp_path)

    def make_app(folder: str) -> None:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "myapp")
        with open(path, "w") as f:
            f.write("#!/bin/sh\necho hi\n")
        os.chmod(path, 0o755)

    # Installed on this machine only
    make_app("machine")
    monkeypatch.setenv(
        "PATH", str(tmp_path / "machine") + os.pathsep + os.environ["PATH"]
    )
    ck_info: dict = {
        "environments": {
            "py": {
                "kind": "venv",
                "path": "requirements.txt",
                "prefix": ".venv",
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    (tmp_path / "requirements.txt").write_text("")
    subprocess.check_call([sys.executable, "-m", "venv", ".venv"])
    problem = check_app_in_env("myapp", "py", ck_info)
    assert problem is not None
    assert "isn't in environment 'py'" in problem
    assert str(tmp_path / "machine" / "myapp") in problem
    # The '_system' environment is this machine, so it only has to be
    # installed
    assert check_app_in_env("myapp", "_system", ck_info) is None
    problem = check_app_in_env("missing-app", "_system", ck_info)
    assert problem is not None and "isn't installed" in problem
    assert is_app_required("myapp", {}, stage={"requirements": ["myapp"]})
    assert not is_app_required("myapp", {"requirements": ["docker"]})
    required = ck_info | {"requirements": ["myapp>=1"]}
    assert check_app_in_env("myapp", "_system", required) is None
    assert check_app_in_env("myapp", "py", required) is None
    # Provided by the environment, it wins over this machine's
    make_app(os.path.join(".venv", "bin"))
    assert check_app_in_env("myapp", "py", ck_info) is None
    # Even when the environment is already active, e.g., under 'uv run'
    with monkeypatch.context() as m:
        venv_bin = str(tmp_path / ".venv" / "bin")
        m.setenv("PATH", venv_bin + os.pathsep + os.environ["PATH"])
        m.setenv("VIRTUAL_ENV", str(tmp_path / ".venv"))
        m.delenv("CONDA_DEFAULT_ENV", raising=False)
        assert check_app_in_env("myapp", "py", ck_info) is None
        os.remove(os.path.join(venv_bin, "myapp"))
        problem = check_app_in_env("myapp", "py", ck_info)
        assert problem is not None and "machine" in problem
        make_app(venv_bin)
    # For '_system', one in an active environment counts, since it's what
    # runs
    with monkeypatch.context() as m:
        m.setenv("PATH", venv_bin + os.pathsep + os.environ["PATH"])
        m.setenv("VIRTUAL_ENV", str(tmp_path / ".venv"))
        assert (
            check_app_in_env("venv-only-app", "_system", ck_info) is not None
        )
        make_app(venv_bin)
        os.rename(
            os.path.join(venv_bin, "myapp"),
            os.path.join(venv_bin, "venv-only-app"),
        )
        assert check_app_in_env("venv-only-app", "_system", ck_info) is None
    # An environment that hasn't been created is only created when asked
    ck_info["environments"]["new"] = {
        "kind": "venv",
        "path": "requirements.txt",
        "prefix": ".venv-new",
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    problem = check_app_in_env("myapp", "new", ck_info)
    assert problem is not None and problem.startswith("Couldn't")
    problem = check_app_in_env("myapp", "new", ck_info, check_env=True)
    assert problem is not None and "isn't in environment 'new'" in problem
    assert os.path.isdir(".venv-new")
    # Environments whose commands don't run here aren't checked
    ck_info["environments"]["img"] = {"kind": "docker", "image": "x"}
    assert check_app_in_env("myapp", "img", ck_info) is None


def test_check_all_in_pipeline_inline_scripts(tmp_dir):
    block = (
        '# /// script\n# requires-python = ">=3.12"\n'
        "# dependencies = []\n# ///\n"
    )
    stages: dict = {
        name: {"kind": "python-script", "script_path": f"{name}.py"}
        for name in ["ok", "bad", "skipped", "frozen"]
    }
    stages["frozen"]["frozen"] = True
    # One script per item, or one for all
    stages["per-item"] = {
        "kind": "python-script",
        "script_path": "scripts/{n}.py",
        "iterate_over": [{"arg_name": "n", "values": ["a", "b"]}],
    }
    stages["shared"] = {
        "kind": "python-script",
        "script_path": "ok.py",
        "args": ["{n}"],
        "iterate_over": [{"arg_name": "n", "values": [1, 2]}],
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"pipeline": {"stages": stages}}, f)
    os.makedirs("scripts")
    for path in ["ok.py", "skipped.py", "frozen.py", "scripts/a.py"]:
        with open(path, "w") as f:
            f.write(block)
    with open("scripts/b.py", "w") as f:
        f.write("print('no block')\n")
    with open("bad.py", "w") as f:
        f.write("print('no block')\n")
    res = calkit.environments.check_all_in_pipeline(skip_stages=["skipped"])
    a_path, b_path = (
        os.path.join("scripts", "a.py"),
        os.path.join("scripts", "b.py"),
    )
    assert set(res) == {"ok.py", "bad.py", a_path, b_path}
    assert res["ok.py"]["success"]
    assert res[a_path]["success"]
    assert os.path.isfile("ok.py.lock")
    assert os.path.isfile(a_path + ".lock")
    for path in ["bad.py", b_path]:
        assert not res[path]["success"]
        assert "'# /// script' block" in res[path]["output"]
    assert not os.path.exists("skipped.py.lock")
    assert not os.path.exists("frozen.py.lock")
    # Only the failed item can't run
    gated, _ = calkit.pipeline.get_gated_stages(
        calkit.load_calkit_info(),
        interactive=False,
        failed_environments={p: "failed" for p in ["bad.py", b_path]},
    )
    assert set(gated) == {"bad", "per-item@b"}
    # Cached until a script changes
    res = calkit.environments.check_all_in_pipeline(skip_stages=["skipped"])
    assert res["ok.py"]["cached"]


def test_check_all_in_pipeline_quiet(tmp_dir, monkeypatch, capfd):
    # Behind a spinner, what the tools print isn't shown, but the end of it
    # is kept for a failure, and the check can say what it's doing
    ck_info = {
        "environments": {
            "py": {"kind": "uv-venv", "path": "requirements.txt"},
        },
        "pipeline": {
            "stages": {
                "thing": {
                    "kind": "shell-command",
                    "environment": "py",
                    "command": "echo hi",
                }
            }
        },
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)

    def failing_check(env_name, verbose=False):
        calkit.progress.report(f"Creating environment '{env_name}'")
        print("from Python")
        # As a tool does, to what it inherits
        subprocess.run(
            [
                sys.executable,
                "-c",
                "for i in range(30): print(f'line {i}')",
            ],
            check=True,
        )
        raise typer.Exit(1)

    monkeypatch.setattr(calkit.cli.check, "check_environment", failing_check)
    reported: list[str] = []
    res = calkit.environments.check_all_in_pipeline(
        quiet=True, progress=reported.append
    )
    assert not res["py"]["success"]
    output = res["py"]["output"].splitlines()
    assert len(output) == calkit.environments.core.FAILED_CHECK_OUTPUT_LINES
    assert output[-1] == "line 29"
    assert reported == [
        "Checking environment 'py'",
        "Creating environment 'py'",
    ]
    out, err = capfd.readouterr()
    assert "line 29" not in out + err
    # Shown as it happens otherwise, so not kept
    res = calkit.environments.check_all_in_pipeline()
    assert not res["py"]["success"]
    assert "output" not in res["py"]
    assert "line 29" in capfd.readouterr().out


def test_get_implied_requirements() -> None:
    envs: dict[str, dict] = {
        "conda": {"kind": "conda", "path": "environment.yml"},
        "uv": {"kind": "uv", "path": "pyproject.toml"},
        "uv-venv": {"kind": "uv-venv", "path": "requirements.txt"},
        "pixi": {"kind": "pixi", "path": "pixi.toml"},
        "julia": {"kind": "julia", "path": "Project.toml", "julia": "1.11"},
        "renv": {"kind": "renv", "path": "DESCRIPTION"},
        "nix": {"kind": "nix", "path": "flake.nix"},
        "docker": {"kind": "docker", "image": "ubuntu"},
        "matlab": {"kind": "matlab", "version": "R2024a"},
        "here": {"kind": "system"},
        "slurm": {"kind": "slurm"},
        "venv": {"kind": "venv", "path": "requirements.txt"},
        # TeX Live, the only kind composed in, is installed by Calkit
        "tex": {"kind": "texlive", "packages": []},
        "far": {"kind": "system", "host": "calkit-test.invalid"},
    }
    envs["uv"]["with"] = ["tex"]
    get = calkit.environments.get_implied_requirements
    used = list(envs.items())[:-1]
    stage: dict = {"kind": "shell-command", "command": "true"}
    # Each environment's, and none for Docker, which offers itself, or for
    # kinds built with nothing beyond Calkit
    assert get(stage, used, []) == {
        "conda": "conda",
        "uv": "uv",
        "uv-venv": "uv",
        "pixi": "pixi",
        "julia": "julia",
        "renv": "Rscript",
        "nix": "nix",
    }
    assert get(stage, [], []) == {}
    # A script's own environment is uv's
    script_stage = {"kind": "python-script", "script_path": "a.py"}
    assert get(script_stage, [], []) == {"a.py": "uv"}
    assert get(script_stage | {"wdir": "sub"}, [], ["uv"]) == {}
    # One declared is what's checked instead, however it's written, and
    # wherever it applies here, as is one a declared app provides
    cases: list[tuple[list, list, str]] = [
        ([{"name": "conda", "setup_command": "echo"}], [], "conda"),
        ([], ["uv>=0.5"], "uv"),
        ([], [{"kind": "app", "name": "juliaup"}], "julia"),
        (["R"], [], "Rscript"),
    ]
    for project_requirements, stage_requirements, left_out in cases:
        implied = get(
            stage | {"requirements": stage_requirements},
            used,
            project_requirements,
        )
        assert left_out not in implied.values()
        assert len(set(implied.values())) == 5
    # Mamba doesn't provide Conda, which the environment check runs
    assert get(stage, used, ["mamba"])["conda"] == "conda"
    envs["here"]["requirements"] = ["pixi"]
    assert "pixi" not in get(stage, used, []).values()
    # Something other than an app of the same name doesn't count, and a
    # malformed one is left to be reported where it's checked
    declared = [{"kind": "env-var", "name": "conda"}, {"x": 1}]
    assert get(stage, used[:1], declared) == {"conda": "conda"}
    # One sent to another machine needs none here, and what's declared for
    # there doesn't count for a stage that runs here in its inner env
    remote = used[:1] + [("far", envs["far"] | {"requirements": ["conda"]})]
    assert get(stage, remote, []) == {}
    notebook = {"kind": "jupyter-notebook", "requirements": ["conda"]}
    assert get(notebook, remote, []) == {"conda": "conda"}
    assert get(notebook, remote, ["conda"]) == {}
