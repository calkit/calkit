"""The ``calkit xr`` command."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Annotated, Any

import git
import typer
from git import InvalidGitRepositoryError

import calkit
from calkit.cli import raise_error
from calkit.cli.main.core import app, run
from calkit.core import DVC_EXTENSIONS, DVC_SIZE_THRESH_BYTES


@app.command(name="xr")
def execute_and_record(
    cmd: Annotated[
        list[str],
        typer.Argument(
            help="Command to execute and record. "
            "If the first argument is a script, notebook or LaTeX file, "
            "it will be treated as a stage with that file as "
            "the target. Any command, including arguments, is supported."
        ),
    ],
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help="Name of or path the spec file for the environment to use.",
        ),
    ] = None,
    inputs: Annotated[
        list[str],
        typer.Option(
            "--input",
            "-i",
            help="Input paths to record.",
        ),
    ] = [],
    outputs: Annotated[
        list[str],
        typer.Option(
            "--output",
            "-o",
            help="Output paths to record.",
        ),
    ] = [],
    no_detect_io: Annotated[
        bool,
        typer.Option(
            "--no-detect-io",
            help=(
                "Don't attempt to detect inputs and outputs from the command, "
                "script, or notebook."
            ),
        ),
    ] = False,
    stage_name: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help=(
                "Name of the DVC stage to create for this command. If not "
                "provided, a name will be generated automatically."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-d",
            help=(
                "Print the environment and stage that would be created "
                "without modifying calkit.yaml or executing the command."
            ),
        ),
    ] = False,
    fmt_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Print xr results as JSON.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force running stage even if it's up-to-date.",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Execute a command and if successful, record in the pipeline."""
    import contextlib
    import io
    import shlex

    from calkit.detect import (
        detect_io,
        generate_stage_name,
    )
    from calkit.docker import (
        extract_docker_run_inner_command,
        infer_xr_docker_environment,
        normalize_xr_docker_command,
        split_xr_command,
    )
    from calkit.environments import EnvForStageResult, detect_env_for_stage
    from calkit.models.io import PathOutput
    from calkit.models.pipeline import (
        CommandStage,
        JuliaCommandStage,
        JuliaScriptStage,
        JupyterNotebookStage,
        LatexStage,
        MatlabCommandStage,
        MatlabScriptStage,
        PythonScriptStage,
        RScriptStage,
        ShellCommandStage,
        ShellScriptStage,
    )
    from calkit.pipeline import stages_are_similar

    def _determine_output_storage(
        path: str,
        repo: git.Repo | None = None,
        dvc_paths: list[str] | None = None,
    ) -> str:
        """Determine storage type (git or dvc) for an output path.

        Parameters
        ----------
        path : str
            Path to check.
        repo : git.Repo | None
            Git repository. If None, only extension and size are checked.
        dvc_paths : list[str] | None
            List of paths tracked by DVC.

        Returns
        -------
        str
            "git" or "dvc".
        """
        if dvc_paths is None:
            dvc_paths = []
        # If already tracked by git, use git
        if repo is not None and repo.git.ls_files(path):
            return "git"
        # If already tracked by dvc, use dvc
        if path in dvc_paths:
            return "dvc"
        # Check extension
        if os.path.splitext(path)[-1] in DVC_EXTENSIONS:
            return "dvc"
        # Check size if file exists
        if os.path.exists(path):
            try:
                if calkit.get_size(path) > DVC_SIZE_THRESH_BYTES:
                    return "dvc"
            except (OSError, IOError):
                # If we cannot determine file size (e.g., permission
                # or I/O issues), fall back to the default "git"
                # behavior below.
                pass
        # Default to git for small/unknown files
        return "git"

    # First, read the pipeline before running so we can revert if the stage
    # fails
    ck_info = calkit.load_calkit_info()
    ck_info_orig = deepcopy(ck_info)
    pipeline = ck_info.get("pipeline", {})
    stages = pipeline.get("stages", {})
    # Populated only when a `docker run ...` command is normalized into an
    # xr `command` stage (e.g., Mermaid CLI), overriding default detection
    docker_override_stage_name = None
    docker_override_env_result = None
    docker_override_detected_inputs: list[str] = []
    docker_override_detected_outputs: list[str] = []
    # Strip and detect uv/pixi run prefix
    if len(cmd) >= 2 and cmd[0] == "uv" and cmd[1] == "run":
        if environment is None and os.path.isfile("pyproject.toml"):
            environment = "pyproject.toml"
        cmd = cmd[2:]
    elif len(cmd) >= 2 and cmd[0] == "pixi" and cmd[1] == "run":
        if environment is None and os.path.isfile("pixi.toml"):
            environment = "pixi.toml"
        cmd = cmd[2:]
    cmd = split_xr_command(cmd)
    # Guard against empty command after stripping uv/pixi run
    if not cmd:
        raise_error(
            "No command specified after stripping environment prefix. "
            "Usage: calkit xr [uv|pixi run] <command> [args]"
        )
    first_arg = cmd[0]
    # Detect what kind of stage this is based on the command
    # If the first argument is a notebook, we'll treat this as a notebook stage
    # If the first argument is `python`, check that the second argument is a
    # script, otherwise it's a shell-command stage
    # If the first argument ends with .tex, we'll treat this as a LaTeX stage
    stage: dict[str, Any] = {}
    language = None
    if first_arg == "docker":
        # Docker runs for entrypoint-mode allowlisted images are normalized
        # into `command` stages; others remain regular shell-command stages
        docker_run_cmd = list(cmd)
        docker_command = normalize_xr_docker_command(
            cmd=cmd,
            environment=environment,
            cwd=os.getcwd(),
        )
        if docker_command is not None:
            cmd = docker_command.command
            cls = CommandStage
            stage = {
                "kind": "command",
                "command": " ".join(shlex.quote(arg) for arg in cmd),
            }
            environment = docker_command.environment_name
            envs = ck_info.get("environments", {})
            if environment not in envs:
                docker_override_env_result = EnvForStageResult(
                    name=environment,
                    env={
                        "kind": "docker",
                        "image": docker_command.image,
                        "description": docker_command.description,
                        "wdir": docker_command.wdir,
                        "command_mode": docker_command.command_mode,
                    },
                    exists=False,
                    spec_path=None,
                    dependencies=[],
                    created_from_dependencies=False,
                )
            docker_override_stage_name = docker_command.stage_name
            docker_override_detected_inputs = docker_command.inputs
            docker_override_detected_outputs = docker_command.outputs
        else:
            inner_command = extract_docker_run_inner_command(docker_run_cmd)
            if inner_command is not None:
                cmd = inner_command
            cls = ShellCommandStage
            stage["kind"] = "shell-command"
            stage["command"] = " ".join(shlex.quote(arg) for arg in cmd)
            language = "shell"
            if environment is None and inner_command is not None:
                inferred_env = infer_xr_docker_environment(cmd=docker_run_cmd)
                if inferred_env is not None:
                    inferred_name, inferred_env_dict = inferred_env
                    envs = ck_info.get("environments", {})
                    existing_env = envs.get(inferred_name)
                    if isinstance(existing_env, dict):
                        docker_override_env_result = EnvForStageResult(
                            name=inferred_name,
                            env=existing_env,
                            exists=True,
                            spec_path=existing_env.get("path"),
                            dependencies=[],
                            created_from_dependencies=False,
                        )
                    else:
                        docker_override_env_result = EnvForStageResult(
                            name=inferred_name,
                            env=inferred_env_dict,
                            exists=False,
                            spec_path=inferred_env_dict.get("path"),
                            dependencies=[],
                            created_from_dependencies=False,
                        )
    elif first_arg.endswith(".ipynb"):
        cls = JupyterNotebookStage
        stage["kind"] = "jupyter-notebook"
        stage["notebook_path"] = first_arg
        storage = calkit.notebooks.determine_storage(first_arg)
        stage["html_storage"] = storage
        stage["executed_ipynb_storage"] = storage
    elif first_arg.endswith(".tex"):
        cls = LatexStage
        stage["kind"] = "latex"
        stage["target_path"] = first_arg
        language = "latex"
        pdf_path = first_arg.removesuffix(".tex") + ".pdf"
        try:
            repo = git.Repo(".")
            if repo.git.ls_files(pdf_path):
                stage["pdf_storage"] = "git"
            else:
                stage["pdf_storage"] = "dvc"
        except InvalidGitRepositoryError:
            stage["pdf_storage"] = "dvc"
    elif first_arg == "python" and len(cmd) > 1 and cmd[1].endswith(".py"):
        cls = PythonScriptStage
        stage["kind"] = "python-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "python"
    elif first_arg.endswith(".py"):
        cls = PythonScriptStage
        stage["kind"] = "python-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "python"
    elif first_arg == "julia" and len(cmd) > 1 and cmd[1].endswith(".jl"):
        cls = JuliaScriptStage
        stage["kind"] = "julia-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "julia"
    elif first_arg.endswith(".jl"):
        cls = JuliaScriptStage
        stage["kind"] = "julia-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "julia"
    elif first_arg == "julia" and len(cmd) > 1:
        cls = JuliaCommandStage
        stage["kind"] = "julia-command"
        stage["command"] = " ".join(cmd[1:])
        language = "julia"
    elif first_arg == "matlab" and len(cmd) > 1 and cmd[1].endswith(".m"):
        cls = MatlabScriptStage
        stage["kind"] = "matlab-script"
        stage["script_path"] = cmd[1]
        language = "matlab"
    elif first_arg.endswith(".m"):
        cls = MatlabScriptStage
        stage["kind"] = "matlab-script"
        stage["script_path"] = first_arg
        language = "matlab"
    elif first_arg == "matlab" and len(cmd) > 1:
        cls = MatlabCommandStage
        stage["kind"] = "matlab-command"
        stage["command"] = " ".join(cmd[1:])
        language = "matlab"
    elif first_arg == "Rscript" and len(cmd) > 1 and cmd[1].endswith(".R"):
        cls = RScriptStage
        stage["kind"] = "r-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "r"
    elif first_arg.endswith(".R"):
        cls = RScriptStage
        stage["kind"] = "r-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "r"
    elif first_arg.endswith((".sh", ".bash", ".zsh")):
        cls = ShellScriptStage
        stage["kind"] = "shell-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        if first_arg.endswith(".bash"):
            stage["shell"] = "bash"
        elif first_arg.endswith(".zsh"):
            stage["shell"] = "zsh"
        else:
            stage["shell"] = "sh"
        language = "shell"
    else:
        cls = ShellCommandStage
        stage["kind"] = "shell-command"
        stage["command"] = " ".join(shlex.quote(arg) for arg in cmd)
        language = "shell"
    # Create a stage name if one isn't provided and check for existing similar
    # stages
    if stage_name is None:
        base_stage_name = docker_override_stage_name or generate_stage_name(
            cmd
        )
        stage_name = base_stage_name
        # If a stage with this name exists and is different, auto-increment
        if stage_name in stages:
            existing_stage = stages[stage_name]
            if not stages_are_similar(existing_stage, stage):
                # Find the next available increment
                counter = 2
                while f"{base_stage_name}-{counter}" in stages:
                    candidate_stage = stages[f"{base_stage_name}-{counter}"]
                    if stages_are_similar(candidate_stage, stage):
                        # Found a matching stage with this incremented name
                        stage_name = f"{base_stage_name}-{counter}"
                        break
                    counter += 1
                else:
                    # No matching stage found, use the next available number
                    stage_name = f"{base_stage_name}-{counter}"
                typer.echo(
                    f"Stage '{base_stage_name}' already exists with different "
                    f"configuration; using '{stage_name}' instead"
                )
    # Check if a similar stage already exists and reuse its environment if not
    # specified
    if stage_name in stages:
        existing_stage = stages[stage_name]
        if not stages_are_similar(existing_stage, stage):
            raise_error(
                f"A stage named '{stage_name}' already exists with "
                "different configuration; "
                f"Please specify a unique stage name with --stage"
            )
            return
        # If no environment was specified and a similar stage exists,
        # reuse its environment
        if environment is None and "environment" in existing_stage:
            environment = existing_stage["environment"]
            typer.echo(
                f"Reusing environment '{environment}' from existing "
                f"stage '{stage_name}'"
            )
    # Detect or create environment for this stage
    if docker_override_env_result is not None:
        env_result = docker_override_env_result
    else:
        env_result = detect_env_for_stage(
            stage=stage,
            environment=environment,
            ck_info=ck_info,
            language=language,
        )
    # If we created an environment from dependencies, write the spec file
    if env_result.created_from_dependencies and not dry_run:
        typer.echo(
            "No existing environment detected; "
            "Attempting to create one based on detected dependencies"
        )
        if env_result.dependencies:
            typer.echo(
                f"Detected {language or 'code'} dependencies: "
                f"{', '.join(env_result.dependencies)}"
            )
        if env_result.spec_path and env_result.spec_content is not None:
            # Create the spec file
            spec_dir = os.path.dirname(env_result.spec_path)
            if spec_dir:
                os.makedirs(spec_dir, exist_ok=True)
            with open(env_result.spec_path, "w") as f:
                f.write(env_result.spec_content)
            typer.echo(f"Created environment spec: {env_result.spec_path}")
    # Add environment to calkit.yaml if it doesn't exist
    if not env_result.exists and not dry_run:
        envs = ck_info.get("environments", {})
        envs[env_result.name] = env_result.env
        ck_info["environments"] = envs
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info, f)
        ck_info = calkit.load_calkit_info()
    env_name = env_result.name
    stage["environment"] = env_name
    # Detect inputs and outputs if not disabled
    detected_inputs = list(docker_override_detected_inputs)
    detected_outputs = list(docker_override_detected_outputs)
    if not no_detect_io and not (detected_inputs or detected_outputs):
        try:
            io_info = detect_io(stage)
            detected_inputs = io_info["inputs"]
            detected_outputs = io_info["outputs"]
        except Exception as e:
            typer.echo(
                f"Warning: Failed to detect inputs/outputs: {e}",
                err=True,
            )
    # Initialize git repo and get DVC paths for storage determination
    try:
        repo = git.Repo(".")
    except InvalidGitRepositoryError:
        repo = None
    dvc_paths = []
    if repo is not None:
        try:
            dvc_paths = calkit.dvc.list_paths()
        except Exception:
            # DVC might not be initialized
            pass
    # Merge user-specified inputs/outputs with detected ones
    # User-specified take precedence and detected ones are added if not already
    # present
    all_inputs = list(inputs)  # Start with user-specified
    for detected in detected_inputs:
        if detected not in all_inputs:
            all_inputs.append(detected)
    # Convert detected outputs to PathOutput models with storage determination
    detected_output_models: list[str | PathOutput] = []
    for detected in detected_outputs:
        storage = _determine_output_storage(detected, repo, dvc_paths)
        detected_output_models.append(
            PathOutput(
                path=detected,
                storage=storage,  # type: ignore[arg-type]
            )
        )
    # Merge outputs
    all_outputs: list[str | PathOutput] = list(
        outputs
    )  # Start with user-specified
    for detected in detected_output_models:
        # Check if this output path is already present
        detected_path = (
            detected.path if isinstance(detected, PathOutput) else detected
        )
        already_present = False
        for existing in all_outputs:
            existing_path = (
                existing.path if isinstance(existing, PathOutput) else existing
            )
            if existing_path == detected_path:
                already_present = True
                break
        if not already_present:
            all_outputs.append(detected)
    # Add inputs and outputs to stage
    if all_inputs:
        stage["inputs"] = all_inputs
    if all_outputs:
        # Convert PathOutput objects to dicts for serialization
        serialized_outputs = []
        for output in all_outputs:
            if isinstance(output, PathOutput):
                serialized_outputs.append(
                    output.model_dump(exclude_unset=True)
                )
            else:
                serialized_outputs.append(output)
        stage["outputs"] = serialized_outputs
    # Create the stage, write to calkit.yaml, and run it to see if
    # it's successful
    try:
        cls.model_validate(stage)
    except Exception as e:
        raise_error(f"Failed to create stage: {e}")

    def _xr_json_result(
        mode: str,
        execution_status: str | None = None,
        error: str | None = None,
        run_stdout: str | None = None,
        run_stderr: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "mode": mode,
            "environment": {
                "name": env_result.name,
                "exists": env_result.exists,
                "created_from_dependencies": (
                    env_result.created_from_dependencies
                ),
                "env": env_result.env,
                "spec_path": env_result.spec_path,
                "spec_content": env_result.spec_content,
                "dependencies": env_result.dependencies,
            },
            "stage": {
                "name": stage_name,
                "stage": stage,
            },
        }
        if execution_status is not None:
            result["execution"] = {
                "status": execution_status,
                "error": error,
                "stdout": run_stdout,
                "stderr": run_stderr,
            }
        return result

    # If dry-run, print environment and stage then return
    if dry_run:
        if fmt_json:
            typer.echo(json.dumps(_xr_json_result(mode="dry-run"), indent=2))
            return
        # Print environment info
        if env_result.created_from_dependencies:
            typer.echo("Environment (would be created):")
            if env_result.spec_path and env_result.spec_content is not None:
                typer.echo(f"  Spec file: {env_result.spec_path}")
                typer.echo("  Content:")
                for line in env_result.spec_content.split("\n"):
                    typer.echo(f"    {line}")
        elif not env_result.exists:
            typer.echo("Environment (would be added to calkit.yaml):")
            yaml_output = io.StringIO()
            calkit.ryaml.dump({env_result.name: env_result.env}, yaml_output)
            for line in yaml_output.getvalue().rstrip().split("\n"):
                typer.echo(f"  {line}")
        else:
            typer.echo(f"Environment: {env_name} (already exists)")
        # Print stage
        typer.echo("\nStage (would be added to pipeline):")
        yaml_output = io.StringIO()
        calkit.ryaml.dump({stage_name: stage}, yaml_output)
        for line in yaml_output.getvalue().rstrip().split("\n"):
            typer.echo(f"  {line}")
        return
    stages[stage_name] = stage
    pipeline["stages"] = stages
    ck_info["pipeline"] = pipeline
    with open("calkit.yaml", "w") as f:
        calkit.ryaml.dump(ck_info, f)
    run_stdout = io.StringIO()
    run_stderr = io.StringIO()
    try:
        if not fmt_json:
            # Format stage as YAML for display
            yaml_output = io.StringIO()
            calkit.ryaml.dump({stage_name: stage}, yaml_output)
            # Indent YAML by 2 spaces
            indented_yaml = "\n".join(
                "  " + line if line.strip() else line
                for line in yaml_output.getvalue().rstrip().split("\n")
            )
            typer.echo(
                f"Adding stage to pipeline and attempting to execute:"
                f"\n{indented_yaml}"
            )
            run(targets=[stage_name], force=force, verbose=verbose)
        else:
            with contextlib.redirect_stdout(run_stdout):
                with contextlib.redirect_stderr(run_stderr):
                    run(
                        targets=[stage_name],
                        force=force,
                        verbose=verbose,
                        quiet=True,
                    )
            stdout_value = run_stdout.getvalue().rstrip() or None
            stderr_value = run_stderr.getvalue().rstrip() or None
            typer.echo(
                json.dumps(
                    _xr_json_result(
                        mode="run",
                        execution_status="completed",
                        run_stdout=stdout_value,
                        run_stderr=stderr_value,
                    ),
                    indent=2,
                )
            )
    except Exception as e:
        # If the stage failed, write the old ck_info back to calkit.yaml to
        # remove the stage that we added
        with open("calkit.yaml", "w") as f:
            calkit.ryaml.dump(ck_info_orig, f)
        if fmt_json:
            stdout_value = run_stdout.getvalue().rstrip() or None
            stderr_value = run_stderr.getvalue().rstrip() or None
            typer.echo(
                json.dumps(
                    _xr_json_result(
                        mode="run",
                        execution_status="failed",
                        error=f"Failed to execute stage: {e}",
                        run_stdout=stdout_value,
                        run_stderr=stderr_value,
                    ),
                    indent=2,
                )
            )
            raise typer.Exit(code=1)
        raise_error(f"Failed to execute stage: {e}")
