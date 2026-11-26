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
                "`_system` for MyST installed on this machine. There's no "
                "default."
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
    """Build the MyST project in this folder, i.e., where its myst.yml is,
    in an environment.

    What its documents' 'ckprovenance' directives say about where their
    figures and tables came from is worked out first, from the pipeline as
    it stands, and the MyST plugin that shows them is written.
    MyST has to come from the environment, so every machine builds with
    the same version, unless the project lists 'myst' as a requirement or
    the environment is `_system`, i.e., this machine.
    """
    import calkit
    import calkit.environments
    import calkit.myst
    import calkit.quarto
    from calkit.cli.main.core import run_in_env
    from calkit.cli.quarto import _RUN_IN_DIR
    from calkit.markdown import MarkdownParseError, results_by_name

    # The project is wherever calkit.yaml is above here, since a stage
    # builds from its working directory
    wdir = os.getcwd()
    if not os.path.isfile("myst.yml"):
        raise_error("There's no myst.yml here; run this where it is")
    project_dir = wdir
    while not os.path.isfile(os.path.join(project_dir, "calkit.yaml")):
        parent = os.path.dirname(project_dir)
        if parent == project_dir:
            raise_error("This isn't in a Calkit project")
        project_dir = parent
    ck_info = calkit.load_calkit_info(wdir=project_dir, read_only=True)
    # Named every time, since a default would change meaning as the project
    # gains environments
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
    myst_dir = Path(os.path.relpath(wdir, project_dir)).as_posix()
    myst_dir = "" if myst_dir == "." else myst_dir
    stage = calkit.myst.get_build_stage(myst_dir or ".", ck_info)
    # Every document's, including what it includes, so a record can't
    # outlive what it was written for
    found = []
    try:
        for document in calkit.myst.find_documents(myst_dir, wdir=project_dir):
            text = calkit.quarto.read_document_text(
                os.path.join(project_dir, document)
            )
            components, roles = (
                calkit.myst.extract_document(
                    text,
                    document,
                    read_text=lambda p: calkit.quarto.read_document_text(
                        os.path.join(project_dir, p)
                    ),
                    results=results_by_name(ck_info),
                )
                if text is not None
                else ([], [])
            )
            if components or roles:
                found.append((document, components, roles))
                continue
            record_path = os.path.join(
                project_dir, calkit.quarto.get_provenance_path(document)
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
        # rebuild when that changes
        if found and stage is not None:
            unlisted = calkit.myst.get_unlisted_paths(
                [c.path for _, components, _ in found for c in components]
                + [
                    v.path
                    for _, _, roles in found
                    for _, _, v in roles
                    if not v.ref
                ],
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
        if any(v.ref for _, _, roles in found for _, _, v in roles):
            from calkit.references.values import write_values_file

            write_values_file(ck_info, wdir=project_dir)
        for document, components, roles in found:
            values = [v for _, _, v in roles]
            texts = calkit.quarto.check_values(
                values, document, wdir=project_dir
            )
            record_path = calkit.quarto.write_provenance(
                components,
                document,
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
    cmd = ["myst", "build"] + (myst_args or [])
    if environment == "_system":
        # Resolved first, so a 'myst.cmd' shim is found on Windows
        cmd[0] = shutil.which("myst") or "myst"
        try:
            subprocess.check_call(cmd)
        except (OSError, subprocess.CalledProcessError) as e:
            raise_error(f"Building failed: {e}")
        return
    # The environment is defined relative to the project, but the build
    # runs here, which locally Calkit's own interpreter goes back to inside
    # the environment, and elsewhere, e.g., in a container, is the working
    # directory relative to the project
    env_kind = (
        (ck_info.get("environments") or {}).get(environment, {}).get("kind")
    )
    run_wdir = None
    if env_kind in calkit.environments.APP_CHECK_ENV_KINDS:
        cmd = [sys.executable, "-c", _RUN_IN_DIR, wdir] + cmd
    else:
        run_wdir = myst_dir or None
    os.chdir(project_dir)
    try:
        run_in_env(cmd, env_name=environment, wdir=run_wdir, no_check=no_check)
    finally:
        os.chdir(wdir)
