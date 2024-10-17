"""Tests for ``cli.main``."""

import subprocess

import pytest

from calkit.core import ryaml


def test_run_in_env(tmp_dir):
    subprocess.check_call("git init", shell=True)
    subprocess.check_call("dvc init", shell=True)
    # First create a new Docker environment for this bare project
    subprocess.check_call(
        "calkit new docker-env "
        "--name my-image "
        "--create-stage build-image "
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
    # Now let's create a 2nd Docker env and make sure we need to call it by
    # name when trying to run
    subprocess.check_call(
        "calkit new docker-env "
        "--name env2 "
        "--image-name my-image-2 "
        "--create-stage build-image-2 "
        "--path Dockerfile.2 "
        "--from ubuntu "
        "--add-layer mambaforge "
        "--add-layer foampy "
        "--description 'This is a test image 2'",
        shell=True,
    )
    with open("dvc.yaml") as f:
        pipeline = ryaml.load(f)
    stg = pipeline["stages"]["build-image-2"]
    cmd = stg["cmd"]
    assert "-f Dockerfile.2" in cmd
    subprocess.check_call("calkit run", shell=True)
    with pytest.raises(subprocess.CalledProcessError):
        out = (
            subprocess.check_output("calkit run-env echo sup", shell=True)
            .decode()
            .strip()
        )
    out = (
        subprocess.check_output(
            [
                "calkit",
                "run-env",
                "-n",
                "env2",
                "python",
                "-c",
                '"import foampy; print(foampy.__version__)"',
            ]
        )
        .decode()
        .strip()
    )
    assert out == "0.0.5"
    # Test that we can create a Docker env with no build stage
    subprocess.check_call(
        "calkit new docker-env "
        "--name py3.10 "
        "--image-name python:3.10.15-bookworm "
        "--description 'Just Python.'",
        shell=True,
    )
    out = (
        subprocess.check_output(
            "calkit run-env -n py3.10 python --version", shell=True
        )
        .decode()
        .strip()
    )
    assert out == "Python 3.10.15"
