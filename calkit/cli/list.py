"""CLI for listing objects."""

from __future__ import annotations

from typing import Annotated, Literal

import typer

import calkit
from calkit.cli import AliasGroup, warn

list_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def _list_objects(
    kind: Literal[
        "notebooks",
        "datasets",
        "figures",
        "references",
        "publications",
    ],
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


@list_app.command(name="notebooks|nb")
def list_notebooks():
    """List notebooks in the project."""
    _list_objects("notebooks")


@list_app.command(name="figures|figs")
def list_figures():
    """List figures in the project."""
    _list_objects("figures")


@list_app.command(name="datasets")
def list_datasets():
    """List datasets in the project."""
    _list_objects("datasets")


@list_app.command(name="publications|pubs")
def list_publications():
    """List publications in the project."""
    _list_objects("publications")


@list_app.command(name="references|refs")
def list_references():
    """List reference collections in the project."""
    _list_objects("references")


@list_app.command(name="environments|envs")
def list_environments():
    """List environments in the project."""
    envs = calkit.load_calkit_info().get("environments", {})
    for name, env in envs.items():
        typer.echo(name + ":")
        for k, v in env.items():
            typer.echo(f"    {k}: {v}")


@list_app.command(name="templates")
def list_templates():
    """List all available Calkit templates."""
    for kind, tpl_dict in calkit.templates.TEMPLATES.items():
        for name in tpl_dict:
            typer.echo(f"{kind}/{name}")


@list_app.command(name="installers")
def list_installers():
    """List apps with a registered native installer.

    These can be declared as ``kind: app`` dependencies in ``calkit.yaml``
    and Calkit will offer to install them via ``calkit install <name>`` or
    automatically during ``calkit run`` on an interactive TTY.
    """
    # Group entries that share the same underlying installer (e.g.,
    # ``cargo``/``rustup``, ``julia``/``juliaup``) so the listing reflects
    # the alias relationship rather than implying separate scripts.
    groups: dict[int, list[str]] = {}
    for name, entry in calkit.install.INSTALLERS.items():
        groups.setdefault(id(entry), []).append(name)
    for names in groups.values():
        names.sort()
        canonical = names[0]
        entry = calkit.install.INSTALLERS[canonical]
        aliases = ", ".join(names[1:])
        header = canonical + (f"  (aliases: {aliases})" if aliases else "")
        typer.echo(header)
        for platform in ("unix", "windows"):
            ins = entry.get(platform)  # type: ignore[arg-type]
            if ins is None:
                continue
            typer.echo(f"  {platform}: {ins['script']}")


@list_app.command(name="procedures")
def list_procedures():
    """List procedures in the current project."""
    ck_info = calkit.load_calkit_info()
    for p in ck_info.get("procedures", {}):
        typer.echo(p)


@list_app.command(name="releases")
def list_releases():
    """List releases."""
    objs = calkit.load_calkit_info().get("releases", {})
    for name, obj in objs.items():
        typer.echo(name + ":")
        # First figure out if the release is published
        published = None
        try:
            published = calkit.invenio.get(
                f"/records/{obj.get('record_id')}",
                service=obj.get("publisher"),
            )["is_published"]
        except Exception:
            try:
                published = calkit.invenio.get(
                    f"/records/{obj.get('record_id')}/draft",
                    service=obj.get("publisher"),
                )["is_published"]
            except Exception as e:
                warn(f"Cannot tell if release {name} is published: {e}")
        if published is not None:
            typer.echo(f"    published: {published}")
        for k, v in obj.items():
            typer.echo(f"    {k}: {v}")


@list_app.command(name="stages")
def list_stages(
    kinds: Annotated[
        list[str] | None,
        typer.Option("--kind", "-k", help="Filter stages by kind."),
    ] = None,
    stale_only: Annotated[
        bool, typer.Option("--stale", help="Show only stale stages.")
    ] = False,
):
    """List pipeline stages."""
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    # If we only want stale stages, we need to get the status first
    if stale_only:
        # First compile pipeline
        status = calkit.pipeline.get_status(ck_info=ck_info)
        stale_stage_names = status.stale_stage_names
    for name, stage in stages.items():
        if kinds is not None and stage.get("kind") not in kinds:
            continue
        if stale_only and name not in stale_stage_names:
            continue
        typer.echo(name)


@list_app.command(name="remotes")
def list_remotes():
    """List Git and DVC remotes."""
    try:
        repo = calkit.git.get_repo()
        for remote in repo.remotes:
            typer.echo(f"(Git) {remote.name}: {remote.url}")
    except Exception as e:
        warn(f"Could not list Git remotes: {e}")
    # Now DVC remotes
    try:
        dvc_remotes = calkit.dvc.get_remotes()
        for name, url in dvc_remotes.items():
            typer.echo(f"(DVC) {name}: {url}")
    except Exception as e:
        warn(f"Could not list DVC remotes: {e}")
