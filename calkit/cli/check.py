"""CLI for checking things."""

from __future__ import annotations

import functools
import json
import os
import platform as _platform
import shutil
import subprocess
from typing import Annotated, Callable

import dotenv
import git
import typer

import calkit
import calkit.environments
import calkit.matlab
import calkit.pipeline
from calkit.check import check_reproducibility
from calkit.cli import raise_error, warn
from calkit.core import get_md5
from calkit.environments import (
    get_all_conda_lock_fpaths,
    get_all_docker_lock_fpaths,
    get_all_venv_lock_fpaths,
    get_env_lock_fpath,
)

check_app = typer.Typer(no_args_is_help=True)


@check_app.command(name="repro")
def check_repro(
    wdir: Annotated[
        str, typer.Option("--wdir", help="Project working directory.")
    ] = ".",
) -> None:
    """Check the reproducibility of a project."""
    res = check_reproducibility(wdir=wdir, log_func=typer.echo)
    typer.echo(res.to_pretty().encode("utf-8", errors="replace"))


@check_app.command(
    name="env",
    help="Check that an environment is up-to-date (alias for 'environment').",
)
@check_app.command(name="environment")
def check_environment(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Name of the environment to check."),
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print verbose output.")
    ] = False,
) -> str | None:
    """Check that an environment is up-to-date."""
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    ck_info = calkit.load_calkit_info(process_includes="environments")
    envs = ck_info.get("environments", {})
    if not envs:
        raise_error("No environments defined in calkit.yaml")
    if isinstance(envs, list):
        raise_error("Error: Environments should be a dict, not a list")
    assert isinstance(envs, dict)
    if env_name not in envs:
        raise_error(f"Environment '{env_name}' does not exist")
    env = envs[env_name]
    if env["kind"] == "docker":
        if "image" not in env:
            raise_error("Image must be defined for Docker environments")
        lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=False
        )
        legacy_lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=False, legacy=True
        )
        # Alt lock paths include other architectures
        alt_lock_fpaths = get_all_docker_lock_fpaths(
            env_name=env_name, as_posix=False
        )
        check_docker_env(
            tag=env["image"],
            fpath=env.get("path"),
            lock_fpath=lock_fpath,
            alt_lock_fpaths_delete=[str(legacy_lock_fpath)],
            alt_lock_fpaths=alt_lock_fpaths,
            platform=env.get("platform"),
            deps=env.get("deps", []),
            env_vars=env.get("env_vars", []),
            ports=env.get("ports", []),
            gpus=env.get("gpus"),
            user=env.get("user"),
            wdir=env.get("wdir"),
            args=env.get("args", []),
            quiet=not verbose,
        )
    elif env["kind"] == "conda":
        lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=False
        )
        legacy_lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=False, legacy=True
        )
        alt_lock_fpaths = get_all_conda_lock_fpaths(
            env_name=env_name, as_posix=False
        )
        check_conda_env(
            env_fpath=env["path"],
            output_fpath=lock_fpath,
            alt_lock_fpaths_delete=[str(legacy_lock_fpath)],
            alt_lock_fpaths=alt_lock_fpaths,
            relaxed=True,  # TODO: Add option?
            quiet=not verbose,
        )
    elif env["kind"] == "pixi":
        cmd = ["pixi", "lock"]
        env_dir = os.path.dirname(env["path"])
        if env_dir:
            cmd += ["--manifest-path", env["path"]]
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            raise_error("Failed to check pixi environment")
    elif env["kind"] == "uv":
        cmd = ["uv", "sync"]
        env_dir = os.path.dirname(env["path"])
        if env_dir:
            cmd += ["--directory", env_dir]
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            raise_error("Failed to check uv environment")
    elif (kind := env["kind"]) in ["uv-venv", "venv"]:
        if "prefix" not in env:
            raise_error("venv environments require a prefix")
        if "path" not in env:
            raise_error("venv environments require a path")
        prefix = env["prefix"]
        path = env["path"]
        lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=False
        )
        legacy_lock_fpath = get_env_lock_fpath(
            env=env, env_name=env_name, as_posix=False, legacy=True
        )
        alt_lock_fpaths = get_all_venv_lock_fpaths(
            env_name=env_name, as_posix=False
        )
        check_venv(
            path=path,
            prefix=prefix,
            use_uv=kind == "uv-venv",
            python=env.get("python"),
            lock_fpath=lock_fpath,
            alt_lock_fpaths_delete=[str(legacy_lock_fpath)],
            alt_lock_fpaths=alt_lock_fpaths,
            verbose=verbose,
        )
    elif env["kind"] == "ssh":
        # TODO: How to check SSH environments?
        # Maybe just check that we can connect
        raise_error(
            "Environment checking not implemented for SSH environments"
        )
    elif env["kind"] == "renv":
        env_path = env.get("path")
        if env_path is None:
            raise_error("renv environments require a path to DESCRIPTION")
        check_renv(env_path=env_path, verbose=verbose)
    elif env["kind"] == "matlab":
        check_matlab_env(
            env_name=env_name,
            output_fpath=get_env_lock_fpath(
                env=env, env_name=env_name, as_posix=False
            ),  # type: ignore
        )
    elif env["kind"] == "julia":
        env_path = env.get("path")
        if env_path is None:
            raise_error(
                "Julia environments require a path pointing to Project.toml"
            )
        julia_version = env.get("julia")
        if julia_version is None:
            raise_error("Julia environments require a Julia version")
        env_fname = os.path.basename(env_path)
        if not env_fname == "Project.toml":
            raise_error(
                "Julia environments require a path pointing to Project.toml"
            )
        # First ensure the Julia version exists
        cmd = ["juliaup", "add", julia_version]
        if verbose:
            typer.echo(f"Running command: {cmd}")
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to install Julia version {julia_version}")
        env_dir = os.path.dirname(env_path)
        if not env_dir:
            env_dir = "."
        # If auto-detection couldn't resolve UUIDs, Project.toml includes a
        # commented dependency list
        # In that case, add those packages with
        # Pkg.add before instantiating so the env is usable at run time
        deps_to_add: list[str] = []
        try:
            with open(env_path, "r") as f:
                content = f.read()
            lines = [line.rstrip() for line in content.splitlines()]
            deps_section = False
            deps_found = False
            for line in lines:
                stripped = line.strip()
                if stripped == "[deps]":
                    deps_section = True
                    continue
                if deps_section:
                    if stripped.startswith("[") and stripped.endswith("]"):
                        break
                    if stripped and not stripped.startswith("#"):
                        if "=" in stripped:
                            deps_found = True
                            break
            if not deps_found:
                for idx, line in enumerate(lines):
                    marker = "# Dependencies (add with Julia's Pkg.add):"
                    if line.strip() == marker and idx + 1 < len(lines):
                        dep_line = lines[idx + 1].strip()
                        if dep_line.startswith("#"):
                            dep_line = dep_line.lstrip("#").strip()
                        deps_to_add = [
                            dep.strip()
                            for dep in dep_line.split(",")
                            if dep.strip()
                        ]
                        break
        except OSError:
            deps_to_add = []
        if deps_to_add:
            pkg_list = ", ".join(f'"{dep}"' for dep in deps_to_add)
            cmd = [
                "julia",
                f"+{julia_version}",
                f"--project={env_dir}",
                "-e",
                f"using Pkg; Pkg.add([{pkg_list}]);",
            ]
            try:
                subprocess.check_call(
                    cmd,
                    env=os.environ.copy() | {"JULIA_LOAD_PATH": "@:@stdlib"},
                )
            except subprocess.CalledProcessError:
                raise_error("Failed to add Julia dependencies")
        cmd = [
            "julia",
            f"+{julia_version}",
            f"--project={env_dir}",
            "-e",
            "using Pkg; Pkg.instantiate();",
        ]
        try:
            subprocess.check_call(
                cmd, env=os.environ.copy() | {"JULIA_LOAD_PATH": "@:@stdlib"}
            )
        except subprocess.CalledProcessError:
            raise_error("Failed to check julia environment")
    else:
        raise_error(f"Environment kind '{env['kind']}' not supported")
    return get_env_lock_fpath(env=env, env_name=env_name, as_posix=False)


@check_app.command(
    name="envs",
    help="Check that all environments are up-to-date.",
)
@check_app.command(name="environments")
def check_environments(
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print verbose output.")
    ] = False,
) -> None:
    ck_info = calkit.load_calkit_info(process_includes="environments")
    envs = ck_info.get("environments", {})
    if not envs:
        typer.echo("No environments defined in calkit.yaml")
        return
    failures = []
    for env_name, env in envs.items():
        if env.get("kind") in calkit.environments.KINDS_NO_CHECK:
            if verbose:
                typer.echo(
                    f"Skipping check for {env['kind']} env '{env_name}'"
                )
            continue
        typer.echo(f"Checking environment: '{env_name}'")
        try:
            check_environment(env_name=env_name, verbose=verbose)
        except Exception as e:
            warn(f"Error checking environment '{env_name}': {e}")
            failures.append(env_name)
    if failures:
        raise_error(
            f"Failed to check the following environments: {', '.join(failures)}"
        )


def check_renv(
    env_path: str,
    verbose: bool = False,
) -> None:
    """Check an R renv environment, initializing if needed.

    This function follows the proper renv workflow:
    1. Ensure renv is installed
    2. Check if renv.lock exists
    3. If not, but DESCRIPTION exists, initialize renv and create lock
    4. If lockfile exists, check if it's in sync with DESCRIPTION
    5. Only update lockfile if DESCRIPTION has changed
    6. Check if library is in sync with lockfile
    7. Only restore packages if library is out of sync

    Parameters
    ----------
    env_path : str
        Path to the DESCRIPTION file for the environment.
    wdir : str | None
        Working directory for execution. If not provided, uses the directory
        containing the DESCRIPTION file.
    verbose : bool
        Print verbose output.
    """
    # Get the directory containing the DESCRIPTION file
    if env_path.endswith("DESCRIPTION"):
        env_dir = os.path.dirname(env_path)
    else:
        # Assume it's already a directory
        env_dir = env_path
    if not env_dir:
        env_dir = "."
    if verbose:
        typer.echo(f"Checking renv environment in: {env_dir}")
    # First, ensure renv is installed in system R
    # Use --vanilla to avoid loading .Rprofile which would activate renv
    if verbose:
        typer.echo("Ensuring renv is installed")
    install_cmd = [
        "Rscript",
        "--vanilla",
        "-e",
        (
            "options(repos = c(CRAN = 'https://cloud.r-project.org')); "
            "if (!requireNamespace('renv', quietly=TRUE)) "
            "install.packages('renv')"
        ),
    ]
    try:
        subprocess.check_call(install_cmd)
    except subprocess.CalledProcessError:
        raise_error("Failed to install renv package")
    # Check if DESCRIPTION and renv.lock exist
    lock_path = os.path.join(env_dir, "renv.lock")
    description_path = os.path.join(env_dir, "DESCRIPTION")
    # Verify DESCRIPTION exists
    if not os.path.isfile(description_path):
        raise_error(
            f"DESCRIPTION file not found at {description_path}. "
            "Cannot initialize renv environment."
        )
    # If renv.lock doesn't exist, initialize renv and create lock from
    # DESCRIPTION
    if not os.path.isfile(lock_path):
        if verbose:
            typer.echo("Initializing renv environment")
        # Initialize renv with bare=TRUE to set up directory structure
        init_cmd = ["Rscript", "--vanilla", "-e", "renv::init(bare=TRUE)"]
        if verbose:
            typer.echo(f"Running: {' '.join(init_cmd)}")
        try:
            subprocess.check_call(init_cmd, cwd=env_dir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to initialize renv in {env_dir}")
        # Use hydrate to install packages from DESCRIPTION and snapshot
        if verbose:
            typer.echo("Setting up environment from DESCRIPTION")
        hydrate_cmd = [
            "Rscript",
            "--vanilla",
            "-e",
            "renv::load(); renv::hydrate()",
        ]
        if verbose:
            typer.echo(f"Running: {' '.join(hydrate_cmd)}")
        try:
            subprocess.check_call(hydrate_cmd, cwd=env_dir)
        except subprocess.CalledProcessError:
            # Hydrate might fail if packages aren't available, continue anyway
            if verbose:
                typer.echo(
                    "Warning: hydrate had issues, continuing to snapshot"
                )
        # Always snapshot after hydrate to create lock file from DESCRIPTION
        if verbose:
            typer.echo("Creating lock file from DESCRIPTION")
        snapshot_cmd = [
            "Rscript",
            "--vanilla",
            "-e",
            "renv::load(); renv::snapshot(type='explicit', prompt=FALSE)",
        ]
        if verbose:
            typer.echo(f"Running: {' '.join(snapshot_cmd)}")
        try:
            subprocess.check_call(snapshot_cmd, cwd=env_dir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to snapshot renv in {env_dir}")
    else:
        # Lock file exists, check if it's in sync with DESCRIPTION
        if verbose:
            typer.echo("Checking if lockfile is in sync with DESCRIPTION")
        # Check status to see if lockfile needs updating
        status_cmd = [
            "Rscript",
            "--vanilla",
            "-e",
            "renv::load(); status <- renv::status(); cat(status$synchronized)",
        ]
        try:
            result = subprocess.run(
                status_cmd,
                cwd=env_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            lockfile_synced = "TRUE" in result.stdout
        except subprocess.CalledProcessError:
            # If status fails, assume we need to update
            lockfile_synced = False
            if verbose:
                typer.echo("Warning: status check failed, will update lock")

        if not lockfile_synced:
            if verbose:
                typer.echo("Lockfile out of sync, updating from DESCRIPTION")
            # Use hydrate to update from DESCRIPTION
            hydrate_cmd = [
                "Rscript",
                "--vanilla",
                "-e",
                "renv::load(); renv::hydrate()",
            ]
            if verbose:
                typer.echo(f"Running: {' '.join(hydrate_cmd)}")
            try:
                subprocess.check_call(hydrate_cmd, cwd=env_dir)
            except subprocess.CalledProcessError:
                if verbose:
                    typer.echo(
                        "Warning: hydrate had issues, continuing to snapshot"
                    )
            # Snapshot to update lock
            snapshot_cmd = [
                "Rscript",
                "--vanilla",
                "-e",
                "renv::load(); renv::snapshot(type='explicit', prompt=FALSE)",
            ]
            if verbose:
                typer.echo(f"Running: {' '.join(snapshot_cmd)}")
            try:
                subprocess.check_call(snapshot_cmd, cwd=env_dir)
            except subprocess.CalledProcessError:
                if verbose:
                    typer.echo("Warning: snapshot failed, using existing lock")
        else:
            if verbose:
                typer.echo("Lockfile is already in sync with DESCRIPTION")

    # Check if library needs restoring
    if verbose:
        typer.echo("Checking if library is in sync with lockfile")
    lib_status_cmd = [
        "Rscript",
        "--vanilla",
        "-e",
        (
            "renv::load(); "
            "status <- tryCatch({"
            "  renv::status();"
            "  cat('synchronized');"
            "}, error = function(e) {"
            "  cat('needs_restore');"
            "})"
        ),
    ]
    try:
        result = subprocess.run(
            lib_status_cmd,
            cwd=env_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        needs_restore = "needs_restore" in result.stdout or (
            "synchronized" not in result.stdout
        )
    except subprocess.CalledProcessError:
        # If check fails, restore to be safe
        needs_restore = True
        if verbose:
            typer.echo("Warning: library status check failed, will restore")

    if needs_restore:
        if verbose:
            typer.echo("Restoring library from lockfile")
        restore_cmd = [
            "Rscript",
            "--vanilla",
            "-e",
            "renv::load(); renv::restore(prompt=FALSE)",
        ]
        if verbose:
            typer.echo(f"Running: {' '.join(restore_cmd)}")
        try:
            subprocess.check_call(restore_cmd, cwd=env_dir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to restore renv in {env_dir}")
    else:
        if verbose:
            typer.echo("Library is already in sync with lockfile")


@check_app.command(name="docker-env")
def check_docker_env(
    tag: Annotated[str, typer.Argument(help="Image tag.")],
    fpath: Annotated[
        str | None,
        typer.Option(
            "-i", "--input", help="Path to input Dockerfile, if applicable."
        ),
    ] = None,
    lock_fpath: Annotated[
        str | None,
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
    alt_lock_fpaths: Annotated[
        list[str],
        typer.Option(
            "--input", help="Alternative lock file input paths to read."
        ),
    ] = [],
    alt_lock_fpaths_delete: Annotated[
        list[str],
        typer.Option(
            "--input-delete",
            help=(
                "Alternative lock input file paths to read and "
                "remove (i.e., legacy paths)."
            ),
        ),
    ] = [],
    platform: Annotated[
        str | None,
        typer.Option("--platform", help="Which platform(s) to build for."),
    ] = None,
    user: Annotated[
        str | None,
        typer.Option("--user", help="Which user to run the container as."),
    ] = None,
    wdir: Annotated[
        str | None,
        typer.Option("--wdir", help="Working directory inside the container."),
    ] = None,
    deps: Annotated[
        list[str],
        typer.Option(
            "--dep",
            "-d",
            help="Declare an explicit dependency for this Docker image.",
        ),
    ] = [],
    env_vars: Annotated[
        list[str],
        typer.Option(
            "--env-var",
            "-e",
            help="Declare an explicit environment variable for the container.",
        ),
    ] = [],
    ports: Annotated[
        list[str],
        typer.Option(
            "--port",
            "-p",
            help="Declare an explicit port for the container.",
        ),
    ] = [],
    gpus: Annotated[
        str | None,
        typer.Option(
            "--gpus",
            "-g",
            help="Declare an explicit GPU requirement for the container.",
        ),
    ] = None,
    args: Annotated[
        list[str],
        typer.Option(
            "--arg",
            "-a",
            help="Declare an explicit run argument for the container.",
        ),
    ] = [],
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Be quiet.")
    ] = False,
) -> None:
    """Check that Docker environment is up-to-date."""
    if fpath is None and lock_fpath is None:
        raise_error(
            "Lock file output path must be provided if input Dockerfile is not"
        )

    def get_docker_inspect(obj_id: str = tag) -> dict:
        # This command returns a list, of which we want the first object
        out = json.loads(
            subprocess.check_output(["docker", "inspect", obj_id]).decode()
        )
        # Remove some keys that can change without the important aspects of
        # the image changing
        # Only keep certain keys that are relevant for identifying the
        # content in the image
        keys = [
            "RepoTags",
            "RepoDigests",
            "Architecture",
            "Os",
            "RootFS",
        ]
        resp = {}
        for key in keys:
            resp[key] = out[0].get(key)
        return resp

    outfile = open(os.devnull, "w") if quiet else None
    typer.echo(f"Checking for existing image with tag {tag}", file=outfile)
    # First call Docker inspect
    try:
        inspect = get_docker_inspect()
    except subprocess.CalledProcessError:
        typer.echo(f"No image with tag {tag} found locally", file=outfile)
        inspect = {}
    if fpath is not None:
        typer.echo(f"Reading Dockerfile from {fpath}", file=outfile)
        dockerfile_md5 = get_md5(fpath)
    else:
        dockerfile_md5 = None
    if lock_fpath is None and fpath is not None:
        lock_fpath = fpath + "-lock.json"
    else:
        lock_fpath = str(lock_fpath)
    # Compute MD5s of any dependencies
    deps_md5s = {}
    for dep in deps:
        deps_md5s[dep] = get_md5(dep, exclude_files=[lock_fpath])
    rebuild_or_pull = True
    lock = None
    if os.path.isfile(lock_fpath):
        typer.echo(f"Reading lock file: {lock_fpath}", file=outfile)
        with open(lock_fpath) as f:
            lock = json.load(f)
        # Handle legacy lock files that are lists
        if isinstance(lock, list):
            lock = lock[0]
    else:
        typer.echo(f"Lock file ({lock_fpath}) does not exist", file=outfile)
        for alt_lock_fpath in alt_lock_fpaths_delete:
            if os.path.isfile(alt_lock_fpath):
                typer.echo(f"Reading alternative lock file: {alt_lock_fpath}")
                with open(alt_lock_fpath) as f:
                    lock = json.load(f)
                # Handle legacy lock files that are lists
                if isinstance(lock, list):
                    lock = lock[0]
                os.remove(alt_lock_fpath)
                break
        if lock is None:
            for alt_lock_fpath in alt_lock_fpaths:
                if os.path.isfile(alt_lock_fpath):
                    typer.echo(
                        f"Reading alternative lock file: {alt_lock_fpath}"
                    )
                    with open(alt_lock_fpath) as f:
                        lock = json.load(f)
                    # Handle legacy lock files that are lists
                    if isinstance(lock, list):
                        lock = lock[0]
                    break
    if inspect and lock:
        typer.echo(
            "Checking image and Dockerfile against lock file", file=outfile
        )
        rebuild_or_pull = inspect["RootFS"]["Layers"] != lock["RootFS"][
            "Layers"
        ] or dockerfile_md5 != lock.get("DockerfileMD5")
        if not rebuild_or_pull:
            for dep, md5 in deps_md5s.items():
                if md5 != lock.get("DepsMD5s", {}).get(dep):
                    typer.echo(f"Found modified dependency: {dep}")
                    rebuild_or_pull = True
                    break
    if fpath is not None and rebuild_or_pull:
        wdir, fname = os.path.split(fpath)
        if not wdir:
            wdir = None
        cmd = ["docker", "build", "-t", tag, "-f", fname]
        if platform is not None:
            cmd += ["--platform", platform]
        cmd.append(".")
        subprocess.check_output(cmd, cwd=wdir)
    elif fpath is None and rebuild_or_pull:
        # First try to pull by repo digest
        pulled = False
        if lock and "RepoDigests" in lock:
            repo_digests = lock["RepoDigests"]
            if repo_digests:
                image_with_digest = repo_digests[0]
                typer.echo(f"Pulling image by digest: {image_with_digest}")
                cmd = ["docker", "pull", image_with_digest]
                tag_cmd = ["docker", "tag", image_with_digest, tag]
                try:
                    subprocess.check_output(cmd)
                    # Now tag the pulled image
                    subprocess.check_output(tag_cmd)
                    pulled = True
                except subprocess.CalledProcessError:
                    warn(
                        f"Failed to pull image by digest: {image_with_digest}; "
                        "falling back to pulling by tag"
                    )
                    pulled = False
        if not pulled:
            typer.echo(f"Pulling image: {tag}")
            cmd = ["docker", "pull", tag]
            try:
                subprocess.check_output(cmd)
            except subprocess.CalledProcessError:
                raise_error(f"Failed to pull image: {tag}")
    # Write the lock file
    inspect = get_docker_inspect()
    # Ensure repo tags only have the tag we wanted, not the digest, so we
    # don't cause stages to rerun from lock file change
    inspect["RepoTags"] = [tag]
    inspect["DockerfileMD5"] = dockerfile_md5
    inspect["DepsMD5s"] = deps_md5s
    if platform is not None:
        inspect["Platform"] = platform
    if wdir is not None:
        inspect["WorkDir"] = wdir
    if user is not None:
        inspect["User"] = user
    if env_vars:
        inspect["EnvVars"] = env_vars
    if ports:
        inspect["Ports"] = ports
    if gpus:
        inspect["GPUs"] = gpus
    if args:
        inspect["Args"] = args
    lock_dir = os.path.dirname(lock_fpath)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
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
        str | None,
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
    alt_lock_fpaths: Annotated[
        list[str],
        typer.Option("--input", help="Alternative lock file input paths."),
    ] = [],
    alt_lock_fpaths_delete: Annotated[
        list[str],
        typer.Option(
            "--input-delete",
            help="Alternative lock file input paths to delete after use.",
        ),
    ] = [],
    relaxed: Annotated[
        bool,
        typer.Option(
            "--relaxed", help="Treat conda and pip dependencies as equivalent."
        ),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Be quiet.")
    ] = False,
) -> None:
    log_func: Callable[..., None]
    if quiet:
        log_func = functools.partial(typer.echo, file=open(os.devnull, "w"))
    else:
        log_func = typer.echo
    try:
        calkit.conda.check_env(
            env_fpath=env_fpath,
            output_fpath=output_fpath,
            alt_lock_fpaths=alt_lock_fpaths,
            alt_lock_fpaths_delete=alt_lock_fpaths_delete,
            log_func=log_func,
            relaxed=relaxed,
            verbose=not quiet,
        )
    except Exception as e:
        raise_error(f"Failed to check conda environment: {e}")


@check_app.command(name="venv")
def check_venv(
    path: Annotated[
        str, typer.Argument(help="Path to requirements file.")
    ] = "requirements.txt",
    prefix: Annotated[str, typer.Option("--prefix", help="Prefix.")] = ".venv",
    lock_fpath: Annotated[
        str | None,
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
    alt_lock_fpaths: Annotated[
        list[str],
        typer.Option("--input", help="Alternative lock file input paths."),
    ] = [],
    alt_lock_fpaths_delete: Annotated[
        list[str],
        typer.Option(
            "--input-delete",
            help="Alternative lock file input paths to delete after use.",
        ),
    ] = [],
    wdir: Annotated[
        str | None,
        typer.Option(
            "--wdir",
            help="Working directory. Defaults to current working directory.",
        ),
    ] = None,
    use_uv: Annotated[bool, typer.Option("--uv", help="Use uv.")] = True,
    python: Annotated[
        str | None,
        typer.Option(
            "--python", help="Python version to specify if using uv."
        ),
    ] = None,
    quiet: Annotated[
        bool, typer.Option("--quiet", help="Do not print any output")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print verbose output.")
    ] = False,
) -> None:
    """Check a Python virtual environment (uv or virtualenv)."""
    kind = "uv-venv" if use_uv else "venv"
    create_cmd = (
        ["uv", "venv"] if kind == "uv-venv" else ["python", "-m", "venv"]
    )
    pip_cmd = "pip" if kind == "venv" else "uv pip"
    pip_freeze_cmd = f"{pip_cmd} freeze"
    if kind == "uv-venv":
        pip_freeze_cmd += " --color never"
    else:
        pip_freeze_cmd += " --no-color"
    pip_install_args = "-q" if quiet else ""
    if python is not None and not use_uv:
        raise_error("Python version cannot be specified if not using uv")
    if python is not None and use_uv:
        create_cmd += ["--python", python]
        pip_install_args += f" --python {python}"
    # Ensure prefix is natively formatted for the OS
    prefix = os.path.normpath(prefix)

    def create_venv() -> None:
        if verbose:
            typer.echo(f"Creating {kind} at {prefix}")
        try:
            subprocess.check_call(create_cmd + [prefix], cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to create {kind} at {prefix}")
        # Put a gitignore file in the env dir if one doesn't exist
        gitignore_fpath = os.path.join(wdir or ".", prefix, ".gitignore")
        if not os.path.isfile(gitignore_fpath):
            with open(gitignore_fpath, "w") as f:
                f.write("*\n")

    if not os.path.isdir(prefix):
        create_venv()
    if lock_fpath is None:
        fname, ext = os.path.splitext(path)
        lock_fpath = fname + "-lock" + ext
    lock_dir = os.path.dirname(lock_fpath)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    # Use main lock file if exists, else try alternatives (including legacy)
    reqs_to_use = lock_fpath
    used_legacy_lock = None
    if not os.path.isfile(lock_fpath):
        for alt_fpath in alt_lock_fpaths:
            if os.path.isfile(alt_fpath):
                reqs_to_use = alt_fpath
                if verbose:
                    typer.echo(f"Using alternative lock file: {alt_fpath}")
                break
        for legacy_fpath in alt_lock_fpaths_delete:
            if os.path.isfile(legacy_fpath):
                reqs_to_use = legacy_fpath
                used_legacy_lock = legacy_fpath
                if verbose:
                    typer.echo(f"Using legacy lock file: {legacy_fpath}")
                break
    if _platform.system() == "Windows":
        activate_cmd = f"{prefix}\\Scripts\\activate"
    else:
        activate_cmd = f". {prefix}/bin/activate"

    def pip_install_and_freeze(reqs_arg: str) -> None:
        check_cmd = (
            f"{activate_cmd} "
            f"&& {pip_cmd} install {pip_install_args} {reqs_arg} "
            f"&& {pip_freeze_cmd} > {lock_fpath} "
            "&& deactivate"
        )
        if verbose:
            typer.echo(f"Running command: {check_cmd}")
        subprocess.run(check_cmd, shell=True, cwd=wdir, check=True)
        # Delete legacy lock file after use
        if used_legacy_lock:
            try:
                os.remove(used_legacy_lock)
                if verbose:
                    typer.echo(
                        "Deleted legacy lock file after use: "
                        f"{used_legacy_lock}"
                    )
            except Exception as e:
                if verbose:
                    typer.echo(
                        "Failed to delete legacy lock file "
                        f"{used_legacy_lock}: {e}"
                    )

    # If the lock file exists, try to install with that
    dep_file_txt = f"-r {path}"
    if os.path.isfile(reqs_to_use):
        dep_file_txt += f" -r {reqs_to_use}"
    try:
        pip_install_and_freeze(dep_file_txt)
    except subprocess.CalledProcessError:
        # Try to rebuild after removing the prefix
        try:
            if verbose:
                typer.echo(
                    f"Removing existing {kind} at {prefix} and rebuilding"
                )
            prefix_full_path = (
                prefix
                if os.path.isabs(prefix)
                else os.path.join(wdir or ".", prefix)
            )
            if os.path.isdir(prefix_full_path):
                shutil.rmtree(prefix_full_path)
            create_venv()
            pip_install_and_freeze(dep_file_txt)
        except subprocess.CalledProcessError:
            warn(
                f"Failed to create environment from lock file ({reqs_to_use}); "
                f"attempting rebuild from input file {path}"
            )
            # Since we failed to use the lock file, rebuild from the spec
            try:
                pip_install_and_freeze(f"-r {path}")
            except subprocess.CalledProcessError:
                raise_error(f"Failed to check {kind} from input file {path}")


@check_app.command(name="matlab-env")
def check_matlab_env(
    env_name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name in calkit.yaml."),
    ],
    output_fpath: Annotated[str, typer.Option("--output", "-o")],
) -> None:
    """Check a MATLAB environment matches its spec and export a JSON lock
    file.
    """
    ck_info = calkit.load_calkit_info()
    environments = ck_info.get("environments", {})
    if env_name not in environments:
        raise_error(f"Environment '{env_name}' not found in calkit.yaml")
    env = environments[env_name]
    if env.get("kind") != "matlab":
        raise_error(f"Environment '{env_name}' is not a MATLAB environment")
    if "version" not in env:
        raise_error("A MATLAB version must be specified")
    typer.echo(f"Checking MATLAB environment '{env_name}'")
    # First generate a Dockerfile for this environment
    out_dir = os.path.join(".calkit", "envs", env_name)
    os.makedirs(out_dir, exist_ok=True)
    dockerfile_fpath = os.path.join(out_dir, "Dockerfile")
    calkit.matlab.create_dockerfile(
        matlab_version=env["version"],
        additional_products=env.get("products", []),
        write=True,
        fpath_out=dockerfile_fpath,
    )
    # Now check that Docker environment
    tag = calkit.matlab.get_docker_image_name(
        ck_info=ck_info,
        env_name=env_name,
    )
    check_docker_env(
        tag=tag,
        fpath=dockerfile_fpath,
        lock_fpath=output_fpath,
        platform="linux/amd64",  # Only one available for now
    )


@check_app.command(name="dependencies")
@check_app.command(name="deps")
def check_dependencies(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output")
    ] = False,
) -> None:
    """Check that a project's system-level dependencies are set up
    correctly.
    """
    typer.echo("Checking project dependencies")
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    try:
        calkit.check_system_deps()
    except Exception as e:
        raise_error(str(e))
    message = "✅ All set!"
    typer.echo(message.encode("utf-8", errors="replace"))


@check_app.command(name="env-vars")
def check_env_vars(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output")
    ] = False,
) -> None:
    """Check that the project's required environmental variables exist."""
    typer.echo("Checking project environmental variables")
    dotenv.load_dotenv(dotenv_path=".env")
    ck_info = calkit.load_calkit_info()
    deps = ck_info.get("dependencies", [])
    env_var_dep_names = calkit.get_env_var_dep_names(ck_info)
    for name in env_var_dep_names:
        if verbose:
            typer.echo(f"Checking for environmental variable '{name}'")
        attrs = {}
        for dep in deps:
            if isinstance(dep, dict) and "name" in dep:
                attrs = dep
                break
            elif isinstance(dep, dict) and list(dep.keys()) == [name]:
                attrs = dep[name]
                break
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


@check_app.command(name="pipeline")
def check_pipeline(
    compile_to_dvc: Annotated[
        bool,
        typer.Option(
            "--compile",
            "-c",
            help="Compile the pipeline to DVC stages and merge into dvc.yaml.",
        ),
    ] = False,
) -> None:
    """Check that the project pipeline is defined correctly."""
    from calkit.models.pipeline import Pipeline

    ck_info = calkit.load_calkit_info()
    if "pipeline" not in ck_info:
        raise_error("No pipeline is defined in calkit.yaml")
    try:
        pipeline = Pipeline.model_validate(ck_info["pipeline"], strict=True)
    except Exception as e:
        raise_error(f"Pipeline is not defined correctly: {e}")
    # Check that we have no leading underscores in stage names, since those
    # are reserved for auto-generated stages
    for stage_name in pipeline.stages.keys():
        if stage_name.startswith("_"):
            raise_error("Stage names cannot start with an underscore")
    message = "✅ This project's pipeline is defined correctly!"
    typer.echo(message.encode("utf-8", errors="replace"))
    if compile_to_dvc:
        typer.echo("Attempting to compile to DVC stages")
        try:
            calkit.pipeline.to_dvc(ck_info=ck_info, write=True)
        except Exception as e:
            raise_error(
                f"Failed to compile pipeline: {e.__class__.__name__}: {e}"
            )


@check_app.command(name="call")
def check_call(
    cmd: Annotated[str, typer.Argument(help="Command to check.")],
    if_error: Annotated[
        str,
        typer.Option(
            "--if-error", help="Command to run if there is an error."
        ),
    ],
) -> None:
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
