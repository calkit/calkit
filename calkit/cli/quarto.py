"""Commands for working with Quarto."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from typing_extensions import Annotated

from calkit.cli.core import raise_error, warn

if TYPE_CHECKING:
    from calkit.models.pipeline import QuartoStage

# Runs a command in a directory, finding it on PATH as a shell would, e.g.,
# a 'quarto.cmd' on Windows
_RUN_IN_DIR = (
    "import os, shutil, subprocess, sys; os.chdir(sys.argv[1]); "
    "cmd = sys.argv[2:]; cmd[0] = shutil.which(cmd[0]) or cmd[0]; "
    "sys.exit(subprocess.call(cmd))"
)

quarto_app = typer.Typer(no_args_is_help=True)


def render_stage(
    stage_dir: str,
    stage: QuartoStage,
    quarto_args: list[str] | None = None,
    allow_machine_quarto: bool = False,
    no_check: bool = False,
) -> None:
    """Render a Quarto document as its pipeline stage does."""
    wdir = os.getcwd()
    os.chdir(os.path.join(stage_dir, stage.wdir or ""))
    try:
        render(
            target_path=stage.target_path,
            quarto_args=stage.args + (quarto_args or []),
            environment=stage.inner_environment,
            allow_machine_quarto=(
                allow_machine_quarto or stage.allows_machine_quarto
            ),
            to=stage.to,
            no_check=no_check,
        )
    finally:
        os.chdir(wdir)


@quarto_app.command(name="render")
def render(
    target_path: Annotated[
        str, typer.Argument(help="Path to the Quarto document to render.")
    ],
    quarto_args: Annotated[
        list[str] | None,
        typer.Argument(
            help="Extra arguments for 'quarto render', after '--', e.g., "
            "'-- --execute'."
        ),
    ] = None,
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help=(
                "Environment to render in, which should provide Quarto, or "
                "`_system` for Quarto installed on this machine. Defaults to "
                "the environment of the document's quarto stage, if any."
            ),
        ),
    ] = None,
    allow_machine_quarto: Annotated[
        bool,
        typer.Option(
            "--allow-machine-quarto",
            help=(
                "Allow Quarto installed on this machine rather than in the "
                "environment, e.g., for a stage listing it as a requirement."
            ),
        ),
    ] = False,
    to: Annotated[
        str | None,
        typer.Option("--to", help="Output format, passed to 'quarto render'."),
    ] = None,
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Don't check the environment is valid before rendering.",
        ),
    ] = False,
) -> None:
    """Render a Quarto document in an environment.

    Quarto has to come from the environment, so every machine renders with
    the same version, unless the project lists 'quarto' as a requirement or
    the environment is `_system`, i.e., this machine.
    If no environment or format is given and a pipeline `quarto` stage
    renders the document, its environment, format, arguments, and working
    directory are used.
    The values the document shows with the 'ckvalue' shortcode are checked
    first, where they and the figures, tables, and files it shows with
    'ckfigure', 'cktable', and 'ckinclude' came from is worked out, and the
    Quarto extension that shows them is written.

    Also available as `calkit doc build`.
    """
    import calkit
    import calkit.environments
    import calkit.quarto
    from calkit.cli.main.core import run_in_env
    from calkit.markdown import MarkdownParseError, results_by_name

    # Without explicit environment or format, render as the document's stage
    if environment is None and to is None:
        import calkit.pipeline
        from calkit.models.pipeline import QuartoStage

        stage_dir, _, found = calkit.pipeline.find_document_stages(
            target_path, kinds=["quarto"]
        )
        matches = [s for _, s in found if isinstance(s, QuartoStage)]
        if stage_dir is not None and matches:
            s = matches[0]
            if len(matches) > 1:
                others = ", ".join(f"'{m.name}'" for m in matches[1:])
                warn(
                    f"Stages '{s.name}' and {others} all render "
                    f"{target_path}; rendering it as '{s.name}'"
                )
            render_stage(
                stage_dir=stage_dir,
                stage=s,
                quarto_args=quarto_args,
                allow_machine_quarto=allow_machine_quarto,
                no_check=no_check,
            )
            return
    # The project is wherever calkit.yaml is above the document, since a
    # stage renders from its working directory
    doc_path = os.path.abspath(target_path)
    project_dir = os.path.dirname(doc_path)
    while not os.path.isfile(os.path.join(project_dir, "calkit.yaml")):
        parent = os.path.dirname(project_dir)
        if parent == project_dir:
            raise_error(f"{target_path} isn't in a Calkit project")
        project_dir = parent
    ck_info = calkit.load_calkit_info(wdir=project_dir, read_only=True)
    # Named every time, since a default would change meaning as the project
    # gains environments
    if environment is None:
        names = list(ck_info.get("environments") or {}) + ["_system"]
        raise_error(
            "Name the environment to render in with '-e', one of: "
            + ", ".join(names)
        )
    problem = (
        None
        if allow_machine_quarto
        else calkit.environments.check_app_in_env(
            "quarto",
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
            f"{problem}. Quarto is 'quarto' in a Conda or Pixi environment, "
            "and 'quarto-cli' in a uv or pip one"
        )
    text = calkit.quarto.read_document_text(target_path)
    if text is None:
        raise_error(f"{target_path} doesn't exist or can't be read")
    document_rel = os.path.relpath(doc_path, project_dir)
    try:
        values = calkit.quarto.extract_values(
            text, document_rel, results=results_by_name(ck_info)
        )
        if any(v.ref for v in values):
            from calkit.references.values import write_values_file

            write_values_file(ck_info, wdir=project_dir)
        if values:
            calkit.quarto.check_values(values, document_rel, wdir=project_dir)
        # Where its components and values came from is decided now, from
        # the pipeline as it stands, for the extension to show
        components = (
            calkit.quarto.extract_components(text)
            if calkit.quarto.has_components(text)
            else []
        )
        filter_problem = (
            calkit.quarto.get_filter_problem(
                text, document_rel, wdir=project_dir, to=to
            )
            if components
            else None
        )
        if (components or values) and filter_problem is None:
            calkit.quarto.write_provenance(
                components,
                document_rel,
                ck_info,
                wdir=project_dir,
                values=values,
            )
        if values or components:
            calkit.quarto.write_components(document_rel, wdir=project_dir)
    except (MarkdownParseError, ValueError) as e:
        raise_error(str(e))
    if filter_problem is not None:
        raise_error(filter_problem)
    cmd = ["quarto", "render", target_path]
    if to is not None:
        cmd += ["--to", to]
    cmd += quarto_args or []
    if environment == "_system":
        # Resolved first, so a 'quarto.cmd' shim is found on Windows
        cmd[0] = shutil.which("quarto") or "quarto"
        try:
            subprocess.check_call(cmd)
        except (OSError, subprocess.CalledProcessError) as e:
            raise_error(f"Rendering {target_path} failed: {e}")
    else:
        # The environment is defined relative to the project, but the
        # document and args are relative to where this was run, e.g., a
        # stage's working directory. Locally, Calkit's own interpreter goes
        # back there inside the environment to run Quarto, finding it on
        # PATH as a shell would; elsewhere, e.g., in a container, that's
        # the working directory relative to the project
        wdir = os.getcwd()
        env_kind = (
            (ck_info.get("environments") or {})
            .get(environment, {})
            .get("kind")
        )
        run_wdir = None
        if env_kind in calkit.environments.APP_CHECK_ENV_KINDS:
            cmd = [sys.executable, "-c", _RUN_IN_DIR, wdir] + cmd
        else:
            run_wdir = Path(os.path.relpath(wdir, project_dir)).as_posix()
            run_wdir = None if run_wdir == "." else run_wdir
        os.chdir(project_dir)
        try:
            run_in_env(
                cmd, env_name=environment, wdir=run_wdir, no_check=no_check
            )
        finally:
            os.chdir(wdir)
