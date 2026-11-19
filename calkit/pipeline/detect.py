"""Detecting pipeline stages."""

from __future__ import annotations

import json
import os
import posixpath
import re
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, Field

import calkit
from calkit.core import DVC_EXTENSIONS, DVC_SIZE_THRESH_BYTES
from calkit.environments import EnvForStageResult

# What calkit xr makes a script stage from, by extension
SCRIPT_EXTS = (".py", ".r", ".jl", ".m", ".ipynb", ".sh")
SCRIPT_EXTS_MESSAGE = (
    "Scripts can be Python, R, Julia, MATLAB, shell, or Jupyter notebooks"
)


class DetectedStage(BaseModel):
    name: str
    # As written under its name in calkit.yaml
    stage: dict[str, Any]


class StageDetection(BaseModel):
    """A stage worked out from a command, with the environment it runs in,
    which may be new, and data it reads from outside the project.
    """

    environment: EnvForStageResult
    stage: DetectedStage
    external_inputs: list[str] = []
    # The language it's in, if any, e.g., for saying what its dependencies
    # are in
    language: str | None = Field(default=None, exclude=True)
    # What's worth saying about how it was worked out, and what went wrong
    # without stopping it
    notes: list[str] = Field(default=[], exclude=True)
    problems: list[str] = Field(default=[], exclude=True)


def normalize_command(
    cmd: list[str], environment: str | None = None
) -> tuple[list[str], str | None]:
    """A command as ``calkit xr`` is given it, without a ``uv run`` or
    ``pixi run`` prefix, which says the environment it runs in, unless
    one's named, and split into its arguments, with that environment.
    """
    from calkit.docker import split_xr_command

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
        raise ValueError(
            "No command specified after stripping environment prefix. "
            "Usage: calkit xr [uv|pixi run] <command> [args]"
        )
    return cmd, environment


def detect_stage(
    cmd: list[str],
    ck_info: dict,
    environment: str | None = None,
    stage_name: str | None = None,
    inputs: Iterable[str] = (),
    outputs: Iterable[str] = (),
    detect_paths: bool = True,
) -> StageDetection:
    """The stage that runs ``cmd``, as normalized by ``normalize_command``,
    in the project in the current directory, with its environment, from
    what kind of file it runs and what that reads, writes, and imports.

    ``inputs`` and ``outputs`` are declared, and others found are added
    unless ``detect_paths`` is false. A stage already named ``stage_name``
    has to be similar, and lends its environment. Raises ``ValueError``
    for a stage that can't be made.
    """
    import shlex

    import git
    from git import InvalidGitRepositoryError

    import calkit.dvc
    import calkit.git
    import calkit.notebooks
    from calkit.detect import (
        detect_io,
        filter_covered_inputs,
        generate_stage_name,
    )
    from calkit.docker import (
        extract_docker_run_inner_command,
        infer_xr_docker_environment,
        normalize_xr_docker_command,
    )
    from calkit.environments import detect_env_for_stage
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
    from calkit.pipeline.core import stages_are_similar

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

    inputs = list(inputs)
    outputs = list(outputs)
    notes: list[str] = []
    problems: list[str] = []
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    # Populated only when a `docker run ...` command is normalized into an
    # xr `command` stage (e.g., Mermaid CLI), overriding default detection
    docker_override_stage_name = None
    docker_override_env_result = None
    docker_override_detected_inputs: list[str] = []
    docker_override_detected_outputs: list[str] = []
    first_arg = cmd[0]
    stage: dict[str, Any] = {}
    language = None
    cls: type[BaseModel]
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
    elif first_arg.lower().endswith(".ipynb"):
        cls = JupyterNotebookStage
        stage["kind"] = "jupyter-notebook"
        stage["notebook_path"] = first_arg
        storage = calkit.notebooks.determine_storage(first_arg)
        stage["html_storage"] = storage
        stage["executed_ipynb_storage"] = storage
    elif first_arg.lower().endswith(".tex"):
        cls = LatexStage
        stage["kind"] = "latex"
        stage["target_path"] = first_arg
        language = "latex"
        pdf_path = first_arg.removesuffix(".tex") + ".pdf"
        try:
            latex_repo = calkit.git.get_repo()
            if latex_repo.git.ls_files(pdf_path):
                stage["pdf_storage"] = "git"
            else:
                stage["pdf_storage"] = "dvc"
        except InvalidGitRepositoryError:
            stage["pdf_storage"] = "dvc"
    elif (
        first_arg == "python"
        and len(cmd) > 1
        and cmd[1].lower().endswith(".py")
    ):
        cls = PythonScriptStage
        stage["kind"] = "python-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "python"
    elif first_arg.lower().endswith(".py"):
        cls = PythonScriptStage
        stage["kind"] = "python-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "python"
    elif (
        first_arg == "julia"
        and len(cmd) > 1
        and cmd[1].lower().endswith(".jl")
    ):
        cls = JuliaScriptStage
        stage["kind"] = "julia-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "julia"
    elif first_arg.lower().endswith(".jl"):
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
    elif (
        first_arg == "matlab"
        and len(cmd) > 1
        and cmd[1].lower().endswith(".m")
    ):
        cls = MatlabScriptStage
        stage["kind"] = "matlab-script"
        stage["script_path"] = cmd[1]
        language = "matlab"
    elif first_arg.lower().endswith(".m"):
        cls = MatlabScriptStage
        stage["kind"] = "matlab-script"
        stage["script_path"] = first_arg
        language = "matlab"
    elif first_arg == "matlab" and len(cmd) > 1:
        cls = MatlabCommandStage
        stage["kind"] = "matlab-command"
        stage["command"] = " ".join(cmd[1:])
        language = "matlab"
    elif (
        first_arg == "Rscript"
        and len(cmd) > 1
        and cmd[1].lower().endswith(".r")
    ):
        cls = RScriptStage
        stage["kind"] = "r-script"
        stage["script_path"] = cmd[1]
        if len(cmd) > 2:
            stage["args"] = cmd[2:]
        language = "r"
    elif first_arg.lower().endswith(".r"):
        cls = RScriptStage
        stage["kind"] = "r-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        language = "r"
    elif first_arg.lower().endswith((".sh", ".bash", ".zsh")):
        cls = ShellScriptStage
        stage["kind"] = "shell-script"
        stage["script_path"] = first_arg
        if len(cmd) > 1:
            stage["args"] = cmd[1:]
        if first_arg.lower().endswith(".bash"):
            stage["shell"] = "bash"
        elif first_arg.lower().endswith(".zsh"):
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
                notes.append(
                    f"Stage '{base_stage_name}' already exists with different "
                    f"configuration; using '{stage_name}' instead"
                )
    # Check if a similar stage already exists and reuse its environment if not
    # specified
    if stage_name in stages:
        existing_stage = stages[stage_name]
        if not stages_are_similar(existing_stage, stage):
            raise ValueError(
                f"A stage named '{stage_name}' already exists with "
                "different configuration; "
                f"Please specify a unique stage name with --stage"
            )
        # If no environment was specified and a similar stage exists,
        # reuse its environment
        if environment is None and "environment" in existing_stage:
            environment = existing_stage["environment"]
            notes.append(
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
    env_name = env_result.name
    stage["environment"] = env_name
    # Detect inputs and outputs if not disabled
    detected_inputs = list(docker_override_detected_inputs)
    detected_outputs = list(docker_override_detected_outputs)
    external_inputs: list[str] = []
    if detect_paths and not (detected_inputs or detected_outputs):
        try:
            io_info = detect_io(stage)
            detected_inputs = io_info["inputs"]
            detected_outputs = io_info["outputs"]
            external_inputs = io_info.get("external_inputs", [])
        except Exception as e:
            problems.append(f"Failed to detect inputs/outputs: {e}")
    # Initialize git repo and get DVC paths for storage determination
    repo: git.Repo | None
    try:
        repo = calkit.git.get_repo()
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
    # covered -- a declared directory already covers everything inside it
    all_inputs = list(inputs) + filter_covered_inputs(detected_inputs, inputs)
    # Convert detected outputs to PathOutput models with storage determination
    detected_output_models: list[str | PathOutput] = []
    for detected in detected_outputs:
        output_storage = _determine_output_storage(detected, repo, dvc_paths)
        detected_output_models.append(
            PathOutput.model_validate(
                {"path": detected, "storage": output_storage}
            )
        )
    # Merge outputs
    all_outputs: list[str | PathOutput] = list(
        outputs
    )  # Start with user-specified
    for detected_output in detected_output_models:
        # Check if this output path is already present
        detected_path = (
            detected_output.path
            if isinstance(detected_output, PathOutput)
            else detected_output
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
            all_outputs.append(detected_output)
    # Add inputs and outputs to stage
    if all_inputs:
        stage["inputs"] = all_inputs
    if all_outputs:
        # Convert PathOutput objects to dicts for serialization
        serialized_outputs: list[str | dict[str, Any]] = []
        for output in all_outputs:
            if isinstance(output, PathOutput):
                serialized_outputs.append(
                    output.model_dump(exclude_unset=True)
                )
            else:
                serialized_outputs.append(output)
        stage["outputs"] = serialized_outputs
    # Checked against the models
    try:
        cls.model_validate(stage)
    except Exception as e:
        raise ValueError(f"Failed to create stage: {e}")
    return StageDetection(
        environment=env_result,
        stage=DetectedStage(name=stage_name, stage=stage),
        external_inputs=external_inputs,
        language=language,
        notes=notes,
        problems=problems,
    )


def get_script_detection(
    script_path: str, wdir: str = ".", timeout: float = 120
) -> dict:
    """What ``calkit xr --dry-run --json`` finds in a script, without
    running it or writing anything: its environment, from what it imports,
    and its stage, with inputs and outputs from the paths it opens.
    """
    import subprocess

    try:
        result = subprocess.run(
            calkit.get_calkit_cmd()
            + ["xr", "--dry-run", "--json", script_path],
            cwd=wdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Reading '{script_path}' took too long")
    if result.returncode != 0 or not result.stdout.strip():
        lines = [x.strip() for x in result.stderr.splitlines() if x.strip()]
        detail = lines[-1].removeprefix("Error: ") if lines else ""
        raise ValueError(detail or f"Can't read '{script_path}'")
    return get_detection_from_output(result.stdout)


def get_detection_from_output(stdout: str) -> dict:
    """What ``calkit xr --dry-run --json`` found, from what it printed."""
    import json

    # Anything printed before the JSON is xr saying what it chose
    start = stdout.find("\n{")
    detected: dict = json.loads(
        stdout if stdout.startswith("{") else stdout[start + 1 :]
    )
    return detected


def get_stage_from_script_plan(
    script_path: str,
    detected: dict,
    ck_info: dict,
    wdir: str = ".",
    shows: str | None = None,
    produces: str | None = None,
    data_paths: Iterable[str] = (),
    is_dvc_output: Callable[[str], bool] = lambda path: False,
) -> dict:
    """The stage a script makes, from what ``get_script_detection`` found.

    A stage that already runs the script keeps what it declares, with
    anything newly found added. ``shows`` is what a document shows, e.g.,
    a figure a paper includes, and ``produces`` which of the script's
    outputs that is, when the script writes it elsewhere; without it, the
    output with the same path, or else the only one with the same file
    name that a document includes, is taken. Each document that would then
    show it from where it's made is in ``included``, with its new text.
    ``data_paths`` are where data the script reads goes in the project, so
    they aren't counted missing.
    """
    import copy

    import calkit.git
    import calkit.latex
    from calkit.pipeline.core import get_stage_for_output

    env = detected["environment"]
    stage_name = detected["stage"]["name"]
    # Copied, since what's found or already declared is added to
    stage = copy.deepcopy(detected["stage"]["stage"])
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    # A stage that already runs the script, by whatever name, is the one
    # added to, in the environment it runs in
    running_it = next(
        (
            name
            for name, s in stages.items()
            if isinstance(s, dict)
            and script_path in (s.get("script_path"), s.get("notebook_path"))
        ),
        None,
    )
    if running_it is not None and running_it != stage_name:
        stage_name = running_it
    existing_stage = stages.get(stage_name)
    if isinstance(existing_stage, dict) and existing_stage.get("environment"):
        envs = ck_info.get("environments") or {}
        env = {
            "name": existing_stage["environment"],
            "exists": True,
            "env": envs.get(existing_stage["environment"]) or {},
        }
    if isinstance(existing_stage, dict):
        merged = copy.deepcopy(existing_stage)
        for field in ("outputs", "inputs"):
            items = list(existing_stage.get(field) or [])
            known = {
                i.get("path") if isinstance(i, dict) else i for i in items
            }
            items += [
                i
                for i in stage.get(field) or []
                if (i["path"] if isinstance(i, dict) else i) not in known
            ]
            if items:
                merged[field] = items
        stage = merged
    outputs = [
        o["path"] if isinstance(o, dict) else o
        for o in stage.get("outputs") or []
    ]
    # What reading it found, before what a document shows is added
    found_outputs = list(outputs)
    # Env vars, schedules, and other stages' outputs aren't paths
    inputs = [
        i if isinstance(i, str) else i["path"]
        for i in stage.get("inputs") or []
        if isinstance(i, str) or "path" in i
    ]
    data_paths = list(data_paths)
    missing = [
        i
        for i in inputs
        if not os.path.exists(os.path.join(wdir, i))
        and not is_dvc_output(i)
        and get_stage_for_output(i, ck_info) is None
        and not any(i == p or i.startswith(p + "/") for p in data_paths)
    ]

    def get_included_texts(shown: str, path: str) -> dict[str, str]:
        # The new text of each document file that would show it from path
        documents = [
            posixpath.normpath(s["target_path"].replace("\\", "/"))
            for s in stages.values()
            if isinstance(s, dict)
            and s.get("kind") == "latex"
            and s.get("target_path")
        ]
        for folder in ck_info.get("overleaf_sync") or {}:
            if os.path.isdir(os.path.join(wdir, folder)):
                documents += [
                    os.path.relpath(d, wdir).replace(os.sep, "/")
                    for d in calkit.latex.root_documents(
                        os.path.join(wdir, folder)
                    )
                ]
        changed: dict[str, str] = {}
        for document in dict.fromkeys(documents):
            changed.update(
                calkit.latex.include_figure(document, shown, path, wdir=wdir)
            )
        return changed

    if produces is not None:
        if produces not in outputs and produces != shows:
            raise ValueError(f"'{script_path}' doesn't write '{produces}'")
    elif shows in outputs:
        produces = shows
    elif shows is not None:
        same_name = [
            o
            for o in outputs
            if posixpath.basename(o) == posixpath.basename(shows)
        ]
        # Only worth guessing if a document includes it, so it can show it
        # from there instead
        if len(same_name) == 1 and get_included_texts(shows, same_name[0]):
            produces = same_name[0]
    # What the document shows is what the stage makes, so if the script
    # isn't found writing it anywhere, it writes it there
    if shows is not None and produces is None:
        produces = shows
    if produces is not None and produces not in outputs:
        repo = calkit.git.get_repo(wdir)
        tracked = bool(repo.git.ls_files("--", produces).strip())
        stage.setdefault("outputs", []).append(
            {"path": produces, "storage": "git"} if tracked else produces
        )
        outputs.append(produces)
    included: dict[str, str] = {}
    # The copy the document showed, e.g., one uploaded to Overleaf, which
    # nothing needs once it shows the stage's output instead
    replaced = None
    if shows is not None and produces is not None and produces != shows:
        included = get_included_texts(shows, produces)
        if not included:
            raise ValueError(
                f"No document includes '{shows}' to show it from "
                f"'{produces}' instead"
            )
        used_by_stages = any(
            shows
            in [
                p["path"] if isinstance(p, dict) else p
                for field in ("inputs", "outputs")
                for p in s.get(field) or []
                if isinstance(p, (str, dict))
            ]
            for s in [*stages.values(), stage]
            if isinstance(s, dict)
        )
        repo = calkit.git.get_repo(wdir)
        # Only a copy Git has, as is, can go, since that's what gets it back
        saved = bool(repo.git.ls_files("--", shows).strip()) and not (
            repo.git.status("--porcelain", "--", shows).strip()
        )
        # Anything else naming it, e.g., slides or a Markdown file that
        # isn't one of the documents here, may still show it
        named_in = repo.git.grep(
            "-l", "-I", "-F", posixpath.basename(shows), with_exceptions=False
        ).splitlines()
        named_elsewhere = any(
            p not in included and p != shows for p in named_in
        )
        if (
            saved
            and not named_elsewhere
            and not used_by_stages
            and shows not in json.dumps(ck_info, default=str)
            and not any(
                re.search(
                    r"\\includegraphics[^{]*\{[^}]*"
                    + re.escape(
                        posixpath.splitext(posixpath.basename(shows))[0]
                    ),
                    text,
                )
                for text in included.values()
            )
        ):
            replaced = shows
    from_dependencies = env.get("created_from_dependencies")
    return {
        "stage_name": stage_name,
        "stage": stage,
        "environment": env["name"],
        "environment_is_new": not env["exists"],
        "env": env["env"],
        "environment_spec_path": (
            env["spec_path"] if from_dependencies else None
        ),
        "environment_spec_content": (
            env["spec_content"] if from_dependencies else None
        ),
        "dependencies": env.get("dependencies") or [],
        "inputs": inputs,
        "outputs": outputs,
        "found_outputs": found_outputs,
        "missing_inputs": missing,
        "external_inputs": detected.get("external_inputs") or [],
        "produces": produces,
        "included": included,
        "replaced": replaced,
    }
