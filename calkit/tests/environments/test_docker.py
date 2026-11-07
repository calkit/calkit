"""Tests for ``calkit.environments.docker``."""

import pytest

import calkit
from calkit.environments.docker import get_image_name


def test_get_image_name(tmp_dir):
    # An environment named after someone else's image keeps that name
    assert (
        get_image_name("main", {"kind": "docker", "image": "alpine:3.18"})
        == "alpine:3.18"
    )
    # One with neither an image nor a Dockerfile has nothing to name
    with pytest.raises(ValueError, match="must define an image"):
        get_image_name("main", {"kind": "docker"})
    calkit.save_calkit_info(
        {"owner": "Someone", "name": "Some-Project", "environments": {}}
    )
    # One that builds its own image is named after the project and the
    # environment, lowercased, since repository names must be
    assert (
        get_image_name("My-Env", {"kind": "docker", "path": "Dockerfile"})
        == "someone/some-project.my-env"
    )
    # An image that is named wins over the one that would be worked out
    assert (
        get_image_name(
            "env", {"kind": "docker", "path": "Dockerfile", "image": "mine"}
        )
        == "mine"
    )
    # A project that isn't published anywhere yet still names itself if
    # calkit.yaml says what it's called
    calkit.save_calkit_info({"name": "Some-Project", "environments": {}})
    assert (
        get_image_name("env", {"kind": "docker", "path": "Dockerfile"})
        == "some-project.env"
    )
    # With nothing to be named after, there's nothing to guess from: the
    # directory a project sits in is not a name, since renaming it would
    # rename the image, and every project called 'analysis' would collide
    calkit.save_calkit_info({"environments": {}})
    with pytest.raises(ValueError, match="Cannot work out what to call"):
        get_image_name("env", {"kind": "docker", "path": "Dockerfile"})
