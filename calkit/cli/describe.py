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


@describe_app.command(name="environment-cache|env-cache")
def describe_env_cache(
    names: Annotated[
        list[str],
        typer.Option(
            "--name",
            "-n",
            help="Environment to include. Repeat for more. Defaults to the "
            "ones the pipeline uses.",
        ),
    ] = [],
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
) -> None:
    """Describe what to cache to restore environments, e.g., in CI.

    Prints the paths to save and a key that changes when an environment's
    definition, spec, lock, or inputs do, scoped to this platform and those
    absolute paths. 'ready' says whether every cached environment has been
    checked successfully here since it last changed, so is worth saving.
    """
    from calkit.environments import get_env_cache_spec

    try:
        spec = get_env_cache_spec(env_names=names or None)
    except ValueError as e:
        raise_error(str(e))
    if json_output:
        echo_json(spec)
        return
    _echo_description(
        {
            "key": spec["key"],
            "restore_key": spec["restore_key"],
            "ready": spec["ready"],
        }
    )
    for path in spec["paths"]:
        typer.echo(f"path: {path}")
    for env_name, desc in spec["environments"].items():
        typer.echo(env_name + ":")
        _echo_description(
            {k: v for k, v in desc.items() if k != "paths"}, indent="    "
        )


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


@describe_app.command(name="storage")
def describe_storage(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
) -> None:
    """Describe project's Git and DVC storage.

    Git storage is the project's Git remote, e.g., on GitHub, and DVC storage
    is set in the project's settings on the hub.
    """

    def get_dvc_storage_name(resource: dict | None) -> str:
        if resource is None:
            return "Calkit Hub storage"
        if resource.get("kind") == "hf-bucket":
            return f"Hugging Face bucket {resource['bucket']}"
        if resource.get("kind") == "box-folder":
            return f"Box, connected by {resource['connected_by']}"
        return str(resource["bucket"])

    def get_git_storage_name(url: str | None) -> str | None:
        if url is None:
            return None
        owner_and_name = calkit.get_owner_and_name_from_git_url(url)
        if "github.com" in url and owner_and_name is not None:
            return f"GitHub repo {'/'.join(owner_and_name)}"
        return url

    def format_gb(gb: float) -> str:
        return f"{gb * 1000:.1f} MB" if gb < 1 else f"{gb:.2f} GB"

    project = calkit.detect_project_name()
    try:
        git_url: str | None = calkit.git.get_repo().remote().url
    except Exception:
        git_url = None
    # A token in an HTTPS remote, e.g., ``https://user:token@host``, isn't
    # printed
    if git_url is not None and "://" in git_url:
        scheme, rest = git_url.split("://", 1)
        host_and_path = (
            rest.split("@", 1)[-1] if "@" in rest.split("/")[0] else rest
        )
        git_url = f"{scheme}://{host_and_path}"
    try:
        settings = calkit.hub.get(f"/projects/{project}/storage")
        usage = calkit.hub.get(f"/projects/{project}/storage/usage")
    except Exception as e:
        raise_error(f"Couldn't get storage for {project}: {e}")
    # Reads fall back through earlier storage, then the hub's own
    previous = [get_dvc_storage_name(r) for r in settings["previous"]]
    if settings["dvc"] is not None:
        previous.append(get_dvc_storage_name(None))
    account = usage.get("account")
    git_storage = get_git_storage_name(git_url)
    dvc_storage = get_dvc_storage_name(settings["dvc"])
    desc = {
        "project": project,
        "git": {"storage": git_storage, "url": git_url},
        "dvc": {
            "storage": dvc_storage,
            "previous_storage": previous,
            "hub_used_gb": usage["project_used_gb"],
            "account_hub_used_gb": account["used_gb"] if account else None,
            "account_hub_limit_gb": account["limit_gb"] if account else None,
        },
    }
    if json_output:
        echo_json(desc)
        return
    _echo_description(
        {
            "project": project,
            "git storage": git_storage,
            "dvc storage": dvc_storage,
            "dvc also read from": ", ".join(previous) or None,
            "hub storage used": format_gb(usage["project_used_gb"]),
            "account hub storage used": (
                f"{format_gb(account['used_gb'])} of "
                f"{account['limit_gb']:g} GB"
                if account
                else None
            ),
        }
    )


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
    with open(output, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    typer.echo(f"Wrote schema to {output}")
