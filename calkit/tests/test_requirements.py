"""Tests for the ``requirements`` module."""

from __future__ import annotations

import os
from unittest import mock

import pytest

import calkit
from calkit import requirements as reqs


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """Fixture to chdir into a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_parse_ttl():
    # Unit suffixes; case-insensitive; surrounding whitespace tolerated.
    assert reqs.parse_ttl(0) == 0
    assert reqs.parse_ttl("30") == 30
    assert reqs.parse_ttl("30s") == 30
    assert reqs.parse_ttl("5m") == 300
    assert reqs.parse_ttl("2h") == 7200
    assert reqs.parse_ttl("7d") == 7 * 86400
    assert reqs.parse_ttl("1w") == 7 * 86400
    assert reqs.parse_ttl(" 12H ") == 12 * 3600
    with pytest.raises(ValueError):
        reqs.parse_ttl("soon")


def test_setup_dep_caches_by_default(tmp_dir):
    # First call probes and caches; the cache file lives under the
    # gitignored .calkit/local dir.
    req = {
        "name": "alpha",
        "kind": "setup",
        "check_command": "true",
    }
    assert reqs.check_setup_dep(req, interactive=False) is True
    cache_file = tmp_dir / ".calkit" / "local" / "dep-checks.sqlite"
    assert cache_file.exists()
    # Second call hits the cache: a now-failing check is masked.
    req_failing = dict(req, check_command="false")
    # Same name, same hash -> would re-probe; flip the check to confirm
    # the *cached* entry (under its original hash) still satisfies when
    # we put the original command back.
    assert reqs.check_setup_dep(req, interactive=False) is True
    # Editing the check command invalidates the cache (hash mismatch).
    assert reqs.check_setup_dep(req_failing, interactive=False) is False
    # use_cache=False forces re-probing even when an entry exists.
    assert (
        reqs.check_setup_dep(req, interactive=False, use_cache=False) is True
    )
    # cache_ttl: 0 disables caching for this dep: no entry written.
    reqs.cache_clear()
    req_no_cache = dict(req, name="beta", cache_ttl=0)
    assert reqs.check_setup_dep(req_no_cache, interactive=False) is True
    assert reqs.cache_lookup("beta", "true") is None
    # A custom cache_ttl is honored.
    req_short = dict(req, name="gamma", cache_ttl="1s")
    assert reqs.check_setup_dep(req_short, interactive=False) is True
    entry = reqs.cache_lookup("gamma", "true")
    assert entry is not None and entry["ttl_seconds"] == 1
    # cache_clear wipes everything.
    reqs.cache_clear()
    assert reqs.cache_lookup("alpha", "true") is None


def test_check_setup_dep(tmp_dir):
    # Passing check returns True without prompting.
    ok = reqs.check_setup_dep(
        {"name": "alpha", "kind": "setup", "check_command": "true"},
        interactive=False,
    )
    assert ok is True
    # Non-interactive failure with setup_command -> False and the setup
    # command does NOT run (we only print the fix-it).
    sentinel = tmp_dir / "should-not-exist"
    ok = reqs.check_setup_dep(
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
        ok = reqs.check_setup_dep(
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
        ok = reqs.check_setup_dep(
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
        ok = reqs.check_setup_dep(
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
        reqs.check_setup_dep(
            {"name": "zeta", "kind": "setup"}, interactive=False
        )


def test_prompt_and_store_env_var(tmp_dir, monkeypatch):
    # User-entered value wins over default and is persisted to .env +
    # exported on os.environ so subsequent code sees it without a reload.
    monkeypatch.delenv("MY_VAR", raising=False)
    with mock.patch("builtins.input", return_value="abc123"):
        value = reqs.prompt_and_store_env_var("MY_VAR", default="zzz")
    assert value == "abc123"
    assert os.environ["MY_VAR"] == "abc123"
    env_text = (tmp_dir / ".env").read_text()
    assert "MY_VAR" in env_text and "abc123" in env_text
    # Empty input falls back to the default.
    monkeypatch.delenv("OTHER_VAR", raising=False)
    with mock.patch("builtins.input", return_value=""):
        value = reqs.prompt_and_store_env_var("OTHER_VAR", default="fallback")
    assert value == "fallback"
    assert os.environ["OTHER_VAR"] == "fallback"
    # No default + empty input returns None (caller decides what to do).
    monkeypatch.delenv("EMPTY_VAR", raising=False)
    with mock.patch("builtins.input", return_value=""):
        assert reqs.prompt_and_store_env_var("EMPTY_VAR") is None
    # EOF (e.g., non-interactive stdin closed mid-prompt) returns None.
    monkeypatch.delenv("EOF_VAR", raising=False)
    with mock.patch("builtins.input", side_effect=EOFError):
        assert reqs.prompt_and_store_env_var("EOF_VAR", default="d") is None
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
    assert reqs.check_calkit_version("0.38.0") is None
    assert reqs.check_calkit_version(">=0.38") is None
    assert reqs.check_calkit_version(">=0.30,<1.0") is None
    # A failing spec raises with a fix-it message naming --use-version
    # and 'calkit upgrade'.
    monkeypatch.setattr(calkit, "__version__", "0.36.0")
    with pytest.raises(ValueError) as exc:
        reqs.check_calkit_version(">=0.38")
    msg = str(exc.value)
    assert "calkit>=0.38" in msg
    assert "0.36.0" in msg
    assert "--use-version 0.38" in msg
    assert "calkit upgrade" in msg
    # A garbage spec is a configuration error.
    with pytest.raises(ValueError, match="Invalid calkit version spec"):
        reqs.check_calkit_version("not-a-spec!!")
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
    assert reqs._format_uvx_from("0.38") == "calkit-python@0.38"
    assert reqs._format_uvx_from("0.38.0") == "calkit-python@0.38.0"
    assert reqs._format_uvx_from(">=0.38") == "calkit-python>=0.38"
    assert reqs._format_uvx_from("==0.38") == "calkit-python==0.38"


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


def test_resolve_env_var_deps(tmp_dir, monkeypatch):
    from calkit.requirements import resolve_env_var_deps

    ck_info = {
        "dependencies": [
            {"kind": "env-var", "name": "CK_A"},
            {"kind": "env-var", "name": "CK_B", "default": "fallback"},
            "git",
        ]
    }
    monkeypatch.delenv("CK_A", raising=False)
    monkeypatch.delenv("CK_B", raising=False)
    # Nobody to answer: report what's missing rather than prompting into a
    # void, so a caller can decide whether that's fatal
    assert resolve_env_var_deps(ck_info, interactive=False) == ["CK_A", "CK_B"]
    # On a terminal, ask. A declared default is offered, and an empty answer
    # takes it.
    answers = iter(["from-user", ""])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert resolve_env_var_deps(ck_info, interactive=True) == []
    assert os.environ["CK_A"] == "from-user"
    assert os.environ["CK_B"] == "fallback"
    # Stored, so the question isn't asked twice
    with open(".env") as f:
        stored = f.read()
    assert "CK_A" in stored and "CK_B" in stored
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("asked"))
    assert resolve_env_var_deps(ck_info, interactive=True) == []
    # Declining leaves it missing rather than storing an empty value
    monkeypatch.delenv("CK_A", raising=False)

    def eof(*a):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert resolve_env_var_deps(ck_info, interactive=True) == ["CK_A"]


def test_prompt_for_env_var_req(tmp_dir, monkeypatch, capsys):
    monkeypatch.delenv("CK_TOKEN", raising=False)
    req = {
        "kind": "env-var",
        "name": "CK_TOKEN",
        "setup_command": "echo got > got.txt",
        "description": "A token for the API.\n",
    }
    # Agreeing runs the setup command, then asks for what it gave
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    answers = iter(["", "tok-1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert reqs.prompt_for_env_var_req(req) == "tok-1"
    assert (tmp_dir / "got.txt").exists()
    assert os.environ["CK_TOKEN"] == "tok-1"
    assert "A token for the API." in capsys.readouterr().out
    # Declining skips straight to asking
    (tmp_dir / "got.txt").unlink()
    answers = iter(["n", "tok-2"])
    assert reqs.prompt_for_env_var_req(req) == "tok-2"
    assert not (tmp_dir / "got.txt").exists()
    # A failing setup command still lets a value be entered
    answers = iter(["y", "tok-3"])
    assert reqs.prompt_for_env_var_req(dict(req, setup_command="false")) == (
        "tok-3"
    )
    assert "exited 1" in capsys.readouterr().out
    # Without a terminal, the command is only shown, so piped input is
    # taken as the value
    monkeypatch.setattr(calkit.core, "is_tty", lambda: False)
    answers = iter(["y"])
    assert reqs.prompt_for_env_var_req(req) == "y"
    assert not (tmp_dir / "got.txt").exists()
    assert "To get a value, run:  echo got" in capsys.readouterr().out
    # Without a terminal, the error says how to get a value
    monkeypatch.delenv("CK_TOKEN", raising=False)
    with pytest.raises(ValueError, match="get a value with 'echo"):
        calkit.check_requirements(
            requirements=[req], interactive=False, described_as="here"
        )


def test_get_path_env_var_candidates(tmp_dir, monkeypatch):
    for version in ("2.9", "2.10", "1.0"):
        folder = tmp_dir / f"App_{version}"
        folder.mkdir()
        (folder / "app.exe").touch()
    (tmp_dir / "other.exe").touch()
    monkeypatch.setenv("CK_APPS", str(tmp_dir))
    monkeypatch.setenv("HOME", str(tmp_dir))
    monkeypatch.setenv("USERPROFILE", str(tmp_dir))

    def names(**req):
        return [
            os.path.relpath(p, tmp_dir).replace(os.sep, "/")
            for p in reqs.get_path_env_var_candidates(req)
        ]

    # Highest version first, numerically rather than as text
    assert names(search_paths="App_*/app.exe") == [
        "App_2.10/app.exe",
        "App_2.9/app.exe",
        "App_1.0/app.exe",
    ]
    # Including where one version is the start of another
    for version in ("2.9.3", "2.9.10"):
        (tmp_dir / f"App_{version}").mkdir()
        (tmp_dir / f"App_{version}" / "app.exe").touch()
    assert names(search_paths="App_2.9*/app.exe") == [
        "App_2.9.10/app.exe",
        "App_2.9.3/app.exe",
        "App_2.9/app.exe",
    ]
    # Patterns keep their order, may use ~ and env vars, and don't repeat
    assert names(
        search_paths=[
            "other.exe",
            "~/App_1*/app.exe",
            "$CK_APPS/App_1*/app.exe",
        ]
    ) == ["other.exe", "App_1.0/app.exe"]
    # A default is tried first, and what doesn't exist isn't suggested
    assert names(default="other.exe", search_paths="App_2.9/app.exe") == [
        "other.exe",
        "App_2.9/app.exe",
    ]
    assert names(default="nope.exe", search_paths=["nope/*"]) == []
    assert names() == []
    # A default is a path, so one with glob characters in it is still found
    (tmp_dir / "[x]").mkdir()
    (tmp_dir / "[x]" / "app.exe").touch()
    assert names(default="[x]/app.exe") == ["[x]/app.exe"]


def test_prompt_for_path_env_var_req(tmp_dir, monkeypatch, capsys):
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)

    def ask(req, *answers):
        monkeypatch.delenv("CK_APP", raising=False)
        replies = iter(answers)
        monkeypatch.setattr("builtins.input", lambda *a: next(replies))
        return reqs.prompt_for_path_env_var_req(req)

    for version in ("1", "2"):
        (tmp_dir / f"app{version}.exe").touch()
    req = {
        "kind": "path-env-var",
        "name": "CK_APP",
        "description": "Path to the app.",
        "notes": "Get a license first.",
        "search_paths": "app*.exe",
    }
    # Enter takes the first thing found, and it's saved for the next run
    value = ask(req, "")
    assert value == str(tmp_dir / "app2.exe")
    assert os.environ["CK_APP"] == value
    assert "app2.exe" in (tmp_dir / ".env").read_text()
    assert ".env" in (tmp_dir / ".gitignore").read_text()
    out = capsys.readouterr().out
    assert "Path to the app." in out and "Get a license first." in out
    # One can be selected by number
    assert ask(req, "2") == str(tmp_dir / "app1.exe")
    # A pasted path, with the quotes Windows' 'Copy as path' adds
    (tmp_dir / "elsewhere.exe").touch()
    assert ask(req, f'"{tmp_dir / "elsewhere.exe"}"') == str(
        tmp_dir / "elsewhere.exe"
    )
    # A path that doesn't exist or a number out of range is asked again
    assert ask(req, "nope.exe", "9", "²", "1") == str(tmp_dir / "app2.exe")
    assert "doesn't exist" in capsys.readouterr().out
    # Skipping leaves it unset, for those without the app
    assert ask(req, "skip") is None
    assert "CK_APP" not in os.environ
    with mock.patch("builtins.input", side_effect=EOFError):
        assert reqs.prompt_for_path_env_var_req(req) is None
    # Installing it while asked, then pressing Enter, finds it
    later = dict(req, search_paths="later/*.exe")

    def install_then_answer(*args):
        (tmp_dir / "later").mkdir()
        (tmp_dir / "later" / "app.exe").touch()
        return ""

    answers = iter([install_then_answer, lambda *a: ""])
    monkeypatch.delenv("CK_APP", raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: next(answers)(*a))
    assert reqs.prompt_for_path_env_var_req(later) == str(
        tmp_dir / "later" / "app.exe"
    )
    assert "Install it" not in capsys.readouterr().out
    # A setup command is only offered when nothing was found
    setup = dict(
        req,
        search_paths="made/*.exe",
        setup_command=(
            "python -c \"import os; os.mkdir('made'); "
            "open('made/app.exe', 'w').close()\""
        ),
    )
    assert ask(setup, "y", "") == str(tmp_dir / "made" / "app.exe")
    assert ask(setup, "") == str(tmp_dir / "made" / "app.exe")
    # Without a terminal, it's only shown, so piped input is the path
    monkeypatch.setattr(calkit.core, "is_tty", lambda: False)
    other = dict(
        setup, search_paths="other/*.exe", setup_command="mkdir other"
    )
    assert ask(other, str(tmp_dir / "app1.exe")) == str(tmp_dir / "app1.exe")
    assert not (tmp_dir / "other").exists()
    assert "To install it, run:  mkdir other" in capsys.readouterr().out
    monkeypatch.setattr(calkit.core, "is_tty", lambda: True)
    # Without a search there's nothing to retry, so Enter gives up
    assert ask({"kind": "path-env-var", "name": "CK_APP"}, "") is None
    # A bad value set outside .env would come back, so that's said
    capsys.readouterr()
    monkeypatch.setenv("CK_APP", str(tmp_dir / "moved.exe"))
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert reqs.prompt_for_path_env_var_req(req) == str(tmp_dir / "app2.exe")
    out = capsys.readouterr().out
    assert "doesn't exist" in out and "also set elsewhere" in out
    # While one that only .env holds is simply replaced
    dotenv_value = str(tmp_dir / "gone.exe")
    (tmp_dir / ".env").write_text(f"CK_APP='{dotenv_value}'\n")
    monkeypatch.setenv("CK_APP", dotenv_value)
    assert reqs.prompt_for_path_env_var_req(req) == str(tmp_dir / "app2.exe")
    assert "also set elsewhere" not in capsys.readouterr().out


def test_check_path_env_var_req(tmp_dir, monkeypatch):
    app = tmp_dir / "app.exe"
    app.touch()
    req = {
        "kind": "path-env-var",
        "name": "CK_APP",
        "search_paths": "app*.exe",
    }
    monkeypatch.delenv("CK_APP", raising=False)
    # Without a terminal, the error gives the command to fix it
    with pytest.raises(
        ValueError, match="found .*app.exe.*calkit set-env-var"
    ):
        calkit.check_requirements(requirements=[req], interactive=False)
    assert not (tmp_dir / ".env").exists()
    # With nothing found, it still says how to set it
    with pytest.raises(ValueError, match="not found.*<path>"):
        calkit.check_requirements(
            requirements=[dict(req, search_paths="nope/*")], interactive=False
        )
    # On a terminal it's asked for
    with mock.patch("builtins.input", return_value=""):
        calkit.check_requirements(requirements=[req], interactive=True)
    assert os.environ["CK_APP"] == str(app)
    # And is then met without asking
    with mock.patch("builtins.input", side_effect=AssertionError):
        calkit.check_requirements(requirements=[req], interactive=True)
    # Being set isn't enough if the path has since gone away
    (tmp_dir / ".env").unlink()
    monkeypatch.setenv("CK_APP", str(tmp_dir / "moved.exe"))
    with pytest.raises(ValueError, match="doesn't exist.*moved.exe"):
        calkit.check_requirements(requirements=[req], interactive=False)
    # The fix the error gives works even when the bad value is the shell's,
    # since .env doesn't override it
    import dotenv

    dotenv.set_key(".env", "CK_APP", str(app))
    calkit.check_requirements(requirements=[req], interactive=False)
    assert os.environ["CK_APP"] == str(app)
    # Quotes that are part of the value are pointed out
    monkeypatch.setenv("CK_APP", f'"{tmp_dir / "moved.exe"}"')
    (tmp_dir / ".env").unlink()
    with pytest.raises(ValueError, match="quotes are part of the value"):
        calkit.check_requirements(requirements=[req], interactive=False)
    # Skipping leaves the requirement unmet
    monkeypatch.delenv("CK_APP")
    with mock.patch("builtins.input", return_value="skip"):
        with pytest.raises(ValueError, match="CK_APP"):
            calkit.check_requirements(requirements=[req], interactive=True)
    # Status-style resolution reports it, and accepts one that's met
    ck_info = {"requirements": [req]}
    assert reqs.resolve_env_var_deps(ck_info, interactive=False) == ["CK_APP"]
    monkeypatch.setenv("CK_APP", str(app))
    assert reqs.resolve_env_var_deps(ck_info, interactive=False) == []
    # An empty search is no search, whatever the kind
    calkit.check_requirements(
        requirements=[
            {"kind": "env-var", "name": "CK_APP", "search_paths": None}
        ],
        interactive=False,
    )
    # Only this kind can search
    for kind in ("env-var", "app"):
        with pytest.raises(ValueError, match="only a 'path-env-var'"):
            calkit.check_requirements(
                requirements=[
                    {"kind": kind, "name": "X", "search_paths": "*"}
                ],
                interactive=False,
            )
    with pytest.raises(ValueError, match="only a 'path-env-var'"):
        calkit.check_requirements(
            requirements=[{"X": {"kind": "env-var", "search_paths": "*"}}],
            interactive=False,
        )


def test_resolve_path_env_var(tmp_dir, monkeypatch, capsys):
    import dotenv

    app = tmp_dir / "app.exe"
    app.touch()
    monkeypatch.delenv("CK_APP", raising=False)
    # Unset, and nothing saved
    assert reqs.resolve_path_env_var("CK_APP") is None
    # Set to a path that exists
    monkeypatch.setenv("CK_APP", str(app))
    assert reqs.resolve_path_env_var("CK_APP") == str(app)
    assert capsys.readouterr().err == ""
    # Set elsewhere to a path that doesn't exist, with a good one saved
    monkeypatch.setenv("CK_APP", str(tmp_dir / "moved.exe"))
    dotenv.set_key(".env", "CK_APP", str(app))
    assert reqs.resolve_path_env_var("CK_APP") == str(app)
    assert os.environ["CK_APP"] == str(app)
    assert "moved.exe" in capsys.readouterr().err
    # A subproject's .env is what it saves to, so a stale value from the
    # parent's doesn't win over it
    sub = tmp_dir / "sub"
    sub.mkdir()
    monkeypatch.setenv("CK_APP", str(tmp_dir / "moved.exe"))
    dotenv.set_key(str(sub / ".env"), "CK_APP", str(app))
    monkeypatch.chdir(sub)
    assert reqs.resolve_path_env_var("CK_APP") == str(app)
    # A saved path that doesn't exist either is no help
    dotenv.set_key(".env", "CK_APP", str(tmp_dir / "gone.exe"))
    monkeypatch.setenv("CK_APP", str(tmp_dir / "moved.exe"))
    assert reqs.resolve_path_env_var("CK_APP") is None


def test_check_aws_credentials_req(tmp_dir, monkeypatch):
    import json
    import shutil
    import subprocess

    calls: list[list[str]] = []
    state = {"account": "012345678901", "fail": False, "sso": ""}

    def fake_run(cmd, **kwargs):
        if isinstance(cmd, str):
            # The setup command, run through the shell
            calls.append([cmd])
            state["fail"] = False
            return subprocess.CompletedProcess(cmd, 0, "", "")
        calls.append(cmd)
        if cmd[1] == "configure":
            return subprocess.CompletedProcess(cmd, 0, state["sso"], "")
        if state["fail"]:
            return subprocess.CompletedProcess(cmd, 255, "", "expired")
        out = json.dumps({"Account": state["account"]})
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(reqs.subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/aws")
    req = calkit.core._normalize_requirement(
        {"kind": "aws-credentials", "account_id": "012345678901"}
    )
    assert req["name"] == "aws-credentials-012345678901"
    # Valid credentials for the right account pass, and are cached
    assert reqs.check_aws_credentials_req(req, interactive=False)
    assert calls[-1][:3] == ["aws", "sts", "get-caller-identity"]
    calls.clear()
    state["fail"] = True
    assert reqs.check_aws_credentials_req(req, interactive=False)
    assert calls == []
    # Credentials selected another way aren't vouched for by the cache
    monkeypatch.setenv("AWS_PROFILE", "other")
    assert not reqs.check_aws_credentials_req(req, interactive=False)
    monkeypatch.delenv("AWS_PROFILE")
    # Without the cache, expired credentials fail, offering 'aws configure'
    assert not reqs.check_aws_credentials_req(
        req, interactive=False, use_cache=False
    )
    assert calls[-1][:3] == ["aws", "configure", "get"]
    # A profile set up for SSO is offered 'aws sso login', and on a
    # terminal it's run and the credentials checked again
    state["sso"] = "my-sso"
    calls.clear()
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    with_profile = dict(req, profile="dev")
    assert reqs.check_aws_credentials_req(
        with_profile, interactive=True, use_cache=False
    )
    assert ["aws sso login --profile dev"] in calls
    assert calls[-1][-2:] == ["--profile", "dev"]
    # Credentials for another account don't satisfy it
    state["account"] = "999999999999"
    assert not reqs.check_aws_credentials_req(
        req, interactive=False, use_cache=False
    )
    # A declared setup command wins over the default
    calls.clear()
    assert not reqs.check_aws_credentials_req(
        dict(req, setup_command="./login.sh"),
        interactive=False,
        use_cache=False,
    )
    assert not any(c[:2] == ["aws", "configure"] for c in calls)
    # Through the top-level check, a failure names the requirement
    with pytest.raises(ValueError, match="aws-credentials-012345678901"):
        calkit.check_requirements(
            requirements=[
                {"kind": "aws-credentials", "account_id": "012345678901"}
            ],
            interactive=False,
            use_cache=False,
        )
    # Without the AWS CLI, that's what's reported
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="AWS CLI"):
        reqs.check_aws_credentials_req(req, interactive=False)
