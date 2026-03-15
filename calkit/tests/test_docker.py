"""Tests for ``calkit.docker``."""

from calkit.docker import (
    _image_name_without_tag_or_digest,
    _parse_docker_run_command,
    _parse_volume_spec,
    _uses_entrypoint_command_mode,
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
