"""CLI for deleting objects."""

from __future__ import annotations

import typer
from typing_extensions import Annotated

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


@delete_app.command(name="comment")
def delete_comment(
    path: Annotated[
        str | None,
        typer.Argument(help="File the thread is in, if not found by --id."),
    ] = None,
    id: Annotated[
        str | None,
        typer.Option(
            "--id",
            help="ID of the thread, which finds it in any of the project's documents.",
        ),
    ] = None,
    line: Annotated[
        int | None,
        typer.Option("--line", "-l", help="Number of any line in the thread."),
    ] = None,
) -> None:
    """Delete a review comment thread and its replies."""
    from calkit.cli.latex import edit_comment

    edit_comment(path, id, line, None)
