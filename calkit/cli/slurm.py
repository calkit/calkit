"""CLI for working with SLURM."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error

slurm_app = typer.Typer(no_args_is_help=True)


@slurm_app.command(name="batch")
def run_sbatch(
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Job name."),
    ],
    script: Annotated[
        str,
        typer.Argument(help="Path to the SLURM script to run."),
    ],
    environment: Annotated[
        str,
        typer.Option(
            "--environment",
            "-e",
            help="Calkit (slurm) environment to use for the job.",
        ),
    ],
    args: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Arguments for sbatch, the first of which should be the "
                "script."
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
    sbatch_opts: Annotated[
        list[str],
        typer.Option(
            "--sbatch-option",
            "-s",
            help="Additional options to pass to sbatch (no spaces allowed).",
        ),
    ] = [],
) -> None:
    """Submit a SLURM batch job for the project.

    Duplicates are not allowed, so if one is already running or queued with
    the same name, we'll wait for it to finish. The only exception is if the
    dependencies have changed, in which case any queued or running jobs will
    be cancelled and a new one submitted.
    """

    def check_job_running_or_queued(job_id: str) -> bool:
        p = subprocess.run(
            ["squeue", "--job", job_id], capture_output=True, text=True
        )
        if p.returncode != 0:
            return False
        return len(p.stdout.strip().split("\n")) > 1

    def cancel_job(job_id: str, reason: str) -> None:
        typer.echo(f"{reason}; canceling existing job ID {job_id}")
        p = subprocess.run(
            ["scancel", job_id], capture_output=True, text=True, check=False
        )
        if p.returncode != 0:
            raise_error(
                f"Failed to cancel existing job ID {job_id}: {p.stderr}"
            )

    if args is None:
        args = []
    cmd = (
        [
            "sbatch",
            "--parsable",
            "--job-name",
            name,
            "-o",
            ".calkit/slurm/logs/%j.out",
        ]
        + sbatch_opts
        + [script]
        + args
    )
    if not os.path.isfile(script):
        raise_error(f"SLURM script '{script}' does not exist")
    if environment != "_system":
        ck_info = calkit.load_calkit_info()
        env = ck_info.get("environments", {}).get(environment, {})
        env_kind = env.get("kind")
        if env_kind != "slurm":
            raise_error(
                f"Environment '{environment}' is not a slurm environment"
            )
        # Check host matches
        env_host = env.get("host", "localhost")
        if env_host != "localhost" and env_host != socket.gethostname():
            raise_error(
                f"Environment '{environment}' is for host '{env_host}', but "
                f"this is '{socket.gethostname()}'"
            )
    deps = [script] + deps
    slurm_dir = os.path.join(".calkit", "slurm")
    logs_dir = os.path.join(slurm_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    jobs_path = os.path.join(slurm_dir, "jobs.json")
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
        job_args = job_info.get("args", [])
        running_or_queued = check_job_running_or_queued(job_id)
        should_wait = True
        if running_or_queued:
            typer.echo(
                f"Job '{name}' with is already running or queued with ID "
                f"{job_id}"
            )
            # Check if args have changed
            if job_args != args:
                should_wait = False
                cancel_job(
                    job_id=job_id,
                    reason=f"Arguments for job '{name}' have changed",
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
                running_or_queued = check_job_running_or_queued(job_id)
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
    p = subprocess.run(cmd, capture_output=True, check=False, text=True)
    if p.returncode != 0:
        raise_error(f"Failed to submit new job: {p.stderr}")
    job_id = p.stdout.strip()
    typer.echo(f"Submitted job with ID: {job_id}")
    new_job = {
        "job_id": job_id,
        "deps": deps,
        "args": args,
        "dep_md5s": current_dep_md5s,
    }
    jobs[name] = new_job
    with open(jobs_path, "w") as f:
        json.dump(jobs, f, indent=4)
    # Now wait for job to finish
    typer.echo("Waiting for job to finish")
    running_or_queued = True
    while running_or_queued:
        running_or_queued = check_job_running_or_queued(job_id)
        time.sleep(1)


@slurm_app.command(name="queue")
def get_queue() -> None:
    """List SLURM jobs submitted via Calkit."""
    slurm_dir = os.path.join(".calkit", "slurm")
    jobs_path = os.path.join(slurm_dir, "jobs.json")
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
        ["squeue", "-j", ",".join(job_ids)],
        capture_output=False,
        text=True,
    )


@slurm_app.command(name="cancel")
def cancel_jobs(
    names: Annotated[
        list[str],
        typer.Argument(help="Names of jobs to cancel."),
    ],
) -> None:
    """Cancel SLURM jobs by their name in the project."""
    slurm_dir = os.path.join(".calkit", "slurm")
    jobs_path = os.path.join(slurm_dir, "jobs.json")
    if os.path.isfile(jobs_path):
        with open(jobs_path, "r") as f:
            jobs = json.load(f)
    else:
        jobs = {}
    if len(jobs) == 0:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)
    # Get any job IDs that are actually running or queued
    job_ids = [j["job_id"] for j in jobs.values()]
    p = subprocess.run(
        ["squeue", "-h", "-o", "%A", "-j", ",".join(job_ids)],
        capture_output=True,
        text=True,
    )
    running_or_queued_ids = p.stdout.strip().split("\n")
    running_or_queued_ids = [j for j in running_or_queued_ids if j]
    for name in names:
        if name not in jobs:
            typer.echo(f"No job named '{name}' found for this project")
            continue
        job_info = jobs[name]
        job_id = job_info["job_id"]
        if job_id not in running_or_queued_ids:
            typer.echo(
                f"Job '{name}' (last submitted ID: {job_id}) is not "
                "running or queued"
            )
            continue
        p = subprocess.run(
            ["scancel", job_id], capture_output=True, text=True, check=False
        )
        if p.returncode != 0:
            raise_error(f"Failed to cancel job ID {job_id}: {p.stderr}")
        typer.echo(f"Cancelled job '{name}' with ID {job_id}")


@slurm_app.command(name="logs")
def get_logs(
    name: Annotated[
        str,
        typer.Argument(help="Name of the job to get logs for."),
    ],
    follow: Annotated[
        bool,
        typer.Option(
            "--follow", "-f", help="Follow the log output like tail -f."
        ),
    ] = False,
) -> None:
    """Get the logs for a SLURM job by its name in the project."""
    slurm_dir = os.path.join(".calkit", "slurm")
    jobs_path = os.path.join(slurm_dir, "jobs.json")
    if os.path.isfile(jobs_path):
        with open(jobs_path, "r") as f:
            jobs = json.load(f)
    else:
        jobs = {}
    if len(jobs) == 0:
        typer.echo("No jobs found for this project")
        raise typer.Exit(0)
    if name not in jobs:
        raise_error(f"No job named '{name}' found for this project")
    job_info = jobs[name]
    job_id = job_info["job_id"]
    log_path = os.path.join(slurm_dir, "logs", f"{job_id}.out")
    if not os.path.isfile(log_path):
        raise_error(f"No log file found for job '{name}' with ID {job_id}")
    if follow:
        p = subprocess.Popen(["tail", "-f", log_path])
        try:
            p.wait()
        except KeyboardInterrupt:
            p.terminate()
            raise typer.Exit(0)
    else:
        with open(log_path, "r") as f:
            typer.echo(f.read())
