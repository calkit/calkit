"""CLI for working with job schedulers (SLURM, PBS).

This module exposes a single typer app that dispatches to the right
underlying scheduler binary (``sbatch``/``squeue``/``scancel`` for SLURM,
``qsub``/``qstat``/``qdel`` for PBS) based on the environment kind. It is
registered under both ``sched`` and ``slurm`` so already-released
pipelines that emit ``calkit slurm batch ...`` keep working unchanged.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import time

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error

scheduler_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)

SCHEDULER_KINDS = ("slurm", "pbs")
_BINARIES = {
    "slurm": {"submit": "sbatch", "query": "squeue", "cancel": "scancel"},
    "pbs": {"submit": "qsub", "query": "qstat", "cancel": "qdel"},
}


def _kind_dir(kind: str) -> str:
    return os.path.join(".calkit", kind)


def _jobs_path(kind: str) -> str:
    return os.path.join(_kind_dir(kind), "jobs.json")


def _load_jobs(kind: str) -> dict:
    path = _jobs_path(kind)
    if os.path.isfile(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def _save_jobs(kind: str, jobs: dict) -> None:
    path = _jobs_path(kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(jobs, f, indent=4)


def _is_active(kind: str, job_id: str) -> bool:
    if kind == "slurm":
        p = subprocess.run(
            ["squeue", "--job", job_id], capture_output=True, text=True
        )
        if p.returncode != 0:
            return False
        return len(p.stdout.strip().split("\n")) > 1
    p = subprocess.run(
        ["qstat", job_id], capture_output=True, text=True, check=False
    )
    return p.returncode == 0


def _cancel(kind: str, job_id: str) -> tuple[bool, str]:
    cancel_bin = _BINARIES[kind]["cancel"]
    p = subprocess.run(
        [cancel_bin, job_id], capture_output=True, text=True, check=False
    )
    return p.returncode == 0, p.stderr


def _detect_local_kind() -> str | None:
    """Return the scheduler kind whose submit binary is on PATH.

    If both are available, prefer the one that has at least one tracked
    job in the project; otherwise fall back to slurm.
    """
    have_slurm = shutil.which("sbatch") is not None
    have_pbs = shutil.which("qsub") is not None
    if have_slurm and not have_pbs:
        return "slurm"
    if have_pbs and not have_slurm:
        return "pbs"
    if have_slurm and have_pbs:
        slurm_jobs = _load_jobs("slurm")
        pbs_jobs = _load_jobs("pbs")
        if slurm_jobs and not pbs_jobs:
            return "slurm"
        if pbs_jobs and not slurm_jobs:
            return "pbs"
        return "slurm"
    return None


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
            "--sbatch-option",
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
        log_path = os.path.join(_kind_dir(kind), "logs", f"{name}.out")
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
    # Build the submit command (kind-specific)
    if kind == "slurm":
        submit_cmd, submit_input = _build_slurm_submit(
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
    os.makedirs(_kind_dir(kind), exist_ok=True)
    logs_dir = os.path.dirname(log_path)
    if logs_dir:
        os.makedirs(logs_dir, exist_ok=True)
    jobs = _load_jobs(kind)
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
        running_or_queued = _is_active(kind, job_id)
        should_wait = True

        def _cancel_with_reason(reason: str) -> None:
            typer.echo(f"{reason}; canceling existing job ID {job_id}")
            ok, stderr = _cancel(kind, job_id)
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
                running_or_queued = _is_active(kind, job_id)
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
        "job_id": job_id,
        "deps": deps,
        "target": target,
        "args": args,
        "setup": setup_cmds,
        "dep_md5s": current_dep_md5s,
    }
    jobs[name] = new_job
    _save_jobs(kind, jobs)
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
    if setup_cmds:
        job_script = " && ".join([*setup_cmds, target_invocation])
    else:
        job_script = target_invocation
    cmd = [
        "qsub",
        "-N",
        name,
        "-j",
        "oe",
        "-o",
        log_path,
        "-V",
    ] + list(options)
    return cmd, job_script


@scheduler_app.command(name="queue|q")
def get_queue() -> None:
    """List scheduler jobs submitted via Calkit (across SLURM and PBS)."""
    found_any = False
    for kind in SCHEDULER_KINDS:
        jobs = _load_jobs(kind)
        if not jobs:
            continue
        found_any = True
        job_ids = [j["job_id"] for j in jobs.values()]
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
    if not found_any:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)


@scheduler_app.command(name="cancel")
def cancel_jobs(
    names: Annotated[
        list[str],
        typer.Argument(help="Names of jobs to cancel."),
    ],
) -> None:
    """Cancel scheduler jobs by their name in the project.

    A job name may exist in both the SLURM and PBS job lists (e.g., the
    user re-submitted under a different scheduler with the same name); in
    that case all matching jobs are canceled.
    """
    all_jobs: dict[str, list[tuple[str, dict]]] = {}
    for kind in SCHEDULER_KINDS:
        for n, info in _load_jobs(kind).items():
            all_jobs.setdefault(n, []).append((kind, info))
    if not all_jobs:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)
    for name in names:
        if name not in all_jobs:
            typer.echo(f"No job named '{name}' found for this project")
            continue
        for kind, job_info in all_jobs[name]:
            job_id = job_info["job_id"]
            if not _is_active(kind, job_id):
                typer.echo(
                    f"Job '{name}' (last submitted {kind} ID: {job_id}) "
                    "is not running or queued"
                )
                continue
            ok, stderr = _cancel(kind, job_id)
            if not ok:
                raise_error(
                    f"Failed to cancel {kind} job ID {job_id}: {stderr}"
                )
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

    Looks across both SLURM and PBS storage; if no names are given, every
    tracked job's log is shown.
    """
    if names is None:
        names = []
        for kind in SCHEDULER_KINDS:
            names += list(_load_jobs(kind).keys())
    log_fpaths: list[str] = []
    for name in names:
        for kind in SCHEDULER_KINDS:
            log_fpath = os.path.join(_kind_dir(kind), "logs", f"{name}.out")
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
