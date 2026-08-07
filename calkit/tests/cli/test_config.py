"""Tests for the config CLI."""

import os
import subprocess
import uuid

import calkit


def test_get_set():
    fpath = calkit.config.get_config_yaml_fpath()
    assert fpath == os.path.join(
        os.path.expanduser("~"), ".calkit", "config-test.yaml"
    )
    # Delete the config if it exists
    if os.path.isfile(fpath):
        os.remove(fpath)
    out = (
        subprocess.check_output(["calkit", "config", "get", "email"])
        .decode()
        .strip()
    )
    assert not out
    email = f"{uuid.uuid4()}@example.com"
    subprocess.check_call(
        ["calkit", "config", "set", "email", email],
    )
    out = (
        subprocess.check_output(["calkit", "config", "get", "email"])
        .decode()
        .strip()
    )
    assert out == email
    out = (
        subprocess.check_output(["calkit", "config", "unset", "email"])
        .decode()
        .strip()
    )
    assert not out
    out = (
        subprocess.check_output(["calkit", "config", "get", "email"])
        .decode()
        .strip()
    )
    assert not out
    # Hub credentials are not accessible through the shared-key commands
    result = subprocess.run(
        ["calkit", "config", "get", "token"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "calkit config hub" in result.stderr
    # Check with secrets, which live under the hub subcommand
    subprocess.check_call(["calkit", "config", "hub", "unset", "token"])
    out = (
        subprocess.check_output(
            ["calkit", "config", "hub", "get", "token"],
        )
        .decode()
        .strip()
    )
    assert not out
    test_token = str(uuid.uuid4())
    subprocess.check_call(
        ["calkit", "config", "hub", "set", "token", test_token],
    )
    out = (
        subprocess.check_output(
            ["calkit", "config", "hub", "get", "token"],
        )
        .decode()
        .strip()
    )
    assert out == test_token
    subprocess.check_call(
        ["calkit", "config", "hub", "unset", "token"],
    )
    out = (
        subprocess.check_output(
            ["calkit", "config", "hub", "get", "token"],
        )
        .decode()
        .strip()
    )
    assert not out
    # Check that if we put a token in the config YAML file, it is removed
    # when the token is set next
    with open(fpath, "w") as f:
        calkit.ryaml.dump({"token": "this-was-in-the-config-file"}, f)
    out = (
        subprocess.check_output(
            ["calkit", "config", "hub", "get", "token"],
        )
        .decode()
        .strip()
    )
    assert out == "this-was-in-the-config-file"
    subprocess.check_call(
        ["calkit", "config", "hub", "set", "token", "this-is-a-new-token"],
    )
    with open(fpath, "r") as f:
        cfg = calkit.ryaml.load(f)
    if calkit.config.KEYRING_SUPPORTED:
        assert "token" not in cfg
    else:
        assert cfg["token"] == "this-is-a-new-token"
    # Hub scoping shares the same config file, so check it here rather
    # than in a separate test that could run in a parallel worker
    _check_hub_scoping()


def _check_hub_scoping():
    hub = "https://hub.example.edu"
    # A credential set for one hub is invisible to others; all hubs share
    # one config file
    hub_token = f"hub-scoped-{uuid.uuid4()}"
    subprocess.check_call(
        ["calkit", "config", "hub", "set", "token", hub_token, "--hub", hub]
    )
    out = (
        subprocess.check_output(
            ["calkit", "config", "hub", "get", "token", "--hub", hub]
        )
        .decode()
        .strip()
    )
    assert out == hub_token
    out = (
        subprocess.check_output(["calkit", "config", "hub", "get", "token"])
        .decode()
        .strip()
    )
    assert out != hub_token
    # Shared settings are visible regardless of hub
    email = f"{uuid.uuid4()}@example.com"
    subprocess.check_call(["calkit", "config", "set", "email", email])
    out = (
        subprocess.check_output(
            ["calkit", "config", "get", "email"],
            env=os.environ | {"CALKIT_HUB": hub},
        )
        .decode()
        .strip()
    )
    assert out == email
    subprocess.check_call(
        ["calkit", "config", "hub", "unset", "token", "--hub", hub]
    )
    out = (
        subprocess.check_output(
            ["calkit", "config", "hub", "get", "token", "--hub", hub]
        )
        .decode()
        .strip()
    )
    assert not out
    # Environment names are rejected as hub values
    result = subprocess.run(
        ["calkit", "config", "hub", "get", "token", "--hub", "staging"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "hub URL" in result.stderr
