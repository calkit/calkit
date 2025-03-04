"""CLI for checking things."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
from typing import Annotated

import checksumdir
import dotenv
import git
import typer

import calkit
from calkit.check import check_reproducibility
from calkit.cli import raise_error

check_app = typer.Typer(no_args_is_help=True)


@check_app.command(name="repro")
def check_repro(
    wdir: Annotated[
        str, typer.Option("--wdir", help="Project working directory.")
    ] = ".",
):
    """Check the reproducibility of a project."""
    res = check_reproducibility(wdir=wdir, log_func=typer.echo)
    typer.echo(res.to_pretty().encode("utf-8", errors="replace"))


@check_app.command(name="call")
def check_call(
    cmd: Annotated[str, typer.Argument(help="Command to check.")],
    if_error: Annotated[
        str,
        typer.Option(
            "--if-error", help="Command to run if there is an error."
        ),
    ],
):
    """Check that a command succeeds and run an alternate if not."""
    try:
        subprocess.check_call(cmd, shell=True)
        typer.echo("Command succeeded")
    except subprocess.CalledProcessError:
        typer.echo("Command failed")
        try:
            typer.echo("Attempting fallback call")
            subprocess.check_call(if_error, shell=True)
            typer.echo("Fallback call succeeded")
        except subprocess.CalledProcessError:
            raise_error("Fallback call failed")


@check_app.command(
    name="docker-env",
    help="Check that Docker image is up-to-date.",
)
def check_docker_env(
    tag: Annotated[str, typer.Argument(help="Image tag.")],
    fpath: Annotated[
        str, typer.Option("-i", "--input", help="Path to input Dockerfile.")
    ] = "Dockerfile",
    platform: Annotated[
        str, typer.Option("--platform", help="Which platform(s) to build for.")
    ] = None,
    deps: Annotated[
        list[str],
        typer.Option(
            "--dep",
            "-d",
            help="Declare an explicit dependency for this Docker image.",
        ),
    ] = [],
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Be quiet.")
    ] = False,
):
    def get_docker_inspect():
        out = json.loads(
            subprocess.check_output(["docker", "inspect", tag]).decode()
        )
        # Remove some keys that can change without the important aspects of
        # the image changing
        _ = out[0].pop("Id")
        _ = out[0].pop("RepoDigests")
        _ = out[0].pop("Metadata")
        _ = out[0].pop("DockerVersion")
        return out

    def get_md5(path: str, exclude_files: list[str] | None = None) -> str:
        if os.path.isdir(path):
            return checksumdir.dirhash(dep, excluded_files=exclude_files)
        else:
            with open(path) as f:
                content = f.read()
            return hashlib.md5(content.encode()).hexdigest()

    outfile = open(os.devnull, "w") if quiet else None
    typer.echo(f"Checking for existing image with tag {tag}", file=outfile)
    # First call Docker inspect
    try:
        inspect = get_docker_inspect()
    except subprocess.CalledProcessError:
        typer.echo(f"No image with tag {tag} found locally", file=outfile)
        inspect = []
    typer.echo(f"Reading Dockerfile from {fpath}", file=outfile)
    dockerfile_md5 = get_md5(fpath)
    lock_fpath = fpath + "-lock.json"
    # Compute MD5s of any dependencies
    deps_md5s = {}
    for dep in deps:
        deps_md5s[dep] = get_md5(dep, exclude_files=lock_fpath)
    rebuild = True
    if os.path.isfile(lock_fpath):
        typer.echo(f"Reading lock file: {lock_fpath}", file=outfile)
        with open(lock_fpath) as f:
            lock = json.load(f)
    else:
        typer.echo(f"Lock file ({lock_fpath}) does not exist", file=outfile)
        lock = None
    if inspect and lock:
        typer.echo(
            "Checking image and Dockerfile against lock file", file=outfile
        )
        rebuild = inspect[0]["RootFS"]["Layers"] != lock[0]["RootFS"][
            "Layers"
        ] or dockerfile_md5 != lock[0].get("DockerfileMD5")
        if not rebuild:
            for dep, md5 in deps_md5s.items():
                if md5 != lock[0].get("DepsMD5s", {}).get(dep):
                    typer.echo(f"Found modified dependency: {dep}")
                    rebuild = True
                    break
    if rebuild:
        wdir, fname = os.path.split(fpath)
        if not wdir:
            wdir = None
        cmd = ["docker", "build", "-t", tag, "-f", fname]
        if platform is not None:
            cmd += ["--platform", platform]
        cmd.append(".")
        subprocess.check_output(cmd, cwd=wdir)
    # Write the lock file
    inspect = get_docker_inspect()
    inspect[0]["DockerfileMD5"] = dockerfile_md5
    inspect[0]["DepsMD5s"] = deps_md5s
    with open(lock_fpath, "w") as f:
        json.dump(inspect, f, indent=4)


@check_app.command(
    name="conda-env",
    help="Check a conda environment and rebuild if necessary.",
)
def check_conda_env(
    env_fpath: Annotated[
        str,
        typer.Option(
            "--file", "-f", help="Path to conda environment YAML file."
        ),
    ] = "environment.yml",
    output_fpath: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Path to which existing environment should be exported. "
                "If not specified, will have the same filename with '-lock' "
                "appended to it, keeping the same extension."
            ),
        ),
    ] = None,
    relaxed: Annotated[
        bool,
        typer.Option(
            "--relaxed", help="Treat conda and pip dependencies as equivalent."
        ),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Be quiet.")
    ] = False,
):
    if quiet:
        log_func = functools.partial(typer.echo, file=open(os.devnull, "w"))
    else:
        log_func = typer.echo
    calkit.conda.check_env(
        env_fpath=env_fpath,
        output_fpath=output_fpath,
        log_func=log_func,
        relaxed=relaxed,
    )


@check_app.command(name="env-vars")
def check_env_vars():
    """Check that the project's required environmental variables exist."""
    typer.echo("Checking project environmental variables")
    dotenv.load_dotenv(dotenv_path=".env")
    ck_info = calkit.load_calkit_info()
    deps = ck_info.get("dependencies", [])
    env_var_deps = {}
    for d in deps:
        if isinstance(d, dict):
            name = list(d.keys())[0]
            attrs = list(d.values())[0]
            if attrs.get("kind") == "env-var":
                env_var_deps[name] = attrs
    for name, attrs in env_var_deps.items():
        if name not in os.environ:
            typer.echo(f"Missing env var '{name}'")
            if "default" in attrs:
                default = attrs["default"]
            else:
                default = None
            value = typer.prompt(
                f"Enter a value for {name}", default=default, type=str
            )
            dotenv.set_key(
                dotenv_path=".env", key_to_set=name, value_to_set=value
            )
    # Ensure that .env is ignored by git
    repo = git.Repo()
    if not repo.ignored(".env"):
        typer.echo("Adding .env to .gitignore")
        with open(".gitignore", "a") as f:
            f.write("\n.env\n")
    message = "✅ All set!"
    typer.echo(message.encode("utf-8", errors="replace"))
