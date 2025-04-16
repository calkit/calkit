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
        subprocess.check_output(["calkit", "config", "get", "username"])
        .decode()
        .strip()
    )
    assert not out
    username = str(uuid.uuid4())
    subprocess.check_call(
        ["calkit", "config", "set", "username", username],
    )
    out = (
        subprocess.check_output(["calkit", "config", "get", "username"])
        .decode()
        .strip()
    )
    assert out == username
    out = (
        subprocess.check_output(["calkit", "config", "unset", "username"])
        .decode()
        .strip()
    )
    assert not out
    out = (
        subprocess.check_output(["calkit", "config", "get", "username"])
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
