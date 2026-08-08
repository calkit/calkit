"""Tests for how our secrets sit in the Windows Credential Manager.

Windows is where the keyring is most constrained, and where our own
naming meets the backend's. Credential Manager holds one credential per
target name, and ``keyring``'s backend simulates multiple users per
service by moving all but the first to a ``{username}@{service}``
compound target. Our hub-scoped credentials put an ``@`` inside the
username itself (``token@https://staging.calkit.io``), so the two
schemes overlap, and one blob is capped at 2560 bytes -- 1280 characters,
since the backend writes UTF-16.

These run everywhere by faking ``win32cred``, which is the only way this
gets covered at all: CI and the machines we develop on aren't Windows.
"""

from __future__ import annotations

from types import SimpleNamespace

import keyring
import keyring.errors
import pytest
from keyring.backends import Windows as windows_backend

import calkit.config as config

# CRED_MAX_CREDENTIAL_BLOB_SIZE: 5 * 512 bytes on Windows 8 and Server
# 2012 and later. It was 512 bytes before that, which is why a single
# long JWT can be too big on an older machine.
CRED_MAX_CREDENTIAL_BLOB_SIZE = 5 * 512
LEGACY_CRED_MAX_CREDENTIAL_BLOB_SIZE = 512


class _FakeWinError(Exception):
    def __init__(self, winerror: int, funcname: str, message: str = ""):
        self.winerror = winerror
        self.funcname = funcname
        super().__init__(winerror, funcname, message)


class _FakeWin32Cred:
    """Enough of ``win32cred`` to exercise the backend's naming."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_ENTERPRISE = 3

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def CredRead(self, Type, TargetName):  # noqa: N803
        if TargetName not in self.store:
            raise _FakeWinError(1168, "CredRead", "Element not found.")
        return dict(self.store[TargetName])

    def CredWrite(self, Credential, Flags):  # noqa: N803
        blob = Credential["CredentialBlob"]
        # pywin32 writes the blob as UTF-16, so every character costs two
        # bytes of the cap. Real CredWrite fails with ERROR_INVALID_DATA.
        encoded = blob.encode("utf-16-le")
        if len(encoded) > CRED_MAX_CREDENTIAL_BLOB_SIZE:
            raise _FakeWinError(
                1783, "CredWrite", "The stub received bad data."
            )
        self.store[Credential["TargetName"]] = {
            "TargetName": Credential["TargetName"],
            "UserName": Credential["UserName"],
            "CredentialBlob": encoded,
        }

    def CredDelete(self, Type, TargetName):  # noqa: N803
        if TargetName not in self.store:
            raise _FakeWinError(1168, "CredDelete", "Element not found.")
        del self.store[TargetName]


@pytest.fixture
def windows_keyring(monkeypatch):
    """Point calkit's secret storage at a faked Credential Manager."""
    # set_secret encodes to bytes on Linux, which the Windows backend
    # would then store as the repr of a bytes object. These are Windows
    # tests, so they say so.
    monkeypatch.setattr(
        config, "platform", SimpleNamespace(system=lambda: "Windows")
    )
    fake = _FakeWin32Cred()
    monkeypatch.setattr(windows_backend, "win32cred", fake, raising=False)
    monkeypatch.setattr(
        windows_backend, "pywintypes", _FakeWinTypes, raising=False
    )
    backend = windows_backend.WinVaultKeyring()
    original = keyring.get_keyring()
    keyring.set_keyring(backend)
    monkeypatch.setattr(config, "_keyring_supported", True)
    monkeypatch.setattr(config, "_secret_cache", {})
    yield fake
    keyring.set_keyring(original)


class _FakeWinTypes:
    error = _FakeWinError


def _use_hub(monkeypatch, hub: str | None) -> None:
    monkeypatch.delenv("CALKIT_ENV", raising=False)
    if hub is None:
        monkeypatch.delenv("CALKIT_HUB", raising=False)
    else:
        monkeypatch.setenv("CALKIT_HUB", hub)


def test_hub_namespaced_usernames_round_trip(windows_keyring, monkeypatch):
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    # calkit.io's credentials are stored flat, other hubs' are namespaced
    # by URL in the username, which is where our naming meets the
    # backend's own {username}@{service} compound targets
    _use_hub(monkeypatch, "calkit.io")
    config.set_secret("token", "prod-token")
    config.set_secret("access_token", "prod-access")
    _use_hub(monkeypatch, "https://staging.calkit.io")
    config.set_secret("token", "staging-token")
    config.set_secret("access_token", "staging-access")
    _use_hub(monkeypatch, "https://hub.example.edu")
    config.set_secret("token", "self-hosted-token")
    # Shared (not hub-scoped) secrets keep their plain username whichever
    # hub is active
    config.set_secret("github_token", "gh-token")
    # Every one comes back as itself, from whichever target the backend
    # decided to file it under
    monkeypatch.setattr(config, "_secret_cache", {})
    assert config.get_secret("token") == "self-hosted-token"
    assert config.get_secret("github_token") == "gh-token"
    _use_hub(monkeypatch, "https://staging.calkit.io")
    monkeypatch.setattr(config, "_secret_cache", {})
    assert config.get_secret("token") == "staging-token"
    assert config.get_secret("access_token") == "staging-access"
    assert config.get_secret("github_token") == "gh-token"
    _use_hub(monkeypatch, "calkit.io")
    monkeypatch.setattr(config, "_secret_cache", {})
    assert config.get_secret("token") == "prod-token"
    assert config.get_secret("access_token") == "prod-access"
    # One credential per target name. The plain service target holds
    # whichever username was written last -- each write moves the one
    # already there to its compound target -- and everything else lives
    # under {username}@{service}. Our '@' in the username just nests:
    # token@https://staging.calkit.io@calkit.
    assert set(windows_keyring.store) == {
        "calkit",
        "token@calkit",
        "access_token@calkit",
        "token@https://staging.calkit.io@calkit",
        "access_token@https://staging.calkit.io@calkit",
        "token@https://hub.example.edu@calkit",
    }
    assert windows_keyring.store["calkit"]["UserName"] == "github_token"


def test_deleting_one_hubs_credential_leaves_the_others(
    windows_keyring, monkeypatch
):
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    _use_hub(monkeypatch, "calkit.io")
    config.set_secret("token", "prod-token")
    _use_hub(monkeypatch, "https://staging.calkit.io")
    config.set_secret("token", "staging-token")
    config.delete_secret("token")
    assert config.get_secret("token") is None
    _use_hub(monkeypatch, "calkit.io")
    monkeypatch.setattr(config, "_secret_cache", {})
    assert config.get_secret("token") == "prod-token"
    # Deleting one that was never stored is an error the callers handle
    _use_hub(monkeypatch, "https://staging.calkit.io")
    with pytest.raises(keyring.errors.PasswordDeleteError):
        config.delete_secret("token")


def test_credential_blob_capacity(windows_keyring, monkeypatch):
    monkeypatch.setattr(config, "_get_default_hub", lambda: None)
    _use_hub(monkeypatch, "calkit.io")
    # A JWT-sized secret fits, with less room to spare than it looks:
    # the cap is on UTF-16 bytes, so 2560 bytes is 1280 characters
    jwt = "e" + "y" * 1199
    config.set_secret("access_token", jwt)
    monkeypatch.setattr(config, "_secret_cache", {})
    assert config.get_secret("access_token") == jwt
    # Just past the limit, Credential Manager rejects the write outright
    with pytest.raises(_FakeWinError):
        config.set_secret("access_token", "e" * 1281)
    # Which is why each secret gets its own credential: all of them in
    # one JSON blob wouldn't fit under this cap, never mind the 512-byte
    # one on Windows 7 and earlier
    combined = len(
        str({k: jwt for k in config.KEYRING_FIELDS}).encode("utf-16-le")
    )
    assert combined > CRED_MAX_CREDENTIAL_BLOB_SIZE
    assert len(jwt.encode("utf-16-le")) > LEGACY_CRED_MAX_CREDENTIAL_BLOB_SIZE
