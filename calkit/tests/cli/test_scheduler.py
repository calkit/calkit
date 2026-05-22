"""Tests for ``calkit.cli.scheduler``."""

import os
import time
from concurrent.futures import ThreadPoolExecutor

from calkit.cli.scheduler import (
    _build_job_command,
    _build_pbs_submit,
    _build_slurm_submit,
    _is_active,
    _load_jobs,
    _mock_enabled,
    _mock_submit,
    _record_job,
    _sanitize_pbs_job_name,
)


def test_record_job(tmp_dir):
    # Sequential writes merge rather than overwrite the whole file.
    _record_job("a", {"job_id": "1"})
    _record_job("b", {"job_id": "2"})
    assert set(_load_jobs()) == {"a", "b"}
    # Concurrent writers each persist their own uniquely named record; the
    # lock + reload-merge prevents a slow writer from clobbering others.
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
    # The lock file is kept out of version control.
    with open(".calkit/scheduler/.gitignore") as f:
        ignored = f.read().splitlines()
    assert "jobs.json" in ignored
    assert "jobs.lock" in ignored


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
