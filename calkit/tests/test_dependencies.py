"""Tests for the ``dependencies`` module."""

from __future__ import annotations

import os
from unittest import mock

import pytest

import calkit
from calkit import dependencies as deps


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """Fixture to chdir into a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_parse_ttl():
    # Unit suffixes; case-insensitive; surrounding whitespace tolerated.
    assert deps.parse_ttl(0) == 0
    assert deps.parse_ttl("30") == 30
    assert deps.parse_ttl("30s") == 30
    assert deps.parse_ttl("5m") == 300
    assert deps.parse_ttl("2h") == 7200
    assert deps.parse_ttl("7d") == 7 * 86400
    assert deps.parse_ttl("1w") == 7 * 86400
    assert deps.parse_ttl(" 12H ") == 12 * 3600
    with pytest.raises(ValueError):
        deps.parse_ttl("soon")


def test_setup_dep_caches_by_default(tmp_dir):
    # First call probes and caches; the cache file lives under the
    # gitignored .calkit/local dir.
    dep = {
        "name": "alpha",
        "kind": "setup",
        "check_command": "true",
    }
    assert deps.check_setup_dep(dep, interactive=False) is True
    cache_file = tmp_dir / ".calkit" / "local" / "dep-checks.sqlite"
    assert cache_file.exists()
    # Second call hits the cache: a now-failing check is masked.
    dep_failing = dict(dep, check_command="false")
    # Same name, same hash -> would re-probe; flip the check to confirm
    # the *cached* entry (under its original hash) still satisfies when
    # we put the original command back.
    assert deps.check_setup_dep(dep, interactive=False) is True
    # Editing the check command invalidates the cache (hash mismatch).
    assert deps.check_setup_dep(dep_failing, interactive=False) is False
    # use_cache=False forces re-probing even when an entry exists.
    assert (
        deps.check_setup_dep(dep, interactive=False, use_cache=False) is True
    )
    # cache_ttl: 0 disables caching for this dep: no entry written.
    deps.cache_clear()
    dep_no_cache = dict(dep, name="beta", cache_ttl=0)
    assert deps.check_setup_dep(dep_no_cache, interactive=False) is True
    assert deps.cache_lookup("beta", "true") is None
    # A custom cache_ttl is honored.
    dep_short = dict(dep, name="gamma", cache_ttl="1s")
    assert deps.check_setup_dep(dep_short, interactive=False) is True
    entry = deps.cache_lookup("gamma", "true")
    assert entry is not None and entry["ttl_seconds"] == 1
    # cache_clear wipes everything.
    deps.cache_clear()
    assert deps.cache_lookup("alpha", "true") is None


def test_check_setup_dep(tmp_dir):
    # Passing check returns True without prompting.
    ok = deps.check_setup_dep(
        {"name": "alpha", "kind": "setup", "check_command": "true"},
        interactive=False,
    )
    assert ok is True
    # Non-interactive failure with setup_command -> False and the setup
    # command does NOT run (we only print the fix-it).
    sentinel = tmp_dir / "should-not-exist"
    ok = deps.check_setup_dep(
        {
            "name": "beta",
            "kind": "setup",
            "check_command": "false",
            "setup_command": f"touch {sentinel}",
        },
        interactive=False,
    )
    assert ok is False
    assert not sentinel.exists()
    # Interactive "y" runs setup, then re-verifies the check.
    marker = tmp_dir / "marker"
    check_command = f"test -f {marker}"
    setup_command = f"touch {marker}"
    with mock.patch("builtins.input", return_value="y"):
        ok = deps.check_setup_dep(
            {
                "name": "gamma",
                "kind": "setup",
                "check_command": check_command,
                "setup_command": setup_command,
            },
            interactive=True,
        )
    assert ok is True
    assert marker.exists()
    # Interactive "n" declines and returns False; setup does not run.
    not_run = tmp_dir / "not-run"
    with mock.patch("builtins.input", return_value="n"):
        ok = deps.check_setup_dep(
            {
                "name": "delta",
                "kind": "setup",
                "check_command": "false",
                "setup_command": f"touch {not_run}",
            },
            interactive=True,
        )
    assert ok is False
    assert not not_run.exists()
    # Setup that claims success but doesn't satisfy the check is caught.
    with mock.patch("builtins.input", return_value="y"):
        ok = deps.check_setup_dep(
            {
                "name": "eps",
                "kind": "setup",
                "check_command": "false",
                "setup_command": "true",
            },
            interactive=True,
        )
    assert ok is False
    # Missing check_command is a configuration error.
    with pytest.raises(ValueError, match="check_command"):
        deps.check_setup_dep(
            {"name": "zeta", "kind": "setup"}, interactive=False
        )


def test_prompt_and_store_env_var(tmp_dir, monkeypatch):
    # User-entered value wins over default and is persisted to .env +
    # exported on os.environ so subsequent code sees it without a reload.
    monkeypatch.delenv("MY_VAR", raising=False)
    with mock.patch("builtins.input", return_value="abc123"):
        value = deps.prompt_and_store_env_var("MY_VAR", default="zzz")
    assert value == "abc123"
    assert os.environ["MY_VAR"] == "abc123"
    env_text = (tmp_dir / ".env").read_text()
    assert "MY_VAR" in env_text and "abc123" in env_text
    # Empty input falls back to the default.
    monkeypatch.delenv("OTHER_VAR", raising=False)
    with mock.patch("builtins.input", return_value=""):
        value = deps.prompt_and_store_env_var("OTHER_VAR", default="fallback")
    assert value == "fallback"
    assert os.environ["OTHER_VAR"] == "fallback"
    # No default + empty input returns None (caller decides what to do).
    monkeypatch.delenv("EMPTY_VAR", raising=False)
    with mock.patch("builtins.input", return_value=""):
        assert deps.prompt_and_store_env_var("EMPTY_VAR") is None
    # EOF (e.g., non-interactive stdin closed mid-prompt) returns None.
    monkeypatch.delenv("EOF_VAR", raising=False)
    with mock.patch("builtins.input", side_effect=EOFError):
        assert deps.prompt_and_store_env_var("EOF_VAR", default="d") is None
    # .env is appended to .gitignore so secrets stay out of git.
    assert ".env" in (tmp_dir / ".gitignore").read_text()


def test_check_system_deps_env_var_interactive(tmp_dir, monkeypatch):
    # On a TTY, a missing env-var dep gets prompted and stored instead of
    # raising -- this is what makes ``calkit run`` work on a fresh clone.
    monkeypatch.delenv("DB_URL", raising=False)
    ck_info = {
        "dependencies": [
            {"name": "DB_URL", "kind": "env-var", "default": "postgres://x"},
        ]
    }
    with mock.patch("builtins.input", return_value=""):
        calkit.check_system_deps(ck_info=ck_info, interactive=True)
    assert os.environ["DB_URL"] == "postgres://x"
    # Non-interactive: still raises so CI gets a clear error.
    monkeypatch.delenv("MISSING_VAR", raising=False)
    ck_info2 = {"dependencies": [{"name": "MISSING_VAR", "kind": "env-var"}]}
    with pytest.raises(ValueError, match="MISSING_VAR"):
        calkit.check_system_deps(ck_info=ck_info2, interactive=False)


def test_setup_dep_name_is_optional(tmp_dir):
    # Real-world setup deps often have a long description and no name;
    # a synthesized ``setup-<hash>`` name keeps error messages stable
    # without forcing users to invent a label.
    ck_info = {
        "dependencies": [
            {
                "kind": "setup",
                "check_command": "true",
                "setup_command": "echo ok",
                "description": "Auth the GitHub CLI.",
            },
        ]
    }
    calkit.check_system_deps(ck_info=ck_info, interactive=False)
    # And a failing nameless dep surfaces the generated name in the error.
    ck_info["dependencies"][0]["check_command"] = "false"
    with pytest.raises(ValueError, match="setup-"):
        calkit.check_system_deps(ck_info=ck_info, interactive=False)


def test_check_calkit_version(monkeypatch):
    # Bare version is interpreted as ``==``; a passing spec returns None.
    monkeypatch.setattr(calkit, "__version__", "0.38.0")
    assert deps.check_calkit_version("0.38.0") is None
    assert deps.check_calkit_version(">=0.38") is None
    assert deps.check_calkit_version(">=0.30,<1.0") is None
    # A failing spec raises with a fix-it message naming --use-version
    # and 'calkit upgrade'.
    monkeypatch.setattr(calkit, "__version__", "0.36.0")
    with pytest.raises(ValueError) as exc:
        deps.check_calkit_version(">=0.38")
    msg = str(exc.value)
    assert "calkit>=0.38" in msg
    assert "0.36.0" in msg
    assert "--use-version 0.38" in msg
    assert "calkit upgrade" in msg
    # A garbage spec is a configuration error.
    with pytest.raises(ValueError, match="Invalid calkit version spec"):
        deps.check_calkit_version("not-a-spec!!")
    # End-to-end through the ``- calkit>=0.38`` string form in calkit.yaml.
    monkeypatch.setattr(calkit, "__version__", "0.36.0")
    ck_info = {"dependencies": ["calkit>=0.38"]}
    with pytest.raises(ValueError, match="--use-version"):
        calkit.check_system_deps(ck_info=ck_info, interactive=False)
    # And with the flat-dict form using ``version_spec``.
    ck_info_flat = {
        "dependencies": [
            {"name": "calkit", "kind": "app", "version_spec": ">=0.38"}
        ]
    }
    with pytest.raises(ValueError, match="--use-version"):
        calkit.check_system_deps(ck_info=ck_info_flat, interactive=False)
    # When the version satisfies the spec, the run is allowed through.
    monkeypatch.setattr(calkit, "__version__", "0.38.0")
    calkit.check_system_deps(ck_info=ck_info, interactive=False)


def test_format_uvx_from():
    # Bare versions become ``calkit-python@<v>`` (uv's exact-pin form);
    # PEP 440 specifiers are appended as-is.
    assert deps._format_uvx_from("0.38") == "calkit-python@0.38"
    assert deps._format_uvx_from("0.38.0") == "calkit-python@0.38.0"
    assert deps._format_uvx_from(">=0.38") == "calkit-python>=0.38"
    assert deps._format_uvx_from("==0.38") == "calkit-python==0.38"


def test_check_system_deps_setup_kind(tmp_dir):
    # End-to-end through the top-level entry point. The legacy and flat
    # dict shapes both flow through ``_normalize_dep`` and reach the
    # ``setup`` branch.
    ck_info = {
        "dependencies": [
            "git",
            {
                "name": "auth-thing",
                "kind": "setup",
                "check_command": "true",
            },
        ]
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    calkit.check_system_deps(ck_info=ck_info, interactive=False)
    # A failing check with no interactive prompt raises a clear error.
    ck_info["dependencies"][1]["check_command"] = "false"
    with pytest.raises(ValueError, match="auth-thing"):
        calkit.check_system_deps(ck_info=ck_info, interactive=False)
