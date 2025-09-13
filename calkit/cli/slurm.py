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
    script: Annotated[str, typer.Argument(help="Path to the sbatch script.")],
    args: Annotated[
        list[str],
        typer.Argument(help="Additional arguments for the sbatch script."),
    ],
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
) -> None:
    """Submit a SLURM batch job for the project.

    Duplicates are not allowed, so if one is already running or queued with
    the same name, we'll wait for it to finish. The only exception is if the
    dependencies have changed, in which case any queued or running jobs will
    be cancelled and a new one submitted.
    """
    cmd = ["sbatch", "--parsable", "--name", name, script] + args
    slurm_dir = os.path.join(".calkit", "slurm")
    os.makedirs(slurm_dir, exist_ok=True)
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
        running_or_queued = (
            subprocess.run(
                ["squeue", "--job", job_id], capture_output=True
            ).returncode
            == 0
        )
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
            # Now just wait for the job to finish
            typer.echo("Waiting for job to finish")
            while running_or_queued and should_wait:
                running_or_queued = (
                    subprocess.run(
                        ["squeue", "--job", job_id], capture_output=True
                    ).returncode
                    == 0
                )
                time.sleep(1)
            if should_wait:
                raise typer.Exit(0)
    # Job is not running or queued, so we can submit
    p = subprocess.run(cmd, capture_output=True, check=False, text=True)
    if p.returncode != 0:
        raise_error("Failed to submit new job")
    job_id = p.stdout.strip()
    typer.echo(f"Submitted job with ID: {job_id}")
    new_job = {"job_id": job_id, "deps": deps, "dep_md5s": current_dep_md5s}
    jobs[name] = new_job
    with open(jobs_path, "w") as f:
        json.dump(jobs, f, indent=4)
    # Now wait for job to finish
    typer.echo("Waiting for job to finish")
    while running_or_queued and should_wait:
        running_or_queued = (
            subprocess.run(
                ["squeue", "--job", job_id], capture_output=True
            ).returncode
            == 0
        )
        time.sleep(1)
