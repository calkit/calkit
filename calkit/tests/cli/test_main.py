"""Tests for ``cli.main``."""

import subprocess


def test_run_in_env(tmp_dir):
    subprocess.check_call("git init", shell=True)
    subprocess.check_call("dvc init", shell=True)
    # First create a new Docker environment for this bare project
    subprocess.check_call(
        "calkit new docker-env "
        "--name my-image "
        "--create-stage build-image "
        "--path Dockerfile "
        "--from ubuntu "
        "--add-layer mambaforge "
        "--description 'This is a test image'",
        shell=True,
    )
    subprocess.check_call("calkit run", shell=True)
    out = (
        subprocess.check_output("calkit run-env echo sup", shell=True)
        .decode()
        .strip()
    )
    assert out == "sup"
