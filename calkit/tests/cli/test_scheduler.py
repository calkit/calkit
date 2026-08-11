"""Tests for ``calkit.cli.scheduler``."""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import typer

import calkit
import calkit.cli.scheduler as sched
from calkit.cli.scheduler import (
    _active_job_ids,
    _build_job_command,
    _build_pbs_submit,
    _build_slurm_submit,
    _count_queued_jobs,
    _finalize_job,
    _is_active,
    _load_jobs,
    _merge_job_summary,
    _mock_enabled,
    _mock_submit,
    _parse_slurm_exit_code,
    _poll_job,
    _record_job,
    _record_job_result,
    _sanitize_pbs_job_name,
    _slurm_exit_code,
    _summary_path,
    _wait_for_output_file,
    _wait_until_done,
    run_batch,
)


def test_record_job(tmp_dir):
    # Reading before anything is recorded returns an empty mapping.
    assert _load_jobs() == {}
    # Writes accumulate by key rather than overwriting prior records.
    _record_job("a", {"job_id": "1"})
    _record_job("b", {"job_id": "2"})
    assert set(_load_jobs()) == {"a", "b"}
    # Concurrent writers each persist their own uniquely named record; SQLite
    # gives atomic per-key writes so none clobber the others.
    names = [f"job{i}" for i in range(50)]
    with ThreadPoolExecutor(max_workers=10) as executor:
        list(
            executor.map(
                lambda n: _record_job(n, {"job_id": n}),
                names,
            )
        )
    jobs = _load_jobs()
    assert set(jobs) == {"a", "b", *names}
    for n in names:
        assert jobs[n] == {"job_id": n}
    # Job records live under the always-ignored .calkit/local tree.
    assert os.path.isfile(".calkit/local/scheduler-jobs.db")


def test_sanitize_pbs_job_name():
    # Plain names are returned unchanged.
    assert _sanitize_pbs_job_name("stage") == "stage"
    # Matrix-iterated names contain ``@`` and ``,`` which qsub rejects
    # with "illegal -N value" — both get replaced with underscores.
    assert (
        _sanitize_pbs_job_name(
            "integrate-slice-halves@flat,Re10000,AoA20,14800,15000"
        )
        == "integrate-slice-halves_flat_Re10000_AoA20_14800_15000"
    )
    # Other PBS-disallowed characters (spaces, slashes, colons) are also
    # replaced so callers don't have to think about which scheduler is
    # downstream when picking stage names.
    assert _sanitize_pbs_job_name("name with spaces") == "name_with_spaces"
    assert _sanitize_pbs_job_name("a/b:c") == "a_b_c"
    # Allowed punctuation passes through.
    assert _sanitize_pbs_job_name("ok-name_1.2+3") == "ok-name_1.2+3"
    # PBS Pro caps job names at 236 characters; sanitize truncates.
    assert len(_sanitize_pbs_job_name("a" * 500)) == 236


def test_mock_enabled(monkeypatch):
    # Absent or falsey values keep the real scheduler backend.
    monkeypatch.delenv("CALKIT_MOCK_SCHEDULER", raising=False)
    assert _mock_enabled() is False
    for falsey in ("", "0", "false", "no"):
        monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", falsey)
        assert _mock_enabled() is False
    for truthy in ("1", "true", "yes"):
        monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", truthy)
        assert _mock_enabled() is True


def test_build_job_command():
    # A command is run as-is (with its args), no interpreter prefix.
    assert (
        _build_job_command("echo", ["hi"], setup_cmds=[], is_command=True)
        == "echo hi"
    )
    # Setup commands are chained before the target.
    assert (
        _build_job_command(
            "echo", ["hi"], setup_cmds=["module load foo"], is_command=True
        )
        == "module load foo && echo hi"
    )


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: mock scheduler invokes a .sh script directly; not portable to Windows",
)
def test_mock_submit_runs_job_locally(tmp_dir, monkeypatch):
    monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", "1")
    with open("job.sh", "w") as f:
        f.write('echo "hello $1" > result.txt\n')
    command = _build_job_command(
        "job.sh", ["world"], setup_cmds=[], is_command=False
    )
    job_id = "testjob"
    pid = _mock_submit(job_id=job_id, job_command=command, log_path="job.log")
    # run_batch records the job so liveness checks can find its PID.
    _record_job("sweep@x", {"job_id": job_id, "pid": pid, "kind": "slurm"})
    # The job is briefly active, then the sentinel flips it to inactive.
    deadline = time.time() + 10
    while _is_active("slurm", job_id) and time.time() < deadline:
        time.sleep(0.05)
    assert not _is_active("slurm", job_id)
    with open("result.txt") as f:
        assert f.read().strip() == "hello world"
    # Mock state stays under the always-ignored .calkit/local tree.
    assert os.path.isfile(".calkit/local/mock-scheduler/testjob.status")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: mock scheduler invokes a .sh script directly; not portable to Windows",
)
def test_wait_until_done_cancels_on_interrupt(tmp_dir, monkeypatch):
    monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", "1")
    # A long-running job stays active while we wait on it
    with open("job.sh", "w") as f:
        f.write("sleep 30\n")
    command = _build_job_command("job.sh", [], setup_cmds=[], is_command=False)
    job_id = "waitjob"
    pid = _mock_submit(job_id=job_id, job_command=command, log_path="job.log")
    _record_job("sweep@x", {"job_id": job_id, "pid": pid, "kind": "slurm"})
    assert _is_active("slurm", job_id)

    # Simulate Ctrl+C while waiting by raising from the poll sleep
    def _interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(sched.time, "sleep", _interrupt)
    with pytest.raises(typer.Exit) as exc:
        _wait_until_done("slurm", job_id, "sweep@x")
    assert exc.value.exit_code == 130
    # The interrupt should have canceled the job rather than leaving it running
    assert not _is_active("slurm", job_id)
    # The record must also be removed so the next run resubmits the job rather
    # than finding it gone from the queue with no exit status and wrongly
    # treating the canceled job as a success.
    assert "sweep@x" not in _load_jobs()


def test_build_pbs_submit():
    # qsub's ``-N`` receives a sanitized version of the name so a matrix
    # iterated stage name (with ``@`` and ``,``) submits successfully,
    # and the job script ``cd``s into ``$PBS_O_WORKDIR`` because PBS
    # jobs otherwise start in the user's ``$HOME``.
    cmd, script = _build_pbs_submit(
        name="run@a,b",
        target="echo",
        args=["hi"],
        options=[],
        setup_cmds=[],
        log_path="/tmp/run.out",
        is_command=True,
    )
    n_idx = cmd.index("-N")
    assert cmd[n_idx + 1] == "run_a_b"
    assert script == 'cd "$PBS_O_WORKDIR" && echo hi'
    # With setup commands, the cd still runs first so relative paths in
    # the setup chain (e.g. ``source .venv/bin/activate``) resolve.
    _, script_with_setup = _build_pbs_submit(
        name="run",
        target="echo",
        args=["hi"],
        options=[],
        setup_cmds=["module load foo"],
        log_path="/tmp/run.out",
        is_command=True,
    )
    assert script_with_setup == (
        'cd "$PBS_O_WORKDIR" && module load foo && echo hi'
    )


def test_build_slurm_submit_keeps_name():
    # SLURM accepts ``@`` and ``,`` in ``--job-name``, and ``sbatch``
    # defaults the working directory to the submission directory, so
    # neither name sanitization nor an explicit ``cd`` is needed.
    cmd, _ = _build_slurm_submit(
        name="run@a,b",
        target="echo",
        args=["hi"],
        options=[],
        setup_cmds=[],
        log_path="/tmp/run.out",
        is_command=True,
    )
    j_idx = cmd.index("--job-name")
    assert cmd[j_idx + 1] == "run@a,b"


def test_poll_job_pbs(monkeypatch):
    # PBS is polled in two steps: plain `qstat -f` for the active queue, then
    # `qstat -x -f` for the finished-job history view. The fake dispatches on
    # whether `-x` is present so each step can be simulated independently, the
    # way a real PBS Pro server answers them.
    active: dict = {}
    history: dict = {}

    def _fake_run(cmd, *args, **kwargs):
        outcomes = history if "-x" in cmd else active
        return subprocess.CompletedProcess(
            cmd,
            returncode=outcomes["returncode"],
            stdout=outcomes.get("stdout", ""),
            stderr=outcomes.get("stderr", ""),
        )

    monkeypatch.setattr(sched.subprocess, "run", _fake_run)
    # A running job (state R) is active with no exit code yet, and resolves
    # from the active queue alone---the history view is never consulted.
    active.update(returncode=0, stdout="    job_state = R\n", stderr="")
    history.clear()
    assert _poll_job("pbs", "1.pbs") == (True, None)
    # The reported bug: on PBS Pro a finished job leaves the active queue and
    # is shown only under `qstat -x`, where it appears as state F with its
    # Exit_status. Plain `qstat -f` errors with a message that is NOT "unknown
    # job", which used to be read as "still active" and hang the wait forever.
    active.update(
        returncode=1,
        stdout="",
        stderr="qstat: 1.pbs Job has finished, use -x to obtain historical "
        "job information\n",
    )
    history.update(
        returncode=0, stdout="    job_state = F\n    Exit_status = 0\n"
    )
    assert _poll_job("pbs", "1.pbs") == (False, 0)
    # A non-zero exit code from the finished job is reported back so the caller
    # can fail the stage.
    history.update(
        returncode=0, stdout="    job_state = F\n    Exit_status = 137\n"
    )
    assert _poll_job("pbs", "1.pbs") == (False, 137)
    # On Torque a completed job lingers in the active queue as state C with its
    # exit status, so it is done without ever needing the history view.
    active.update(
        returncode=0, stdout="    job_state = C\n    exit_status = 137\n"
    )
    history.update(returncode=1, stdout="", stderr="should not be reached\n")
    assert _poll_job("pbs", "1.pbs") == (False, 137)
    # A finished job whose record lacks an exit status yields an unknown code.
    active.update(returncode=1, stdout="", stderr="qstat: Unknown Job Id\n")
    history.update(returncode=0, stdout="    job_state = F\n")
    assert _poll_job("pbs", "1.pbs") == (False, None)
    # Once purged from history too, both views error with "unknown job": done,
    # but with no way to recover the exit status.
    active.update(
        returncode=1, stdout="", stderr="qstat: Unknown Job Id 1.pbs\n"
    )
    history.update(
        returncode=1, stdout="", stderr="qstat: Unknown Job Id 1.pbs\n"
    )
    assert _poll_job("pbs", "1.pbs") == (False, None)
    # A transient qstat failure (busy/unreachable server) on both views is NOT
    # completion: treating it as done would stop the wait while the job still
    # runs, so the job is reported active and the caller keeps polling.
    active.update(
        returncode=1, stdout="", stderr="qstat: cannot connect to server\n"
    )
    history.update(
        returncode=1, stdout="", stderr="qstat: cannot connect to server\n"
    )
    assert _poll_job("pbs", "1.pbs") == (True, None)
    # `_is_active` is a thin wrapper that drops the exit code.
    assert _is_active("pbs", "1.pbs")


def test_poll_job_slurm(monkeypatch):
    queue: dict = {}

    def _fake_run(cmd, *args, **kwargs):
        if cmd[0] == "squeue":
            return subprocess.CompletedProcess(
                cmd,
                queue["returncode"],
                stdout=queue.get("stdout", ""),
                stderr=queue.get("stderr", ""),
            )
        # Any exit-code lookup (scontrol/sacct) reports a clean completion.
        return subprocess.CompletedProcess(
            cmd, 0, stdout="JobState=COMPLETED ExitCode=0:0", stderr=""
        )

    monkeypatch.setattr(sched.subprocess, "run", _fake_run)
    # A header row plus a job row means the job is still active.
    queue.update(returncode=0, stdout="JOBID ST\n1 R\n", stderr="")
    assert _poll_job("slurm", "1") == (True, None)
    # Just the header means the job has left the queue; its exit code is read.
    queue.update(returncode=0, stdout="JOBID ST\n")
    assert _poll_job("slurm", "1") == (False, 0)
    # A non-zero squeue reporting an invalid job id means it is gone.
    queue.update(
        returncode=1,
        stdout="",
        stderr="slurm_load_jobs error: Invalid job id specified\n",
    )
    assert _poll_job("slurm", "1") == (False, 0)
    # Any other squeue failure is transient: keep waiting rather than ending
    # the wait early while the job may still be running.
    queue.update(
        returncode=1, stdout="", stderr="slurm_load_jobs error: timeout\n"
    )
    assert _poll_job("slurm", "1") == (True, None)


def test_wait_for_output_file(tmp_dir, monkeypatch):
    # Drive the clock and the file's appearance from a scripted sequence of
    # poll ticks so the test is deterministic and does not actually sleep.
    log_path = "job.out"
    ticks = {"n": 0}

    def _fake_sleep(_seconds):
        ticks["n"] += 1
        # The file appears mid-wait, then grows once, then holds steady.
        if ticks["n"] == 2:
            with open(log_path, "w") as f:
                f.write("partial")
        elif ticks["n"] == 3:
            with open(log_path, "w") as f:
                f.write("partial and then some more")

    monkeypatch.setattr(sched.time, "sleep", _fake_sleep)
    monkeypatch.setattr(sched.time, "monotonic", lambda: float(ticks["n"]))
    # Returns only after the size repeats across polls, i.e. once the file has
    # stopped growing---never while it is missing or mid-write.
    _wait_for_output_file(log_path, timeout=100)
    with open(log_path) as f:
        assert f.read() == "partial and then some more"
    # A file that never appears returns once the timeout elapses rather than
    # hanging, leaving DVC to surface the real (missing-output) state.
    os.remove(log_path)
    ticks["n"] = 0
    monkeypatch.setattr(
        sched.time, "sleep", lambda _s: ticks.__setitem__("n", ticks["n"] + 1)
    )
    _wait_for_output_file("never.out", timeout=3)
    assert not os.path.exists("never.out")


def test_parse_slurm_exit_code():
    # SLURM reports "<code>:<signal>"; a clean exit has signal 0.
    assert _parse_slurm_exit_code("0:0") == 0
    assert _parse_slurm_exit_code("1:0") == 1
    # A job killed by a signal (e.g. OOM, walltime) is a failure even when the
    # exit code is 0; the signal is folded into a conventional 128+N code.
    assert _parse_slurm_exit_code("0:9") == 137
    # Malformed values yield an unknown (None) rather than a bogus code.
    assert _parse_slurm_exit_code("oops") is None


def test_slurm_exit_code(monkeypatch):
    responses: dict = {}

    def _fake_run(cmd, *args, **kwargs):
        key = cmd[0]
        rc, out = responses.get(key, (1, ""))
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")

    monkeypatch.setattr(sched.subprocess, "run", _fake_run)
    # scontrol is preferred: a completed job reports exit 0.
    responses["scontrol"] = (0, "JobId=5 JobState=COMPLETED ExitCode=0:0")
    assert _slurm_exit_code("5") == 0
    # A failed job reports its non-zero code.
    responses["scontrol"] = (0, "JobId=5 JobState=FAILED ExitCode=2:0")
    assert _slurm_exit_code("5") == 2
    # When scontrol has dropped the job, sacct is consulted instead.
    responses["scontrol"] = (1, "")
    responses["sacct"] = (0, "FAILED|1:0\nFAILED|1:0\n")
    assert _slurm_exit_code("5") == 1
    # Neither source knows the job: the outcome is unknown.
    responses["sacct"] = (0, "")
    assert _slurm_exit_code("5") is None


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: mock scheduler invokes a .sh script directly; not portable to Windows",
)
def test_poll_job_mock_exit_code(tmp_dir, monkeypatch):
    monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", "1")
    # A failing job records its non-zero exit code, which the poll reports.
    with open("job.sh", "w") as f:
        f.write("exit 3\n")
    command = _build_job_command("job.sh", [], setup_cmds=[], is_command=False)
    job_id = "failjob"
    pid = _mock_submit(job_id=job_id, job_command=command, log_path="job.log")
    _record_job("sweep@x", {"job_id": job_id, "pid": pid, "kind": "slurm"})
    deadline = time.time() + 10
    while _poll_job("slurm", job_id)[0] and time.time() < deadline:
        time.sleep(0.05)
    assert _poll_job("slurm", job_id) == (False, 3)


def test_finalize_job(tmp_dir, monkeypatch):
    monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", "1")
    # A zero exit code finishes cleanly with no error raised.
    _finalize_job("sweep@x", "id", 0, "job.log")
    # A non-zero exit code fails the command so DVC marks the stage failed.
    with pytest.raises(typer.Exit) as exc:
        _finalize_job("sweep@x", "id", 7, "job.log")
    assert exc.value.exit_code == 1
    # An unknown exit code only warns---the stage's declared outputs decide.
    _finalize_job("sweep@x", "id", None, "job.log")


def test_record_job_result(tmp_dir):
    # Updating before anything is recorded is a no-op (nothing to attach to).
    _record_job_result("sweep@x", 0)
    assert _load_jobs() == {}
    # A definite exit code is attached to the existing record, along with a
    # completion timestamp, without disturbing the other fields.
    _record_job("sweep@x", {"job_id": "1", "deps": ["a.txt"]})
    _record_job_result("sweep@x", 7)
    info = _load_jobs()["sweep@x"]
    assert info["exit_code"] == 7
    assert info["deps"] == ["a.txt"]
    assert info["finished_at"]
    # A canceled-and-deleted job is not resurrected by a later result.
    _record_job_result("gone", 0)
    assert "gone" not in _load_jobs()


def test_active_job_ids_slurm(monkeypatch):
    calls: list[list[str]] = []
    result: dict = {}

    def _fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            result["returncode"],
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
        )

    monkeypatch.setattr(sched.subprocess, "run", _fake_run)
    # An empty set of jobs never queries the scheduler at all.
    assert _active_job_ids("slurm", []) == set()
    assert calls == []
    # Occupancy for many jobs is answered by a single `squeue --me` call, and
    # only the ids we asked about are returned.
    result.update(returncode=0, stdout="1\n3\n99\n")
    assert _active_job_ids("slurm", ["1", "2", "3"]) == {"1", "3"}
    assert len(calls) == 1
    assert calls[0][:2] == ["squeue", "--me"]
    # Array and step ids belong to the job we recorded.
    result.update(returncode=0, stdout="7_2\n8.batch\n")
    assert _active_job_ids("slurm", ["7", "8"]) == {"7", "8"}
    # If squeue fails we fall back to polling each job rather than reporting
    # an empty queue we never confirmed---which would let submissions through.
    calls.clear()
    result.update(returncode=1, stdout="", stderr="squeue: error: timeout\n")
    assert _active_job_ids("slurm", ["1", "2"]) == {"1", "2"}
    assert len(calls) > 1


def test_count_queued_jobs(tmp_dir, monkeypatch):
    active = {"1", "2", "3", "4", "5"}
    monkeypatch.setattr(
        sched,
        "_active_job_ids",
        lambda kind, job_ids: {j for j in job_ids if j in active},
    )
    _record_job("a", {"kind": "slurm", "environment": "hpc", "job_id": "1"})
    _record_job("b", {"kind": "slurm", "environment": "hpc", "job_id": "2"})
    # A job in another environment does not count against this one's limit.
    _record_job("c", {"kind": "slurm", "environment": "other", "job_id": "3"})
    assert _count_queued_jobs("hpc", exclude="none") == 2
    # Our own prior record is excluded, so a resubmission does not count
    # itself against the limit.
    assert _count_queued_jobs("hpc", exclude="a") == 1
    # A job already observed to have finished is not in the queue, even if
    # the scheduler still lists it.
    _record_job(
        "d",
        {
            "kind": "slurm",
            "environment": "hpc",
            "job_id": "4",
            "exit_code": 0,
        },
    )
    assert _count_queued_jobs("hpc", exclude="none") == 2
    # Records predating environment tracking are counted rather than ignored:
    # over-counting delays a submission, under-counting floods the queue.
    _record_job("e", {"kind": "slurm", "job_id": "5"})
    assert _count_queued_jobs("hpc", exclude="none") == 3


def test_queue_slot_waits_for_room(tmp_dir, monkeypatch):
    # No limit means no waiting and no queue queries.
    monkeypatch.setattr(
        sched,
        "_count_queued_jobs",
        lambda *a, **kw: pytest.fail("should not check occupancy"),
    )
    with sched._queue_slot("hpc", "job", None):
        pass

    # 0 is how the limit is cleared, so it means no limit rather than
    # "never submit anything".
    with sched._queue_slot("hpc", "job", 0):
        pass

    # With a limit, the slot is granted immediately when there is room. Room
    # is confirmed twice: once cheaply without the lock, then again under it.
    counts = iter([0, 0])
    monkeypatch.setattr(
        sched, "_count_queued_jobs", lambda *a, **kw: next(counts)
    )
    entered = False
    with sched._queue_slot("hpc", "job", 2):
        entered = True
    assert entered

    # A full queue blocks until a slot frees up, rather than submitting.
    counts = iter([2, 2, 1, 1])
    sleeps: list[float] = []
    monkeypatch.setattr(
        sched, "_count_queued_jobs", lambda *a, **kw: next(counts)
    )
    monkeypatch.setattr(sched.time, "sleep", sleeps.append)
    with sched._queue_slot("hpc", "job", 2):
        pass
    assert len(sleeps) == 2
    # Waiters jitter their polling so a capped sweep's worth of them does not
    # wake and query the scheduler in lockstep.
    interval = (
        sched.MOCK_QUEUE_SLOT_POLL_INTERVAL
        if sched._mock_enabled()
        else sched.QUEUE_SLOT_POLL_INTERVAL
    )
    jitter = sched.QUEUE_SLOT_POLL_JITTER
    assert all(
        interval * (1 - jitter) <= s <= interval * (1 + jitter) for s in sleeps
    )
    assert len(set(sleeps)) == len(sleeps)

    # A slot claimed by another process between the unlocked check and the
    # locked one is not double-booked; we keep waiting instead.
    counts = iter([1, 2, 1, 1])
    sleeps.clear()
    monkeypatch.setattr(
        sched, "_count_queued_jobs", lambda *a, **kw: next(counts)
    )
    with sched._queue_slot("hpc", "job", 2):
        pass
    assert len(sleeps) == 1


def test_queue_slot_rejects_bad_limits(tmp_dir, monkeypatch):
    # max_concurrent_jobs comes straight out of calkit.yaml without going
    # through the model, so a hand-edited value can be anything. A limit we
    # cannot honor must fail loudly---waiting forever on a condition that can
    # never come true would look like a hung pipeline.
    monkeypatch.setattr(
        sched,
        "_count_queued_jobs",
        lambda *a, **kw: pytest.fail("should not check occupancy"),
    )
    for bad in [-1, "2", 1.5, True]:
        with pytest.raises(typer.Exit):
            with sched._queue_slot("hpc", "job", bad):  # type: ignore
                pytest.fail("should not have been granted a slot")


def test_queue_lock_is_exclusive(tmp_dir):
    # A second holder cannot enter while the first is inside the block, which
    # is what stops concurrent submitters from claiming the same free slot.
    order: list[str] = []

    def _hold(label: str, hold_s: float) -> None:
        with sched._queue_lock():
            order.append(f"enter {label}")
            time.sleep(hold_s)
            order.append(f"exit {label}")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_hold, "a", 0.3)
        time.sleep(0.05)
        second = executor.submit(_hold, "b", 0.0)
        first.result()
        second.result()
    # Whoever went first finished before the other started.
    assert order[0].startswith("enter")
    assert order[1] == order[0].replace("enter", "exit")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="TODO: mock scheduler invokes a .sh script directly; not portable to Windows",
)
def test_job_summary(tmp_dir, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setenv("CALKIT_MOCK_SCHEDULER", "1")
    monkeypatch.setattr(
        "calkit.cli.scheduler.warn", lambda msg: warnings.append(msg)
    )
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump({"environments": {"slurm": {"kind": "slurm"}}}, f)
    batch_kwargs: dict[str, Any] = dict(
        environment="slurm",
        deps=[],
        outs=[],
        options=[],
        setup_cmds=[],
        is_command=False,
    )
    # A job that writes a valid JSON object gets its payload merged with a
    # calkit metadata block recording the observed exit code and job id.
    with open("write_summary.sh", "w") as f:
        f.write(
            'printf \'{"score": 42, "gpu": "a100"}\' > '
            '"$CALKIT_JOB_SUMMARY_PATH"\n'
        )
    run_batch(name="job1", target="write_summary.sh", **batch_kwargs)
    summary_path = ".calkit/scheduler/logs/job1.summary.json"
    with open(summary_path) as f:
        data = json.load(f)
    assert data["score"] == 42
    assert data["gpu"] == "a100"
    job_id = _load_jobs()["job1"]["job_id"]
    assert data["calkit"]["job_id"] == job_id
    assert data["calkit"]["exit_code"] == 0
    # A job that writes nothing leaves no summary file behind.
    with open("no_summary.sh", "w") as f:
        f.write("echo hello\n")
    run_batch(name="job2", target="no_summary.sh", **batch_kwargs)
    assert not os.path.exists(".calkit/scheduler/logs/job2.summary.json")
    # A reserved top-level ``calkit`` key is overwritten and warned about.
    with open("reserved_key.sh", "w") as f:
        f.write(
            'printf \'{"calkit": {"fake": 1}, "score": 1}\' > '
            '"$CALKIT_JOB_SUMMARY_PATH"\n'
        )
    warnings.clear()
    run_batch(name="job3", target="reserved_key.sh", **batch_kwargs)
    assert any("reserved" in w for w in warnings)
    with open(".calkit/scheduler/logs/job3.summary.json") as f:
        reserved_data = json.load(f)
    assert "fake" not in reserved_data["calkit"]
    assert reserved_data["calkit"]["name"] == "job3"
    # A top-level JSON list, and separately malformed JSON, are left untouched.
    for rel_path, raw in [
        ("list.summary.json", b"[1, 2, 3]\n"),
        ("bad.summary.json", b"{not json\n"),
    ]:
        warnings.clear()
        with open(rel_path, "wb") as f:
            f.write(raw)
        _merge_job_summary("ignored", rel_path)
        assert warnings
        with open(rel_path, "rb") as f:
            assert f.read() == raw
    # A custom ``--log-path`` places the summary next to that log, not under
    # ``LOGS_DIR``.
    os.makedirs("custom", exist_ok=True)
    with open("custom_log.sh", "w") as f:
        f.write(
            'printf \'{"where": "custom"}\' > "$CALKIT_JOB_SUMMARY_PATH"\n'
        )
    run_batch(
        name="job4",
        target="custom_log.sh",
        log_path="custom/run.out",
        **batch_kwargs,
    )
    assert os.path.isfile("custom/run.summary.json")
    assert not os.path.exists(".calkit/scheduler/logs/job4.summary.json")
    # A failing job still writes its summary before the failure is surfaced.
    with open("fail_summary.sh", "w") as f:
        f.write(
            'printf \'{"attempted": true}\' > "$CALKIT_JOB_SUMMARY_PATH"\n'
            "exit 7\n"
        )
    with pytest.raises(typer.Exit) as exc:
        run_batch(name="job5", target="fail_summary.sh", **batch_kwargs)
    assert exc.value.exit_code == 1
    with open(".calkit/scheduler/logs/job5.summary.json") as f:
        fail_data = json.load(f)
    assert fail_data["attempted"] is True
    assert fail_data["calkit"]["exit_code"] == 7
    # Resubmitting deletes a stale summary from a prior run before the new job
    # starts, so leftover payloads cannot be stamped with fresh metadata.
    stale_path = ".calkit/scheduler/logs/job6.summary.json"
    os.makedirs(os.path.dirname(stale_path), exist_ok=True)
    with open(stale_path, "w") as f:
        json.dump({"stale": True}, f)
    with open("no_summary.sh", "w") as f:
        f.write("echo again\n")
    run_batch(name="job6", target="no_summary.sh", **batch_kwargs)
    assert not os.path.exists(stale_path)
    # Re-merging an already-merged summary produces identical bytes.
    merged_path = ".calkit/scheduler/logs/remerge.summary.json"
    os.makedirs(os.path.dirname(merged_path), exist_ok=True)
    with open(merged_path, "w") as f:
        json.dump({"metric": 1}, f)
        f.write("\n")
    _record_job(
        "remerge",
        {
            "kind": "slurm",
            "job_id": "abc",
            "dep_md5s": {},
            "submitted_at": "2020-01-01T00:00:00",
        },
    )
    _record_job_result("remerge", 0)
    _merge_job_summary("remerge", merged_path)
    with open(merged_path, "rb") as f:
        first_bytes = f.read()
    _merge_job_summary("remerge", merged_path)
    with open(merged_path, "rb") as f:
        second_bytes = f.read()
    assert first_bytes == second_bytes
    assert _summary_path("custom/run.out") == "custom/run.summary.json"
