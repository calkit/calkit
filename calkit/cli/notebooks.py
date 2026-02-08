"""Notebooks CLI."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from typing_extensions import Annotated

import calkit
import calkit.notebooks
from calkit.cli.core import raise_error

notebooks_app = typer.Typer(no_args_is_help=True)


@notebooks_app.command("clean")
def clean_notebook_outputs(
    path: str,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Do not print output.")
    ] = False,
):
    """Clean notebook and place a copy in the cleaned notebooks directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    if os.path.isabs(path):
        raise_error("Path must be relative")
    if not quiet:
        typer.echo(f"Cleaning notebook: {path}")
    try:
        calkit.notebooks.clean_notebook_outputs(path)
    except Exception as e:
        raise_error(str(e))


@notebooks_app.command("clean-all")
def clean_all_in_pipeline(
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Do not print output.")
    ] = False,
):
    """Clean all notebooks in the pipeline."""
    if not quiet:
        typer.echo("Cleaning all notebooks in pipeline")
    try:
        cleaned = calkit.notebooks.clean_all_in_pipeline()
        if not quiet:
            for path in cleaned:
                typer.echo(f"Cleaned: {path}")
    except Exception as e:
        raise_error(str(e))


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


@notebooks_app.command("check-kernel")
def check_env_kernel(
    env_name: Annotated[
        str,
        typer.Option(
            "--environment",
            "--env",
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
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            "-l",
            help=(
                "Notebook language; if 'matlab', MATLAB kernel must be "
                "available in environment."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Check that an environment has a registered Jupyter kernel."""
    from calkit.cli.check import check_environment
    from calkit.cli.main import run_in_env

    def get_env():
        ck_info = calkit.load_calkit_info()
        envs = ck_info.get("environments", {})
        if env_name not in envs:
            raise_error(
                f"No environment '{env_name}' defined for this project"
            )
        return envs[env_name]

    env = None
    # Detect language from environment
    if language is None:
        env = get_env()
        if env.get("kind") == "julia":
            language = "julia"
        else:
            language = "python"
    project_name = calkit.detect_project_name(prepend_owner=False)
    kernel_name = calkit.to_kebab_case(f"{project_name}-{env_name}")
    display_name = f"{project_name}: {env_name}"
    if language == "python":
        cmd = [
            "python",
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            kernel_name,
            "--display-name",
            display_name,
        ]
        res = run_in_env(
            cmd=cmd,
            env_name=env_name,
            no_check=no_check,
            verbose=verbose,
            relaxed_check=True,
        )
        return kernel_name
    elif language == "julia":
        if not no_check:
            check_environment(env_name=env_name, verbose=verbose)
        if env is None:
            env = get_env()
        env_path = env.get("path")
        julia_version = env.get("julia")
        env_fname = os.path.basename(env_path)
        if not env_fname == "Project.toml":
            raise_error(
                "Julia environments require a path pointing to Project.toml"
            )
        env_dir = os.path.dirname(env_path)
        if not env_dir:
            env_dir = "."
        julia_cmd = (
            "import IJulia;"
            "kp=IJulia.installkernel("
            f'"{display_name}",'
            '"--project=@.",'
            'env=Dict("JULIA_LOAD_PATH" => "@:@stdlib")'
            ");"
            "println(kp);"
        )
        cmd = [
            "julia",
            f"+{julia_version}",
            "--project=" + env_dir,
            "-e",
            julia_cmd,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise_error(f"Failed to create kernel:\n{res.stdout}")
        kernel_path = res.stdout.strip()
        typer.echo(f"Registered IJulia kernel at: {kernel_path}")
        kernel_name = os.path.basename(kernel_path)
        return kernel_name
    else:
        raise_error(f"{language} not supported")


@notebooks_app.command("exec", help="Alias for 'execute'.")
@notebooks_app.command("execute")
def execute_notebook(
    path: str,
    env_name: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help=(
                "Name or path to the spec of the environment in which "
                "to run the notebook."
            ),
        ),
    ] = None,
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
    params_json: Annotated[
        str | None,
        typer.Option(
            "--params-json",
            "-j",
            help=(
                "JSON string to parse as parameters to pass to the notebook."
            ),
        ),
    ] = None,
    params_base64: Annotated[
        str | None,
        typer.Option(
            "--params-base64",
            "-b",
            help=(
                "Base64-encoded JSON string to parse as parameters to pass to "
                "the notebook."
            ),
        ),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option(
            "--language",
            "-l",
            help=(
                "Notebook language; if 'matlab', MATLAB kernel must be "
                "available in environment."
            ),
        ),
    ] = None,
    no_replace: Annotated[
        bool,
        typer.Option(
            "--no-replace",
            help="Do not replace notebook outputs from executed version.",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Execute notebook and place a copy in the relevant directory.

    This can be useful to use as a preprocessing DVC stage to use a clean
    notebook as a dependency for a stage that caches and executed notebook.
    """
    import papermill

    from calkit.cli.main import run_in_env
    from calkit.environments import (
        env_from_name_or_path,
        env_from_notebook_path,
    )

    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    # Detect environment
    ck_info = calkit.load_calkit_info()
    envs = ck_info.get("environments", {})
    if env_name is not None:
        res = env_from_name_or_path(env_name, ck_info=ck_info)
        env = res.env
        env_name = res.name
    else:
        try:
            res = env_from_notebook_path(path, ck_info=ck_info)
            typer.echo(
                f"Detected environment '{res.name}' for notebook '{path}'"
            )
            env = res.env
            env_name = res.name
        except Exception:
            raise_error(f"Could not detect environment for notebook: {path}")
            return  # For typing analysis since raise_error exits
    if not res.exists:
        # Create this environment and write it to file
        envs[res.name] = res.env
        ck_info["environments"] = envs
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
    # Detect language from environment
    if language is None:
        env = envs[env_name]
        if env.get("kind") == "julia":
            language = "julia"
        else:
            language = "python"
        typer.echo(f"Using {language} as notebook language")
    if language.lower() not in ["python", "matlab", "julia"]:
        raise ValueError(
            "Language must be one of 'python', 'matlab', or 'julia'"
        )
    # First, ensure the specified environment has a kernel we can use
    # We need to check the environment type and create the kernel if needed
    if language.lower() in ["python", "julia"]:
        kernel_name = check_env_kernel(
            env_name=env_name, no_check=no_check, verbose=verbose
        )
    elif language.lower() == "matlab":
        kernel_name = "jupyter_matlab_kernel"
    # We can't handle parameters unless language is Python or Julia
    if language.lower() not in ["python", "julia"]:
        if params or params_json is not None or params_base64 is not None:
            raise_error("Parameters can only be passed to Python notebooks")
    # Parse parameters
    if params:
        try:
            parsed_params = _parse_params(params)
        except ValueError as e:
            raise_error(str(e))
    else:
        parsed_params = {}
    # Parse JSON parameters
    if params_json is not None:
        parsed_params_json = json.loads(params_json)
        parsed_params |= parsed_params_json
    # Parse base64 parameters
    if params_base64 is not None:
        try:
            decoded_json = base64.b64decode(params_base64).decode("utf-8")
            parsed_params |= json.loads(decoded_json)
        except Exception as e:
            raise_error(f"Failed to parse base64 parameters: {e}")
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
    if verbose:
        typer.echo(f"Executing notebook {path} with params: {parsed_params}")
        typer.echo(f"Using kernel: {kernel_name}")
        typer.echo(f"Running with cwd: {notebook_dir}")
        typer.echo(f"Output will be saved to: {fpath_out_exec}")
    # If this is a Python or Julia notebook, we can use Papermill
    # If it's a MATLAB notebook, we need to use the MATLAB kernel inside the
    # specified environment
    if language.lower() in ["python", "julia"]:
        papermill.execute_notebook(
            input_path=path,
            output_path=fpath_out_exec,
            kernel_name=kernel_name,
            log_output=True,
            parameters=parsed_params,
            cwd=notebook_dir,
        )
    elif language.lower() == "matlab":
        # Use nbconvert to execute the notebook with the MATLAB kernel
        cmd = [
            "python",
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            f"--ExecutePreprocessor.kernel_name={kernel_name}",
            "--output",
            fpath_out_exec,
            path,
        ]
        run_in_env(cmd, env_name=env_name, no_check=no_check, verbose=verbose)
    if not no_replace:
        # Replace original notebook outputs with those from executed version
        with open(fpath_out_exec, "r") as f:
            executed_nb = json.load(f)
        with open(path, "r") as f:
            original_nb = json.load(f)
        for orig_cell, exec_cell in zip(
            original_nb.get("cells", []), executed_nb.get("cells", [])
        ):
            if "outputs" in orig_cell and "outputs" in exec_cell:
                orig_cell["outputs"] = exec_cell["outputs"]
            if (
                "execution_count" in orig_cell
                and "execution_count" in exec_cell
            ):
                orig_cell["execution_count"] = exec_cell["execution_count"]
        with open(path, "w") as f:
            json.dump(original_nb, f, indent=1)
    for to_fmt in to:
        if to_fmt != "notebook":
            try:
                fpath_out = calkit.notebooks.get_executed_notebook_path(
                    notebook_path=path,
                    to=to_fmt,  # type: ignore
                    parameters=parsed_params,
                )
            except ValueError:
                raise_error(f"Invalid output format: '{to_fmt}'")
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
                Path(folder).as_posix(),
                "--output",
                fname_out,
            ]
            typer.echo(f"Exporting {to_fmt}")
            p = subprocess.run(cmd)
            if p.returncode != 0:
                raise_error(f"nbconvert failed for format '{to_fmt}'")
