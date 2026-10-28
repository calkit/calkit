"""Tests for ``calkit.config``."""

from __future__ import annotations

import os
from types import SimpleNamespace
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


def test_user_home(monkeypatch, tmp_path):
    # A project's env_vars can point the home directory elsewhere for a tool
    # a stage runs, and Calkit's own files have to stay where the user keeps
    # them
    project_home = str(tmp_path / "project-home")
    user_home = str(tmp_path / "user-home")
    monkeypatch.delenv(config.USER_HOME_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", project_home)
    monkeypatch.setenv("USERPROFILE", project_home)
    assert config.get_user_home() == project_home
    monkeypatch.setenv(config.USER_HOME_ENV_VAR, user_home)
    assert config.get_user_home() == user_home
    assert config.get_config_yaml_fpath().startswith(user_home)
    # The macOS keychain finds the login keychain through HOME, so a keyring
    # call sees the user's home, and HOME is put back afterwards
    seen: list[str] = []
    monkeypatch.setattr(config, "_secret_cache", {})
    monkeypatch.setattr(config, "_uses_security_tool", lambda: False)
    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda service, username: seen.append(os.environ["HOME"]),
    )
    assert config.get_secret("token") is None
    assert seen == [user_home]
    assert os.environ["HOME"] == project_home
    # Likewise for the security tool, which reads the macOS keychain
    config._secret_cache.clear()
    monkeypatch.setattr(config, "_uses_security_tool", lambda: True)

    def run_security(
        args: list[str], input: str | None = None
    ) -> SimpleNamespace:
        seen.append(os.environ["HOME"])
        return SimpleNamespace(returncode=44, stdout="", stderr="")

    monkeypatch.setattr(config, "_run_security", run_security)
    assert config.get_secret("token") is None
    assert seen == [user_home, user_home]
    assert os.environ["HOME"] == project_home


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
        self.writes: list[str] = []

    def get_password(self, service, username):
        self.reads.append((service, username))
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.writes.append(username)
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.writes.append(username)
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
    # A secret can also come from the environment, and CI sets some of
    # these; the keyring is what's under test here
    for field in config.KEYRING_FIELDS:
        for prefix in ["CALKIT_", "CALKIT_TEST_"]:
            monkeypatch.delenv(f"{prefix}{field.upper()}", raising=False)
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
    # Nor does it rewrite one that didn't change: on macOS, rewriting an
    # item forgets which apps the user chose to always allow to read it
    assert fake_keyring.writes == []
    cfg.access_token = "refreshed"
    cfg.write()
    assert fake_keyring.writes == ["access_token"]
    monkeypatch.setattr(config, "_secret_cache", {})
    # Through get_secret rather than the store, since what's stored is
    # bytes on Linux
    assert config.get_secret("github_token") == "gh-secret"
    reread = config.read()
    assert reread.email == "someone@example.com"
    assert reread.github_token == "gh-secret"
    # Clearing one really does remove it
    fake_keyring.writes.clear()
    reread.github_token = None
    reread.write()
    assert (app, "github_token") not in fake_keyring.store
    assert fake_keyring.writes == ["github_token"]


def test_macos_secrets_go_through_the_security_tool(monkeypatch, tmp_path):
    import shlex
    import subprocess
    from contextlib import contextmanager

    import keyring.backends.macOS

    class MacKeyring(keyring.backends.macOS.Keyring):
        priority = 0

        def __init__(self):
            self.store: dict[str, str] = {}
            self.error: Exception | None = None

        def get_password(self, service, username):
            if self.error is not None:
                raise self.error
            return self.store.get(username)

        def set_password(self, service, username, password):
            self.store[username] = password

    # The keychain as the security tool sees it, by account: each item's
    # value and whether Calkit wrote it through the tool
    items: dict[str, tuple[str, bool]] = {}
    calls: list[list[str]] = []
    timeout_after: list[bool] = []

    def run_security(args, input=None):
        calls.append(args)
        if args == ["-i"]:
            argv = shlex.split(input)
            assert argv[:4] == ["add-generic-password", "-U", "-c", "ckit"]
            opts = dict(zip(argv[4::2], argv[5::2]))
            items[opts["-a"]] = (opts["-w"], True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        account = args[args.index("-a") + 1]
        if account not in items:
            return SimpleNamespace(returncode=44, stdout="", stderr="")
        value, ours = items[account]
        if args[0] == "delete-generic-password":
            del items[account]
            out = ""
        elif "-w" in args:
            if timeout_after:
                raise keyring.errors.KeyringLocked("dialog")
            out = value + "\n"
        else:
            crtr = '"ckit"' if ours else "<NULL>"
            out = f'attributes:\n    "crtr"<uint32>={crtr}\n'
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    ui: list[bool] = []

    @contextmanager
    def keychain_ui(allowed):
        ui.append(allowed)
        yield

    terminal = [False]
    backend = MacKeyring()
    monkeypatch.setattr(keyring.core, "_keyring_backend", backend)
    monkeypatch.setattr(config.platform, "system", lambda: "Darwin")
    (tmp_path / "security").touch()
    monkeypatch.setattr(config, "_SECURITY", str(tmp_path / "security"))
    monkeypatch.setattr(config, "_run_security", run_security)
    monkeypatch.setattr(config, "_keychain_ui", keychain_ui)
    monkeypatch.setattr(config, "_has_terminal", lambda: terminal[0])
    monkeypatch.setattr(config, "_secret_cache", {})
    assert config._uses_security_tool()
    # A new secret goes in through the tool, on stdin rather than in the
    # arguments, which other users can see
    secret = 'eyJ "quoted" \\ $not-expanded'
    config.set_secret("github_token", secret)
    assert items["github_token"] == (secret, True)
    assert not any(secret in arg for call in calls for arg in call)
    config._secret_cache.clear()
    assert config.get_secret("github_token") == secret
    assert calls[-1][-1] == "-w"
    assert backend.store == {} and ui == []
    # Calkit's own item is updated in place, keeping who may read it
    calls.clear()
    config.set_secret("github_token", "refreshed")
    assert items["github_token"] == ("refreshed", True)
    assert [c[0] for c in calls] == ["find-generic-password", "-i"]
    # An older Calkit's item is read in-process, without a dialog when
    # no one can answer it, then replaced with one the tool owns
    items["access_token"] = ("unused", False)
    backend.store["access_token"] = "old-token"
    calls.clear()
    assert config.get_secret("access_token") == "old-token"
    assert ui == [False]
    assert items["access_token"] == ("old-token", True)
    assert "delete-generic-password" in [c[0] for c in calls]
    # One this interpreter can't read without a dialog fails at once with
    # no terminal, and asks as before with one
    ui.clear()
    items["refresh_token"] = ("unused", False)
    backend.error = keyring.errors.KeyringError("OSStatus -25293")
    config._secret_cache.clear()
    with pytest.raises(keyring.errors.KeyringLocked, match="terminal"):
        config.get_secret("refresh_token")
    terminal[0] = True
    with pytest.raises(keyring.errors.KeyringError, match="-25293"):
        config.get_secret("refresh_token")
    assert ui == [False, True]
    assert items["refresh_token"] == ("unused", False)
    backend.error = None
    # A value the tool would read back as hex stays with keyring
    config.set_secret("overleaf_session", "naïve")
    assert backend.store["overleaf_session"] == "naïve"
    assert "overleaf_session" not in items
    # Deleting goes through the tool too
    config.delete_secret("github_token")
    assert "github_token" not in items
    with pytest.raises(keyring.errors.PasswordDeleteError):
        config.delete_secret("github_token")
    # A read that waits on a dialog gives up when no one can answer it
    config._secret_cache.clear()
    timeout_after.append(True)
    with pytest.raises(keyring.errors.KeyringLocked):
        config.get_secret("access_token")
    timeouts: list[float | None] = []

    def fake_run(*args, timeout=None, **kwargs):
        # As if a dialog were up
        timeouts.append(timeout)
        if timeout is not None:
            raise subprocess.TimeoutExpired(args[0], timeout)
        return SimpleNamespace(returncode=0)

    monkeypatch.undo()
    monkeypatch.setattr(config.subprocess, "run", fake_run)
    monkeypatch.setattr(config, "_has_terminal", lambda: False)
    with pytest.raises(keyring.errors.KeyringLocked, match="terminal"):
        config._run_security(["find-generic-password"])
    # With a terminal, someone may be there to answer it
    monkeypatch.setattr(config, "_has_terminal", lambda: True)
    assert config._run_security(["find-generic-password"]).returncode == 0
    assert timeouts == [config._SECURITY_TIMEOUT, None]


def test_secrets_round_trip_on_linux(fake_keyring, monkeypatch, tmp_path):
    # Linux stores the value as bytes, so what comes back out of the
    # keyring -- and out of the cache -- has to be the string either way.
    # CI is Linux and the developers' machines aren't, so it's faked here
    # rather than left to the platform the tests happen to run on.
    monkeypatch.setattr(
        config, "platform", SimpleNamespace(system=lambda: "Linux")
    )
    monkeypatch.setattr(
        config, "get_config_yaml_fpath", lambda: str(tmp_path / "config.yaml")
    )
    config.set_secret("github_token", "gh-secret")
    app = config.get_app_name()
    assert fake_keyring.store[(app, "github_token")] == b"gh-secret"
    assert config.get_secret("github_token") == "gh-secret"
    monkeypatch.setattr(config, "_secret_cache", {})
    assert config.get_secret("github_token") == "gh-secret"
    assert config.read().github_token == "gh-secret"
