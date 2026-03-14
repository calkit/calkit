"""Tests for ``calkit.docker``."""

from calkit.docker import _parse_volume_spec, _uses_entrypoint_command_mode


def test_parse_volume_spec_basic():
    assert _parse_volume_spec("./data:/work") == ("./data", "/work")


def test_parse_volume_spec_with_mode():
    assert _parse_volume_spec("./data:/work:ro") == ("./data", "/work")


def test_parse_volume_spec_windows_without_mode():
    assert _parse_volume_spec(r"C:\Users\me:/data") == (
        r"C:\Users\me",
        "/data",
    )


def test_parse_volume_spec_windows_with_mode():
    assert _parse_volume_spec(r"C:\Users\me:/data:ro") == (
        r"C:\Users\me",
        "/data",
    )


def test_parse_volume_spec_invalid():
    assert _parse_volume_spec("not-a-volume") is None


def test_uses_entrypoint_command_mode_allowlist():
    assert _uses_entrypoint_command_mode("minlag/mermaid-cli:latest")
    assert _uses_entrypoint_command_mode("minlag/mermaid-cli")
    assert _uses_entrypoint_command_mode("docker.io/minlag/mermaid-cli")
    assert _uses_entrypoint_command_mode(
        "docker.io/minlag/mermaid-cli@sha256:1234567890abcdef"
    )
    assert not _uses_entrypoint_command_mode("ubuntu:latest")
