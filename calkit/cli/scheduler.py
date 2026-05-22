"""CLI for working with job schedulers (SLURM, PBS).

This module exposes a single typer app that dispatches to the right
underlying scheduler binary (``sbatch``/``squeue``/``scancel`` for SLURM,
``qsub``/``qstat``/``qdel`` for PBS) based on the environment kind.
Registered as ``scheduler|sch``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import time
import uuid

import typer
from filelock import FileLock
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error

scheduler_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)

SCHEDULER_KINDS = ("slurm", "pbs")
_BINARIES = {
    "slurm": {"submit": "sbatch", "query": "squeue", "cancel": "scancel"},
    "pbs": {"submit": "qsub", "query": "qstat", "cancel": "qdel"},
}

SCHEDULER_DIR = os.path.join(".calkit", "scheduler")
JOBS_PATH = os.path.join(SCHEDULER_DIR, "jobs.json")
JOBS_LOCK_PATH = os.path.join(SCHEDULER_DIR, "jobs.lock")
LOGS_DIR = os.path.join(SCHEDULER_DIR, "logs")
# Mock-job sentinels live under .calkit/local, which is always gitignored.
LOCAL_DIR = os.path.join(".calkit", "local")
MOCK_DIR = os.path.join(LOCAL_DIR, "mock-scheduler")
# When set, scheduler commands run jobs on the local host instead of
# dispatching to a real SLURM/PBS install (see _mock_enabled).
MOCK_ENV_VAR = "CALKIT_MOCK_SCHEDULER"


def _ensure_local_gitignore() -> None:
    """Make sure ``.calkit/scheduler/jobs.json`` is ignored by Git.

    Uses a directory-local ``.gitignore`` so we don't have to touch the
    project-root ``.gitignore`` or call into the user's git repo.
    """
    os.makedirs(SCHEDULER_DIR, exist_ok=True)
    gitignore_path = os.path.join(SCHEDULER_DIR, ".gitignore")
    # jobs.lock is filelock's guard file for atomic jobs.json updates.
    desired_entries = ["jobs.json", "jobs.lock"]
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, "r") as f:
            existing = f.read().splitlines()
        if all(entry in existing for entry in desired_entries):
            return
    with open(gitignore_path, "w") as f:
        f.write("\n".join(desired_entries) + "\n")


def _load_jobs() -> dict:
    if os.path.isfile(JOBS_PATH):
        with open(JOBS_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def _record_job(name: str, info: dict) -> None:
    """Atomically merge a single job record into jobs.json.

    Each iterated stage submits its items as separate processes that all
    write the shared jobs.json; without a lock + reload-merge, a slow writer
    would clobber records written by faster ones. Each process only touches
    its own uniquely named key, so a per-key merge under the lock is safe.
    """
    os.makedirs(SCHEDULER_DIR, exist_ok=True)
    _ensure_local_gitignore()
    with FileLock(JOBS_LOCK_PATH):
        jobs = _load_jobs()
        jobs[name] = info
        with open(JOBS_PATH, "w") as f:
            json.dump(jobs, f, indent=4)


def _mock_enabled() -> bool:
    """Whether scheduler commands should run jobs locally.

    Enabled via the ``CALKIT_MOCK_SCHEDULER`` env var. Lets scheduler
    workflows (and their tests) run on a plain host with no SLURM/PBS install:
    jobs execute in the background, their output goes to the usual log files,
    and queue/cancel act on locally tracked processes.
    """
    return os.environ.get(MOCK_ENV_VAR, "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    )


def _ensure_mock_dir() -> None:
    # Everything under .calkit/local is gitignored via a "*" .gitignore.
    os.makedirs(MOCK_DIR, exist_ok=True)
    gitignore_path = os.path.join(LOCAL_DIR, ".gitignore")
    if not os.path.isfile(gitignore_path):
        with open(gitignore_path, "w") as f:
            f.write("*\n")


def _mock_status_path(job_id: str) -> str:
    # Absolute so the sentinel resolves even if the job cd's elsewhere.
    return os.path.abspath(os.path.join(MOCK_DIR, f"{job_id}.status"))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _mock_pid(job_id: str) -> int | None:
    for record in _load_jobs().values():
        if record.get("job_id") == job_id:
            pid = record.get("pid")
            return pid if isinstance(pid, int) else None
    return None


def _mock_active(job_id: str) -> bool:
    # A finished job writes its exit code to the sentinel before exiting, so
    # the sentinel is authoritative; fall back to process liveness only when
    # it is absent (e.g. the job was killed without recording a status).
    if os.path.exists(_mock_status_path(job_id)):
        return False
    pid = _mock_pid(job_id)
    if pid is None:
        return False
    return _pid_alive(pid)


def _build_job_command(
    target: str,
    args: list[str],
    setup_cmds: list[str],
    is_command: bool,
) -> str:
    """Build the shell command a mock job runs on the host.

    Mirrors what the real submit builders hand the scheduler: setup commands
    chained before the target, with a non-executable script invoked through
    its shebang interpreter (or bash).
    """
    parts = [target] + list(args)
    if (
        not is_command
        and os.path.isfile(target)
        and not os.access(target, os.X_OK)
    ):
        parts = _detect_interpreter(target) + parts
    invocation = shlex.join(parts)
    if setup_cmds:
        return " && ".join([*setup_cmds, invocation])
    return invocation


def _mock_submit(job_id: str, job_command: str, log_path: str) -> int:
    """Run a job locally in the background, returning its PID.

    Completion is signaled by writing the exit code to a sentinel file, which
    keeps liveness checks independent of PID reuse.
    """
    _ensure_mock_dir()
    status_path = _mock_status_path(job_id)
    if os.path.exists(status_path):
        os.remove(status_path)
    wrapped = f"{job_command}; echo $? > {shlex.quote(status_path)}"
    env = dict(os.environ)
    env.setdefault("PBS_O_WORKDIR", os.getcwd())
    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            ["bash", "-c", wrapped],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    return proc.pid


def _mock_cancel(job_id: str) -> tuple[bool, str]:
    pid = _mock_pid(job_id)
    if pid is not None:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    # Drop a sentinel so later liveness checks report the job as finished.
    status_path = _mock_status_path(job_id)
    _ensure_mock_dir()
    if not os.path.exists(status_path):
        with open(status_path, "w") as f:
            f.write("canceled\n")
    return True, ""


def _is_active(kind: str, job_id: str) -> bool:
    if _mock_enabled():
        return _mock_active(job_id)
    if kind == "slurm":
        p = subprocess.run(
            ["squeue", "--job", job_id], capture_output=True, text=True
        )
        if p.returncode != 0:
            return False
        return len(p.stdout.strip().split("\n")) > 1
    # Use `qstat -f` and parse job_state: on Torque/OpenPBS, plain `qstat
    # <id>` returns exit 0 even for completed (C) jobs, so checking the
    # return code alone would cause `calkit sched batch` to hang forever
    # after a PBS job finishes.  States C and F mean the job is done.
    p = subprocess.run(
        ["qstat", "-f", job_id], capture_output=True, text=True, check=False
    )
    if p.returncode != 0:
        return False
    for line in p.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("job_state"):
            state = stripped.split("=", 1)[-1].strip()
            return state not in ("C", "F")
    return False


def _cancel(kind: str, job_id: str) -> tuple[bool, str]:
    if _mock_enabled():
        return _mock_cancel(job_id)
    cancel_bin = _BINARIES[kind]["cancel"]
    p = subprocess.run(
        [cancel_bin, job_id], capture_output=True, text=True, check=False
    )
    return p.returncode == 0, p.stderr


@scheduler_app.command(name="batch")
def run_batch(
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Job name."),
    ],
    target: Annotated[
        str,
        typer.Argument(
            help=(
                "The target to run. "
                "This can be a shell script or an executable."
            )
        ),
    ],
    environment: Annotated[
        str,
        typer.Option(
            "--environment",
            "-e",
            help="Calkit (scheduler) environment to use for the job.",
        ),
    ],
    args: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Arguments for the target command, passed to the job script "
                "after the target."
            )
        ),
    ] = None,
    deps: Annotated[
        list[str],
        typer.Option(
            "--dep",
            "-d",
            help=(
                "Additional dependencies to track, which if changed signify"
                " a job is invalid."
            ),
        ),
    ] = [],
    outs: Annotated[
        list[str],
        typer.Option(
            "--out",
            "-o",
            help=(
                "Non-persistent output files or directories produced by the "
                "job, which will be deleted before submitting a new job."
            ),
        ),
    ] = [],
    options: Annotated[
        list[str],
        typer.Option(
            "--option",
            "-s",
            help=(
                "Additional options to pass to the scheduler submit command "
                "(no spaces allowed)."
            ),
        ),
    ] = [],
    setup_cmds: Annotated[
        list[str],
        typer.Option(
            "--setup",
            help=(
                "Shell setup command to run before launching the target "
                "(repeat for multiple commands)."
            ),
        ),
    ] = [],
    log_path: Annotated[
        str | None, typer.Option("--log-path", help="Output log path.")
    ] = None,
    is_command: Annotated[
        bool | None,
        typer.Option(
            "--command",
            help="Whether the target is a command instead of a script.",
        ),
    ] = None,
    env_default_options: Annotated[
        str,
        typer.Option(
            "--env-default-options",
            help=(
                "How to apply the environment's default scheduler options: "
                "'replace' (default) uses env defaults only when no "
                "options were provided here; 'merge' prepends env defaults "
                "(the scheduler's last-occurrence wins, so explicit options "
                "still override); 'ignore' never applies env defaults."
            ),
        ),
    ] = "replace",
    env_default_setup: Annotated[
        str,
        typer.Option(
            "--env-default-setup",
            help=(
                "How to apply the environment's default setup commands: "
                "'replace' (default) uses env defaults only when no setup "
                "commands were provided here; 'merge' prepends env "
                "defaults; 'ignore' never applies env defaults."
            ),
        ),
    ] = "replace",
) -> None:
    """Submit a batch job through the scheduler associated with the env.

    Duplicates are not allowed, so if one is already running or queued with
    the same name, we'll wait for it to finish. The only exception is if the
    dependencies have changed, in which case any queued or running jobs will
    be canceled and a new one submitted.
    """
    if args is None:
        args = []
    valid_modes = ("ignore", "replace", "merge")
    if env_default_options not in valid_modes:
        raise_error(
            f"Invalid --env-default-options value '{env_default_options}'; "
            f"expected one of {', '.join(valid_modes)}"
        )
    if env_default_setup not in valid_modes:
        raise_error(
            f"Invalid --env-default-setup value '{env_default_setup}'; "
            f"expected one of {', '.join(valid_modes)}"
        )
    if environment == "_system":
        raise_error(
            "Scheduler batch submission requires a scheduler environment; "
            "got '_system'"
        )
    ck_info = calkit.load_calkit_info()
    env = ck_info.get("environments", {}).get(environment, {})
    kind = env.get("kind")
    if kind not in SCHEDULER_KINDS:
        raise_error(
            f"Environment '{environment}' is not a scheduler environment "
            f"(expected one of {', '.join(SCHEDULER_KINDS)}, got "
            f"'{kind}')"
        )
    if log_path is None:
        log_path = os.path.join(LOGS_DIR, f"{name}.out")
    if is_command is None:
        is_command = not os.path.isfile(target)
    # Host check
    env_host = env.get("host", "localhost")
    if env_host != "localhost":
        current_host = socket.gethostname()
        current_fqdn = socket.getfqdn()
        if (
            env_host != current_host
            and env_host != current_fqdn
            and current_host != env_host.split(".")[0]
            and current_fqdn != env_host
        ):
            raise_error(
                f"Environment '{environment}' is for host '{env_host}', "
                f"but this is '{current_host}'"
            )
    # Apply env defaults per mode
    env_setup_cmds = env.get("default_setup", []) or []
    if env_default_setup == "merge" and env_setup_cmds:
        setup_cmds = [s for s in [*env_setup_cmds, *setup_cmds] if s.strip()]
    elif env_default_setup == "replace" and not setup_cmds:
        setup_cmds = [s for s in env_setup_cmds if s.strip()]
    env_default_opts = env.get("default_options", []) or []
    if env_default_options == "merge" and env_default_opts:
        options = [opt for opt in [*env_default_opts, *options] if opt.strip()]
    elif env_default_options == "replace" and not options:
        options = [opt for opt in env_default_opts if opt.strip()]
    # Build the submit command (kind-specific), or the local job command when
    # the scheduler is mocked.
    if _mock_enabled():
        job_command = _build_job_command(
            target=target,
            args=args,
            setup_cmds=setup_cmds,
            is_command=is_command,
        )
    elif kind == "slurm":
        submit_cmd, submit_input = _build_slurm_submit(
            name=name,
            target=target,
            args=args,
            options=options,
            setup_cmds=setup_cmds,
            log_path=log_path,
            is_command=is_command,
        )
    else:
        submit_cmd, submit_input = _build_pbs_submit(
            name=name,
            target=target,
            args=args,
            options=options,
            setup_cmds=setup_cmds,
            log_path=log_path,
            is_command=is_command,
        )
    if not is_command and target not in deps:
        deps = [target] + deps
    # Set up storage
    os.makedirs(SCHEDULER_DIR, exist_ok=True)
    logs_dir = os.path.dirname(log_path)
    if logs_dir:
        os.makedirs(logs_dir, exist_ok=True)
    jobs = _load_jobs()
    typer.echo("Computing MD5s for dependencies")
    current_dep_md5s = {}
    for dep in deps:
        if not os.path.exists(dep):
            raise_error(f"Dependency path '{dep}' does not exist.")
        current_dep_md5s[dep] = calkit.get_md5(dep)
    # See if there is a job with this name already running/queued
    if name in jobs:
        job_info = jobs[name]
        job_id = job_info["job_id"]
        job_deps = job_info["deps"]
        job_target = job_info.get("target")
        job_args = job_info.get("args", [])
        job_setup = job_info.get("setup", [])
        # The recorded job may have been submitted under a different
        # scheduler kind; use its own kind for activity/cancel checks.
        prev_kind = job_info.get("kind", kind)
        running_or_queued = _is_active(prev_kind, job_id)
        should_wait = True

        def _cancel_with_reason(reason: str) -> None:
            typer.echo(f"{reason}; canceling existing job ID {job_id}")
            ok, stderr = _cancel(prev_kind, job_id)
            if not ok:
                raise_error(
                    f"Failed to cancel existing job ID {job_id}: {stderr}"
                )

        if running_or_queued:
            typer.echo(
                f"Job '{name}' is already running or queued with ID {job_id}"
            )
            if job_target != target:
                should_wait = False
                _cancel_with_reason(
                    f"Target for job '{name}' has changed",
                )
            if job_args != args:
                should_wait = False
                _cancel_with_reason(
                    f"Arguments for job '{name}' have changed",
                )
            if job_setup != setup_cmds:
                should_wait = False
                _cancel_with_reason(
                    f"Setup commands for job '{name}' have changed",
                )
            if set(job_deps) != set(deps):
                should_wait = False
                _cancel_with_reason(
                    f"Dependencies for job '{name}' have changed",
                )
            job_dep_md5s = job_info.get("dep_md5s", {})
            for dep_path, md5 in current_dep_md5s.items():
                job_md5 = job_dep_md5s.get(dep_path)
                if md5 != job_md5:
                    should_wait = False
                    _cancel_with_reason(
                        f"Dependency '{dep_path}' for job '{name}' has "
                        "changed",
                    )
                    break
            if should_wait:
                typer.echo("Waiting for job to finish")
            while running_or_queued and should_wait:
                running_or_queued = _is_active(prev_kind, job_id)
                time.sleep(1)
            if should_wait:
                raise typer.Exit(0)
    # Job is not running or queued, so we can submit. First, delete any
    # non-persistent outputs.
    for out in outs:
        if os.path.exists(out):
            typer.echo(f"Deleting output path '{out}'")
            try:
                if os.path.isfile(out):
                    os.remove(out)
                else:
                    shutil.rmtree(out)
            except Exception as e:
                raise_error(f"Error deleting '{out}': {e}")
    pid = None
    if _mock_enabled():
        job_id = uuid.uuid4().hex[:12]
        pid = _mock_submit(
            job_id=job_id, job_command=job_command, log_path=log_path
        )
    else:
        p = subprocess.run(
            submit_cmd,
            input=submit_input,
            capture_output=True,
            check=False,
            text=True,
        )
        if p.returncode != 0:
            raise_error(f"Failed to submit new job: {p.stderr}")
        job_id = p.stdout.strip()
    typer.echo(f"Submitted job with ID: {job_id}")
    new_job = {
        "kind": kind,
        "job_id": job_id,
        "deps": deps,
        "target": target,
        "args": args,
        "setup": setup_cmds,
        "dep_md5s": current_dep_md5s,
    }
    if pid is not None:
        new_job["pid"] = pid
    _record_job(name, new_job)
    typer.echo("Waiting for job to finish")
    running_or_queued = True
    while running_or_queued:
        running_or_queued = _is_active(kind, job_id)
        time.sleep(1)


def _detect_interpreter(target: str) -> list[str]:
    """Return the interpreter to invoke a non-executable script with.

    Reads the shebang if present; otherwise falls back to ``bash``.
    """
    interpreter: list[str] | None = None
    try:
        with open(target, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("#!"):
            shebang = first_line[2:].strip()
            if shebang:
                interpreter = shlex.split(shebang)
    except OSError:
        interpreter = None
    if interpreter is None:
        interpreter = ["bash"]
    return interpreter


def _build_slurm_submit(
    name: str,
    target: str,
    args: list[str],
    options: list[str],
    setup_cmds: list[str],
    log_path: str,
    is_command: bool,
) -> tuple[list[str], str | None]:
    cmd = [
        "sbatch",
        "--parsable",
        "--job-name",
        name,
        "-o",
        log_path,
    ] + list(options)
    if setup_cmds:
        wrapped_target_parts = [target] + args
        if not is_command and os.path.isfile(target):
            if not os.access(target, os.X_OK):
                wrapped_target_parts = (
                    _detect_interpreter(target) + [target] + args
                )
        wrapped_target = shlex.join(wrapped_target_parts)
        setup_chain = " && ".join([*setup_cmds, wrapped_target])
        cmd += ["--wrap", setup_chain]
    elif is_command:
        cmd += ["--wrap", shlex.join([target] + args)]
    else:
        cmd += [target] + args
    return cmd, None


def _sanitize_pbs_job_name(name: str) -> str:
    # qsub rejects names containing characters outside a narrow safe set
    # (e.g. ``@`` and ``,``), which is exactly what matrix-iterated stage
    # names look like (``stage@arg1,arg2,...``). Replace any disallowed
    # character with ``_`` and cap the length at PBS Pro's 236-char limit.
    return re.sub(r"[^A-Za-z0-9._+-]", "_", name)[:236]


def _build_pbs_submit(
    name: str,
    target: str,
    args: list[str],
    options: list[str],
    setup_cmds: list[str],
    log_path: str,
    is_command: bool,
) -> tuple[list[str], str]:
    target_invocation_parts = [target] + args
    if not is_command and os.path.isfile(target):
        if not os.access(target, os.X_OK):
            target_invocation_parts = (
                _detect_interpreter(target) + [target] + args
            )
    target_invocation = shlex.join(target_invocation_parts)
    # PBS jobs start in ``$HOME`` by default (unlike SLURM, which inherits
    # the submission directory). Both Torque/OpenPBS and PBS Pro export
    # ``$PBS_O_WORKDIR``, so ``cd`` into it before anything else so
    # relative paths in stage scripts resolve correctly.
    cd_step = 'cd "$PBS_O_WORKDIR"'
    job_script = " && ".join([cd_step, *setup_cmds, target_invocation])
    # `-` tells qsub to read the job script from stdin; without it most PBS
    # variants ignore the `input=` payload and wait for an interactive terminal.
    cmd = (
        [
            "qsub",
            "-N",
            _sanitize_pbs_job_name(name),
            "-j",
            "oe",
            "-o",
            log_path,
            "-V",
        ]
        + list(options)
        + ["-"]
    )
    return cmd, job_script


@scheduler_app.command(name="queue|q")
def get_queue() -> None:
    """List scheduler jobs submitted via Calkit (across SLURM and PBS)."""
    jobs = _load_jobs()
    if not jobs:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)
    if _mock_enabled():
        typer.echo(f"{'NAME':<32}{'JOBID':<16}STATUS")
        for job_name, info in jobs.items():
            job_id = info.get("job_id", "")
            status = "RUNNING" if _mock_active(job_id) else "DONE"
            typer.echo(f"{job_name:<32}{job_id:<16}{status}")
        raise typer.Exit(0)
    by_kind: dict[str, list[str]] = {}
    for info in jobs.values():
        by_kind.setdefault(info.get("kind", "slurm"), []).append(
            info["job_id"]
        )
    for kind, job_ids in by_kind.items():
        query_bin = _BINARIES[kind]["query"]
        if kind == "slurm":
            subprocess.run(
                [query_bin, "-j", ",".join(job_ids)],
                capture_output=False,
                text=True,
                check=False,
            )
        else:
            subprocess.run(
                [query_bin] + job_ids,
                capture_output=False,
                text=True,
                check=False,
            )


@scheduler_app.command(name="cancel")
def cancel_jobs(
    names: Annotated[
        list[str],
        typer.Argument(help="Names of jobs to cancel."),
    ],
) -> None:
    """Cancel scheduler jobs by their name in the project."""
    jobs = _load_jobs()
    if not jobs:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)
    for name in names:
        if name not in jobs:
            typer.echo(f"No job named '{name}' found for this project")
            continue
        job_info = jobs[name]
        kind = job_info.get("kind", "slurm")
        job_id = job_info["job_id"]
        if not _is_active(kind, job_id):
            typer.echo(
                f"Job '{name}' ({kind} ID: {job_id}) is not running or queued"
            )
            continue
        ok, stderr = _cancel(kind, job_id)
        if not ok:
            raise_error(f"Failed to cancel {kind} job ID {job_id}: {stderr}")
        typer.echo(f"Canceled {kind} job '{name}' with ID {job_id}")


@scheduler_app.command(name="logs")
def get_logs(
    names: Annotated[
        list[str] | None,
        typer.Argument(help="Names of the jobs to get logs for."),
    ] = None,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow", "-f", help="Follow the log output like tail -f."
        ),
    ] = False,
) -> None:
    """Get the logs for scheduler jobs by their name in the project.

    If no names are given, every tracked job's log is shown.
    """
    if names is None:
        names = list(_load_jobs().keys())
    log_fpaths: list[str] = []
    for name in names:
        log_fpath = os.path.join(LOGS_DIR, f"{name}.out")
        if os.path.isfile(log_fpath):
            log_fpaths.append(log_fpath)
    if not log_fpaths:
        raise_error("No log files found")
    if follow:
        p = subprocess.Popen(["tail", "-f"] + log_fpaths)
        try:
            p.wait()
        except KeyboardInterrupt:
            p.terminate()
            raise typer.Exit(0)
    else:
        for log_path in log_fpaths:
            with open(log_path, "r") as f:
                typer.echo(f.read())
