"""Tests for ``calkit.environments.inline``."""

import os
import time

import pytest

import calkit.environments.inline as inline


def test_has_metadata(tmp_dir):
    for text, expected in [
        ("# /// script\n# dependencies = []\n# ///\n", True),
        (
            '"""Doc."""\n\n# /// script\n#\n# requires-python = ">=3.12"\n'
            "# ///\nimport os\n",
            True,
        ),
        ("import os\n", False),
        # Another kind of block, and one never closed
        ("# /// pyproject\n# x = 1\n# ///\n", False),
        ("# /// script\n# dependencies = []\nimport os\n", False),
    ]:
        with open("s.py", "w") as f:
            f.write(text)
        assert inline.has_metadata("s.py") is expected


def test_lock(tmp_dir, monkeypatch):
    os.makedirs("scripts")
    script_path = os.path.join("scripts", "plot.py")
    with open(script_path, "w") as f:
        f.write("# /// script\n# dependencies = []\n# ///\nprint('hi')\n")
    lock_path = inline.lock(script_path)
    assert lock_path == script_path + ".lock"
    assert os.path.isfile(lock_path)
    # uv leaves a current lock as it is, so it's touched to skip next time
    os.utime(lock_path, (0, 0))
    inline.lock(script_path)
    assert os.path.getmtime(lock_path) >= os.path.getmtime(script_path)
    # Not again until the script changes, unless forced
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
    # A script that declares nothing, or what can't be resolved
    with open(script_path, "w") as f:
        f.write("print('hi')\n")
    with pytest.raises(ValueError, match="no '# /// script' block"):
        inline.lock(script_path)
    with open(script_path, "w") as f:
        f.write(
            "# /// script\n"
            '# requires-python = ">=99"\n'
            "# dependencies = []\n"
            "# ///\n"
        )
    with pytest.raises(RuntimeError, match="Failed to lock"):
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
