"""Tests for ``calkit.environments``."""

import os
import shutil
import subprocess

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
    assert res.env["prefix"] == ".venv"
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
    assert res.env["prefix"] == "envs/myenv/.venv"
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
