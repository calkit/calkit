"""CLI for checking things."""

from __future__ import annotations

import functools
import json
import os
import platform as _platform
import shutil
import subprocess
import textwrap
from typing import Annotated, Callable

import dotenv
import typer

import calkit
from calkit.cli import AliasGroup, raise_error, warn
from calkit.core import get_md5

check_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def _juliaup_version_installed(julia_version: str) -> bool:
    """Return True if juliaup already has the given channel installed locally."""
    try:
        result = subprocess.run(
            ["juliaup", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        warn("Timed out while running `juliaup status`.")
        return False
    if result.returncode != 0:
        err_output = (result.stderr or result.stdout or "").strip()
        if err_output:
            warn(f"`juliaup status` failed: {err_output}")
        else:
            warn(
                f"`juliaup status` failed with exit code {result.returncode}."
            )
        return False
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        # Columns: [Default?] Channel Version [Update?]
        # Default column is either empty or "*", so channel is parts[0] or parts[1]
        for col in parts[:2]:
            if col == julia_version:
                return True
    return False


def _check_julia_env(
    env_path: str,
    julia_version: str | None = None,
    verbose: bool = False,
    cache_key: str | None = None,
) -> str:
    """Check a Julia environment and instantiate only when needed."""
    abs_env_path = os.path.abspath(env_path)
    env_fname = os.path.basename(abs_env_path)
    if env_fname != "Project.toml":
        raise_error(
            "Julia environments require a path pointing to Project.toml"
        )
    env_dir = os.path.dirname(abs_env_path) or "."
    env_path_for_cache = os.path.basename(abs_env_path)
    env = {
        "kind": "julia",
        "path": env_path_for_cache,
        "julia": julia_version or "",
    }
    cache_env_name = cache_key or (
        f"julia::{abs_env_path}::{julia_version or ''}"
    )
    if calkit.environments.check_cache(
        env_name=cache_env_name,
        env=env,
        wdir=env_dir,
        respect_ttl=False,
    ):
        if verbose:
            typer.echo(
                "Julia environment cache is valid; skipping Pkg.instantiate()"
            )
        lock_fpath = calkit.environments.get_env_lock_fpath(
            env=env,
            env_name=cache_env_name,
            wdir=env_dir,
            as_posix=False,
        )
        return lock_fpath or os.path.join(env_dir, "Manifest.toml")
    if julia_version:
        if shutil.which("juliaup") is not None:
            if _juliaup_version_installed(julia_version):
                if verbose:
                    typer.echo(
                        f"Julia {julia_version} is already installed; "
                        "skipping juliaup add"
                    )
            else:
                cmd = ["juliaup", "add", julia_version]
                if verbose:
                    typer.echo(f"Running command: {cmd}")
                try:
                    subprocess.run(cmd, check=True)
                except subprocess.CalledProcessError:
                    raise_error(
                        f"Failed to install Julia version {julia_version}"
                    )
        else:
            try:
                compatible = calkit.julia.current_version_is_compatible(
                    julia_version
                )
            except ValueError as e:
                raise_error(str(e))
            if not compatible:
                raise_error(
                    "Current Julia version is not compatible with required "
                    f"version ({julia_version}), and juliaup is not "
                    "available to install it"
                )
    deps_to_add: list[str] = []
    try:
        with open(abs_env_path, "r") as f:
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
        cmd = [calkit.julia.get_julia_exe()]
        if julia_version:
            cmd.append(f"+{julia_version}")
        cmd += [
            f"--project={env_dir}",
            "-e",
            f"using Pkg; Pkg.add([{pkg_list}]);",
        ]
        if julia_version:
            try:
                cmd = calkit.julia.check_version_in_command(cmd)
            except Exception as e:
                raise_error(f"Failed to check Julia version: {e}")
        cmd = calkit.julia.ensure_startup_file_disabled_in_command(cmd)
        try:
            subprocess.check_call(
                cmd,
                env=os.environ.copy()
                | {"JULIA_LOAD_PATH": calkit.julia.load_path()},
            )
        except subprocess.CalledProcessError:
            calkit.environments.save_cache(
                env_name=cache_env_name,
                env=env,
                wdir=env_dir,
                success=False,
            )
            raise_error("Failed to add Julia dependencies")
    cmd = [calkit.julia.get_julia_exe()]
    if julia_version:
        cmd.append(f"+{julia_version}")
    cmd += [
        f"--project={env_dir}",
        "-e",
        # Resolve only when the manifest no longer matches the project
        # (e.g. a dependency was added, or the manifest was written by a
        # different Julia version): plain instantiate would install it
        # as-is and fail later at precompile. A current manifest is
        # installed exactly as locked, with no registry involved---
        # resolving one unconditionally can fail spuriously (and would
        # rewrite the lock). Older Julias without the check keep the
        # plain instantiate they always had.
        "using Pkg; "
        "if hasmethod(Pkg.is_manifest_current, Tuple{String}) && "
        "Pkg.is_manifest_current(dirname(Base.active_project())) == false; "
        "Pkg.resolve(); end; "
        "Pkg.instantiate();",
    ]
    if julia_version:
        try:
            cmd = calkit.julia.check_version_in_command(cmd)
        except Exception as e:
            raise_error(f"Failed to check Julia version: {e}")
    cmd = calkit.julia.ensure_startup_file_disabled_in_command(cmd)
    try:
        subprocess.check_call(
            cmd,
            env=os.environ.copy()
            | {"JULIA_LOAD_PATH": calkit.julia.load_path()},
        )
    except subprocess.CalledProcessError:
        calkit.environments.save_cache(
            env_name=cache_env_name,
            env=env,
            wdir=env_dir,
            success=False,
        )
        raise_error("Failed to check julia environment")
    calkit.environments.save_cache(
        env_name=cache_env_name,
        env=env,
        wdir=env_dir,
        success=True,
    )
    lock_fpath = calkit.environments.get_env_lock_fpath(
        env=env,
        env_name=cache_env_name,
        wdir=env_dir,
        as_posix=False,
    )
    return lock_fpath or os.path.join(env_dir, "Manifest.toml")


def _require_nix_available() -> None:
    """Ensure the ``nix`` CLI is on PATH, with a friendly error otherwise.

    On Windows we steer users to WSL2 rather than attempting native Nix,
    which isn't officially supported.
    """
    if shutil.which("nix") is not None:
        return
    if _platform.system() == "Windows":
        raise_error(
            "Nix is not available natively on Windows. Run Calkit inside "
            "WSL2 (https://learn.microsoft.com/en-us/windows/wsl/install) "
            "and install Nix there."
        )
    raise_error(
        "The 'nix' command was not found. Install it with "
        "'calkit install nix' or from https://nixos.org/download."
    )


def check_nix_env(env: dict, verbose: bool = False) -> str:
    """Materialize / refresh ``flake.lock`` next to the flake.

    Running ``nix flake lock`` writes ``flake.lock`` if missing and is a
    no-op when the lock is already up-to-date. The lock file is what we
    track as a DVC dep, so an out-of-date lock invalidates dependent
    stages on the next ``calkit run``.
    """
    env_path = env.get("path")
    if env_path is None:
        raise_error("Nix environments require a path pointing to flake.nix")
    assert isinstance(env_path, str)
    if os.path.basename(env_path) != "flake.nix":
        raise_error("Nix environments require a path pointing to flake.nix")
    if not os.path.isfile(env_path):
        raise_error(f"Nix flake not found: {env_path}")
    _require_nix_available()
    env_dir = os.path.dirname(os.path.abspath(env_path)) or "."
    cmd = [
        "nix",
        "--extra-experimental-features",
        "nix-command flakes",
        "flake",
        "lock",
    ]
    if verbose:
        typer.echo(f"Running command: {cmd} (cwd={env_dir})")
    try:
        subprocess.check_call(cmd, cwd=env_dir)
    except subprocess.CalledProcessError:
        raise_error("Failed to lock Nix flake")
    lock_fpath = os.path.join(os.path.dirname(env_path), "flake.lock")
    return lock_fpath


@check_app.command(name="repro")
def check_repro(
    wdir: Annotated[
        str, typer.Option("--wdir", help="Project working directory.")
    ] = ".",
    as_json: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
) -> None:
    """Check the reproducibility of a project."""
    from calkit.reproducibility import check_reproducibility

    res = check_reproducibility(wdir=wdir, log_func=typer.echo)
    if as_json:
        calkit.echo(res.model_dump_json(indent=2))
        return
    calkit.echo(res.to_pretty())
    if res.untraceable_literals:
        try:
            from rich.console import Console
            from rich.table import Table

            console = Console()
            table = Table(
                title="Untraceable Literals",
                title_justify="left",
                show_header=True,
                header_style="bold",
            )
            table.add_column("File", style="cyan")
            table.add_column("Line", justify="right")
            table.add_column("Col", justify="right")
            table.add_column("Value", style="red")
            table.add_column("Context")
            table.add_column("Suggestion")
            # One row per finding, in the order the checker sorted them
            for finding in res.untraceable_literals:
                table.add_row(
                    finding["file"],
                    str(finding["line"]),
                    str(finding["column"]),
                    finding["value"],
                    finding["context"],
                    finding["suggestion"],
                )
            calkit.echo("")
            console.print(table)
        except ImportError:
            pass


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
    from calkit.environments import (
        get_all_conda_lock_fpaths,
        get_all_docker_lock_fpaths,
        get_all_venv_lock_fpaths,
        get_default_venv_prefix,
        get_env_lock_fpath,
        write_scheduler_env_lock,
        write_system_env_lock,
    )

    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    ck_info = calkit.load_calkit_info()
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
        image = calkit.docker.get_image_name(env, env_name)
        if image is None:
            if not env.get("path"):
                raise_error(
                    f"Environment '{env_name}' must define an image, since "
                    "it has no Dockerfile to build one from"
                )
            raise_error(
                f"Cannot work out what to call the image for environment "
                f"'{env_name}': set 'image' on it, or set 'owner' and "
                "'name' in calkit.yaml"
            )
        check_docker_env(
            tag=image,
            fpath=env.get("path"),
            lock_fpath=lock_fpath,
            alt_lock_fpaths_delete=[str(legacy_lock_fpath)],
            alt_lock_fpaths=alt_lock_fpaths,
            platform=env.get("platform"),
            deps=calkit.environments.get_env_input_paths(env, env_name),
            env_vars=env.get("env_vars", []),
            ports=env.get("ports", []),
            gpus=env.get("gpus"),
            user=env.get("user"),
            wdir=env.get("wdir"),
            args=env.get("args", []),
            build_platforms=env.get("build_platforms", []),
            registry=env.get("registry"),
            lock_archs=calkit.docker.get_lock_archs(env),
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
        cmd = ["pixi", "install"]
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
        if "path" not in env:
            raise_error("venv environments require a path")
        path = os.path.expandvars(env["path"])
        # Resolve the prefix on the fly if it isn't pinned in calkit.yaml
        prefix = env.get("prefix")
        if prefix is None:
            prefix = get_default_venv_prefix(envs, path, env_name)
        prefix = os.path.expandvars(prefix)
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
        _check_julia_env(
            env_path=env_path,
            julia_version=julia_version,
            verbose=verbose,
            cache_key=env_name,
        )
    elif env["kind"] in ("slurm", "pbs"):
        # Job-scheduler envs have no external manifest to validate; the
        # "check" is just writing a deterministic JSON lock file from the
        # env config so DVC stages that depend on the env get invalidated
        # when the config changes.
        write_scheduler_env_lock(env_name=env_name, env=env)
    elif env["kind"] == "system":
        # Nothing is installed or built for a system env; checking it means
        # making sure the machine is as the project requires, then reading
        # the properties it declared it depends on and recording them, so
        # stages depending on the env see them change.
        if calkit.environments.env_is_local(env):
            try:
                calkit.check_requirements(
                    requirements=env.get("requirements", [])
                )
                write_system_env_lock(env_name=env_name, env=env)
            except ValueError as e:
                # A requirement that isn't met, or a property that can't be
                # locked -- a misspelled one, or a tool that isn't
                # installed. Both are the user's to fix. The remote branch
                # below already reports these; this one used to let them
                # out as a traceback.
                raise_error(f"Environment '{env_name}': {e}")
        else:
            # For a host that isn't this one, checking means getting to the
            # point where we can actually reach it -- better sorted out here
            # than partway through a pipeline -- and reading the properties
            # from that machine, since those are the ones the results
            # depend on.
            import calkit.workspace as workspace
            from calkit.dependencies import _is_interactive

            interactive = _is_interactive()
            ck_info = calkit.load_calkit_info()
            try:
                # Anything written as ${CK_SSH_HOST} is the first thing to
                # be missing for anyone but the project's author, since a
                # project shares its calkit.yaml but not its .env
                env = dict(env)
                for key in workspace.CONNECTION_FIELDS:
                    if isinstance(env.get(key), str):
                        env[key] = workspace.expand_with_prompts(
                            env[key],
                            interactive=interactive,
                            described_as=(
                                f"environment '{env_name}' "
                                f"{key.replace('_', ' ')}"
                            ),
                        )
                ws = workspace.Workspace.from_env(
                    env=env,
                    env_name=env_name,
                    ck_info=ck_info,
                )
                # Reassigned: a key created during setup belongs to the
                # workspace we go on to use
                ws = workspace.ensure_reachable(
                    ws, interactive=interactive, verbose=verbose
                )
                # Calkit is needed there to read the machine's properties,
                # and to activate an inner env, but an environment that
                # only dispatches a command never calls it. A declared
                # machine ID needs it for the same reason a lock does: the
                # far end is what reports its own ID, so it has to be asked.
                # Requirements only need it when one of them asks about the
                # machine itself rather than about what's installed on it.
                locks = bool(env.get("lock"))
                requirements = env.get("requirements", []) or []
                needs_system_info = (
                    locks
                    or bool(ws.machine_id)
                    or workspace.requirements_need_system_info(requirements)
                )
                workspace.ensure_calkit_installed(
                    ws,
                    interactive=interactive,
                    required=needs_system_info,
                    verbose=verbose,
                )
                system_info = None
                if needs_system_info:
                    system_info = workspace.remote_system_info(ws)
                    # Before anything else is decided from it, so a
                    # mismatched machine is reported rather than measured
                    # and recorded as what results depend on
                    workspace.verify_machine_id(ws, system_info)
                # Before the lock: a machine that doesn't meet the project's
                # requirements shouldn't have its properties written down as
                # though stages had run there.
                workspace.check_requirements(
                    ws,
                    requirements,
                    system_info=system_info,
                    verbose=verbose,
                )
                # Returns None when the env locks nothing, so nothing is
                # written for an env with nothing to record
                write_system_env_lock(
                    env_name=env_name,
                    env=env,
                    system_info=system_info,
                )
            except ValueError as e:
                raise_error(f"Environment '{env_name}': {e}")
    elif env["kind"] == "nix":
        check_nix_env(env=env, verbose=verbose)
    else:
        raise_error(f"Environment kind '{env['kind']}' not supported")
    return get_env_lock_fpath(env=env, env_name=env_name, as_posix=False)


@check_app.command(
    name="julia-env",
    help=(
        "Check a Julia environment and instantiate only when project, "
        "manifest, and package cache state have changed."
    ),
)
def check_julia_env(
    env_path: Annotated[
        str,
        typer.Argument(help="Path to Julia Project.toml file."),
    ] = "Project.toml",
    julia_version: Annotated[
        str | None,
        typer.Option(
            "--julia",
            help="Julia version to enforce (e.g., 1.11).",
        ),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print verbose output.")
    ] = False,
) -> str:
    return _check_julia_env(
        env_path=env_path,
        julia_version=julia_version,
        verbose=verbose,
    )


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
    ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    if not envs:
        typer.echo("No environments defined in calkit.yaml")
        return
    # Set any project-level environmental variables before checking
    # environments
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    calkit.set_env_vars(ck_info=ck_info, cli=True)
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
        except typer.Exit:
            # The check reported its own reason through raise_error, which
            # has already printed it. Repeating it here would replace a
            # real message ("Unknown system property to lock: ...") with
            # the exit code, since that is all this exception carries.
            failures.append(env_name)
        except Exception as e:
            warn(f"Error checking environment '{env_name}': {e}")
            failures.append(env_name)
    if failures:
        raise_error(
            f"Failed to check the following environments: {', '.join(failures)}"
        )


def _renv_snapshot_from_description(env_dir: str, verbose: bool) -> None:
    """Install packages from DESCRIPTION and (re)write renv.lock.

    Used to create the initial lock, to add newly declared packages, and as a
    fallback when an existing lock can't be restored (e.g. its versions don't
    build against the installed R version).
    """
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
        # Hydrate may fail if some packages aren't available; snapshot anyway
        if verbose:
            typer.echo("Warning: hydrate had issues, continuing to snapshot")
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


@check_app.command(name="renv")
def check_renv(
    env_path: Annotated[
        str,
        typer.Argument(
            help="Path to DESCRIPTION file or renv environment directory."
        ),
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", help="Print verbose output.")
    ] = False,
) -> None:
    """Check an renv R environment, initializing if needed."""
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
        # Install packages from DESCRIPTION and write the lock file
        if verbose:
            typer.echo("Setting up environment from DESCRIPTION")
        _renv_snapshot_from_description(env_dir, verbose=verbose)
    else:
        # A lock file exists, so treat it as the source of truth: restore the
        # library to the exact recorded versions rather than re-resolving from
        # DESCRIPTION (which would bump packages and overwrite the lock).
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
            restored = True
        except subprocess.CalledProcessError:
            restored = False
        if not restored:
            # The locked versions couldn't be installed (e.g. they don't build
            # against the installed R version). Fall back to re-resolving from
            # DESCRIPTION, which updates renv.lock to a working set.
            warn(
                f"Could not restore renv environment in {env_dir} from "
                "renv.lock; the locked versions may be incompatible with the "
                "installed R version. Re-resolving from DESCRIPTION and "
                "updating renv.lock."
            )
            _renv_snapshot_from_description(env_dir, verbose=verbose)
        else:
            # Only update the lock if DESCRIPTION declares dependencies the
            # lock doesn't cover (e.g. the user added a package). After the
            # restore the library matches the lock, so status is unsynchronized
            # only when DESCRIPTION and the lock genuinely disagree---not merely
            # because packages were missing on a fresh checkout.
            if verbose:
                typer.echo("Checking if DESCRIPTION matches lockfile")
            status_cmd = [
                "Rscript",
                "--vanilla",
                "-e",
                "renv::load(); cat(renv::status()$synchronized)",
            ]
            try:
                result = subprocess.run(
                    status_cmd,
                    cwd=env_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                in_sync = "TRUE" in result.stdout
            except subprocess.CalledProcessError:
                # If status fails, keep the lock rather than risk clobbering it
                in_sync = True
                if verbose:
                    typer.echo("Warning: status check failed, keeping lock")
            if not in_sync:
                if verbose:
                    typer.echo("DESCRIPTION changed; updating lockfile")
                _renv_snapshot_from_description(env_dir, verbose=verbose)
            elif verbose:
                typer.echo("Lockfile is already in sync with DESCRIPTION")


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
        typer.Option(
            "--platform",
            help=(
                "Platform to pull and run the image as, e.g., "
                "'linux/amd64'. Also used when building, unless "
                "--platform-build says otherwise."
            ),
        ),
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
    build_platforms: Annotated[
        list[str],
        typer.Option(
            "--platform-build",
            help=(
                "Platform to build the image for, as opposed to --platform, "
                "which is the one it's pulled and run as. Repeat for a "
                "multi-platform image, which requires a registry."
            ),
        ),
    ] = [],
    registry: Annotated[
        str | None,
        typer.Option(
            "--registry",
            help=(
                "Registry prefix to push built images to and pull them from, "
                "e.g., 'ghcr.io/someone/some-project', or 'none' to disable."
            ),
        ),
    ] = None,
    lock_archs: Annotated[
        list[str],
        typer.Option(
            "--lock-arch",
            help=(
                "Architecture to write an additional lock file for, "
                "alongside this machine's, e.g., 'amd64'."
            ),
        ),
    ] = [],
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Be quiet.")
    ] = False,
) -> None:
    """Check that Docker environment is up-to-date."""
    from calkit import docker as ck_docker
    from calkit.environments import get_docker_arch

    if fpath is None and lock_fpath is None:
        raise_error(
            "Lock file output path must be provided if input Dockerfile is not"
        )
    outfile = open(os.devnull, "w") if quiet else None
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

    def read_lock(path: str) -> dict | None:
        # A lock that can't be read is treated as one that isn't there:
        # rebuilding is always an option, so there's no reason to fail
        try:
            with open(path) as f:
                loaded = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # Handle legacy lock files that are lists
        if isinstance(loaded, list):
            loaded = loaded[0] if loaded else None
        return loaded if isinstance(loaded, dict) else None

    # Read the lock file, falling back to legacy paths and then to other
    # architectures, which still identify the image well enough to pull it
    lock = None
    lock_is_current_arch = False
    if os.path.isfile(lock_fpath):
        typer.echo(f"Reading lock file: {lock_fpath}", file=outfile)
        lock = read_lock(lock_fpath)
        lock_is_current_arch = lock is not None
    else:
        typer.echo(f"Lock file ({lock_fpath}) does not exist", file=outfile)
        for alt_lock_fpath in alt_lock_fpaths_delete:
            if os.path.isfile(alt_lock_fpath):
                typer.echo(f"Reading alternative lock file: {alt_lock_fpath}")
                lock = read_lock(alt_lock_fpath)
                # A legacy lock was written before locks were kept per
                # architecture, by the machine that checked the
                # environment, so it describes this one. Taking it for
                # another architecture's would skip checking the local image
                # against it, and an image left under this tag by something
                # else would be locked in as this environment's
                lock_is_current_arch = lock is not None
                os.remove(alt_lock_fpath)
                break
        if lock is None:
            for alt_lock_fpath in alt_lock_fpaths:
                if os.path.isfile(alt_lock_fpath):
                    typer.echo(
                        f"Reading alternative lock file: {alt_lock_fpath}"
                    )
                    lock = read_lock(alt_lock_fpath)
                    if lock is not None:
                        break
    # A lock that doesn't describe the current spec is stale, not merely
    # out-of-date with the local image: the image it identifies was built
    # from a different Dockerfile or dependencies, so it must not be pulled
    # in place of the one asked for
    if lock is not None and not ck_docker.lock_matches_spec(
        lock, dockerfile_md5=dockerfile_md5, deps_md5s=deps_md5s
    ):
        typer.echo(
            "Lock file does not match the current environment", file=outfile
        )
        lock = None
        lock_is_current_arch = False
    # Work out where this image lives in a registry, so it can be pulled
    # instead of rebuilt, and pushed after being built. Only an image built
    # from a Dockerfile goes to the project's registry; one named directly
    # already lives somewhere it can be pulled back from.
    remote_ref = None
    registry_prefix = ck_docker.resolve_registry_prefix(
        {"registry": registry, "path": fpath}
    )
    if registry_prefix is None and ck_docker.registry_is_auto(registry):
        warn(
            "Could not work out a registry for this project; name one "
            "explicitly, e.g., 'ghcr.io/someone/some-project', or set "
            "a GitHub remote"
        )
    remote_repo = None
    if registry_prefix is not None and fpath is not None:
        remote_ref = ck_docker.get_remote_image_ref(tag, registry_prefix)
        remote_repo = ck_docker.get_repo_from_ref(remote_ref)
    # Where a digest the lock records can be pulled from, since the lock
    # names the digest alone: the project's registry for an image we build,
    # or the image's own repo for one named directly. Working this out from
    # the environment definition rather than the lock is what stops a digest
    # left over from a different image resolving to anything
    digest_source_ref = remote_ref if remote_ref is not None else tag
    typer.echo(f"Checking for existing image with tag {tag}", file=outfile)
    identity = ck_docker.inspect_image_for_lock(tag)
    if identity is None:
        typer.echo(f"No image with tag {tag} found locally", file=outfile)
    # Only a lock for this architecture can say whether the image here is
    # the one it describes: another architecture's layers never match, so
    # its lock is taken as an instruction to fetch the image it names rather
    # than as a blessing for whatever happens to carry this tag
    up_to_date = (
        identity is not None
        and lock is not None
        and lock_is_current_arch
        and ck_docker.lock_matches_image(lock, identity)
    )

    def delete_lock_on_failure() -> None:
        if lock_fpath and os.path.exists(lock_fpath):
            os.remove(lock_fpath)

    pulled_from_registry = False
    already_pushed = False
    built = False
    if not up_to_date:
        obtained = False
        # Prefer pulling the exact image the lock identifies, since a rebuild
        # can't reproduce it, and would silently pick up whatever its
        # undeclared upstream dependencies have become
        if lock is not None:
            for digest_ref in ck_docker.get_lock_digest_refs(
                lock, digest_source_ref
            ):
                typer.echo(f"Pulling image by digest: {digest_ref}")
                # A private image needs credentials we may be able to get,
                # but only a registry that refused us is worth logging in to
                if not ck_docker.pull_image_with_login(
                    digest_ref, platform=platform
                ):
                    warn(f"Failed to pull image by digest: {digest_ref}")
                    continue
                if not ck_docker.tag_image(digest_ref, tag):
                    warn(f"Failed to tag pulled image as {tag}")
                    continue
                identity = ck_docker.inspect_image_for_lock(tag)
                if identity is None:
                    continue
                if lock_is_current_arch and not ck_docker.lock_matches_image(
                    lock, identity
                ):
                    warn(
                        f"Image pulled from {digest_ref} does not match the "
                        "lock file"
                    )
                    continue
                obtained = True
                pulled_from_registry = (
                    remote_repo is not None
                    and digest_ref.split("@", 1)[0] == remote_repo
                )
                break
        # A lock from another architecture named an image we've now tried
        # to pull. Failing that, an image already here was built from this
        # same spec, so it stands rather than being rebuilt for a lock that
        # was never able to describe it
        if (
            not obtained
            and identity is not None
            and lock is not None
            and not lock_is_current_arch
        ):
            obtained = True
        # Fall back to an image archived in a release, since a registry makes
        # no promise to keep an image forever, and rebuilding can't reproduce
        # one whose upstream dependencies have moved on
        if not obtained and lock is not None and lock_is_current_arch:
            layers = (lock.get("RootFS") or {}).get("Layers") or []
            archived = calkit.releases.find_archived_docker_image(layers)
            if archived is not None:
                release_name, image_id, entry = archived
                typer.echo(
                    f"Fetching image archived in release '{release_name}'"
                )
                if calkit.releases.fetch_archived_docker_image(
                    release_name, entry
                ) and ck_docker.tag_image(image_id, tag):
                    identity = ck_docker.inspect_image_for_lock(tag)
                    if identity is not None and ck_docker.lock_matches_image(
                        lock, identity
                    ):
                        obtained = True
                    else:
                        warn(
                            f"Image archived in release '{release_name}' does "
                            "not match the lock file"
                        )
                else:
                    warn(
                        "Failed to fetch image archived in release "
                        f"'{release_name}'"
                    )
        if not obtained and fpath is not None:
            dockerfile_dir, dockerfile_name = os.path.split(fpath)
            build_cwd = dockerfile_dir if dockerfile_dir else None
            # A multi-platform image can't live in the local image store, so
            # it's built straight into the registry and pulled back for the
            # platform we're on
            multi_platform = len(build_platforms) > 1
            if multi_platform and remote_ref is None:
                raise_error(
                    "Building for multiple platforms requires a registry; "
                    "set 'registry' on this environment"
                )
            if multi_platform:
                assert remote_ref is not None
                cmd = [
                    "docker",
                    "buildx",
                    "build",
                    "--platform",
                    ",".join(build_platforms),
                    "-t",
                    remote_ref,
                    "--push",
                    "-f",
                    dockerfile_name,
                    ".",
                ]
            else:
                cmd = ["docker", "build", "-t", tag, "-f", dockerfile_name]
                build_platform = (
                    build_platforms[0] if build_platforms else platform
                )
                if build_platform is not None:
                    cmd += ["--platform", build_platform]
                cmd.append(".")
            try:
                subprocess.check_output(cmd, cwd=build_cwd)
            except subprocess.CalledProcessError:
                delete_lock_on_failure()
                raise_error(
                    f"Failed to build Docker image with tag {tag} from {fpath}"
                )
            built = True
            if multi_platform:
                assert remote_ref is not None
                already_pushed = True
                if not ck_docker.pull_image_with_login(
                    remote_ref, platform=platform
                ) or not ck_docker.tag_image(remote_ref, tag):
                    delete_lock_on_failure()
                    raise_error(
                        f"Failed to pull image back from {remote_ref} after "
                        "building it"
                    )
        elif not obtained:
            typer.echo(f"Pulling image: {tag}")
            if not ck_docker.pull_image_with_login(tag, platform=platform):
                delete_lock_on_failure()
                raise_error(f"Failed to pull image: {tag}")
    identity = ck_docker.inspect_image_for_lock(tag)
    if identity is None:
        delete_lock_on_failure()
        raise_error(f"Failed to inspect image with tag {tag}")
    assert identity is not None
    # Checking an environment doesn't publish it: that's what 'calkit push'
    # is for. A multi-platform build is the exception, since buildx has
    # nowhere but the registry to put the image it assembles.
    pushed = already_pushed
    # A digest already recorded for the project's own registry stands, since
    # it says the image got there on some earlier push or pull. The image's
    # own digests can't answer this: tagging one for a registry gives it a
    # digest under that repo whether or not anything was ever sent.
    lock_remote_digests = []
    if lock is not None and remote_repo is not None:
        lock_remote_digests = [
            d
            for d in (lock.get("RepoDigests") or [])
            # A digest recorded bare is one this project put in its own
            # registry, since that's the only kind it records; locks written
            # before digests were stored bare name their repo outright
            if "@" not in d or d.split("@", 1)[0] == remote_repo
        ]
    # A digest belongs in the lock whenever there's a registry to pull it
    # from. An image store that keeps a manifest gives a build the digest it
    # will have once pushed, since a manifest is content-addressed, so it
    # can be recorded before the push and a clone pulls the image as soon as
    # anyone sends it. One that doesn't has to be pushed to learn it.
    if remote_ref is not None:
        if pushed or pulled_from_registry:
            remote_digests = ck_docker.keep_only_repo_digests(
                identity, remote_ref
            )["RepoDigests"]
        elif lock is not None and ck_docker.lock_matches_image(lock, identity):
            # Still the same image an earlier run verified, so what it
            # recorded stands and the lock doesn't churn. A lock written
            # before digests were taken from the build recorded none, and
            # keeping that would leave the gap in place for as long as the
            # image goes unrebuilt, so the image's own digest fills it
            remote_digests = (
                lock_remote_digests or ck_docker.get_content_digests(identity)
            )
        else:
            remote_digests = ck_docker.get_content_digests(identity)
        # An image store that keeps no manifest gives a build no digest of
        # its own: a manifest names the compressed layers, and nothing
        # compresses them until a push. Pushing is then the only way to
        # learn the digest, and a lock without one sends everyone else back
        # to rebuilding an image that's sitting in the registry.
        if not remote_digests and fpath is not None:
            typer.echo(
                f"Pushing image to {remote_ref} to record its digest, since "
                "this Docker engine only assigns one on a push"
            )
            if not ck_docker.tag_image(tag, remote_ref):
                warn(f"Failed to tag image as {remote_ref}")
            else:
                # Checks run inside pipelines, so a missing credential is
                # reported rather than prompted for
                pushed_ok, push_output = ck_docker.push_image_with_login(
                    remote_ref
                )
                if pushed_ok:
                    pushed_identity = ck_docker.inspect_image_for_lock(tag)
                    if pushed_identity is not None:
                        identity = pushed_identity
                    remote_digests = ck_docker.keep_only_repo_digests(
                        identity, remote_ref
                    )["RepoDigests"]
                else:
                    # Leaving the tag would fake a registry digest on the
                    # image, making every later push look unnecessary
                    ck_docker.untag_image(remote_ref)
                    warn(
                        f"Failed to push image to {remote_ref}; its lock "
                        "file will record no digest, so anyone else who "
                        "uses this project will rebuild this image rather "
                        "than pull it\n"
                        + textwrap.indent(push_output.strip()[-500:], "    ")
                    )
        identity = dict(identity, RepoDigests=remote_digests)
    elif fpath is None:
        # An environment named after someone else's image is pullable by
        # whatever digests it arrived with
        identity = ck_docker.keep_only_repo_digests(identity, tag)
    else:
        # An image built where the store assigns no digest, with no registry
        # to send it to, leaves nothing in the lock that anyone could pull
        if built and not ck_docker.get_content_digests(identity):
            warn(
                "This Docker engine only assigns an image a digest when "
                "it's pushed, so this environment's lock file will record "
                "none, and anyone else who uses this project will rebuild "
                "the image rather than pull it; set 'registry' on the "
                "environment to publish it and record its digest"
            )
        identity = ck_docker.keep_only_repo_digests(identity, None)
    # Read the other platforms from the exact image this one locked, rather
    # than from the tag. A tag moves, and asking it again would lock the
    # other platforms to whatever it points at now, leaving one set of lock
    # files describing two different builds. Going by digest gives every
    # platform the same image and its own layers within it.
    remote_source_ref = None
    if identity["RepoDigests"]:
        remote_source_ref = ck_docker.get_lock_digest_refs(
            identity, digest_source_ref
        )[0]
    elif fpath is None:
        remote_source_ref = tag
    # Run configuration doesn't affect which image we need, but does affect
    # how stages run in it, so it belongs in the lock to invalidate them
    run_config: dict = {}
    if platform is not None:
        run_config["Platform"] = platform
    if wdir is not None:
        run_config["WorkDir"] = wdir
    if user is not None:
        run_config["User"] = user
    if env_vars:
        run_config["EnvVars"] = env_vars
    if ports:
        run_config["Ports"] = ports
    if gpus:
        run_config["GPUs"] = gpus
    if args:
        run_config["Args"] = args

    def write_lock(arch: str, arch_identity: dict) -> None:
        if arch == current_arch:
            arch_lock_fpath = lock_fpath
        else:
            arch_lock_fpath = os.path.join(lock_dir, arch + ".json")
        arch_lock = ck_docker.build_lock(
            identity=arch_identity,
            dockerfile_md5=dockerfile_md5,
            deps_md5s=deps_md5s,
            run_config=run_config,
        )
        with open(arch_lock_fpath, "w") as f:
            json.dump(arch_lock, f, indent=4)

    current_arch = get_docker_arch()
    lock_dir = os.path.dirname(lock_fpath)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    write_lock(current_arch, identity)
    # Lock the platforms this machine can't run, so that moving the project
    # to one of them doesn't invalidate every stage in the environment. An
    # existing lock that still describes this spec is reused rather than
    # re-read from the registry, which keeps checks working offline
    stale_archs = []
    contradicted = False
    for arch in [a for a in lock_archs if a != current_arch]:
        arch_lock_fpath = os.path.join(lock_dir, arch + ".json")
        existing = (
            read_lock(arch_lock_fpath)
            if os.path.isfile(arch_lock_fpath)
            else None
        )
        if (
            existing is not None
            and ck_docker.lock_matches_spec(
                existing,
                dockerfile_md5=dockerfile_md5,
                deps_md5s=deps_md5s,
            )
            and ck_docker.get_content_digests(existing)
            == ck_docker.get_content_digests(identity)
        ):
            write_lock(arch, existing)
        else:
            # A lock naming a different image than this platform's describes
            # another build entirely, and leaving one set of lock files
            # saying two things is worse than the round-trip to settle it
            contradicted = contradicted or existing is not None
            stale_archs.append(arch)
    # Asking the registry which platforms it serves costs a round-trip, and
    # the answer only changes when the image does. An image that's still the
    # one the lock describes was already asked about on the run that locked
    # it, so a platform the registry doesn't publish isn't asked about again
    # on every check from then on. Nothing is removed either, since a lock
    # can only be judged stale against an answer we actually have.
    if (
        stale_archs
        and remote_source_ref is not None
        and (not up_to_date or contradicted)
    ):
        typer.echo(
            f"Reading platforms available for {remote_source_ref}",
            file=outfile,
        )
        remote_locks = ck_docker.get_remote_image_platform_locks(
            remote_source_ref
        )
        if remote_locks is None:
            # Being unable to ask says nothing about what the registry
            # serves, and a lock can only be judged stale against an answer
            # we actually have, so the other platforms' locks stand
            typer.echo(
                f"Could not read platforms available for {remote_source_ref}",
                file=outfile,
            )
        else:
            for arch in stale_archs:
                arch_lock_fpath = os.path.join(lock_dir, arch + ".json")
                if arch in remote_locks:
                    write_lock(arch, remote_locks[arch])
                elif os.path.isfile(arch_lock_fpath):
                    # A lock left behind for a platform this image no longer
                    # has would describe an image built from something else
                    os.remove(arch_lock_fpath)


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
            lock_fpath=output_fpath,
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
    prefix_full_path = (
        prefix if os.path.isabs(prefix) else os.path.join(wdir or ".", prefix)
    )

    def create_venv() -> None:
        if verbose:
            typer.echo(f"Creating {kind} at {prefix}")
        try:
            subprocess.check_call(create_cmd + [prefix], cwd=wdir)
        except subprocess.CalledProcessError:
            raise_error(f"Failed to create {kind} at {prefix}")
        # Put a gitignore file in the env dir if one doesn't exist
        gitignore_fpath = os.path.join(prefix_full_path, ".gitignore")
        if not os.path.isfile(gitignore_fpath):
            with open(gitignore_fpath, "w") as f:
                f.write("*\n")

    def venv_was_moved() -> bool:
        """Check if the venv's activate script points somewhere else.

        Renaming or moving a project leaves the absolute path baked into the
        activate script pointing at the old location, so activating prepends a
        nonexistent directory to PATH and commands silently resolve to whatever
        is outside the environment.
        """
        if _platform.system() == "Windows":
            activate_fpath = os.path.join(
                prefix_full_path, "Scripts", "activate.bat"
            )
        else:
            activate_fpath = os.path.join(prefix_full_path, "bin", "activate")
        if not os.path.isfile(activate_fpath):
            return True
        with open(activate_fpath) as f:
            content = f.read()
        this_prefix = os.path.abspath(prefix_full_path)
        return os.path.normcase(this_prefix) not in os.path.normcase(content)

    if not os.path.isdir(prefix_full_path):
        create_venv()
    elif venv_was_moved():
        if not quiet:
            typer.echo(f"Recreating {kind} at {prefix} since it was moved")
        # uv refuses to create over an existing env, and packages are
        # reinstalled from the lock file below
        try:
            shutil.rmtree(prefix_full_path)
            create_venv()
        except OSError as e:
            # Removal can fail if the environment is in use, e.g., on Windows,
            # where files can't be removed while open, in which case we keep
            # it and let the install below attempt a rebuild
            warn(f"Failed to remove {kind} at {prefix}: {e}")
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
            if os.path.isdir(prefix_full_path):
                # This can fail if the environment is in use, e.g., on
                # Windows, where files can't be removed while open, in which
                # case we keep it and fall back to rebuilding from the spec
                shutil.rmtree(prefix_full_path)
            create_venv()
            pip_install_and_freeze(dep_file_txt)
        except (subprocess.CalledProcessError, OSError):
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


@check_app.command(
    name="deps|dependencies",
    hidden=True,
    help=(
        "Check that a project's system-level requirements are met "
        "(alias for 'reqs')."
    ),
)
@check_app.command(name="reqs|requirements")
def check_project_requirements(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output")
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help=(
                "Re-probe every setup requirement, ignoring (and clearing) "
                "the cache at .calkit/local/dep-checks.sqlite."
            ),
        ),
    ] = False,
) -> None:
    """Check that a project's system-level requirements are met."""
    typer.echo("Checking project requirements")
    dotenv.load_dotenv(dotenv_path=".env", verbose=verbose)
    if no_cache:
        calkit.dependencies.cache_clear()
    try:
        calkit.check_requirements(use_cache=not no_cache)
    except Exception as e:
        raise_error(str(e))
    message = "✅ All set!"
    calkit.echo(message)


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
    deps = calkit.get_requirements(ck_info)
    env_var_dep_names = calkit.get_env_var_dep_names(ck_info)
    for name in env_var_dep_names:
        if verbose:
            typer.echo(f"Checking for environmental variable '{name}'")
        # Pull the dep's attrs to honor any per-var default.
        attrs: dict = {}
        for dep in deps:
            if isinstance(dep, dict) and dep.get("name") == name:
                attrs = dep
                break
            if isinstance(dep, dict) and list(dep.keys()) == [name]:
                attrs = dep[name] or {}
                break
        if name not in os.environ:
            typer.echo(f"Missing env var '{name}'")
            value = calkit.dependencies.prompt_and_store_env_var(
                name, default=attrs.get("default")
            )
            if value is None:
                raise_error(f"No value provided for '{name}'")
    message = "✅ All set!"
    calkit.echo(message)


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
    calkit.echo(message)
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
