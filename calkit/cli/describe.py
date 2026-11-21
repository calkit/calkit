"""CLI for describing things."""

from __future__ import annotations

import os
from typing import Annotated

import typer

import calkit
from calkit.cli import AliasGroup, echo_json, raise_error

describe_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def _describe_env(env: dict, env_name: str) -> dict:
    """Build the description of a single environment.

    The keys here are a stable contract for tools consuming ``--json``, so
    they are always present, even if their value is null.
    """
    # Here rather than at the top, since every command imports this module;
    # what that saves is a question in decisions/calkit.yaml
    from calkit.environments import get_env_lock_fpath

    return {
        "kind": env.get("kind"),
        "spec_path": env.get("path"),
        "lock_path": get_env_lock_fpath(env=env, env_name=env_name),
        "prefix": env.get("prefix"),
        "python": env.get("python"),
    }


def _echo_description(desc: dict, indent: str = "") -> None:
    """Print a description as human-readable YAML-ish lines.

    Keys with null values are dropped since they typically don't apply to the
    kind of thing being described.
    """
    for key, val in desc.items():
        if val is None:
            continue
        typer.echo(f"{indent}{key}: {val}")


@describe_app.command(name="system")
def describe_system(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
    apps: Annotated[
        list[str],
        typer.Option(
            "--app",
            help="An app whose version to include, beyond the ones always "
            "reported. Repeat for more.",
        ),
    ] = [],
):
    """Describe the system."""
    system_info = calkit.get_system_info(apps=apps)
    if json_output:
        echo_json(system_info)
        return
    _echo_description(system_info)


@describe_app.command(name="environment|env")
def describe_env(
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="Environment name."),
    ],
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """Describe a single environment, including spec and lock file paths."""
    ck_info = calkit.load_calkit_info()
    envs: dict = ck_info.get("environments", {})
    if name not in envs:
        raise_error(f"Environment '{name}' not found.")
    result = _describe_env(env=envs[name], env_name=name)
    if json_output:
        echo_json(result)
        return
    _echo_description(result)


@describe_app.command(name="environments|envs")
def describe_envs(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """Describe all environments, including spec and lock file paths."""
    ck_info = calkit.load_calkit_info()
    envs: dict = ck_info.get("environments", {})
    result = {
        env_name: _describe_env(env=env, env_name=env_name)
        for env_name, env in envs.items()
    }
    if json_output:
        echo_json(result)
        return
    for env_name, desc in result.items():
        typer.echo(env_name + ":")
        _echo_description(desc, indent="    ")


@describe_app.command(name="subprojects")
def describe_subprojects(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
) -> None:
    """Describe subprojects, including nested ones.

    Stages and environments are named as in the subproject itself; from
    here, they're addressed as '<path>:<name>'.
    """
    subprojects = calkit.get_subprojects()
    result = {}
    for path, sp in subprojects.items():
        info = sp["ck_info"]
        result[path] = {
            "parent": sp["parent"],
            "description": sp["entry"].get("description"),
            "name": info.get("name"),
            "title": info.get("title"),
            # With its own DVC repo, a subproject runs as one parent stage
            "isolated": os.path.isdir(os.path.join(path, ".dvc")),
            "environments": list(info.get("environments") or {}),
            "stages": list((info.get("pipeline") or {}).get("stages") or {}),
            "subprojects": [
                p
                for p, child in subprojects.items()
                if child["parent"] == path
            ],
        }
    if json_output:
        echo_json(result)
        return
    for path, desc in result.items():
        typer.echo(path + ":")
        _echo_description(desc, indent="    ")


@describe_app.command(name="schema")
def describe_schema(
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help="Path at which to write the schema instead of printing it.",
        ),
    ] = None,
) -> None:
    """Print the JSON schema for calkit.yaml.

    Editors can use this to validate and autocomplete the file. See
    https://docs.calkit.org/calkit-yaml for how to set that up.
    """
    txt = calkit.schema.generate_json()
    if output is None:
        typer.echo(txt, nl=False)
        return
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(txt)
    typer.echo(f"Wrote schema to {output}")
