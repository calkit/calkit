"""Tests for ``calkit.docker``."""

import sys
from unittest import mock
from unittest.mock import Mock

import pytest

import calkit.docker
from calkit.docker import (
    _image_name_without_tag_or_digest,
    _parse_docker_run_command,
    _parse_volume_spec,
    _uses_entrypoint_command_mode,
    get_remote_image_ref,
    is_auth_error,
    keep_only_repo_digests,
    login_to_registry,
    platform_to_arch_name,
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


def test_pull_image_with_login(monkeypatch):
    logins = []
    pulls = []

    def fake_login(ref, interactive=False):
        logins.append(ref)
        return True, None

    def make_pull(results):
        def fake_pull(ref, platform=None):
            pulls.append(ref)
            return results.pop(0)

        return fake_pull

    monkeypatch.setattr(calkit.docker, "login_to_registry", fake_login)
    # A pull that works needs no credentials, and logging in would replace
    # whatever the machine already holds for that registry
    monkeypatch.setattr(calkit.docker, "pull_image", make_pull([(True, "")]))
    assert calkit.docker.pull_image_with_login("ghcr.io/o/p:latest")
    assert logins == []
    # Neither does one that failed for a reason credentials can't fix
    monkeypatch.setattr(
        calkit.docker,
        "pull_image",
        make_pull([(False, "manifest unknown")]),
    )
    assert not calkit.docker.pull_image_with_login("ghcr.io/o/p@sha256:abc")
    assert logins == []
    # Only a registry that actually refused us is worth logging in to
    monkeypatch.setattr(
        calkit.docker,
        "pull_image",
        make_pull(
            [
                (False, "denied: requested access to the resource is denied"),
                (True, ""),
            ]
        ),
    )
    assert calkit.docker.pull_image_with_login("ghcr.io/o/p:latest")
    assert logins == ["ghcr.io/o/p:latest"]


def test_is_auth_error():
    # What GHCR says when the token lacks 'write:packages'
    assert is_auth_error(
        "error from registry: permission_denied: The token provided does "
        "not match expected scopes."
    )
    assert is_auth_error("denied: requested access to the resource is denied")
    assert is_auth_error(
        "8b7a0e7328e7: Waiting\nerror from registry: denied\ndenied"
    )
    assert is_auth_error("unauthorized: authentication required")
    # Anything else has to be reported as-is rather than sending the user
    # off to fix credentials that were fine
    assert not is_auth_error("dial tcp: lookup ghcr.io: no such host")
    assert not is_auth_error("manifest unknown")
    assert not is_auth_error(
        "permission denied while trying to connect to the Docker daemon socket"
    )
    assert not is_auth_error("")


def test_registry_login_hint(monkeypatch):
    import calkit.docker

    monkeypatch.setattr(
        calkit.docker, "get_github_username", lambda: "someone"
    )
    ref = "ghcr.io/o/p/img:latest"
    # A refusal from GHCR says how to get a token that can push, since a
    # push that can't prompt otherwise ends on a bare "unauthorized"
    hint = calkit.docker.registry_login_hint(
        ref, "error from registry: unauthorized"
    )
    assert calkit.docker.GITHUB_PACKAGES_TOKEN_URL in hint
    assert "docker login ghcr.io -u someone" in hint
    assert "calkit push docker" in hint
    # Another registry gets only what Calkit knows: log in to it
    hint = calkit.docker.registry_login_hint(
        "docker.io/someone/img:v1", "unauthorized: authentication required"
    )
    assert "docker login docker.io" in hint
    # Anything other than refused credentials is no login problem
    assert calkit.docker.registry_login_hint(ref, "manifest unknown") == ""


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
    # On stderr, so a command run in the environment keeps stdout
    shown = capfd.readouterr().err
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


def test_ensure_image_available() -> None:
    # An image already here needs no registry at all
    with mock.patch("calkit.docker.image_exists_locally", return_value=True):
        with mock.patch("calkit.docker.pull_image") as pull:
            calkit.docker.ensure_image_available("some/image:1")
            pull.assert_not_called()
    # A pull that says nothing never reached the registry, which is local
    # and affects every pull on the machine, so it's reported that way
    # rather than as a missing image
    with mock.patch("calkit.docker.image_exists_locally", return_value=False):
        with mock.patch(
            "calkit.docker.pull_image",
            return_value=(False, "Docker said nothing for 60 seconds"),
        ):
            with pytest.raises(ValueError, match="never reached the registry"):
                calkit.docker.ensure_image_available("some/image:1")
        # Nor is a credential helper to blame when the daemon refused us
        with mock.patch(
            "calkit.docker.pull_image",
            return_value=(
                False,
                "permission denied while trying to connect to the docker "
                "API at unix:///var/run/docker.sock",
            ),
        ):
            with pytest.raises(ValueError, match="'docker' group"):
                calkit.docker.ensure_image_available("some/image:1")
            # Under WSL, the group only applies once WSL itself restarts
            with mock.patch("calkit.core.is_wsl", return_value=True):
                with pytest.raises(ValueError, match="wsl --shutdown"):
                    calkit.docker.ensure_image_available("some/image:1")
        # A credential helper denied permission isn't about the group
        with mock.patch(
            "calkit.docker.pull_image",
            return_value=(
                False,
                "error getting credentials - err: fork/exec "
                "/usr/bin/docker-credential-desktop.exe: permission denied",
            ),
        ):
            with pytest.raises(ValueError, match="credential helper"):
                calkit.docker.ensure_image_available("some/image:1")
        # One that got as far as talking to the registry is about the image
        with mock.patch(
            "calkit.docker.pull_image",
            return_value=(False, "1: Pulling from some/image\nnot found"),
        ):
            with pytest.raises(ValueError, match="may not exist"):
                calkit.docker.ensure_image_available("some/image:1")
        # A successful pull is not an error
        with mock.patch(
            "calkit.docker.pull_image", return_value=(True, "1: Pulling")
        ):
            calkit.docker.ensure_image_available("some/image:1")


def test_ensure_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def docker_info(returncode: int, stderr: str = "") -> Mock:
        return Mock(return_value=Mock(returncode=returncode, stderr=stderr))

    monkeypatch.setattr(
        "calkit.docker.DAEMON_START_TIMEOUT", 0.0, raising=True
    )
    monkeypatch.setattr("time.sleep", lambda _: None)
    # Not installed, which offers the installer only on a TTY
    monkeypatch.setattr("shutil.which", lambda _: None)
    with mock.patch("calkit.install.prompt_and_install") as install:
        with pytest.raises(
            calkit.docker.DockerNotReadyError, match="calkit install docker"
        ):
            calkit.docker.ensure_ready()
        install.assert_not_called()
        install.return_value = False
        with pytest.raises(
            calkit.docker.DockerNotReadyError, match="not installed"
        ):
            calkit.docker.ensure_ready(interactive=True)
        install.assert_called_once_with("docker", interactive=True)
    # Installed and running
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/docker")
    with mock.patch("subprocess.run", docker_info(0)):
        calkit.docker.ensure_ready()
    # Installed but not running
    not_running = docker_info(1, "Cannot connect to the Docker daemon")
    with mock.patch("subprocess.run", not_running):
        with pytest.raises(
            calkit.docker.DockerNotReadyError, match="not running"
        ):
            calkit.docker.ensure_ready()
    # Installed but not usable by this user
    with mock.patch("subprocess.run", docker_info(1, "permission denied")):
        with pytest.raises(
            calkit.docker.DockerNotReadyError, match="'docker' group"
        ):
            calkit.docker.ensure_ready()
    # A daemon that doesn't answer at all
    with mock.patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 30)
    ):
        with pytest.raises(
            calkit.docker.DockerNotReadyError, match="did not answer"
        ):
            calkit.docker.ensure_ready()
    # Docker Desktop is offered to be started on a TTY, and waited for
    monkeypatch.setattr("calkit.docker.DAEMON_START_TIMEOUT", 10.0)
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("os.path.isdir", lambda _: True)
    starting = Mock(
        side_effect=[
            Mock(returncode=1, stderr="Cannot connect"),
            Mock(returncode=1, stderr="Cannot connect"),
            Mock(returncode=0, stderr=""),
        ]
    )
    with (
        mock.patch("subprocess.run", starting),
        mock.patch("subprocess.Popen") as popen,
        mock.patch("builtins.input", return_value=""),
    ):
        calkit.docker.ensure_ready(interactive=True)
    assert popen.call_args.args[0] == ["open", "-a", "Docker"]
    assert starting.call_count == 3
    # Declining to start it says how to
    with (
        mock.patch("subprocess.run", not_running),
        mock.patch("subprocess.Popen") as popen,
        mock.patch("builtins.input", return_value="n"),
    ):
        with pytest.raises(
            calkit.docker.DockerNotReadyError, match="start Docker Desktop"
        ):
            calkit.docker.ensure_ready(interactive=True)
    popen.assert_not_called()
