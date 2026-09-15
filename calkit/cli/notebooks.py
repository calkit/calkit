"""Notebooks CLI."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from typing_extensions import Annotated

import calkit
import calkit.notebooks
from calkit.cli.core import raise_error, warn

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


def _check_ijulia_available(
    julia_version: str,
    env_dir: str,
) -> bool:
    ijulia_check_cmd = [
        calkit.julia.get_julia_exe(),
        f"+{julia_version}",
        "--project=" + env_dir,
        "-e",
        (
            "import Pkg; "
            "deps = Pkg.project().dependencies; "
            'if !haskey(deps, "IJulia"); '
            'println("IJulia is not in this Julia project environment."); '
            "exit(3); "
            "end"
        ),
    ]
    try:
        ijulia_check_cmd_checked = calkit.julia.check_version_in_command(
            ijulia_check_cmd
        )
    except Exception as e:
        raise_error(f"Failed to check Julia version: {e}")
        return False
    ijulia_check_cmd_checked = (
        calkit.julia.ensure_startup_file_disabled_in_command(
            ijulia_check_cmd_checked
        )
    )
    res = subprocess.run(
        ijulia_check_cmd_checked,
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def _sanitize_kernel_name_component(name: str, label: str) -> str:
    """Keep readable names while removing kernelspec-unfriendly characters."""
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("._-")
    if not sanitized:
        raise_error(
            f"{label} cannot be empty after sanitizing for kernel name"
        )
        return ""  # For typing analysis since raise_error exits
    return sanitized


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
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
    auto_add_deps: Annotated[
        bool,
        typer.Option(
            "--auto-add-deps",
            help=(
                "Automatically install missing kernel dependencies "
                "(e.g., IJulia for Julia environments)."
            ),
        ),
    ] = False,
) -> tuple[str, str]:
    """Check that an environment has a registered Jupyter kernel."""
    from calkit.cli.check import check_environment
    from calkit.cli.main import run_in_env
    from calkit.cli.update import update_environment
    from calkit.environments import language_from_env

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
        language = language_from_env(env) or "python"
    project_name = calkit.detect_project_name(prepend_owner=False)
    if not project_name:
        raise_error("Project name cannot be empty")
    kernel_name = (
        f"{_sanitize_kernel_name_component(project_name, 'Project name')}"
        f".{_sanitize_kernel_name_component(env_name, 'Environment name')}"
    )
    display_name = f"{project_name}: {env_name}"
    if verbose and not json_output:
        typer.echo(f"Using kernel name: {kernel_name}")
        typer.echo(f"Using display name: {display_name}")
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
        if json_output:
            # For JSON output, run silently and don't show intermediate
            # messages
            res = run_in_env(
                cmd=cmd,
                env_name=env_name,
                no_check=no_check,
                verbose=False,
                relaxed_check=True,
            )
        else:
            res = run_in_env(
                cmd=cmd,
                env_name=env_name,
                no_check=no_check,
                verbose=verbose,
                relaxed_check=True,
            )
    elif language == "r":
        cmd = [
            "Rscript",
            "-e",
            (
                "IRkernel::installspec("
                f'"{kernel_name}", displayname = "{display_name}", user = TRUE)'
            ),
        ]
        run_in_env(
            cmd=cmd,
            env_name=env_name,
            no_check=no_check,
            verbose=verbose,
            relaxed_check=True,
        )
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
        env_dir_abs = os.path.abspath(env_dir)
        # In reproducible Julia environments we disable global package loading,
        # so IJulia must exist in the project environment itself.
        ijulia_ok = _check_ijulia_available(
            julia_version=julia_version,
            env_dir=env_dir,
        )
        if not ijulia_ok:
            should_install = auto_add_deps
            if not should_install and sys.stdin.isatty() and not json_output:
                should_install = typer.confirm(
                    (
                        "IJulia is not installed in this Julia environment. "
                        "Install now with "
                        f"'calkit update env --name {env_name} --add IJulia'?"
                    ),
                    default=True,
                )
            if not should_install:
                raise_error(
                    "IJulia is not installed in this Julia environment. "
                    "Install it and retry, or pass --auto-add-deps to "
                    "install automatically."
                )
            try:
                update_environment(env_name=env_name, add_packages=["IJulia"])
            except Exception as e:
                raise_error(f"Failed to install IJulia: {e}")
            ijulia_ok = _check_ijulia_available(
                julia_version=julia_version,
                env_dir=env_dir,
            )
            if not ijulia_ok:
                raise_error(
                    "IJulia installation completed but the dependency check "
                    "still failed."
                )
        # Don't include version in display_name; IJulia appends it automatically
        # Escape interpolated values for the Julia string literals---notably the
        # Windows project path, whose backslashes are otherwise read as invalid
        # unicode escapes.
        esc = calkit.julia.escape_string
        julia_cmd = (
            "import IJulia;"
            "kp=IJulia.installkernel("
            f'"{esc(kernel_name)}",'
            f'"--project={esc(env_dir_abs)}",'
            '"--startup-file=no",'
            f'displayname="{esc(display_name)}",'
            f'env=Dict("JULIA_LOAD_PATH" => "{esc(calkit.julia.load_path())}")'
            ");"
            "println(kp);"
        )
        cmd = [
            calkit.julia.get_julia_exe(),
            f"+{julia_version}",
            "--project=" + env_dir,
            "-e",
            julia_cmd,
        ]
        try:
            cmd = calkit.julia.check_version_in_command(cmd)
        except Exception as e:
            raise_error(f"Failed to check Julia version: {e}")
        cmd = calkit.julia.ensure_startup_file_disabled_in_command(cmd)
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise_error(f"Failed to create kernel:\n{res.stderr}")
        kernel_path = res.stdout.strip()
        kernel_name = os.path.basename(kernel_path)
        # Update display_name to include version for matching in VS Code
        # The kernel name format is like: project_-env-X.Y or project_-env-X.Y.Z
        # Extract version from kernel_name or use julia_version
        display_name = f"{display_name} {julia_version}"
        if not json_output:
            typer.echo(
                f"Registered IJulia kernel '{kernel_name}' at: {kernel_path}"
            )
    else:
        raise_error(f"{language} not supported")
        return "", ""  # For typing analysis since raise_error exits
    # Output result
    if json_output:
        result = {
            "kernel_name": kernel_name,
            "display_name": display_name,
        }
        typer.echo(json.dumps(result))
    return kernel_name, display_name


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
    from calkit.detect import language_from_notebook
    from calkit.environments import (
        env_from_name_or_path,
        env_from_notebook_path,
        language_from_env,
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
        calkit.save_calkit_info(ck_info)
    # Detect language from environment
    if language is None:
        detected_language = language_from_notebook(path)
        if detected_language is not None:
            language = detected_language
        else:
            env = envs[env_name]
            language = language_from_env(env) or "python"
        typer.echo(f"Using {language} as notebook language")
    # First, ensure the specified environment has a kernel we can use
    # We need to check the environment type and create the kernel if needed
    docker_env = env.get("kind") == "docker"
    if docker_env:
        # Docker environments run the kernel inside the container, so there is
        # no host kernel to register. Use the container's own kernel (default
        # 'python3', overridable with the env's 'jupyter_kernel' key) and
        # execute with Papermill inside the container further below.
        kernel_name = env.get("jupyter_kernel") or {"r": "ir"}.get(
            language.lower(), "python3"
        )
        display_name = kernel_name
    elif language.lower() in ["python", "julia", "r"]:
        kernel_name, display_name = check_env_kernel(
            env_name=env_name,
            no_check=no_check,
            verbose=verbose,
            language=language.lower(),
        )
    elif language.lower() == "matlab":
        kernel_name = "jupyter_matlab_kernel"
        display_name = "MATLAB"
    else:
        raise ValueError(
            "Language must be one of 'python', 'matlab', 'julia', or 'r'"
        )
    # Try to set kernelspec metadata so execution uses the expected kernel.
    # Always read/write as UTF-8: notebooks routinely contain non-ASCII (e.g.,
    # Greek letters such as "ν" in code), and on Windows the default open()
    # encoding is cp1252, which mangles UTF-8 content into mojibake ("ν" ->
    # "Î½") and breaks execution.
    try:
        with open(path, "r", encoding="utf-8") as f:
            nb_json = json.load(f)
        metadata = nb_json.setdefault("metadata", {})
        kernelspec = metadata.setdefault("kernelspec", {})
        kernelspec["name"] = kernel_name
        kernelspec["display_name"] = display_name
        kernelspec["language"] = language.lower()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(nb_json, f, indent=1)
    except Exception as e:
        if verbose:
            warn(f"Warning: failed to set kernelspec metadata: {e}")
    # We can't handle parameters unless language is Python, Julia, or R
    if language.lower() not in ["python", "julia", "r"]:
        if params or params_json is not None or params_base64 is not None:
            raise_error(
                "Parameters can only be passed to Python, Julia, or R "
                "notebooks"
            )
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
    # If this is a Python, Julia, or R notebook, we can use Papermill.
    # If it's a MATLAB notebook, we need to use the MATLAB kernel inside the
    # specified environment.
    # Exception: If the environment is a Docker environment, we run Papermill
    # inside the container so the kernel (which lives in the image) and
    # Papermill share a process namespace---this avoids registering a host
    # kernel and cross-container networking entirely
    if docker_env:
        # run_in_env mounts the project at the working directory and applies
        # the env's user/platform/args, so we only need to invoke Papermill
        # ipykernel is in the image, but Papermill may not be, so install it
        # on demand (warning the user) before executing. We install into a
        # writable temp dir on PYTHONPATH rather than the image's site-packages:
        # run_in_env maps the host user into the container, so writing to the
        # system location is typically denied, but /tmp is world-writable
        pm_target = "/tmp/calkit-papermill"
        pythonpath = f"PYTHONPATH={pm_target}"
        pm_cmd = [
            pythonpath,
            "python",
            "-c",
            "import papermill",
            "2>/dev/null",
            "||",
            "(",
            "echo",
            "papermill not found in image; installing it with pip...",
            "&&",
            "python",
            "-m",
            "pip",
            "install",
            "-q",
            "--target",
            pm_target,
            "papermill",
            ")",
            "&&",
            pythonpath,
            "python",
            "-m",
            "papermill",
            path,
            fpath_out_exec,
            "-k",
            kernel_name,
            "--log-output",
        ]
        if notebook_dir:
            pm_cmd += ["--cwd", notebook_dir]
        if parsed_params:
            # JSON is valid YAML, so pass parameters as base64-encoded JSON to
            # avoid shell-quoting issues across the container boundary
            params_b64 = base64.b64encode(
                json.dumps(parsed_params).encode()
            ).decode()
            pm_cmd += ["-b", params_b64]
        run_in_env(
            pm_cmd,
            env_name=env_name,
            no_check=no_check,
            verbose=verbose,
        )
    elif language.lower() in ["python", "julia", "r"]:
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
        with open(fpath_out_exec, "r", encoding="utf-8") as f:
            executed_nb = json.load(f)
        with open(path, "r", encoding="utf-8") as f:
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
        with open(path, "w", encoding="utf-8") as f:
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


def _pyodide_provided_packages() -> set[str]:
    """Return the packages Pyodide ships, per marimo's lock file.

    These are binary builds pinned by the runtime, so their versions come
    from Pyodide rather than from the project's environment. Fetched from
    the same URL marimo's exported apps read at load time.

    A failure here returns an empty set, so nothing gets pinned rather than
    pinned wrongly -- a missing pin is a lost record, a wrong one is a
    version that never runs.
    """
    import json

    import requests

    import calkit

    cache_path = (
        pathlib.Path(calkit.ensure_local_dir())
        / "marimo"
        / "pyodide-lock.json"
    )
    url = "https://wasm.marimo.app/pyodide-lock.json"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(resp.text)
        lock = resp.json()
    except Exception as e:
        # Fall back to a previous fetch so an offline build still splits
        # pinnable packages from Pyodide's correctly
        if cache_path.is_file():
            warn(f"Using cached Pyodide lock ({e})")
            lock = json.loads(cache_path.read_text())
        else:
            warn(
                f"Could not read Pyodide lock, so nothing will be pinned: {e}"
            )
            return set()
    return {
        name.lower().replace("_", "-") for name in lock.get("packages", {})
    }


@notebooks_app.command(
    name="export-marimo-wasm",
    help="Export a marimo notebook to a WebAssembly app.",
)
# This wraps `marimo export html-warm` rather than letting a stage call it
# through `calkit xenv` for two reasons.
#
# First, marimo's export is not self-contained. It requires the data an app
# reads to already sit in a `public` directory beside the notebook, and
# copies only that directory into the output. Nothing in marimo puts the
# files there, so without this step either the export ships an app whose
# data 404s, or the project keeps a generated `public` directory next to its
# source. We assemble a build directory instead, so nothing is generated in
# the project tree and the notebook's location doesn't matter.
#
# Second, a stage's command is recorded in dvc.lock, so it has to stay
# stable. Spelling out marimo's flags in the stage means every stage in
# every project goes stale when those flags change; keeping them here means
# one wrapper absorbs it.
def export_marimo_wasm(
    path: Annotated[str, typer.Argument(help="Notebook path.")],
    output_path: Annotated[
        str,
        typer.Option("-o", "--output", help="Output path for the app."),
    ],
    env_name: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help=(
                "Name or path to the spec of the environment in which to "
                "export the notebook; must include marimo."
            ),
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode", help="Whether the app is read-only ('run') or editable."
        ),
    ] = "run",
    show_code: Annotated[
        bool,
        typer.Option("--show-code", help="Show notebook code in the app."),
    ] = False,
    layout_path: Annotated[
        str | None,
        typer.Option(
            "--layout",
            help=(
                "Path to the layout file named in the notebook's "
                "marimo.App(layout_file=...) call."
            ),
        ),
    ] = None,
    include_paths: Annotated[
        list[str],
        typer.Option(
            "--include",
            help=(
                "Path to publish with the app, copied beneath 'public' at "
                "its project-relative path. May be a glob, and may be "
                "repeated."
            ),
        ),
    ] = [],
    no_validate: Annotated[
        bool,
        typer.Option(
            "--no-validate",
            help=(
                "Skip executing the notebook to check it works before "
                "exporting."
            ),
        ),
    ] = False,
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check", help="Do not check environment before exporting."
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
) -> None:
    import ast
    import glob
    import json
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    from calkit.cli.main import run_in_env
    from calkit.notebooks import MARIMO_DETECT_N_BYTES, is_marimo_notebook

    # The notebook kind is detected from the file rather than named in a
    # command per kind, so adding Jupyter export later is additive and
    # doesn't rename this one out from under anybody.
    if not os.path.isfile(path):
        raise_error(f"Notebook does not exist: {path}")
    with open(path) as f:
        head = f.read(MARIMO_DETECT_N_BYTES)
    # Named for the engine rather than for what it produces, so a future
    # export-jupyterlite sits beside it without either pretending to be a
    # generic 'export' whose options are actually engine-specific.
    if path.endswith(".ipynb") or not is_marimo_notebook(head):
        raise_error(
            f"{path} is not a marimo notebook; to render a Jupyter "
            "notebook to HTML use 'calkit nb execute --to html'"
        )
    if mode not in ("run", "edit"):
        raise_error(f"Invalid mode '{mode}'; use run or edit")
    # marimo copies the 'public' directory that sits next to the notebook, so
    # exporting in place would generate files in the project root. Assemble a
    # build directory instead, under .calkit/local, which carries its own
    # '*' .gitignore so this never needs an entry in the project's. Named for
    # the notebook's whole path, since two notebooks in different directories
    # can share a stem and would otherwise wipe out each other's build.
    build_name = Path(path).with_suffix("").as_posix().replace("/", "_")
    build_dir = (
        Path(calkit.ensure_local_dir()) / "marimo" / "build" / build_name
    )
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    build_notebook_path = build_dir / Path(path).name
    shutil.copy2(path, build_notebook_path)
    # marimo needs an inline PEP 723 block to know what to install in the
    # browser, and without one the app dies on its first third-party import.
    # Rather than make the notebook carry a second dependency spec beside the
    # project's environment, generate one into the build copy from what the
    # notebook actually imports. A hand-written block is left alone, so this
    # can still be overridden.
    source = build_notebook_path.read_text()
    if "# /// script" not in source:
        import_roots: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                import_roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                # A relative import resolves within the project, not to a
                # distribution we could install
                if node.level == 0 and node.module:
                    import_roots.add(node.module.split(".")[0])
        import_roots -= sys.stdlib_module_names
        # Resolve module names to distribution names in the stage's own
        # environment, since they often differ (sklearn is scikit-learn) and
        # only that environment knows which distribution provided what.
        resolver = build_dir / "_resolve_dists.py"
        dists_path = build_dir / "_dists.json"
        resolver.write_text(
            "import json, sys\n"
            "from importlib.metadata import packages_distributions, version\n"
            "mods = json.loads(sys.argv[1])\n"
            "found = packages_distributions()\n"
            "out = {}\n"
            "for d in sorted({found.get(m, [m])[0] for m in mods}):\n"
            "    try:\n"
            "        out[d] = version(d)\n"
            "    except Exception:\n"
            "        out[d] = None\n"
            "open(sys.argv[2], 'w').write(json.dumps(out))\n"
        )
        run_in_env(
            [
                "python",
                str(resolver),
                json.dumps(sorted(import_roots)),
                str(dists_path),
            ],
            env_name=env_name,
            no_check=no_check,
            verbose=False,
            relaxed_check=True,
        )
        versions = json.loads(dists_path.read_text())
        resolver.unlink()
        dists_path.unlink()
        # Only packages micropip installs can meaningfully be pinned.
        # Anything Pyodide ships is a binary build whose version the runtime
        # fixes, so a pin there would record a version that never runs and
        # would actively conflict if pins were ever enforced. Ask marimo's
        # Pyodide lock which packages those are.
        provided = _pyodide_provided_packages()
        deps = ["marimo"]
        for dist, ver in sorted(versions.items()):
            if dist == "marimo":
                continue
            if ver is None or dist.lower().replace("_", "-") in provided:
                deps.append(dist)
            else:
                deps.append(f"{dist}=={ver}")
        block = (
            "# /// script\n"
            "# dependencies = [\n"
            + "".join(f'#     "{d}",\n' for d in deps)
            + "# ]\n# ///\n\n"
        )
        build_notebook_path.write_text(block + source)
        typer.echo(f"Declared dependencies for the browser: {', '.join(deps)}")
    # marimo resolves layout_file relative to the notebook, not the project,
    # so the copy has to keep that same relative position. These differ for
    # any notebook that doesn't sit at the project root.
    if layout_path is not None:
        if not os.path.isfile(layout_path):
            raise_error(f"Layout file does not exist: {layout_path}")
        notebook_dir = os.path.dirname(path)
        rel_layout = (
            os.path.relpath(layout_path, notebook_dir)
            if notebook_dir
            else layout_path
        )
        if rel_layout.startswith(".."):
            raise_error(
                f"Layout file {layout_path} is outside the notebook's "
                f"directory ({notebook_dir}); marimo can only reference a "
                "layout beneath it"
            )
        build_layout_path = build_dir / rel_layout
        build_layout_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(layout_path, build_layout_path)
    # Copy included paths beneath public/, preserving project-relative paths
    # so notebook code reads the same locally and in the browser
    public_dir = build_dir / "public"
    n_included = 0
    for pattern in include_paths:
        matches = sorted(glob.glob(pattern, recursive=True))
        if not matches:
            raise_error(f"No files match included path: {pattern}")
        for match in matches:
            dest = public_dir / match
            if os.path.isdir(match):
                shutil.copytree(match, dest, dirs_exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(match, dest)
            n_included += 1
    if include_paths:
        typer.echo(f"Copied {n_included} included path(s) into public")
    # We don't ship marimo, so it has to be in the project environment. Probe
    # for it up front, since otherwise a missing marimo surfaces as the
    # notebook failing to execute, which sends people looking in the wrong
    # place. run_in_env turns a failed command into raise_error, i.e., a
    # typer.Exit, rather than letting CalledProcessError out, so that's what
    # has to be caught to replace its message with a useful one.
    typer.echo("Checking marimo is available")
    try:
        run_in_env(
            ["marimo", "--version"],
            env_name=env_name,
            no_check=no_check,
            verbose=False,
            relaxed_check=True,
        )
    except (typer.Exit, subprocess.CalledProcessError, FileNotFoundError):
        raise_error(
            "marimo is not available in environment "
            f"'{env_name or 'default'}'; add it to that environment's "
            "dependencies. Calkit doesn't ship marimo."
        )
    # A WASM export never executes the notebook, and exits zero even if every
    # cell is broken, so without this a totally broken app ships green. An
    # 'html' export does execute, and fails properly. It only works after
    # assembly, since mo.notebook_location() then resolves to the build
    # directory, where public/ exists.
    if not no_validate:
        typer.echo("Checking the notebook executes")
        validate_path = build_dir / "_validate.html"
        try:
            run_in_env(
                ["marimo", "export", "html", str(build_notebook_path)]
                + ["-o", str(validate_path)],
                env_name=env_name,
                no_check=no_check,
                verbose=verbose,
                relaxed_check=True,
            )
        except (typer.Exit, subprocess.CalledProcessError):
            raise_error(
                "Notebook failed to execute; fix it or pass --no-validate. "
                "Note this runs in the project environment, not the "
                "browser's, so it can't catch every failure."
            )
        validate_path.unlink(missing_ok=True)
    cmd = ["marimo", "export", "html-wasm", str(build_notebook_path)]
    cmd += ["-o", output_path, "--mode", mode]
    if show_code:
        cmd.append("--show-code")
    typer.echo(f"Exporting {path} to {output_path}")
    run_in_env(
        cmd,
        env_name=env_name,
        no_check=no_check,
        verbose=verbose,
        relaxed_check=True,
    )
    if not Path(output_path).exists():
        raise_error(f"Export did not produce {output_path}")
    typer.echo(f"Exported app to {output_path}")
