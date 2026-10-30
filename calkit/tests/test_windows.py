"""Tests for the ``windows`` module."""

import pytest

import calkit.windows


def test_app_control(monkeypatch: pytest.MonkeyPatch) -> None:
    import contextlib
    import sys
    import types

    # Blocks as Python, uv, and exit codes report them
    assert calkit.windows.app_control_blocked(
        "ImportError: DLL load failed while importing _sqlite3: "
        "An Application Control policy has blocked this file."
    )
    assert calkit.windows.app_control_blocked(
        "error: Querying Python at `python.exe` failed with exit status "
        "exit code: 0xc0e90002"
    )
    assert calkit.windows.app_control_blocked("exited with 3236495362")
    assert calkit.windows.app_control_blocked(returncode=0xC0E90002)
    assert calkit.windows.app_control_blocked(returncode=-1058471934)
    # Ordinary failures aren't blocks
    assert not calkit.windows.app_control_blocked(
        "ModuleNotFoundError: No module"
    )
    assert not calkit.windows.app_control_blocked("took 132364953620 ms")
    assert not calkit.windows.app_control_blocked(returncode=1)
    assert not calkit.windows.app_control_blocked()
    # Smart App Control only blocks when enforcing, according to the registry
    state: dict[str, int] = {}

    def query_value(key: object, name: str) -> tuple[int, int]:
        assert name == "VerifiedAndReputablePolicyState"
        if "value" not in state:
            raise FileNotFoundError(name)
        return state["value"], 4

    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=0,
        KEY_READ=1,
        KEY_WOW64_64KEY=2,
        OpenKey=lambda *args: contextlib.nullcontext(),
        QueryValueEx=query_value,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(sys, "platform", "win32")
    assert not calkit.windows.smart_app_control_on()
    for value, on in [(0, False), (1, True), (2, False)]:
        state["value"] = value
        assert calkit.windows.smart_app_control_on() is on
    # Never on other platforms
    monkeypatch.setattr(sys, "platform", "linux")
    assert not calkit.windows.smart_app_control_on()
