"""Commands for working with Quarto."""

from __future__ import annotations

import os
import subprocess
import sys

import typer
from typing_extensions import Annotated

from calkit.cli.core import raise_error

quarto_app = typer.Typer(no_args_is_help=True)


@quarto_app.command(name="prepare")
def prepare(
    target_path: Annotated[
        str, typer.Argument(help="Path to the Quarto document.")
    ],
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help=(
                "Environment the document is rendered in, to check Quarto "
                "comes from it or is a declared requirement."
            ),
        ),
    ] = None,
    stage_name: Annotated[
        str | None,
        typer.Option(
            "--stage",
            help="Stage rendering the document, whose requirements count.",
        ),
    ] = None,
    project_dir: Annotated[
        str,
        typer.Option(
            "--project-dir",
            help="Project directory, if not the current one.",
        ),
    ] = ".",
) -> None:
    """Get a Quarto document ready for its pipeline stage to render it.

    Checks Quarto comes from the document's environment, or that the
    project lists it as a requirement, so a version installed on this
    machine isn't used without saying so. Then writes the values the
    document shows with the 'ckvalue' shortcode, read from their results
    files, beside it with the shortcode itself.
    """
    import calkit
    import calkit.quarto
    from calkit.markdown import MarkdownParseError, results_by_name

    def get_quarto_bin_dir(prefix: list[str]) -> str | None:
        # Quarto reports where its binary is, which a launcher on PATH, e.g.,
        # Pixi's for a global install, wouldn't
        try:
            res = subprocess.run(
                prefix + ["quarto", "--paths"],
                capture_output=True,
                text=True,
                cwd=project_dir,
            )
        except OSError:
            return None
        if res.returncode != 0 or not res.stdout.strip():
            return None
        return os.path.realpath(res.stdout.strip().splitlines()[0].strip())

    ck_info = calkit.load_calkit_info(wdir=project_dir, read_only=True)
    stage = (ck_info.get("pipeline", {}).get("stages") or {}).get(
        stage_name or ""
    )
    if environment is not None and not calkit.quarto.is_quarto_required(
        ck_info, stage if isinstance(stage, dict) else None
    ):
        system_bin = get_quarto_bin_dir([])
        if environment == "_system":
            env_bin = system_bin
        else:
            env_bin = get_quarto_bin_dir(
                [sys.executable, "-m", "calkit", "xenv", "-n", environment]
                + ["--no-check", "--"]
            )
        fix = (
            "add it to the environment, e.g., 'quarto' to a Conda or Pixi "
            "one, or 'quarto-cli' to a uv or pip one, or list 'quarto' in "
            "the project's requirements"
        )
        where = (
            "isn't in an environment"
            if environment == "_system"
            else f"isn't in environment '{environment}'"
        )
        if env_bin is None:
            raise_error(f"Quarto {where}; {fix}")
        if env_bin == system_bin:
            raise_error(
                f"Quarto {where}, so the one installed on this machine "
                f"({env_bin}) would be used; {fix}"
            )
    text = calkit.quarto.read_document_text(target_path)
    if text is None:
        raise_error(f"{target_path} doesn't exist or can't be read")
    document_rel = os.path.relpath(target_path, project_dir)
    try:
        values = calkit.quarto.extract_values(
            text, document_rel, results=results_by_name(ck_info)
        )
        if not values:
            return
        resolved = calkit.quarto.resolve_values(
            values, document_rel, wdir=project_dir
        )
    except (MarkdownParseError, ValueError) as e:
        raise_error(str(e))
    calkit.quarto.write_components(target_path, resolved)
