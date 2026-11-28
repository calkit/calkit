"""Commands for working with MyST."""

from __future__ import annotations

import os
import posixpath
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from typing_extensions import Annotated

from calkit.cli.core import raise_error

myst_app = typer.Typer(no_args_is_help=True)


@myst_app.command(name="build")
def build(
    target_path: Annotated[
        str,
        typer.Argument(
            help="The MyST project's folder, its myst.yml, or a document in "
            "it to build alone."
        ),
    ],
    myst_args: Annotated[
        list[str] | None,
        typer.Argument(
            help="Arguments for 'myst build', after '--', e.g., '-- --html'."
        ),
    ] = None,
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help=(
                "Environment to build in, which should provide MyST, or "
                "`_system` for MyST installed on this machine. Defaults to "
                "the environment of its myst stage, if any."
            ),
        ),
    ] = None,
    allow_machine_myst: Annotated[
        bool,
        typer.Option(
            "--allow-machine-myst",
            help=(
                "Allow MyST installed on this machine rather than in the "
                "environment, e.g., for a stage listing it as a requirement."
            ),
        ),
    ] = False,
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Don't check the environment is valid before building.",
        ),
    ] = False,
) -> None:
    """Build a MyST project, or one document in it, in an environment.

    It builds from the project's folder, i.e., where its myst.yml is,
    passing a document to 'myst build' to build only its exports.

    The values its documents show with the 'ckvalue' and 'ckrefval' roles,
    and where they and the figures, tables, and files they show with the
    'ckfigure', 'cktable', and 'ckinclude' directives came from, are worked
    out first, from the pipeline as it stands, and the MyST plugin that
    shows them is written.
    MyST has to come from the environment, so every machine builds with
    the same version, unless the project lists 'myst' as a requirement or
    the environment is `_system`, i.e., this machine.

    Also available as `calkit doc build`.
    """
    import calkit
    import calkit.environments
    import calkit.myst
    import calkit.quarto
    from calkit.cli.main.core import run_in_env
    from calkit.cli.quarto import _RUN_IN_DIR
    from calkit.markdown import MarkdownParseError, results_by_name

    # The Calkit project is wherever calkit.yaml is above the target, and
    # the MyST project wherever myst.yml is between them
    wdir = os.getcwd()
    target_abs = os.path.abspath(target_path)
    if not os.path.exists(target_abs):
        raise_error(f"{target_path} doesn't exist")
    project_dir = (
        target_abs
        if os.path.isdir(target_abs)
        else os.path.dirname(target_abs)
    )
    while not os.path.isfile(os.path.join(project_dir, "calkit.yaml")):
        parent = os.path.dirname(project_dir)
        if parent == project_dir:
            raise_error(f"{target_path} isn't in a Calkit project")
        project_dir = parent
    ck_info = calkit.load_calkit_info(wdir=project_dir, read_only=True)
    target_rel = Path(os.path.relpath(target_abs, project_dir)).as_posix()
    found_dir, document = calkit.myst.get_target_paths(
        target_rel, wdir=project_dir
    )
    if found_dir is None:
        raise_error(f"There's no myst.yml for {target_path}")
    myst_dir = found_dir
    myst_abs = os.path.join(project_dir, myst_dir)
    stage = calkit.myst.get_build_stage(target_rel, ck_info, wdir=project_dir)
    stage_info = (
        ((ck_info.get("pipeline") or {}).get("stages") or {}).get(stage)
        if stage is not None
        else None
    )
    # A myst stage says how it builds, unless an environment is given
    is_myst_stage = (
        isinstance(stage_info, dict) and stage_info.get("kind") == "myst"
    )
    if environment is None and is_myst_stage:
        from calkit.models.pipeline import MystStage

        s = MystStage.model_validate(stage_info)
        environment = s.inner_environment
        allow_machine_myst = allow_machine_myst or s.allows_machine_myst
        myst_args = s.args + (myst_args or [])
    # Otherwise named every time, since a default would change meaning as
    # the project gains environments
    if environment is None:
        names = list(ck_info.get("environments") or {}) + ["_system"]
        raise_error(
            "Name the environment to build in with '-e', one of: "
            + ", ".join(names)
        )
    problem = (
        None
        if allow_machine_myst
        else calkit.environments.check_app_in_env(
            "myst",
            environment,
            ck_info,
            wdir=project_dir,
            check_env=not no_check,
        )
    )
    if problem is not None and problem.startswith("Couldn't"):
        raise_error(problem)
    if problem is not None:
        raise_error(
            f"{problem}. MyST is 'mystmd' in a Conda, Pixi, uv, or pip "
            "environment"
        )
    # Where each document's components and values came from, and the
    # values, are worked out now, from the pipeline as it stands, for the
    # plugin to show, since MyST doesn't read results files
    # Every document's, including what it includes, so a record can't
    # outlive what it was written for
    found = []
    try:
        documents = (
            [document]
            if document is not None
            else calkit.myst.find_documents(myst_dir, wdir=project_dir)
        )
        for document_path in documents:
            text = calkit.quarto.read_document_text(
                os.path.join(project_dir, document_path)
            )
            components, roles, included = (
                calkit.myst.extract_document(
                    text,
                    document_path,
                    read_text=lambda p: calkit.quarto.read_document_text(
                        os.path.join(project_dir, p)
                    ),
                    results=results_by_name(ck_info),
                )
                if text is not None
                else ([], [], [])
            )
            if components or roles:
                found.append((document_path, components, roles, included))
                continue
            record_path = os.path.join(
                project_dir, calkit.quarto.get_provenance_path(document_path)
            )
            if os.path.isfile(record_path):
                os.remove(record_path)
        if found:
            problem = calkit.myst.get_plugin_problem(
                myst_dir, wdir=project_dir
            )
            if problem is not None:
                raise_error(problem)
        # What they show is what the stage is built from, or it won't
        # rebuild when that changes, which a myst stage finds itself
        if found and stage is not None and not is_myst_stage:
            unlisted = calkit.myst.get_unlisted_paths(
                [c.path for _, components, _, _ in found for c in components]
                + [
                    v.path
                    for _, _, roles, _ in found
                    for _, _, v in roles
                    if not v.ref
                ]
                # And what they include, which changes them too
                + [p for _, _, _, included in found for p in included],
                stage,
                wdir=project_dir,
            )
            if unlisted:
                stage_wdir = myst_dir or "."
                raise_error(
                    f"Stage '{stage}' doesn't list what its documents show "
                    "as inputs, so it won't rebuild when they change; add "
                    "to its inputs: "
                    + ", ".join(
                        posixpath.relpath(p, stage_wdir) for p in unlisted
                    )
                )
        if any(v.ref for _, _, roles, _ in found for _, _, v in roles):
            from calkit.references.values import write_values_file

            write_values_file(ck_info, wdir=project_dir)
        for document_path, components, roles, _ in found:
            values = [v for _, _, v in roles]
            texts = calkit.quarto.check_values(
                values, document_path, wdir=project_dir
            )
            record_path = calkit.quarto.write_provenance(
                components,
                document_path,
                ck_info,
                wdir=project_dir,
                document_stage=stage,
                values=values,
            )
            calkit.myst.add_role_values(
                os.path.join(project_dir, record_path), roles, texts
            )
        if found:
            calkit.myst.write_plugin(myst_dir, wdir=project_dir)
    except (MarkdownParseError, ValueError) as e:
        raise_error(str(e))
    cmd = ["myst", "build"]
    if document is not None:
        cmd.append(posixpath.relpath(document, myst_dir))
    cmd += myst_args or []
    if environment == "_system":
        # Resolved first, so a 'myst.cmd' shim is found on Windows
        cmd[0] = shutil.which("myst") or "myst"
        try:
            subprocess.check_call(cmd, cwd=myst_abs)
        except (OSError, subprocess.CalledProcessError) as e:
            raise_error(f"Building failed: {e}")
        return
    # The environment is defined relative to the project, but the build
    # runs from the MyST project's folder, which locally Calkit's own interpreter goes back to inside
    # the environment, and elsewhere, e.g., in a container, is the working
    # directory relative to the project
    env_kind = (
        (ck_info.get("environments") or {}).get(environment, {}).get("kind")
    )
    run_wdir = None
    if env_kind in calkit.environments.APP_CHECK_ENV_KINDS:
        cmd = [sys.executable, "-c", _RUN_IN_DIR, myst_abs] + cmd
    else:
        run_wdir = None if myst_dir == "." else myst_dir
    os.chdir(project_dir)
    try:
        run_in_env(cmd, env_name=environment, wdir=run_wdir, no_check=no_check)
    finally:
        os.chdir(wdir)
