"""CLI for listing objects."""

from __future__ import annotations

from typing import Literal

import typer

import calkit

list_app = typer.Typer(no_args_is_help=True)


def _list_objects(
    kind: Literal[
        "notebooks", "datasets", "figures", "references", "publications"
    ]
):
    """List objects.

    TODO: This should probably just use some library to dump YAML to string.
    """
    ck_info = calkit.load_calkit_info()
    objects = ck_info.get(kind, [])
    for obj in objects:
        path = obj.pop("path")
        typer.echo(f"- path: {path}")
        for k, v in obj.items():
            if isinstance(v, dict):
                typer.echo(f"    {k}:")
                for k1, v1 in v.items():
                    typer.echo(f"      {k1}: {v1}")
            elif isinstance(v, list):
                typer.echo(f"    {k}:")
                for item in v:
                    if isinstance(item, dict):
                        for n, (k1, v1) in enumerate(item.items()):
                            if n == 0:
                                typer.echo(f"      - {k1}: {v1}")
                            else:
                                typer.echo(f"        {k1}: {v1}")
                    else:
                        typer.echo(f"        - {item}")
            else:
                typer.echo(f"  {k}: {v}")


@list_app.command(name="notebooks")
def list_notebooks():
    _list_objects("notebooks")


@list_app.command(name="figures")
def list_figures():
    _list_objects("figures")


@list_app.command(name="datasets")
def list_datasets():
    _list_objects("datasets")


@list_app.command(name="publications")
def list_publications():
    _list_objects("publications")


@list_app.command(name="references")
def list_references():
    _list_objects("references")
