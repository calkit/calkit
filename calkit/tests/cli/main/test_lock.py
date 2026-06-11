"""Tests for DVC repo-lock handling during pipeline runs and status.

These exercise the real DVC locking machinery (no mocking of DVC) on real
Calkit projects, covering the failure modes reported in issue #942: brief
contention for DVC's repo-level lock between concurrent processes (a running
pipeline, a stage that itself runs ``calkit run``, DVC's own per-stage re-lock,
and a background ``calkit status`` poller such as the VS Code extension)
aborting the run with "Unable to acquire lock".
"""

import os
import subprocess
import sys
import time

import dvc.lock
import pytest
from dvc.lock import LockError

import calkit
import calkit.dvc
import calkit.pipeline


def _write(path: str, content: str) -> None:
    with open(path, "w") as f:
        f.write(content)


def _init_project_with_command_stage(stage_cmd: str, output: str) -> None:
    """Create a Calkit project with a single ``_system`` command stage."""
    subprocess.check_call(["calkit", "init"])
    ck_info = {
        "pipeline": {
            "stages": {
                "stage1": {
                    "kind": "command",
                    "environment": "_system",
                    "command": stage_cmd,
                    "outputs": [output],
                }
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)


# A standalone script that acquires the project's real DVC repo lock, signals
# that it holds it by creating a file, holds for a given number of seconds, then
# releases. Used to create genuine cross-process lock contention.
_LOCK_HOLDER_SCRIPT = """
import sys
import time
import calkit.dvc

ready_file, hold_seconds = sys.argv[1], float(sys.argv[2])
repo = calkit.dvc.get_dvc_repo()
with repo.lock:
    with open(ready_file, "w") as f:
        f.write("locked")
    time.sleep(hold_seconds)
"""


def _start_lock_holder(ready_file: str, hold_seconds: float):
    """Start a subprocess holding the real DVC repo lock; wait until it does."""
    _write("lock_holder.py", _LOCK_HOLDER_SCRIPT)
    proc = subprocess.Popen(
        [sys.executable, "lock_holder.py", ready_file, str(hold_seconds)]
    )
    deadline = time.monotonic() + 30
    while not os.path.exists(ready_file):
        if time.monotonic() > deadline:
            proc.kill()
            raise AssertionError("lock holder never acquired the lock")
        time.sleep(0.05)
    return proc


def test_default_dvc_lock_timeout_is_too_short(tmp_dir):
    """Baseline: DVC's 3s default makes a held lock abort acquisition.

    This is the failure the fix targets---it must genuinely fail without the
    extended timeout, otherwise the success test below proves nothing.
    """
    subprocess.check_call(["calkit", "init"])
    # Hold the lock comfortably longer than DVC's 3s default.
    proc = _start_lock_holder("ready.txt", hold_seconds=8)
    try:
        repo = calkit.dvc.get_dvc_repo()
        t0 = time.monotonic()
        with pytest.raises(LockError):
            with repo.lock:
                pass
        # It should have given up around DVC's default, not waited out the hold.
        assert time.monotonic() - t0 < 7
    finally:
        proc.wait(timeout=30)


def test_dvc_lock_timeout_waits_out_a_held_lock(tmp_dir):
    """With the extended timeout, acquisition waits out a brief lock holder.

    Holds the real repo lock for longer than DVC's 3s default in a separate
    process, then shows that under ``dvc_lock_timeout`` the acquisition waits
    and ultimately succeeds instead of raising ``LockError``.
    """
    subprocess.check_call(["calkit", "init"])
    proc = _start_lock_holder("ready.txt", hold_seconds=5)
    try:
        repo = calkit.dvc.get_dvc_repo()
        t0 = time.monotonic()
        with calkit.dvc.dvc_lock_timeout(60):
            with repo.lock:
                waited = time.monotonic() - t0
        # It waited past DVC's 3s default for the holder to release.
        assert waited > 3
    finally:
        proc.wait(timeout=30)


def test_dvc_lock_timeout_only_raises(tmp_dir):
    """The context manager never lowers an existing timeout and restores it."""
    base = dvc.lock.DEFAULT_TIMEOUT
    with calkit.dvc.dvc_lock_timeout(base + 100):
        assert dvc.lock.DEFAULT_TIMEOUT == base + 100
    assert dvc.lock.DEFAULT_TIMEOUT == base
    # A smaller request does not lower the timeout.
    with calkit.dvc.dvc_lock_timeout(base - 1):
        assert dvc.lock.DEFAULT_TIMEOUT == base
    assert dvc.lock.DEFAULT_TIMEOUT == base


def test_recursive_calkit_run_stage_succeeds(tmp_dir):
    """A stage whose command is ``calkit run`` completes without a lock error.

    DVC releases the repo lock while a stage command runs, so a nested
    ``calkit run`` competes with the parent for the lock (notably when the
    parent re-locks the instant the command finishes). The run must complete and
    produce both stages' outputs without surfacing "Unable to acquire lock".
    """
    subprocess.check_call(["calkit", "init"])
    _write(
        "make_inner.py",
        "with open('inner_out.txt', 'w') as f:\n    f.write('inner')\n",
    )
    # The outer stage runs `calkit run -s inner` (the nested call) and then
    # writes its own output. A script file avoids shell-quoting differences.
    _write(
        "run_inner.py",
        "import subprocess\n"
        "subprocess.check_call(['calkit', 'run', '-s', 'inner'])\n"
        "with open('outer_out.txt', 'w') as f:\n    f.write('outer')\n",
    )
    ck_info = {
        "pipeline": {
            "stages": {
                "inner": {
                    "kind": "command",
                    "environment": "_system",
                    "command": f"{sys.executable} make_inner.py",
                    "outputs": ["inner_out.txt"],
                },
                "outer": {
                    "kind": "command",
                    "environment": "_system",
                    "command": f"{sys.executable} run_inner.py",
                    "outputs": ["outer_out.txt"],
                },
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    proc = subprocess.run(
        ["calkit", "run"], capture_output=True, text=True, timeout=180
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "Unable to acquire lock" not in combined, combined
    assert os.path.isfile("inner_out.txt")
    assert os.path.isfile("outer_out.txt")


def test_get_status_reports_dvc_op_in_progress_during_pull(tmp_dir):
    """``get_status`` names the in-progress DVC op instead of failing.

    Reproduces the reported failure: a ``dvc pull`` (here, any process holding
    the repo lock) is in progress and ``ck status`` cannot compute pipeline
    status. Rather than a raw ``LockError`` (or a wrong "a run may be in
    progress" guess), status should state which process is running and not
    raise.
    """
    _init_project_with_command_stage(
        f"{sys.executable} make_out.py", "out.txt"
    )
    _write(
        "make_out.py",
        "with open('out.txt', 'w') as f:\n    f.write('hi')\n",
    )
    subprocess.check_call(["calkit", "run"])
    # A separate process holds the repo lock, as a real `dvc pull` would.
    proc = _start_lock_holder("ready.txt", hold_seconds=10)
    try:
        status = calkit.pipeline.get_status(
            check_environments=False,
            clean_notebooks=False,
            compile_to_dvc=False,
        )
    finally:
        proc.wait(timeout=30)
    assert status.errors
    joined = " ".join(status.errors)
    # It reports that a DVC process is in progress rather than crashing.
    assert "in progress" in joined
    # The raw, alarming failure message must not be used for a mere lock hold.
    assert "Failed to get pipeline status from DVC" not in joined
    # On POSIX we can additionally identify the holder by PID. On Windows the
    # lock file/owner can't be read while held, so the message is generic.
    if sys.platform != "win32":
        assert str(proc.pid) in joined


def test_concurrent_calkit_runs_do_not_fail_on_lock(tmp_dir):
    """Two ``calkit run`` processes for different stages must not collide.

    DVC supports running separate stages concurrently in separate processes;
    they briefly contend for the repo lock (status, dvc.lock writes, the
    per-stage re-lock). Without a generous lock timeout, one aborts with
    "Unable to acquire lock"; with it, both wait and succeed.
    """
    subprocess.check_call(["calkit", "init"])
    # Two independent stages that each take a moment, maximizing lock overlap.
    for name in ("a", "b"):
        _write(
            f"make_{name}.py",
            "import time\n"
            "time.sleep(2)\n"
            f"with open('{name}.txt', 'w') as f:\n    f.write('{name}')\n",
        )
    ck_info = {
        "pipeline": {
            "stages": {
                name: {
                    "kind": "command",
                    "environment": "_system",
                    "command": f"{sys.executable} make_{name}.py",
                    "outputs": [f"{name}.txt"],
                }
                for name in ("a", "b")
            }
        }
    }
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    procs = [
        subprocess.Popen(
            ["calkit", "run", "-s", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for name in ("a", "b")
    ]
    outputs = []
    for p in procs:
        out, _ = p.communicate(timeout=180)
        outputs.append((p.returncode, out))
    for rc, out in outputs:
        assert rc == 0, out
        assert "Unable to acquire lock" not in out, out
    assert os.path.isfile("a.txt")
    assert os.path.isfile("b.txt")
