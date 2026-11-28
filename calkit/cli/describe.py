"""CLI for describing things."""

from __future__ import annotations

import os
import pathlib
from typing import Annotated

import typer

import calkit
from calkit.cli import DefaultCommandGroup, echo_json, raise_error


class DescribeGroup(DefaultCommandGroup):
    default_command = "artifact"


describe_app = typer.Typer(cls=DescribeGroup, no_args_is_help=True)


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
        if resource.get("kind") == "s3-bucket":
            read_only = " (read-only)" if resource.get("read_only") else ""
            return f"S3 bucket s3://{resource['bucket']}{read_only}"
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
    kit: Annotated[
        bool,
        typer.Option(
            "--kit", help="Print the schema for calkit manifests instead."
        ),
    ] = False,
) -> None:
    """Print the JSON schema for calkit.yaml.

    Editors can use this to validate and autocomplete the file. See
    https://docs.calkit.org/calkit-yaml for how to set that up.
    """
    if kit:
        from calkit.kits import generate_schema_json

        txt = generate_schema_json()
    else:
        txt = calkit.schema.generate_json()
    if output is None:
        typer.echo(txt, nl=False)
        return
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    typer.echo(f"Wrote schema to {output}")


@describe_app.command(name="artifact")
def describe_artifact(
    path: Annotated[str, typer.Argument(help="Path of a file.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print as JSON.")
    ] = False,
) -> None:
    """Describe a file, what made it, and whether it's reproducible.

    Says what kind of artifact it is, which stage makes it, whether that's
    up to date, and which inputs have no recorded origin. Reads the calkit
    embedded in it, if it has one, so this works for a file shared from
    another project; otherwise, describes it as part of this project.
    'calkit describe PATH' is short for this.
    """
    import calkit.kits
    import calkit.pipeline
    import calkit.provenance

    if not os.path.isfile(path):
        # Probably a mistyped subcommand, if it doesn't look like a path
        if "/" not in path and "." not in path:
            raise_error(f"No such command or file: {path}")
        raise_error(f"{path} doesn't exist")
    try:
        kit = calkit.kits.read(path)
    except ValueError as e:
        raise_error(f"Can't read calkit: {e}")
    # A file with a calkit is described by it, wherever it is
    if kit is not None:
        manifest = kit.manifest
        if as_json:
            echo_json(
                {
                    "path": path,
                    "calkit": manifest.model_dump(
                        exclude_none=True, by_alias=True
                    ),
                    "calkit_size": len(kit.kit),
                    "artifact_unchanged": kit.artifact_unchanged,
                    "matches_pipeline": kit.matches_pipeline,
                }
            )
            return
        source = manifest.source
        where = source.name or "project"
        if source.commit_sha:
            where += f" at {source.commit_sha[:7]}"
        remote = source.git_remotes.get("origin") or next(
            iter(source.git_remotes.values()), None
        )
        if remote:
            where += f" ({remote})"
        typer.echo(f"{manifest.artifact.path} from {where}")
        hub_url = calkit.kits.get_hub_file_url(manifest)
        if hub_url:
            typer.echo(f"On hub: {hub_url}")
        typer.echo(f"Made by stage: {manifest.artifact.stage}")
        if not kit.artifact_unchanged:
            typer.echo(
                typer.style("Modified since calkit was created", fg="red")
            )
        elif kit.matches_pipeline is False:
            typer.echo(
                typer.style("Doesn't match pipeline's output", fg="red")
            )
        else:
            typer.echo("Unchanged since calkit was created")
        if not source.up_to_date:
            typer.echo(typer.style("Pipeline was out of date", fg="yellow"))
        if source.uncommitted_paths:
            typer.echo(
                typer.style(
                    "Uncommitted changes: "
                    + ", ".join(source.uncommitted_paths),
                    fg="yellow",
                )
            )
        for gap in manifest.provenance_gaps:
            typer.echo(typer.style(gap.message, fg="yellow"))
        if not manifest.provenance_gaps:
            typer.echo("Provenance defined for all inputs")
        left_out = [f for f in manifest.files if not f.included]
        typer.echo(
            f"Calkit: {len(kit.kit) / 1e3:.0f} KB, "
            f"{len(manifest.files) - len(left_out)} file"
            + "s" * (len(manifest.files) - len(left_out) != 1)
            + (f", {len(left_out)} left out" if left_out else "")
        )
        for f in manifest.files:
            mark = " " if f.included else "-"
            typer.echo(f"  {mark} {f.path} ({f.size:,} bytes)")
        if left_out:
            typer.echo(
                "  (- left out; pull or remake after 'calkit kit expand')"
            )
        return
    # Otherwise it has to be part of this project
    rel_path = pathlib.Path(os.path.relpath(path)).as_posix()
    if not os.path.isfile("calkit.yaml") or rel_path.startswith("../"):
        raise_error(f"{path} has no calkit and isn't in a Calkit project here")
    ck_info = calkit.load_calkit_info()
    found = calkit.provenance.find_artifact(ck_info, rel_path)
    kind, artifact = found if found is not None else (None, {})
    stage = calkit.pipeline.get_stage_for_output(rel_path, ck_info)
    stale_stages = None
    if stage is not None:
        status = calkit.pipeline.get_status(ck_info=ck_info, targets=[stage])
        if status.errors:
            raise_error("Pipeline checks failed: " + "; ".join(status.errors))
        stale_stages = status.stale_stage_names
    gaps = calkit.provenance.find_project_provenance_gaps(
        [rel_path], ck_info=ck_info
    )
    if as_json:
        echo_json(
            {
                "path": rel_path,
                "calkit": None,
                "kind": kind,
                "title": artifact.get("title"),
                "stage": stage,
                "up_to_date": None
                if stale_stages is None
                else not stale_stages,
                "imported_from": artifact.get("imported_from"),
                "created_by": artifact.get("created_by"),
                "provenance_gaps": [
                    {
                        "path": g.path,
                        "unchecked": g.unchecked,
                        "message": str(g),
                    }
                    for g in gaps
                ],
            }
        )
        return
    title = artifact.get("title")
    if kind is not None:
        name = kind.removesuffix("s") if kind != "misc" else "file"
        typer.echo(f"{rel_path}: {name}" + (f" '{title}'" if title else ""))
    else:
        typer.echo(f"{rel_path}: not declared in calkit.yaml")
    if stage is not None:
        typer.echo(f"Made by stage: {stage}")
        if stale_stages:
            typer.echo(
                typer.style(
                    "Out of date: " + ", ".join(stale_stages), fg="yellow"
                )
            )
        else:
            typer.echo("Up to date")
    elif artifact.get("imported_from"):
        typer.echo(f"Imported from: {artifact['imported_from']}")
    elif artifact.get("created_by"):
        typer.echo(f"Created by: {artifact['created_by']}")
    for project_gap in gaps:
        typer.echo(typer.style(str(project_gap), fg="yellow"))
    if not gaps:
        typer.echo("Provenance defined for all inputs")
    if stage is not None:
        typer.echo(
            f"No calkit; to share with one: calkit kit create {rel_path}"
        )
