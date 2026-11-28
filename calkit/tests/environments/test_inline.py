"""Tests for ``calkit.environments.inline``."""

import os
import time

import pytest

import calkit.environments.inline as inline

BLOCK = (
    '# /// script\n# requires-python = ">=3.12"\n# dependencies = []\n# ///\n'
)


def test_get_metadata(tmp_dir):
    for text, expected in [
        (BLOCK, {"requires-python": ">=3.12", "dependencies": []}),
        (
            '"""Doc."""\n\n# /// script\n#\n# dependencies = ["six"]\n'
            "#\n# [tool.uv.sources]\n# six = { path = '../six' }\n"
            "# ///\nimport os\n",
            {
                "dependencies": ["six"],
                "tool": {"uv": {"sources": {"six": {"path": "../six"}}}},
            },
        ),
        ("import os\n", None),
        # Another kind of block, and one never closed
        ("# /// pyproject\n# x = 1\n# ///\n", None),
        ("# /// script\n# dependencies = []\nimport os\n", None),
    ]:
        with open("s.py", "w") as f:
            f.write(text)
        assert inline.get_metadata("s.py") == expected


def test_get_python_version_path(tmp_dir):
    os.makedirs("sub/scripts")
    assert inline.get_python_version_path("sub/scripts/a.py") is None
    for path in [".python-version", "sub/.python-version"]:
        with open(path, "w") as f:
            f.write("3.12\n")
        assert inline.get_python_version_path("sub/scripts/a.py") == path
    assert inline.get_python_version_path("a.py") == ".python-version"
    # From elsewhere
    os.chdir("sub")
    assert (
        inline.get_python_version_path("a.py", project_dir="..")
        == ".python-version"
    )


def test_lock(tmp_dir, monkeypatch):
    os.makedirs("scripts")
    script_path = os.path.join("scripts", "plot.py")
    with open(script_path, "w") as f:
        f.write(BLOCK + "print('hi')\n")
    lock_path = inline.lock(script_path)
    assert lock_path == script_path + ".lock"
    assert os.path.isfile(lock_path)
    assert inline.lock_is_current(script_path)
    # uv leaves a current lock as it is, so it's touched to skip next time
    os.utime(lock_path, (0, 0))
    assert not inline.lock_is_current(script_path)
    inline.lock(script_path)
    assert inline.lock_is_current(script_path)
    # Not again until the script or its .python-version changes, unless
    # forced
    calls = []

    def run(*args, **kwargs):
        calls.append(args[0])
        os.utime(lock_path)

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    with monkeypatch.context() as m:
        m.setattr(inline.subprocess, "run", run)
        inline.lock(script_path)
        assert not calls
        inline.lock(script_path, force=True)
        assert calls == [["uv", "lock", "--script", script_path]]
        future = time.time() + 10
        os.utime(script_path, (future, future))
        inline.lock(script_path)
        assert len(calls) == 2
        with open(".python-version", "w") as f:
            f.write("3.12\n")
        future += 10
        os.utime(".python-version", (future, future))
        inline.lock(script_path)
        assert len(calls) == 3
    # A script that declares nothing, no Python, or what can't be resolved
    for text, error, match in [
        ("print('hi')\n", ValueError, "no '# /// script' block"),
        (
            "# /// script\n# dependencies = []\n# ///\n",
            ValueError,
            "no 'requires-python'",
        ),
        (
            '# /// script\n# requires-python = ">=99"\n# ///\n',
            RuntimeError,
            "Failed to lock",
        ),
    ]:
        with open(script_path, "w") as f:
            f.write(text)
        with pytest.raises(error, match=match):
            inline.lock(script_path)


def test_get_stage_script_path():
    for stage, expected in [
        ({"kind": "python-script", "script_path": "a.py"}, "a.py"),
        (
            {
                "kind": "python-script",
                "script_path": "a.py",
                "environment": "_inline",
                "wdir": "sub",
            },
            os.path.join("sub", "a.py"),
        ),
        (
            {
                "kind": "python-script",
                "script_path": "a.py",
                "environment": "py1",
            },
            None,
        ),
        ({"kind": "shell-script", "script_path": "a.sh"}, None),
    ]:
        assert inline.get_stage_script_path(stage) == expected
