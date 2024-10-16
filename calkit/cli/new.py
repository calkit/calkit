"""CLI for creating new objects."""

from __future__ import annotations

import os
import subprocess

import git
import typer
from typing_extensions import Annotated

import calkit
from calkit.core import ryaml
from calkit.docker import LAYERS

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


@new_app.command("docker-env")
def new_docker_env(
    name: Annotated[str, typer.Option("--name")],
    base: Annotated[
        str, typer.Option("--from", help="Base image, e.g., ubuntu.")
    ],
    path: Annotated[str, typer.Option("--path")] = "Dockerfile",
    create_stage: Annotated[
        str,
        typer.Option(
            "--create-stage", help="Create a DVC stage with this name."
        ),
    ] = None,
    layers: Annotated[
        list[str],
        typer.Option(
            "--layers", help="Layers to add (options: mambaforge, foampy)."
        ),
    ] = [],
    wdir: Annotated[
        str, typer.Option("--wdir", help="Working directory.")
    ] = "/work",
    description: Annotated[
        str, typer.Option("--description", help="Description.")
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            "-f",
            help="Overwrite any existing environment with this name.",
        ),
    ] = False,
):
    """Create a new Docker environment."""
    if os.path.isfile(path) and not overwrite:
        typer.echo("Output path already exists (use -f to overwrite)")
        raise typer.Exit(1)
    txt = "FROM " + base + "\n\n"
    for layer in layers:
        if layer not in LAYERS:
            typer.echo(f"Unknown layer type '{layer}'")
            raise typer.Exit(1)
        txt += LAYERS[layer] + "\n\n"
    txt += f"RUN mkdir {wdir}\n"
    txt += f"WORKDIR {wdir}\n"
    with open(path, "w") as f:
        f.write(txt)
    # Add environment to Calkit info
    ck_info = calkit.load_calkit_info()
    # If environments is a list instead of a dict, reformulate it
    envs = ck_info.get("environments", {})
    if isinstance(envs, list):
        envs = {env.pop("name"): env for env in envs}
    if name in envs and not overwrite:
        typer.echo(
            f"Environment with name {name} already exists "
            "(use -f to overwrite)"
        )
        raise typer.Exit(1)
    typer.echo("Adding environment to calkit.yaml")
    env = dict(
        kind="docker",
        path=path,
        wdir=wdir,
    )
    if create_stage is not None:
        env["stage"] = create_stage
    if description is not None:
        env["description"] = description
    if layers:
        env["layers"] = layers
    envs[name] = env
    ck_info["environments"] = envs
    with open("calkit.yaml", "w") as f:
        ryaml.dump(ck_info, f)
    # If we're creating a stage, do so with DVC
    if create_stage:
        typer.echo(f"Creating DVC stage {create_stage}")
        subprocess.call(
            [
                "dvc",
                "stage",
                "add",
                "-f",
                "-n",
                create_stage,
                "-d",
                path,
                "--outs-no-cache",
                path + ".digest",
                (
                    f"docker build -t {name} . && docker inspect --format "
                    f"'{{{{.Id}}}}' {name} > Dockerfile.digest"
                ),
            ]
        )
