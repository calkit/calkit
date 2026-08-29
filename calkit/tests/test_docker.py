"""Tests for ``calkit.docker``."""

import sys
from unittest.mock import Mock

import pytest

from calkit.docker import (
    _image_name_without_tag_or_digest,
    _parse_docker_run_command,
    _parse_volume_spec,
    _uses_entrypoint_command_mode,
    build_lock,
    get_image_name,
    get_lock_archs,
    get_lock_digest_refs,
    get_remote_image_ref,
    is_auth_error,
    keep_only_repo_digests,
    lock_matches_image,
    lock_matches_spec,
    login_to_registry,
    platform_to_arch_name,
    resolve_registry_prefix,
    split_image_ref,
)


def test_parse_volume_spec():
    assert _parse_volume_spec("./data:/work") == ("./data", "/work")
    assert _parse_volume_spec("./data:/work:ro") == ("./data", "/work")
    assert _parse_volume_spec(r"C:\Users\me:/data") == (
        r"C:\Users\me",
        "/data",
    )
    assert _parse_volume_spec(r"C:\Users\me:/data:ro") == (
        r"C:\Users\me",
        "/data",
    )
    assert _parse_volume_spec("not-a-volume") is None


def test_uses_entrypoint_command_mode_allowlist():
    assert _uses_entrypoint_command_mode("minlag/mermaid-cli:latest")
    assert _uses_entrypoint_command_mode("minlag/mermaid-cli")
    assert _uses_entrypoint_command_mode("docker.io/minlag/mermaid-cli")
    assert _uses_entrypoint_command_mode(
        "docker.io/minlag/mermaid-cli@sha256:1234567890abcdef"
    )
    assert not _uses_entrypoint_command_mode("ubuntu:latest")


def test_image_name_without_tag_or_digest_with_registry_port():
    assert (
        _image_name_without_tag_or_digest("localhost:5000/myimg:1.0")
        == "localhost:5000/myimg"
    )
    assert (
        _image_name_without_tag_or_digest(
            "LOCALHOST:5000/org/repo/image@sha256:abcdef"
        )
        == "localhost:5000/org/repo/image"
    )


def test_parse_docker_run_command_with_common_and_unknown_flags():
    parsed = _parse_docker_run_command(
        [
            "docker",
            "run",
            "--env",
            "A=1",
            "--env-file",
            ".env",
            "--network",
            "host",
            "--pull=always",
            "--another-unknown-flag",
            "minlag/mermaid-cli:latest",
            "-i",
            "in.mmd",
            "-o",
            "out.svg",
        ]
    )
    assert parsed is not None
    assert parsed["image"] == "minlag/mermaid-cli:latest"
    assert parsed["command"] == ["-i", "in.mmd", "-o", "out.svg"]


def test_split_image_ref():
    assert split_image_ref("ubuntu") == (None, "ubuntu", None, None)
    assert split_image_ref("ubuntu:22.04") == (None, "ubuntu", "22.04", None)
    assert split_image_ref("library/ubuntu") == (
        None,
        "library/ubuntu",
        None,
        None,
    )
    assert split_image_ref("ghcr.io/o/p/env:v1") == (
        "ghcr.io",
        "o/p/env",
        "v1",
        None,
    )
    assert split_image_ref("localhost:5000/foo/bar:v1") == (
        "localhost:5000",
        "foo/bar",
        "v1",
        None,
    )
    assert split_image_ref("ghcr.io/o/p@sha256:abc") == (
        "ghcr.io",
        "o/p",
        None,
        "sha256:abc",
    )


def test_get_remote_image_ref():
    assert (
        get_remote_image_ref("my-image", "ghcr.io/owner/proj")
        == "ghcr.io/owner/proj/my-image:latest"
    )
    # Repository names must be lowercase, but a tag is case-sensitive
    assert (
        get_remote_image_ref("My-Image:v1.2-RC", "ghcr.io/Owner/Proj")
        == "ghcr.io/owner/proj/my-image:v1.2-RC"
    )
    # An already-qualified local name keeps only its final component
    assert (
        get_remote_image_ref("docker.io/someone/img:v1", "reg.example.com/ns")
        == "reg.example.com/ns/img:v1"
    )
    assert (
        get_remote_image_ref("img", "ghcr.io/owner/proj/")
        == "ghcr.io/owner/proj/img:latest"
    )


def test_platform_to_arch_name():
    assert platform_to_arch_name("linux/amd64") == "amd64"
    assert platform_to_arch_name("linux/arm/v7") == "arm-v7"
    assert platform_to_arch_name({"os": "linux", "architecture": "arm64"}) == (
        "arm64"
    )
    assert (
        platform_to_arch_name(
            {"os": "linux", "architecture": "arm", "variant": "v5"}
        )
        == "arm-v5"
    )
    # Attestation manifests and non-Linux images aren't runnable environments
    assert (
        platform_to_arch_name({"os": "unknown", "architecture": "unknown"})
        is None
    )
    assert platform_to_arch_name("windows/amd64") is None


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


def test_keep_only_repo_digests():
    identity = {
        "RepoDigests": [
            "my-image@sha256:local",
            "ghcr.io/o/p/my-image@sha256:remote",
        ]
    }
    assert keep_only_repo_digests(identity, None)["RepoDigests"] == []
    # Only the digest itself is kept, so moving the environment to another
    # registry doesn't rewrite the lock and rerun every stage in it
    assert keep_only_repo_digests(identity, "ghcr.io/o/p/my-image:latest")[
        "RepoDigests"
    ] == ["sha256:remote"]
    # Digests already stored bare pass through, so re-locking an unchanged
    # image doesn't churn
    assert keep_only_repo_digests({"RepoDigests": ["sha256:remote"]}, "any")[
        "RepoDigests"
    ] == ["sha256:remote"]
    # The original is left alone so callers can keep using it
    assert len(identity["RepoDigests"]) == 2


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


def test_is_auth_error():
    # What GHCR says when the token lacks 'write:packages'
    assert is_auth_error(
        "error from registry: permission_denied: The token provided does "
        "not match expected scopes."
    )
    assert is_auth_error("denied: requested access to the resource is denied")
    assert is_auth_error("unauthorized: authentication required")
    # Anything else has to be reported as-is rather than sending the user
    # off to fix credentials that were fine
    assert not is_auth_error("dial tcp: lookup ghcr.io: no such host")
    assert not is_auth_error("manifest unknown")
    assert not is_auth_error("")


def test_login_to_registry_ignores_other_registries():
    # Only GHCR has credentials Calkit can obtain; everything else relies
    # on the user's own docker login
    assert login_to_registry("docker.io/someone/img:v1") == (False, None)
    assert login_to_registry("localhost:5000/proj/img:v1") == (False, None)


def test_login_to_registry_credentials(monkeypatch):
    from unittest.mock import patch

    import calkit.config
    import calkit.docker
    import calkit.github

    ref = "ghcr.io/o/p/img:v1"
    logins = []
    monkeypatch.setattr(
        calkit.docker, "get_github_username", lambda: "someone"
    )
    monkeypatch.setattr(
        calkit.docker.subprocess,
        "run",
        lambda *args, **kwargs: logins.append(kwargs["input"].decode()),
    )
    monkeypatch.setattr(
        calkit.github, "get_token", lambda: "app-token-with-no-scopes"
    )
    # A stored token is used as-is, without asking GitHub about its scopes
    with patch.object(
        calkit.config, "read", return_value=Mock(github_packages_token="pat")
    ):
        assert login_to_registry(ref) == (True, None)
    assert logins == ["pat"]
    # Without one, the token Calkit already holds is tried, even though a
    # GitHub App token reports no scopes at all. Whether it can push is
    # settled by pushing with it, not by asking beforehand
    logins.clear()
    with patch.object(
        calkit.config, "read", return_value=Mock(github_packages_token=None)
    ):
        assert login_to_registry(ref) == (True, None)
    assert logins == ["app-token-with-no-scopes"]
    # Prompting is only reached once those have been refused, so it asks for
    # a new token rather than trying the held ones over again
    logins.clear()
    monkeypatch.setattr(
        calkit.docker, "prompt_for_packages_token", lambda: "pasted-token"
    )
    with patch.object(
        calkit.config, "read", return_value=Mock(github_packages_token="pat")
    ):
        assert login_to_registry(ref, interactive=True) == (
            True,
            "pasted-token",
        )
    assert logins == ["pasted-token"]


def test_run_showing_output_collapses_repeated_layer_status(capfd):
    from calkit.docker import _run_showing_output

    script = (
        "print('The push refers to repository [example]')\n"
        "print('abc123: Waiting')\n"
        "print('abc123: Waiting')\n"
        "print('def456: Waiting')\n"
        "print('abc123: Pushing [==>   ]  1.2GB')\n"
        "print('abc123: Pushing [====> ]  2.4GB')\n"
        "print('abc123: Pushed')\n"
    )
    success, output = _run_showing_output([sys.executable, "-c", script])
    assert success
    # Everything Docker said is kept, since what a registry says on refusal
    # decides what happens next
    assert output.count("abc123: Waiting") == 2
    shown = capfd.readouterr().out
    # ...but a repeat of the same status isn't worth showing twice
    assert shown.count("abc123: Waiting") == 1
    assert shown.count("def456: Waiting") == 1
    # A transfer that's actually moving still comes through
    assert "1.2GB" in shown
    assert "2.4GB" in shown
    assert "abc123: Pushed" in shown


def test_run_showing_output_reports_a_missing_docker():
    from calkit.docker import _run_showing_output

    success, output = _run_showing_output(["definitely-not-a-real-binary"])
    assert not success
    assert "not installed" in output


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """Fixture to change to a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_get_image_name(tmp_dir):
    import calkit

    # An environment named after someone else's image keeps that name
    assert (
        get_image_name({"kind": "docker", "image": "alpine:3.18"}, "main")
        == "alpine:3.18"
    )
    # One with neither an image nor a Dockerfile has nothing to name
    assert get_image_name({"kind": "docker"}, "main") is None
    calkit.save_calkit_info(
        {"owner": "Someone", "name": "Some-Project", "environments": {}}
    )
    # One that builds its own image is named after the project and the
    # environment, lowercased, since repository names must be
    assert (
        get_image_name({"kind": "docker", "path": "Dockerfile"}, "My-Env")
        == "someone/some-project.my-env"
    )
    # An image that is named wins over the one that would be worked out
    assert (
        get_image_name(
            {"kind": "docker", "path": "Dockerfile", "image": "mine"}, "env"
        )
        == "mine"
    )
