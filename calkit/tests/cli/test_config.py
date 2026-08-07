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
    # Check with secrets
    subprocess.check_call(["calkit", "config", "unset", "token"])
    out = (
        subprocess.check_output(
            ["calkit", "config", "get", "token"],
        )
        .decode()
        .strip()
    )
    assert not out
    test_token = str(uuid.uuid4())
    subprocess.check_call(
        ["calkit", "config", "set", "token", test_token],
    )
    out = (
        subprocess.check_output(
            ["calkit", "config", "get", "token"],
        )
        .decode()
        .strip()
    )
    assert out == test_token
    subprocess.check_call(
        ["calkit", "config", "unset", "token"],
    )
    out = (
        subprocess.check_output(
            ["calkit", "config", "get", "token"],
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
            ["calkit", "config", "get", "token"],
        )
        .decode()
        .strip()
    )
    assert out == "this-was-in-the-config-file"
    subprocess.check_call(
        ["calkit", "config", "set", "token", "this-is-a-new-token"],
    )
    with open(fpath, "r") as f:
        cfg = calkit.ryaml.load(f)
    if calkit.config.KEYRING_SUPPORTED:
        assert "token" not in cfg
    else:
        assert cfg["token"] == "this-is-a-new-token"


def test_config_hub_option():
    # Per-hub config lives in its own file, keyed by the slugified hub
    fpath = os.path.join(
        os.path.expanduser("~"), ".calkit", "config-hub.example.edu.yaml"
    )
    if os.path.isfile(fpath):
        os.remove(fpath)
    email = f"{uuid.uuid4()}@example.com"
    subprocess.check_call(
        [
            "calkit",
            "config",
            "--hub",
            "https://hub.example.edu",
            "set",
            "email",
            email,
        ]
    )
    assert os.path.isfile(fpath)
    out = (
        subprocess.check_output(
            [
                "calkit",
                "config",
                "--hub",
                "https://hub.example.edu",
                "get",
                "email",
            ]
        )
        .decode()
        .strip()
    )
    assert out == email
    # The active (test) hub's config is unaffected
    out = (
        subprocess.check_output(["calkit", "config", "get", "email"])
        .decode()
        .strip()
    )
    assert out != email
    # A built-in hub URL resolves to the same config as its env name
    out = (
        subprocess.check_output(
            ["calkit", "config", "--hub", "calkit.io", "get", "email"],
            env=os.environ | {"CALKIT_ENV": "production"},
        )
        .decode()
        .strip()
    )
    assert out != email
    os.remove(fpath)
