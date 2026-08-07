"""Tests for ``calkit.config``."""

from __future__ import annotations

import pytest

import calkit.config as config


def test_normalize_hub_url():
    assert config.normalize_hub_url("calkit.io") == "https://calkit.io"
    assert (
        config.normalize_hub_url("https://calkit.io/") == "https://calkit.io"
    )
    assert (
        config.normalize_hub_url("localhost:5173") == "http://localhost:5173"
    )
    assert (
        config.normalize_hub_url("127.0.0.1:8000") == "http://127.0.0.1:8000"
    )
    assert (
        config.normalize_hub_url("hub.example.edu/sub/")
        == "https://hub.example.edu/sub"
    )


def test_get_hub(monkeypatch, tmp_dir):
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    # CALKIT_ENV=test is set by pytest config
    assert config.get_hub() == "test"
    monkeypatch.setenv("CALKIT_ENV", "staging")
    assert config.get_hub() == "staging"
    # CALKIT_HUB takes precedence and must be a URL; environment names
    # are deployment-internal vocabulary and are rejected
    monkeypatch.setenv("CALKIT_HUB", "production")
    with pytest.raises(ValueError, match="must be a hub URL"):
        config.get_hub()
    # Built-in hub URLs map to their environment names, with or without
    # scheme, so they share config with the env-based spellings
    monkeypatch.setenv("CALKIT_HUB", "https://staging.calkit.io")
    assert config.get_hub() == "staging"
    monkeypatch.setenv("CALKIT_HUB", "calkit.io")
    assert config.get_hub() == "production"
    # Arbitrary hubs pass through, normalized
    monkeypatch.setenv("CALKIT_HUB", "https://hub.example.edu/")
    assert config.get_hub() == "https://hub.example.edu"
    # The default_hub config value fills in when neither CALKIT_HUB nor
    # CALKIT_ENV is set, falling back to production without it
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    monkeypatch.setattr(
        config, "_get_default_hub", lambda: "https://staging.calkit.io"
    )
    assert config.get_hub() == "staging"
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    assert config.get_hub() == "production"
    # An environment name in default_hub is rejected too
    monkeypatch.setattr(config, "_get_default_hub", lambda: "staging")
    with pytest.raises(ValueError, match="default_hub must be a hub URL"):
        config.get_hub()
    # An explicitly set environment beats default_hub
    monkeypatch.setattr(
        config, "_get_default_hub", lambda: "https://staging.calkit.io"
    )
    monkeypatch.setenv("CALKIT_ENV", "local")
    assert config.get_hub() == "local"
    # The working directory project's declared hub is respected, beating
    # default_hub; the scheme is optional, with localhost getting http
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    monkeypatch.setattr(
        config, "_get_default_hub", lambda: "https://hub.example.edu"
    )
    with open("calkit.yaml", "w") as f:
        f.write("hub: staging.calkit.io\n")
    assert config.get_hub() == "staging"
    with open("calkit.yaml", "w") as f:
        f.write("hub: localhost:5173\n")
    assert config.get_hub() == "local"
    # An explicit environment still overrides the project's hub
    monkeypatch.setenv("CALKIT_ENV", "production")
    assert config.get_hub() == "production"


def test_per_hub_config_naming(monkeypatch):
    # Built-in aliases keep their existing filenames and service names
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    assert config.get_env_suffix() == "-test"
    assert config.get_app_name() == "calkit-test"
    monkeypatch.setenv("CALKIT_ENV", "production")
    assert config.get_env_suffix() == ""
    assert config.get_app_name() == "calkit"
    monkeypatch.setenv("CALKIT_HUB", "http://localhost:5173")
    assert config.get_env_suffix() == "-local"
    # Arbitrary hubs get a slugified key that is Windows-filename and
    # keyring safe
    monkeypatch.setenv("CALKIT_HUB", "https://hub.example.edu")
    assert config.get_env_suffix() == "-hub.example.edu"
    assert config.get_app_name() == "calkit-hub.example.edu"
    assert config.get_config_yaml_fpath().endswith(
        "config-hub.example.edu.yaml"
    )
    monkeypatch.setenv("CALKIT_HUB", "https://myhub.org:8443")
    suffix = config.get_env_suffix()
    assert suffix == "-myhub.org-8443"
    assert ":" not in suffix and "/" not in suffix
    # Env var prefixes can't contain dots or dashes
    assert config.get_env_suffix(sep="_") == "_myhub_org_8443"
