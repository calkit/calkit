"""CLI for working with PBS (OpenPBS, PBS Pro, TORQUE)."""

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
from calkit.cli import raise_error

pbs_app = typer.Typer(no_args_is_help=True)


def _qstat_active(job_id: str) -> bool:
    """Return True if the job ID is currently queued or running."""
    p = subprocess.run(
        ["qstat", job_id], capture_output=True, text=True, check=False
    )
    return p.returncode == 0


@pbs_app.command(name="batch")
def run_qsub(
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
            help="Calkit (PBS) environment to use for the job.",
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
    qsub_opts: Annotated[
        list[str],
        typer.Option(
            "--qsub-option",
            "-q",
            help=(
                "Additional options to pass to qsub (no spaces allowed). "
                "When provided, the environment's default options are "
                "ignored."
            ),
        ),
    ] = [],
    setup_cmds: Annotated[
        list[str],
        typer.Option(
            "--setup",
            help=(
                "Shell setup command to run before launching the target "
                "(repeat for multiple commands). When provided, the "
                "environment's default setup commands are ignored."
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
    merge_env_default_options: Annotated[
        bool,
        typer.Option(
            "--merge-env-default-options/--no-merge-env-default-options",
            help=(
                "Whether to prepend the environment's default qsub options "
                "to those provided here (qsub's last-occurrence wins, so "
                "explicit options still override)."
            ),
        ),
    ] = True,
    merge_env_default_setup: Annotated[
        bool,
        typer.Option(
            "--merge-env-default-setup/--no-merge-env-default-setup",
            help=(
                "Whether to prepend the environment's default setup "
                "commands to those provided here."
            ),
        ),
    ] = True,
) -> None:
    """Submit a PBS batch job for the project.

    Duplicates are not allowed, so if one is already running or queued with
    the same name, we'll wait for it to finish. The only exception is if the
    dependencies have changed, in which case any queued or running jobs will
    be canceled and a new one submitted.
    """

    def cancel_job(job_id: str, reason: str) -> None:
        typer.echo(f"{reason}; canceling existing job ID {job_id}")
        p = subprocess.run(
            ["qdel", job_id], capture_output=True, text=True, check=False
        )
        if p.returncode != 0:
            raise_error(
                f"Failed to cancel existing job ID {job_id}: {p.stderr}"
            )

    if args is None:
        args = []
    if log_path is None:
        log_path = f".calkit/pbs/logs/{name}.out"
    if is_command is None:
        is_command = not os.path.isfile(target)
    if environment != "_system":
        ck_info = calkit.load_calkit_info()
        env = ck_info.get("environments", {}).get(environment, {})
        env_kind = env.get("kind")
        if env_kind != "pbs":
            raise_error(
                f"Environment '{environment}' is not a PBS environment"
            )
        # Check host matches
        env_host = env.get("host", "localhost")
        if env_host != "localhost":
            current_host = socket.gethostname()
            current_fqdn = socket.getfqdn()
            # Match against both short hostname and FQDN
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
        # Env defaults are prepended to anything provided here; qsub honors
        # the last occurrence of a flag, so explicit options still win.
        if merge_env_default_setup:
            env_setup_cmds = env.get("default_setup", []) or []
            if env_setup_cmds:
                setup_cmds = [
                    s for s in [*env_setup_cmds, *setup_cmds] if s.strip()
                ]
        if merge_env_default_options:
            env_default_options = env.get("default_options", []) or []
            if env_default_options:
                qsub_opts = [
                    opt
                    for opt in [*env_default_options, *qsub_opts]
                    if opt.strip()
                ]
    # Build the job script (executed inside the qsub job). PBS does not have
    # an analog of `sbatch --wrap`, so we always pipe a small shell script
    # through stdin.
    target_invocation_parts = [target] + args
    if not is_command and os.path.isfile(target):
        # If the script is not executable, invoke it through its interpreter
        # (shebang or fallback to bash).
        if not os.access(target, os.X_OK):
            interpreter = None
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
            target_invocation_parts = interpreter + [target] + args
    target_invocation = shlex.join(target_invocation_parts)
    if setup_cmds:
        job_script = " && ".join([*setup_cmds, target_invocation])
    else:
        job_script = target_invocation
    if not is_command and target not in deps:
        deps = [target] + deps
    cmd = [
        "qsub",
        "-N",
        name,
        "-j",
        "oe",
        "-o",
        log_path,
        "-V",
    ] + qsub_opts
    pbs_dir = os.path.join(".calkit", "pbs")
    os.makedirs(pbs_dir, exist_ok=True)
    logs_dir = os.path.dirname(log_path)
    if logs_dir:
        os.makedirs(logs_dir, exist_ok=True)
    jobs_path = os.path.join(pbs_dir, "jobs.json")
    if os.path.isfile(jobs_path):
        with open(jobs_path, "r") as f:
            jobs = json.load(f)
    else:
        jobs = {}
    typer.echo("Computing MD5s for dependencies")
    current_dep_md5s = {}
    for dep in deps:
        if not os.path.exists(dep):
            raise_error(f"Dependency path '{dep}' does not exist.")
        current_dep_md5s[dep] = calkit.get_md5(dep)
    # See if there is a job with this name
    if name in jobs:
        job_info = jobs[name]
        job_id = job_info["job_id"]
        job_deps = job_info["deps"]
        job_target = job_info.get("target")
        job_args = job_info.get("args", [])
        job_setup = job_info.get("setup", [])
        running_or_queued = _qstat_active(job_id)
        should_wait = True
        if running_or_queued:
            typer.echo(
                f"Job '{name}' is already running or queued with ID {job_id}"
            )
            # Check if target has changed
            if job_target != target:
                should_wait = False
                cancel_job(
                    job_id=job_id,
                    reason=f"Target for job '{name}' has changed",
                )
            # Check if args have changed
            if job_args != args:
                should_wait = False
                cancel_job(
                    job_id=job_id,
                    reason=f"Arguments for job '{name}' have changed",
                )
            # Check if setup commands have changed
            if job_setup != setup_cmds:
                should_wait = False
                cancel_job(
                    job_id=job_id,
                    reason=f"Setup commands for job '{name}' have changed",
                )
            # Check if dependency paths have changed
            if set(job_deps) != set(deps):
                should_wait = False
                cancel_job(
                    job_id=job_id,
                    reason=f"Dependencies for job '{name}' have changed",
                )
            # Check dependency hashes
            job_dep_md5s = job_info.get("dep_md5s", {})
            for dep_path, md5 in current_dep_md5s.items():
                job_md5 = job_dep_md5s.get(dep_path)
                if md5 != job_md5:
                    should_wait = False
                    cancel_job(
                        job_id=job_id,
                        reason=(
                            f"Dependency '{dep_path}' for job '{name}' has "
                            "changed"
                        ),
                    )
                    break
            # Wait for the job to finish if it's running or queued and valid
            if should_wait:
                typer.echo("Waiting for job to finish")
            while running_or_queued and should_wait:
                running_or_queued = _qstat_active(job_id)
                time.sleep(1)
            if should_wait:
                raise typer.Exit(0)
    # Job is not running or queued, so we can submit
    # But first, delete any non-persistent outputs
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
        cmd,
        input=job_script,
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
    with open(jobs_path, "w") as f:
        json.dump(jobs, f, indent=4)
    # Now wait for job to finish
    typer.echo("Waiting for job to finish")
    running_or_queued = True
    while running_or_queued:
        running_or_queued = _qstat_active(job_id)
        time.sleep(1)


@pbs_app.command(name="queue")
def get_queue() -> None:
    """List PBS jobs submitted via Calkit."""
    pbs_dir = os.path.join(".calkit", "pbs")
    jobs_path = os.path.join(pbs_dir, "jobs.json")
    if os.path.isfile(jobs_path):
        with open(jobs_path, "r") as f:
            jobs = json.load(f)
    else:
        jobs = {}
    if len(jobs) == 0:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)
    job_ids = [j["job_id"] for j in jobs.values()]
    subprocess.run(
        ["qstat"] + job_ids,
        capture_output=False,
        text=True,
        check=False,
    )


@pbs_app.command(name="cancel")
def cancel_jobs(
    names: Annotated[
        list[str],
        typer.Argument(help="Names of jobs to cancel."),
    ],
) -> None:
    """Cancel PBS jobs by their name in the project."""
    pbs_dir = os.path.join(".calkit", "pbs")
    jobs_path = os.path.join(pbs_dir, "jobs.json")
    if os.path.isfile(jobs_path):
        with open(jobs_path, "r") as f:
            jobs = json.load(f)
    else:
        jobs = {}
    if len(jobs) == 0:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)
    for name in names:
        if name not in jobs:
            typer.echo(f"No job named '{name}' found for this project")
            continue
        job_info = jobs[name]
        job_id = job_info["job_id"]
        if not _qstat_active(job_id):
            typer.echo(
                f"Job '{name}' (last submitted ID: {job_id}) is not "
                "running or queued"
            )
            continue
        p = subprocess.run(
            ["qdel", job_id], capture_output=True, text=True, check=False
        )
        if p.returncode != 0:
            raise_error(f"Failed to cancel job ID {job_id}: {p.stderr}")
        typer.echo(f"Canceled job '{name}' with ID {job_id}")


@pbs_app.command(name="logs")
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
    """Get the logs for a PBS job by its name in the project."""
    pbs_dir = os.path.join(".calkit", "pbs")
    # If names are none, use all job names
    if names is None:
        jobs_path = os.path.join(pbs_dir, "jobs.json")
        if os.path.isfile(jobs_path):
            with open(jobs_path, "r") as f:
                jobs = json.load(f)
        else:
            jobs = {}
        names = list(jobs.keys())
    log_fpaths = []
    for name in names:
        log_fpath = os.path.join(pbs_dir, "logs", f"{name}.out")
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
