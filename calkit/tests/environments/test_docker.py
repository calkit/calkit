"""Tests for ``calkit.environments.docker``."""

import pytest

import calkit
from calkit.environments.docker import (
    build_lock,
    get_image_name,
    get_lock_archs,
    get_lock_digest_refs,
    lock_matches_image,
    lock_matches_spec,
    resolve_registry_prefix,
)


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


def test_lock_matching():
    lock = {
        "RootFS": {"Type": "layers", "Layers": ["sha256:a", "sha256:b"]},
        "DockerfileMD5": "abc",
        "DepsMD5s": {"reqs.txt": "def"},
    }
    kwargs = dict(dockerfile_md5="abc", deps_md5s={"reqs.txt": "def"})
    assert lock_matches_spec(lock, **kwargs)  # type: ignore[arg-type]
    # Inputs that decide what gets built are what make a lock stale
    assert not lock_matches_spec(
        lock,
        dockerfile_md5="changed",
        deps_md5s={"reqs.txt": "def"},
    )
    assert not lock_matches_spec(lock, dockerfile_md5="abc", deps_md5s={})
    # For an environment named after an image, the image is the spec, but a
    # lock written before that was recorded doesn't say, so it still matches
    image_lock: dict = {
        "DockerfileMD5": None,
        "DepsMD5s": {},
        "Image": "alpine:3",
    }
    assert lock_matches_spec(
        image_lock, dockerfile_md5=None, deps_md5s={}, image="alpine:3"
    )
    assert not lock_matches_spec(
        image_lock, dockerfile_md5=None, deps_md5s={}, image="ubuntu:24.04"
    )
    del image_lock["Image"]
    assert lock_matches_spec(
        image_lock, dockerfile_md5=None, deps_md5s={}, image="ubuntu:24.04"
    )
    assert lock_matches_image(
        lock, {"RootFS": {"Layers": ["sha256:a", "sha256:b"]}}
    )
    assert not lock_matches_image(lock, {"RootFS": {"Layers": ["sha256:a"]}})
    assert not lock_matches_image(lock, {})
    assert not lock_matches_image({}, {"RootFS": {"Layers": ["sha256:a"]}})


def test_get_lock_digest_refs():
    lock = {"RepoDigests": ["sha256:remote"]}
    # A bare digest is only pullable once paired with a repo, and the repo
    # comes from the environment as it is now, so a digest left over from a
    # different image is asked for somewhere it cannot resolve
    assert get_lock_digest_refs(lock) == []
    assert get_lock_digest_refs(lock, "ghcr.io/o/p/my-image:latest") == [
        "ghcr.io/o/p/my-image@sha256:remote"
    ]
    assert get_lock_digest_refs(lock, "other/image:latest") == [
        "other/image@sha256:remote"
    ]
    # Locks written before digests were stored bare still work, and the
    # project's own registry is preferred, since that's the copy it controls
    legacy = {
        "RepoDigests": [
            "my-image@sha256:local",
            "ghcr.io/o/p/my-image@sha256:remote",
        ]
    }
    assert get_lock_digest_refs(legacy) == [
        "my-image@sha256:local",
        "ghcr.io/o/p/my-image@sha256:remote",
    ]
    assert get_lock_digest_refs(legacy, "ghcr.io/o/p/my-image:latest")[0] == (
        "ghcr.io/o/p/my-image@sha256:remote"
    )
    assert get_lock_digest_refs({}) == []
    assert get_lock_digest_refs({"RepoDigests": ["no-digest-here"]}) == []
    assert (
        get_lock_digest_refs(
            {"RepoDigests": ["no-digest-here"]}, "ghcr.io/o/p/img"
        )
        == []
    )


def test_build_lock():
    identity = {
        "RepoTags": ["something-else:latest"],
        "RepoDigests": ["sha256:abc"],
        "Architecture": "amd64",
        "Os": "linux",
        "RootFS": {"Type": "layers", "Layers": ["sha256:a"]},
    }
    lock = build_lock(
        identity=identity,
        dockerfile_md5="abc",
        deps_md5s={},
        run_config={"WorkDir": "/work"},
    )
    # What an image is called says nothing about what it is, and a lock
    # already belongs to the environment whose directory it sits in, so
    # renaming an image doesn't rerun every stage in it
    assert "RepoTags" not in lock
    assert lock["WorkDir"] == "/work"
    assert lock["DockerfileMD5"] == "abc"
    # Key order has to be stable, since a lock written for another platform
    # must match what that platform would write for itself
    other = build_lock(
        identity=dict(reversed(list(identity.items()))),
        dockerfile_md5="abc",
        deps_md5s={},
        run_config={"WorkDir": "/work"},
    )
    assert list(lock) == list(other)
    # Only an environment named after an image records it
    assert "Image" not in lock
    named = build_lock(
        identity=identity,
        dockerfile_md5=None,
        deps_md5s={},
        run_config={},
        image="alpine:3",
    )
    assert named["Image"] == "alpine:3"


def test_resolve_registry_prefix(tmp_dir):
    # Registries are opt-in, since pushing publishes an image
    assert resolve_registry_prefix(
        {"kind": "docker", "path": "Dockerfile"}
    ) is (None)
    assert resolve_registry_prefix({"registry": "none"}) is None
    assert resolve_registry_prefix({"registry": "reg.example.com/ns"}) == (
        "reg.example.com/ns"
    )


def test_get_lock_archs():
    assert get_lock_archs({}) == ["amd64", "arm64"]
    archs = get_lock_archs(
        {"build_platforms": ["linux/amd64", "linux/arm/v7"]}
    )
    assert archs == ["amd64", "arm64", "arm-v7"]


def test_lock_digest_refs_stay_with_their_repo() -> None:
    # A digest recorded against another repository is left over from an
    # image the project no longer uses. Pulling it would go on building
    # with the old image however the environment was changed, which is
    # what made changing an image in calkit.yaml do nothing.
    stale = {"RepoDigests": ["texlive/texlive@sha256:abc"]}
    assert get_lock_digest_refs(stale, "ghcr.io/calkit/latex:0.1.0") == []
    same = {"RepoDigests": ["ghcr.io/calkit/latex@sha256:abc"]}
    assert get_lock_digest_refs(same, "ghcr.io/calkit/latex:0.1.0") == [
        "ghcr.io/calkit/latex@sha256:abc"
    ]
    # Docker reports what it pulled in full while a project names it short
    assert get_lock_digest_refs(
        {"RepoDigests": ["docker.io/library/alpine@sha256:abc"]}, "alpine:3.19"
    ) == ["docker.io/library/alpine@sha256:abc"]
    # A bare digest names no repository, so it belongs to whichever one
    # the environment now points at; a digest that isn't there fails the
    # pull and the tag is fetched instead
    assert get_lock_digest_refs(
        {"RepoDigests": ["sha256:abc"]}, "ghcr.io/calkit/latex:0.1.0"
    ) == ["ghcr.io/calkit/latex@sha256:abc"]
    # With nowhere to pull from, only self-describing digests are usable
    assert get_lock_digest_refs(
        {"RepoDigests": ["sha256:abc", "foo/bar@sha256:def"]}, None
    ) == ["foo/bar@sha256:def"]
