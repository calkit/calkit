"""Tests for ``calkit.environments``."""

import json
import os
import platform
import shutil
import socket
import subprocess
from datetime import timedelta
from unittest import mock

import pytest

import calkit
import calkit.environments


def test_check_all_in_pipeline(tmp_dir):
    ck_info = {
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
    assert res.env["kind"] == "docker"
    assert res.env["image"] == "texlive/texlive:latest-full"


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

    import calkit.environments as envs
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


def test_host_is_local_by_address(monkeypatch):
    import calkit.environments as envs

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
    import calkit.environments as envs

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
    import calkit.environments as envs

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
        "33C4DDA7-7423-5B6A-B86F-EA6859EB058E",
        "33c4dda774235b6ab86fea6859eb058e",
    )
    assert calkit.machine_ids_match(" 33c4dda7 ", "33C4DDA7")
    assert not calkit.machine_ids_match("33c4dda7", "0000ffff")
    # Not knowing which machine this is is never evidence that it's the one
    # being asked about, so an unknown ID matches nothing -- not even
    # another unknown one
    assert not calkit.machine_ids_match(None, None)
    assert not calkit.machine_ids_match("33c4dda7", None)
    assert not calkit.machine_ids_match(None, "33c4dda7")
    assert not calkit.machine_ids_match("", "")


def test_env_is_local_prefers_the_machine_id_over_the_name():
    import calkit.environments as envs

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
    import calkit.environments as envs

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


def test_machine_id_is_reported_and_lockable():
    import calkit.environments as envs

    # Pinning results to one machine is what 'hostname' was being used for,
    # badly: renaming the machine breaks that pin, and a machine elsewhere
    # with the same name satisfies it
    assert envs.SYSTEM_LOCK_PROPERTIES["machine-id"] == "machine_id"
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id": "abc-123"}
    ):
        assert envs.get_system_lock_data(["machine-id"]) == {
            "machine-id": "abc-123"
        }
    # A machine that can't report one can't pin to one either, rather than
    # recording null and claiming a pin that isn't there
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id": None}
    ):
        with pytest.raises(ValueError, match="not available on this machine"):
            envs.get_system_lock_data(["machine-id"])


def test_declaring_a_machine_id_does_not_lock_it(tmp_dir):
    import calkit.environments as envs

    # Naming a machine says where to run, which is a separate question from
    # whether results depend on it: moving a project to a new machine and
    # updating 'machine_id' need not invalidate everything computed on the
    # old one. Whether it does is the project's call, made through 'lock'.
    env = {"kind": "system", "machine_id": "abc-123"}
    assert envs.get_env_lock_fpath(env=env, env_name="laptop") is None
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id": "abc-123"}
    ):
        assert envs.write_system_env_lock(env_name="laptop", env=env) is None
        # Saying so explicitly is what pins it
        env_locked = env | {"lock": ["machine-id"]}
        lock_fpath = envs.write_system_env_lock(
            env_name="laptop", env=env_locked
        )
    assert lock_fpath is not None
    with open(lock_fpath) as f:
        assert json.load(f) == {"machine-id": "abc-123"}


def test_locking_an_unreadable_machine_id_says_how_to_supply_one(tmp_dir):
    import calkit.environments as envs

    # Recording null would claim a pin that isn't there, so this raises --
    # but this is the one lockable property a user can supply by hand, and
    # the way to is a config setting they have no reason to know about
    with mock.patch.object(
        calkit, "get_system_info", return_value={"machine_id": None}
    ):
        with pytest.raises(ValueError, match="calkit config set machine_id"):
            envs.write_system_env_lock(
                env_name="laptop",
                env={"kind": "system", "lock": ["machine-id"]},
            )


def test_system_lock_can_describe_another_machine(tmp_dir):
    import calkit.environments as envs

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


def test_system_env_checks_are_not_cached():
    import calkit.environments as envs

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
    import calkit.environments as envs

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
    # Docker's is a rename of a field that has been published for a while,
    # so tightening it would retroactively invalidate existing projects
    assert DockerEnvironment(image="x", inputs=["../outside.C"]).inputs == [
        "../outside.C"
    ]
