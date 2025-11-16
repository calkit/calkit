"""Commands for working with LaTeX."""

from __future__ import annotations

import json
import os
import string
import subprocess
from copy import deepcopy

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import raise_error

latex_app = typer.Typer(no_args_is_help=True)


@latex_app.command(name="from-json")
def from_json(
    input_fpath: Annotated[str, typer.Argument(help="Input JSON file path.")],
    output_fpath: Annotated[
        str, typer.Argument(help="Output LaTeX file path.")
    ],
    command_name: Annotated[
        str,
        typer.Option("--command", help="Command name to use in LaTeX output."),
    ],
    fmt_json: Annotated[
        str | None,
        typer.Option(
            "--format-json",
            help=(
                "Additional JSON input to use for formatting. "
                "Can be used to add extra keys with simple expressions, etc."
            ),
        ),
    ] = None,
):
    """Convert a JSON file to LaTeX.

    This is useful for referencing calculated values in LaTeX documents.
    """
    import arithmetic_eval
    import json2latex

    def tokens_from_format_string(fmt: str):
        return [
            field.strip()
            for _, field, _, _ in string.Formatter().parse(fmt)
            if field
        ]

    # Validate some stuff
    if not os.path.isfile(input_fpath):
        raise_error(f"Input file {input_fpath} does not exist")
    if not input_fpath.endswith(".json"):
        raise_error("Input file must be a JSON file")
    if not output_fpath.endswith(".tex"):
        raise_error("Output file must be a .tex file")
    if fmt_json is not None:
        try:
            fmt_dict = json.loads(fmt_json)
        except json.JSONDecodeError:
            raise_error("Format JSON is not valid JSON")
    else:
        fmt_dict = {}
    with open(input_fpath) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            raise_error("Input JSON file is not valid JSON")
    formatted = deepcopy(data)
    for tex_var_name, fmt_string in fmt_dict.items():
        fmt_string = str(fmt_string)
        data_for_formatting = deepcopy(data)
        # Do any relevant evals and add them to the data for formatting
        tokens = tokens_from_format_string(fmt_string)
        for t in tokens:
            try:
                data_for_formatting[t] = arithmetic_eval.evaluate(t, data)
            except Exception:
                raise_error(
                    f"Error evaluating expression '{t}' for formatting"
                )
        formatted[tex_var_name] = fmt_string.format(**data_for_formatting)
    # Create output directory if it doesn't exist
    outdir = os.path.dirname(output_fpath)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(output_fpath, "w") as f:
        json2latex.dump(command_name, formatted, f)


@latex_app.command(name="build")
def build(
    tex_file: Annotated[str, typer.Argument(help="The .tex file to compile.")],
    environment: Annotated[
        str | None,
        typer.Option(
            "--env",
            "-e",
            help=("Environment in which to run latexmk, if applicable."),
        ),
    ] = None,
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help=(
                "Don't check the environment is valid before running latexmk."
            ),
        ),
    ] = False,
    latexmk_rc_path: Annotated[
        str | None,
        typer.Option(
            "--latexmk-rc",
            "-r",
            help="Path to a latexmkrc file to use for compilation.",
        ),
    ] = None,
    no_synctex: Annotated[
        bool,
        typer.Option(
            "--no-synctex",
            help="Don't generate synctex file for source-to-pdf mapping.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Force latexmk to recompile all files, even if they are up to "
                "date."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Build a PDF of a LaTeX document with latexmk.

    If a Calkit environment is not specified, latexmk will be run in the
    system environment if available. If not available, a TeX Live Docker
    container will be used.
    """
    # Now formulate the command
    latexmk_cmd = ["latexmk", "-pdf", "-cd"]
    if latexmk_rc_path is not None:
        latexmk_cmd += ["-r", latexmk_rc_path]
    if not no_synctex:
        latexmk_cmd.append("-synctex=1")
    if not verbose:
        latexmk_cmd.append("-silent")
    if force:
        latexmk_cmd.append("-f")
    latexmk_cmd += ["-interaction=nonstopmode", tex_file]
    if environment is not None:
        if no_check:
            check_cmd = ["--no-check"]
        else:
            check_cmd = []
        cmd = (
            ["calkit", "xenv", "--name", environment]
            + check_cmd
            + ["--"]
            + latexmk_cmd
        )
        if verbose:
            typer.echo(f"Running command: {cmd}")
    elif calkit.check_dep_exists("latexmk"):
        cmd = latexmk_cmd
    else:
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{os.getcwd()}:/work",
            "-w",
            "/work",
            "texlive/texlive:latest-full",
        ] + latexmk_cmd
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        raise_error("latexmk failed")
