"""Tests for ``calkit.config``."""

from __future__ import annotations

import calkit.config as config


def test_get_hub(monkeypatch):
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    # CALKIT_ENV=test is set by pytest config
    assert config.get_hub() == "test"
    monkeypatch.setenv("CALKIT_ENV", "staging")
    assert config.get_hub() == "staging"
    # CALKIT_HUB takes precedence and accepts an environment name
    monkeypatch.setenv("CALKIT_HUB", "production")
    assert config.get_hub() == "production"
    # Built-in hub URLs map to their environment names, with or without
    # scheme, so they share config with the env-based spellings
    monkeypatch.setenv("CALKIT_HUB", "https://staging.calkit.io")
    assert config.get_hub() == "staging"
    monkeypatch.setenv("CALKIT_HUB", "calkit.io")
    assert config.get_hub() == "production"
    # Arbitrary hubs pass through, normalized
    monkeypatch.setenv("CALKIT_HUB", "https://hub.example.edu/")
    assert config.get_hub() == "https://hub.example.edu"


def test_per_hub_config_naming(monkeypatch):
    # Built-in aliases keep their existing filenames and service names
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    assert config.get_env_suffix() == "-test"
    assert config.get_app_name() == "calkit-test"
    monkeypatch.setenv("CALKIT_HUB", "production")
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
