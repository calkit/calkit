"""CLI for describing things."""

from __future__ import annotations

import os
from typing import Annotated

import typer

import calkit
from calkit.cli import AliasGroup, echo_json, raise_error
from calkit.environments import get_env_lock_fpath

describe_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def _describe_env(env: dict, env_name: str) -> dict:
    """Build the description of a single environment.

    The keys here are a stable contract for tools consuming ``--json``, so
    they are always present, even if their value is null.
    """
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
):
    """Describe the system."""
    system_info = calkit.get_system_info()
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
