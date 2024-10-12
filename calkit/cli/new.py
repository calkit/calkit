"""CLI for creating new objects."""

from __future__ import annotations

import os

import git
import typer
from typing_extensions import Annotated

import calkit
from calkit.core import ryaml

new_app = typer.Typer(no_args_is_help=True)


@new_app.command(name="figure")
def new_figure(
    path: str,
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--desc")] = None,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new figure."""
    ck_info = calkit.load_calkit_info()
    figures = ck_info.get("figures", [])
    paths = [f.get("path") for f in figures]
    if path in paths:
        raise ValueError(f"Figure at path {path} already exists")
    obj = dict(path=path, title=title)
    if description is not None:
        obj["description"] = description
    figures.append(obj)
    ck_info["figures"] = figures
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", f"Add figure {path}"])


@new_app.command("question")
def new_question(
    question: str,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new question."""
    ck_info = calkit.load_calkit_info()
    questions = ck_info.get("questions", [])
    if question in questions:
        raise ValueError("Question already exists")
    if not question.endswith("?"):
        raise ValueError("Questions must end with a question mark")
    questions.append(question)
    ck_info["questions"] = questions
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", "Add question"])


@new_app.command("notebook")
def new_notebook(
    path: Annotated[str, typer.Argument(help="Notebook path (relative)")],
    title: Annotated[str, typer.Option("--title")],
    description: Annotated[str, typer.Option("--desc")] = None,
    commit: Annotated[bool, typer.Option("--commit")] = False,
):
    """Add a new notebook."""
    if os.path.isabs(path):
        raise ValueError("Path must be relative")
    if not os.path.isfile(path):
        raise ValueError("Path is not a file")
    if not path.endswith(".ipynb"):
        raise ValueError("Path does not have .ipynb extension")
    # TODO: Add option to create stages that run `calkit nb clean` and
    # `calkit nb execute`
    ck_info = calkit.load_calkit_info()
    notebooks = ck_info.get("notebooks", [])
    paths = [f.get("path") for f in notebooks]
    if path in paths:
        raise ValueError(f"Notebook at path {path} already exists")
    obj = dict(path=path, title=title)
    if description is not None:
        obj["description"] = description
    notebooks.append(obj)
    ck_info["notebooks"] = notebooks
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    if commit:
        repo = git.Repo()
        repo.git.add("calkit.yaml")
        repo.git.commit(["-m", f"Add notebook {path}"])
