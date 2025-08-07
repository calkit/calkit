"""Notebooks CLI."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import PurePosixPath
from typing import Any

import papermill
import typer
from typing_extensions import Annotated

import calkit.notebooks
from calkit.cli.core import raise_error

notebooks_app = typer.Typer(no_args_is_help=True)


@notebooks_app.command("clean")
def clean_notebook_outputs(path: str):
    """Clean notebook and place a copy in the cleaned notebooks directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    fpath_out = calkit.notebooks.get_cleaned_notebook_path(path)
    folder = os.path.dirname(fpath_out)
    os.makedirs(folder, exist_ok=True)
    fpath_out = os.path.abspath(fpath_out)
    subprocess.call(
        [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            path,
            "--clear-output",
            "--to",
            "notebook",
            "--output",
            fpath_out,
        ]
    )


def _parse_params(params: list[str]) -> dict[str, Any]:
    """Parse parameters from command line arguments."""
    parameters = {}
    for param in params:
        if "=" not in param:
            raise ValueError(f"Parameter must be in key=value format: {param}")
        key, value = param.split("=", 1)
        # Try to convert to appropriate types
        try:
            if "." in value:
                parameters[key] = float(value)
            elif value.isdigit() or (
                value.startswith("-") and value[1:].isdigit()
            ):
                parameters[key] = int(value)
            elif value.lower() in ("true", "false"):
                parameters[key] = value.lower() == "true"
            else:
                parameters[key] = value
        except ValueError:
            parameters[key] = value
    return parameters


@notebooks_app.command("check-env-kernel")
def check_env_kernel(
    env_name: Annotated[
        str,
        typer.Option(
            "--environment",
            "-e",
            help="Environment name in which to run the notebook.",
        ),
    ],
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check", help="Do not check environment before executing."
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Check that an environment has a registered kernel."""
    from calkit.cli.main import run_in_env

    project_name = calkit.detect_project_name(prepend_owner=False)
    kernel_name = calkit.to_kebab_case(f"{project_name}-{env_name}")
    cmd = [
        "python",
        "-m",
        "ipykernel",
        "install",
        "--user",
        "--name",
        kernel_name,
        "--display-name",
        f"{project_name}: {env_name}",
    ]
    run_in_env(cmd=cmd, env_name=env_name, no_check=no_check, verbose=verbose)
    return kernel_name


@notebooks_app.command("execute")
def execute_notebook(
    path: str,
    env_name: Annotated[
        str,
        typer.Option(
            "--environment",
            "-e",
            help="Environment name in which to run the notebook.",
        ),
    ],
    to: Annotated[
        list[str],
        typer.Option("--to", help="Output format ('html' or 'notebook')."),
    ] = ["notebook"],
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check", help="Do not check environment before executing."
        ),
    ] = False,
    params: Annotated[
        list[str],
        typer.Option(
            "--param",
            "-p",
            help="Parameter to pass to the notebook in key=value format.",
        ),
    ] = [],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Execute notebook and place a copy in the relevant directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    from calkit.cli.main import run_in_env

    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    # First, ensure the specified environment has a kernel we can use
    kernel_name = check_env_kernel(
        env_name=env_name, no_check=no_check, verbose=verbose
    )
    # Parse parameters
    if params:
        try:
            parsed_params = _parse_params(params)
        except ValueError as e:
            raise_error(str(e))
    else:
        parsed_params = {}
    # Next, always execute the notebook and save as ipynb
    fpath_out_exec = calkit.notebooks.get_executed_notebook_path(
        notebook_path=path,
        to="notebook",
        as_posix=True,
        parameters=parsed_params,
    )
    folder = os.path.dirname(fpath_out_exec)
    os.makedirs(folder, exist_ok=True)
    notebook_dir = os.path.dirname(path) or None
    papermill.execute_notebook(
        input_path=path,
        output_path=fpath_out_exec,
        kernel_name=kernel_name,
        log_output=True,
        parameters=parsed_params,
        cwd=notebook_dir,
    )
    for to_fmt in to:
        if to_fmt != "notebook":
            try:
                fpath_out = calkit.notebooks.get_executed_notebook_path(
                    notebook_path=path,
                    to=to_fmt,  # type: ignore
                    parameters=parsed_params,
                )
            except ValueError:
                raise_error(f"Invalid output format: '{to}'")
            folder = os.path.dirname(fpath_out)
            os.makedirs(folder, exist_ok=True)
            fname_out = os.path.basename(fpath_out)
            # Now convert without executing or checking the environment
            cmd = [
                sys.executable,
                "-m",
                "jupyter",
                "nbconvert",
                fpath_out_exec,
                "--to",
                to_fmt,
                "--output-dir",
                PurePosixPath(folder).as_posix(),
                "--output",
                fname_out,
            ]
            typer.echo(f"Exporting {to_fmt}")
            run_in_env(
                cmd=cmd, env_name=env_name, no_check=True, verbose=verbose
            )
