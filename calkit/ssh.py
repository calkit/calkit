"""Working with remote machines via SSH."""

import glob
import os
import subprocess
import time

import typer

import calkit
from calkit.cli import raise_error
from calkit.core import to_shell_cmd


def run_command(
    env: dict, env_name: str, cmd: list[str], verbose: bool = False
):
    """Run a command on a remote machine via SSH.

    TODO:
    - Ensure Calkit is installed and install if specified in the env def.
    - Ensure we have credentials set up.
    - Ensure Git is configured like the client w.r.t. the user.
    - Ensure there's a Calkit DVC token.
    - Ensure the repo is cloned there by default.
    - Check out and pull the correct branch.
    - Run the command and sync via the repo remotes, not scp.
    """
    try:
        host = os.path.expandvars(env["host"])
        user = os.path.expandvars(env["user"])
        remote_wdir: str = env["wdir"]
    except KeyError:
        raise_error(
            "Host, user, and wdir must be defined for ssh environments"
        )
    send_paths = env.get("send_paths")
    get_paths = env.get("get_paths")
    key = env.get("key")
    if key is not None:
        key = os.path.expanduser(os.path.expandvars(key))
    remote_shell_cmd = to_shell_cmd(cmd)
    # Run with nohup so we can disconnect
    # TODO: Should we collect output instead of send to /dev/null?
    remote_cmd = (
        f"cd '{remote_wdir}' ; nohup {remote_shell_cmd} "
        "> /dev/null 2>&1 & echo $! "
    )
    key_cmd = ["-i", key] if key is not None else []
    # Check to see if we've already submitted a job with this command
    jobs_fpath = ".calkit/jobs.yaml"
    job_key = f"{env_name}::{remote_shell_cmd}"
    remote_pid = None
    if os.path.isfile(jobs_fpath):
        with open(jobs_fpath) as f:
            jobs = calkit.ryaml.load(f)
        if jobs is None:
            jobs = {}
    else:
        jobs = {}
    job = jobs.get(job_key, {})
    remote_pid = job.get("remote_pid")
    if remote_pid is None:
        # First make sure the remote working dir exists
        typer.echo("Ensuring remote working directory exists")
        subprocess.check_call(
            ["ssh"] + key_cmd + [f"{user}@{host}", f"mkdir -p {remote_wdir}"]
        )
        # Now send any necessary files
        if send_paths:
            typer.echo("Sending to remote directory")
            # Accept glob patterns
            paths = []
            for p in send_paths:
                paths += glob.glob(p)
            scp_cmd = (
                ["scp", "-r"]
                + key_cmd
                + paths
                + [f"{user}@{host}:{remote_wdir}/"]
            )
            if verbose:
                typer.echo(f"scp cmd: {scp_cmd}")
            subprocess.check_call(scp_cmd)
        # Now run the command
        typer.echo(f"Running remote command: {remote_shell_cmd}")
        if verbose:
            typer.echo(f"Full command: {remote_cmd}")
        remote_pid = (
            subprocess.check_output(
                ["ssh"] + key_cmd + [f"{user}@{host}", remote_cmd]
            )
            .decode()
            .strip()
        )
        typer.echo(f"Running with remote PID: {remote_pid}")
        # Save PID to jobs database so we can resume waiting
        typer.echo("Updating jobs database")
        os.makedirs(".calkit", exist_ok=True)
        job["remote_pid"] = remote_pid
        job["submitted"] = time.time()
        job["finished"] = None
        jobs[job_key] = job
        with open(jobs_fpath, "w") as f:
            calkit.ryaml.dump(jobs, f)
    # Now wait for the job to complete
    typer.echo(f"Waiting for remote PID {remote_pid} to finish")
    ps_cmd = ["ssh"] + key_cmd + [f"{user}@{host}", "ps", "-p", remote_pid]
    finished = False
    while not finished:
        try:
            subprocess.check_output(ps_cmd)
            finished = False
            time.sleep(2)
        except subprocess.CalledProcessError:
            finished = True
            typer.echo("Remote process finished")
    # Now sync the files back
    # TODO: Figure out how to do this in one command
    # Getting the syntax right is troublesome since it appears to work
    # differently on different platforms
    if get_paths:
        typer.echo("Copying files back from remote directory")
        for src_path in get_paths:
            src_path = remote_wdir + "/" + src_path  # type: ignore
            src = f"{user}@{host}:{src_path}"
            scp_cmd = ["scp", "-r"] + key_cmd + [src, "."]
            subprocess.check_call(scp_cmd)
    # Now delete the remote PID from the jobs file
    typer.echo("Updating jobs database")
    os.makedirs(".calkit", exist_ok=True)
    job["remote_pid"] = None
    job["finished"] = time.time()
    jobs[job_key] = job
    with open(jobs_fpath, "w") as f:
        calkit.ryaml.dump(jobs, f)
