"""Commands for working with LaTeX."""

from __future__ import annotations

import json
import string
from copy import deepcopy

import typer
from typing_extensions import Annotated

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

    # TODO: Lots of validation needed here!

    if fmt_json is None:
        fmt_dict = {}
    else:
        fmt_dict = json.loads(fmt_json)
    with open(input_fpath) as f:
        data = json.load(f)
    formatted = deepcopy(data)
    for tex_var_name, fmt_string in fmt_dict.items():
        fmt_string = str(fmt_string)
        data_for_formatting = deepcopy(data)
        # Do any relevant evals and add them to the data for formatting
        tokens = tokens_from_format_string(fmt_string)
        for t in tokens:
            data_for_formatting[t] = arithmetic_eval.evaluate(t, data)
        formatted[tex_var_name] = fmt_string.format(**data_for_formatting)
    with open(output_fpath, "w") as f:
        json2latex.dump(command_name, formatted, f)
