"""Tests for ``calkit.environments``."""

import os
import shutil

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
