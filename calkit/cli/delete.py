"""CLI for deleting objects."""

from __future__ import annotations

import typer

import calkit
from calkit.cli import AliasGroup, raise_error
from calkit.core import ryaml

delete_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


@delete_app.command(name="question")
def delete_question(
    index: int = typer.Argument(
        ...,
        help="1-based index of the question to remove (see `calkit list questions`).",
    ),
):
    """Remove a question by its 1-based index."""
    ck_info = calkit.load_calkit_info()
    questions = ck_info.get("questions", []) or []
    if index < 1 or index > len(questions):
        raise_error(
            f"Invalid question index {index}; "
            f"there are {len(questions)} question(s)."
        )
    removed = questions.pop(index - 1)
    ck_info["questions"] = questions
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    typer.echo(f"Removed question: {removed}")
