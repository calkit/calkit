"""Tests for ``calkit.config``."""

from __future__ import annotations

from typing import get_args

import keyring
import keyring.backend
import keyring.errors
import pytest
import yaml

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
    # CALKIT_ENV=test is set by pytest config, and is the only environment
    # name that still means anything: it keeps the suite off real
    # credentials. Naming an instance is CALKIT_HUB's job.
    assert config.get_hub() == "test"
    monkeypatch.setenv("CALKIT_ENV", "staging")
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    assert config.get_hub() == "production"
    monkeypatch.setenv("CALKIT_ENV", "test")
    # CALKIT_HUB takes precedence and must be a URL; environment names
    # are the hub operator's vocabulary and are rejected
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
    # The default_hub config value fills in when CALKIT_HUB isn't set,
    # falling back to production without it
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
    # The working directory project's declared hub is respected, beating
    # default_hub; the scheme is optional, with localhost getting http
    monkeypatch.setattr(
        config, "_get_default_hub", lambda: "https://hub.example.edu"
    )
    with open("calkit.yaml", "w") as f:
        f.write("hub: staging.calkit.io\n")
    assert config.get_hub() == "staging"
    with open("calkit.yaml", "w") as f:
        f.write("hub: localhost:5173\n")
    assert config.get_hub() == "local"
    # CALKIT_HUB still overrides what the project declares, which is what
    # makes pushing a copy of a project to another hub possible
    monkeypatch.setenv("CALKIT_HUB", "calkit.io")
    assert config.get_hub() == "production"


def test_get_env(monkeypatch, tmp_dir):
    # The environment name is derived from the hub, not the other way
    # around: it only exists to pick API URLs and sandbox credentials
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    monkeypatch.setenv("CALKIT_HUB", "https://staging.calkit.io")
    assert config.get_env() == "staging"
    monkeypatch.setenv("CALKIT_HUB", "localhost:5173")
    assert config.get_env() == "local"
    # A self-hosted hub isn't one of ours, so it gets production behavior
    monkeypatch.setenv("CALKIT_HUB", "https://hub.example.edu")
    assert config.get_env() == "production"
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    monkeypatch.setenv("CALKIT_ENV", "test")
    assert config.get_env() == "test"


def test_keyring_probe_is_lazy(monkeypatch):
    # Probing the keyring can pop an unlock prompt on macOS, and editors
    # run commands like `calkit status` on every file save, so importing
    # the module must not touch it
    calls = []
    monkeypatch.setattr(config, "_keyring_supported", None)
    monkeypatch.setattr(
        config, "_probe_keyring", lambda: calls.append(1) or True
    )
    assert calls == []
    assert config.supports_keyring() is True
    assert len(calls) == 1
    # And the result is cached rather than re-probed per secret
    assert config.supports_keyring() is True
    assert len(calls) == 1


def test_config_naming(monkeypatch):
    # The test environment gets an isolated config file and keyring
    # service so tests never touch real credentials
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    assert config.get_env_suffix() == "-test"
    assert config.get_app_name() == "calkit-test"
    assert config.get_config_yaml_fpath().endswith("config-test.yaml")
    # All real hubs share one config file and keyring service
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    assert config.get_env_suffix() == ""
    assert config.get_app_name() == "calkit"
    monkeypatch.setenv("CALKIT_HUB", "https://staging.calkit.io")
    assert config.get_env_suffix() == ""
    monkeypatch.setenv("CALKIT_HUB", "https://hub.example.edu")
    assert config.get_env_suffix() == ""
    assert config.get_config_yaml_fpath().endswith("config.yaml")


def test_hub_storage_key(monkeypatch):
    # The test environment's own hub and production store credentials
    # flat, with plain keyring usernames
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    assert config._hub_storage_key() is None
    assert config._keyring_username("token") == "token"
    monkeypatch.setenv("CALKIT_HUB", "calkit.io")
    assert config._hub_storage_key() is None
    # Other hubs key their own sub-maps and keyring entries by URL
    monkeypatch.setenv("CALKIT_HUB", "https://staging.calkit.io")
    assert config._hub_storage_key() == "https://staging.calkit.io"
    monkeypatch.setenv("CALKIT_HUB", "hub.example.edu")
    assert config._hub_storage_key() == "https://hub.example.edu"
    assert config._keyring_username("token") == "token@https://hub.example.edu"
    # Only hub credentials are namespaced; shared settings are not
    assert config._keyring_username("zenodo_token") == "zenodo_token"


def test_hub_scoped_settings(monkeypatch, tmp_path):
    # Force file-based storage so the round trip is observable, in an
    # isolated file so this can't race CLI tests using the real one
    fpath = str(tmp_path / "config-test.yaml")
    monkeypatch.setattr(config, "get_config_yaml_fpath", lambda: fpath)
    monkeypatch.setattr(config, "supports_keyring", lambda: False)
    monkeypatch.delenv("CALKIT_HUB", raising=False)
    # The default hub stores credentials flat
    cfg = config.read()
    cfg.email = "unify@example.com"
    cfg.token = "default-hub-token"
    cfg.write()
    # Another hub sees shared settings but not the default hub's token
    monkeypatch.setenv("CALKIT_HUB", "https://hub.example.edu")
    cfg = config.read()
    assert cfg.email == "unify@example.com"
    assert cfg.token is None
    cfg.token = "other-hub-token"
    cfg.write()
    with open(fpath) as f:
        raw = yaml.safe_load(f)
    assert raw["token"] == "default-hub-token"
    assert raw["hubs"]["https://hub.example.edu"]["token"] == "other-hub-token"
    cfg = config.read()
    assert cfg.token == "other-hub-token"
    # Back on the default hub, the flat token is intact
    monkeypatch.delenv("CALKIT_HUB")
    cfg = config.read()
    assert cfg.token == "default-hub-token"
    # A token env var (CALKIT_TOKEN outside the test environment)
    # overrides the stored credential for any hub
    monkeypatch.setenv("CALKIT_TEST_TOKEN", "env-token")
    monkeypatch.setenv("CALKIT_HUB", "https://hub.example.edu")
    cfg = config.read()
    assert cfg.token == "env-token"
    monkeypatch.delenv("CALKIT_HUB")
    cfg = config.read()
    assert cfg.token == "env-token"


class _FakeKeyring(keyring.backend.KeyringBackend):
    """A keyring backend that counts what it's asked for."""

    priority = 1  # type: ignore[assignment]

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
        self.reads: list[tuple[str, str]] = []

    def get_password(self, service, username):
        self.reads.append((service, username))
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError(service)
        del self.store[(service, username)]


@pytest.fixture
def fake_keyring(monkeypatch):
    backend = _FakeKeyring()
    original = keyring.get_keyring()
    keyring.set_keyring(backend)
    monkeypatch.setattr(config, "_keyring_supported", True)
    monkeypatch.setattr(config, "_secret_cache", {})
    yield backend
    keyring.set_keyring(original)


def test_keyring_fields_match_the_model():
    # KEYRING_FIELDS is consulted on every attribute read, so it's a
    # constant rather than derived per access; this keeps it honest
    annotated = {
        name
        for name, field in config.Settings.model_fields.items()
        if config.KeyringOptionalSecret in get_args(field.annotation)
    }
    assert annotated == set(config.KEYRING_FIELDS)


def test_secrets_are_read_lazily(fake_keyring, monkeypatch, tmp_path):
    monkeypatch.setattr(
        config, "get_config_yaml_fpath", lambda: str(tmp_path / "config.yaml")
    )
    app = config.get_app_name()
    fake_keyring.store[(app, "github_token")] = "gh-secret"
    fake_keyring.store[(app, "dvc_token")] = "dvc-secret"
    # Reading the config touches no secrets at all. Each one costs a
    # keychain authorization prompt on macOS, and reading all eight up
    # front prompted eight times for secrets no command wanted.
    cfg = config.read()
    assert fake_keyring.reads == []
    assert cfg.github_token == "gh-secret"
    assert [u for _, u in fake_keyring.reads] == ["github_token"]
    # Repeat access is free, and so is a second Settings instance, since
    # the cache lives with the process rather than the model
    assert cfg.github_token == "gh-secret"
    assert config.read().github_token == "gh-secret"
    assert [u for _, u in fake_keyring.reads] == ["github_token"]
    # An absent secret is looked up once and remembered as absent
    assert cfg.zenodo_token is None
    assert cfg.zenodo_token is None
    assert [u for _, u in fake_keyring.reads] == [
        "github_token",
        "zenodo_token",
    ]
    # An assignment wins over what's stored, including a None meaning
    # "forget this credential"
    cfg.github_token = "replaced"
    assert cfg.github_token == "replaced"
    cfg.dvc_token = None
    assert cfg.dvc_token is None
    assert "dvc_token" not in [u for _, u in fake_keyring.reads]


def test_write_keeps_secrets_it_never_read(
    fake_keyring, monkeypatch, tmp_path
):
    # write() reads an absent value as "delete this from the keyring", so
    # a lazily-unresolved secret would be destroyed by any unrelated save
    monkeypatch.setattr(
        config, "get_config_yaml_fpath", lambda: str(tmp_path / "config.yaml")
    )
    app = config.get_app_name()
    fake_keyring.store[(app, "github_token")] = "gh-secret"
    cfg = config.read()
    cfg.email = "someone@example.com"
    cfg.write()
    assert fake_keyring.store[(app, "github_token")] == "gh-secret"
    monkeypatch.setattr(config, "_secret_cache", {})
    reread = config.read()
    assert reread.email == "someone@example.com"
    assert reread.github_token == "gh-secret"
    # Clearing one really does remove it
    reread.github_token = None
    reread.write()
    assert (app, "github_token") not in fake_keyring.store
