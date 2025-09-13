"""CLI for working with SLURM."""

from __future__ import annotations

import json
import os
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
        typer.Option("--name", "-n", help="Name for the SLURM job."),
    ],
    script: Annotated[
        str,
        typer.Argument(help="Path to the SLURM script to run."),
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
    time_limit: Annotated[
        str | None,
        typer.Option(
            "--time",
            "-t",
            help="Time limit for the job, e.g. '1:00:00' for one hour.",
        ),
    ] = None,
    gpus: Annotated[
        int | None,
        typer.Option(
            "--gpus",
            "-g",
            help="Number of GPUs to request for the job.",
        ),
    ] = None,
    nodes: Annotated[
        int | None,
        typer.Option(
            "--nodes",
            "-N",
            help="Number of nodes to request for the job.",
        ),
    ] = None,
    tasks_per_node: Annotated[
        int | None,
        typer.Option(
            "--tasks-per-node",
            "-p",
            help="Number of tasks per node to request for the job.",
        ),
    ] = None,
    tasks: Annotated[
        int | None,
        typer.Option(
            "--ntasks",
            "-n",
            help="Total number of tasks to request for the job.",
        ),
    ] = None,
    sbatch_opts: Annotated[
        list[str],
        typer.Option(
            "--sbatch-option",
            "-s",
            help="Additional options to pass to sbatch.",
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

    if args is None:
        args = []
    cmd = [
        "sbatch",
        "--parsable",
        "--job-name",
        name,
        "-o",
        ".calkit/slurm/logs/%j.out",
    ] + sbatch_opts
    if time_limit is not None:
        cmd += ["--time", time_limit]
    if gpus is not None:
        cmd += ["--gpus", str(gpus)]
    if nodes is not None:
        cmd += ["--nodes", str(nodes)]
    if tasks_per_node is not None:
        cmd += ["--ntasks-per-node", str(tasks_per_node)]
    if tasks is not None:
        cmd += ["--ntasks", str(tasks)]
    cmd += [script] + args
    if not os.path.isfile(script):
        raise_error(f"SLURM script '{script}' does not exist")
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
        running_or_queued = check_job_running_or_queued(job_id)
        should_wait = True
        if running_or_queued:
            typer.echo(
                f"Job '{name}' with is already running or queued with ID "
                f"{job_id}"
            )
            # Check if dependency paths have changed
            if set(job_deps) != set(deps):
                should_wait = False
                typer.echo(
                    f"Dependencies for job '{name}' have changed; canceling"
                    " existing job"
                )
                try:
                    subprocess.run(
                        ["scancel", job_id], check=True, capture_output=True
                    )
                except subprocess.CalledProcessError as e:
                    raise_error(
                        f"Failed to cancel existing job ID {job_id}: {e}"
                    )
            # Check dependency hashes
            job_dep_md5s = job_info.get("dep_md5s", {})
            for dep_path, md5 in current_dep_md5s.items():
                job_md5 = job_dep_md5s.get(dep_path)
                if md5 != job_md5:
                    typer.echo(
                        f"Dependency '{dep_path}' for job '{name}' has "
                        "changed; canceling existing job"
                    )
                    should_wait = False
                    try:
                        subprocess.run(
                            ["scancel", job_id],
                            check=True,
                            capture_output=True,
                        )
                    except subprocess.CalledProcessError as e:
                        raise_error(
                            f"Failed to cancel existing job ID {job_id}: {e}"
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
    p = subprocess.run(cmd, capture_output=True, check=False, text=True)
    if p.returncode != 0:
        raise_error(f"Failed to submit new job: {p.stderr}")
    job_id = p.stdout.strip()
    typer.echo(f"Submitted job with ID: {job_id}")
    new_job = {"job_id": job_id, "deps": deps, "dep_md5s": current_dep_md5s}
    jobs[name] = new_job
    with open(jobs_path, "w") as f:
        json.dump(jobs, f, indent=4)
    # Now wait for job to finish
    typer.echo("Waiting for job to finish")
    running_or_queued = True
    while running_or_queued:
        running_or_queued = check_job_running_or_queued(job_id)
        time.sleep(1)
