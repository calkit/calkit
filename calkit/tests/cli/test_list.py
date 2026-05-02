"""Tests for ``cli.list``."""

import subprocess

import calkit


def test_list_environments(tmp_dir):
    subprocess.check_call("calkit list environments", shell=True)
    # TODO: Create some environments


def test_list_templates():
    subprocess.check_call("calkit list templates", shell=True)


def test_list_stages(tmp_dir):
    subprocess.check_call("calkit list stages", shell=True)
    ck_info = {
        "pipeline": {
            "stages": {
                "stage1": {"kind": "python-script", "script_path": "train.py"},
                "stage2": {"kind": "shell-command", "command": "echo Hello"},
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    out = subprocess.check_output("calkit list stages", shell=True, text=True)
    assert "stage1" in out
    assert "stage2" in out
    out = subprocess.check_output(
        "calkit list stages --kind python-script", shell=True, text=True
    )
    assert "stage1" in out
    assert "stage2" not in out


def test_list_remotes(tmp_dir):
    # Outside a repo: should warn but not fail
    result = subprocess.run(
        ["calkit", "list", "remotes"], capture_output=True, text=True
    )
    assert result.returncode == 0
    # Inside a repo with a Git remote and a DVC remote
    subprocess.check_call(["git", "init"])
    subprocess.check_call(
        ["git", "remote", "add", "origin", "https://github.com/test/repo.git"]
    )
    subprocess.check_call(["dvc", "init", "-q"])
    subprocess.check_call(
        ["dvc", "remote", "add", "myremote", "s3://my-bucket/dvc"]
    )
    out = subprocess.check_output(["calkit", "list", "remotes"], text=True)
    assert "(Git) origin: https://github.com/test/repo.git" in out
    assert "(DVC) myremote: s3://my-bucket/dvc" in out
