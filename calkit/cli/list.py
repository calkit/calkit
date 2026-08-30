"""CLI for listing objects."""

from __future__ import annotations

from typing import Annotated, Literal

import typer

import calkit
from calkit.cli import AliasGroup, echo_json, raise_error, warn

list_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def _echo_object(obj: dict) -> None:
    """Print a single object in the human-readable YAML-ish listing format."""
    # Copy so popping 'path' doesn't mutate the caller's dict.
    obj = dict(obj)
    path = obj.pop("path", None)
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


def _list_objects(
    kind: Literal[
        "notebooks",
        "datasets",
        "figures",
        "references",
        "publications",
        "misc",
    ],
    json_output: bool = False,
):
    """List objects."""
    ck_info = calkit.load_calkit_info()
    objs = ck_info.get(kind, []) or []
    if json_output:
        echo_json(objs)
        return
    for obj in objs:
        _echo_object(obj)


def _list_artifacts(
    kind: Literal["figures", "datasets", "results", "presentations"],
    json_output: bool,
    declared_only: bool,
):
    """List figures or datasets, optionally including auto-detected ones.

    By default, artifacts declared in ``calkit.yaml`` are merged with any
    auto-detected from the project's files; ``--declared-only`` returns just the
    declared ones. Each entry carries a ``detected`` flag so callers can tell
    declared and auto-detected artifacts apart.
    """
    ck_info = calkit.load_calkit_info()
    declared = [o for o in ck_info.get(kind) or [] if isinstance(o, dict)]
    declared_paths = {o.get("path") for o in declared}
    detected: list[dict] = []
    if not declared_only:
        found = calkit.detect.detect_project_artifacts(ck_info=ck_info)
        for path in found.get(kind, []):
            if path not in declared_paths:
                detected.append({"path": path})
    if json_output:
        result = [
            {**o, "detected": False} for o in declared if isinstance(o, dict)
        ]
        result += [{**o, "detected": True} for o in detected]
        echo_json(result)
        return
    for obj in declared:
        _echo_object(obj)
    for obj in detected:
        _echo_object({**obj, "detected": True})


@list_app.command(name="notebooks|nb")
def list_notebooks(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List notebooks in the project."""
    _list_objects("notebooks", json_output)


@list_app.command(name="figures|figs")
def list_figures(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
    declared_only: Annotated[
        bool,
        typer.Option(
            "--declared-only",
            help=(
                "Only list figures declared in calkit.yaml; "
                "skip auto-detection."
            ),
        ),
    ] = False,
):
    """List figures in the project."""
    _list_artifacts("figures", json_output, declared_only)


@list_app.command(name="datasets")
def list_datasets(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
    declared_only: Annotated[
        bool,
        typer.Option(
            "--declared-only",
            help=(
                "Only list datasets declared in calkit.yaml; "
                "skip auto-detection."
            ),
        ),
    ] = False,
):
    """List datasets in the project."""
    _list_artifacts("datasets", json_output, declared_only)


@list_app.command(name="results")
def list_results(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
    declared_only: Annotated[
        bool,
        typer.Option(
            "--declared-only",
            help=(
                "Only list results declared in calkit.yaml; "
                "skip auto-detection."
            ),
        ),
    ] = False,
):
    """List results in the project."""
    _list_artifacts("results", json_output, declared_only)


@list_app.command(name="presentations|pres")
def list_presentations(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
    declared_only: Annotated[
        bool,
        typer.Option(
            "--declared-only",
            help=(
                "Only list presentations declared in calkit.yaml; "
                "skip auto-detection."
            ),
        ),
    ] = False,
):
    """List presentations in the project."""
    _list_artifacts("presentations", json_output, declared_only)


def _echo_question(n: int, question: str | dict) -> None:
    """Print a single question in the human-readable YAML-ish listing format.

    String questions are shown as a numbered line. Rich (dict) questions are
    shown with their text on the first line followed by hypothesis, answer,
    evidence, and any other fields in YAML-like indented form.
    """
    if isinstance(question, str):
        typer.echo(f"{n}. {question}")
        return
    # Copy so popping 'question' doesn't mutate the caller's dict.
    question = dict(question)
    text = question.pop("question", "")
    typer.echo(f"{n}. question: {text}")
    for k, v in question.items():
        if isinstance(v, dict):
            typer.echo(f"    {k}:")
            for k1, v1 in v.items():
                typer.echo(f"      {k1}: {v1}")
        elif isinstance(v, list):
            typer.echo(f"    {k}:")
            for item in v:
                if isinstance(item, dict):
                    for n1, (k1, v1) in enumerate(item.items()):
                        if n1 == 0:
                            typer.echo(f"      - {k1}: {v1}")
                        else:
                            typer.echo(f"        {k1}: {v1}")
                else:
                    typer.echo(f"        - {item}")
        else:
            typer.echo(f"    {k}: {v}")


@list_app.command(name="questions")
def list_questions(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List the project's questions (1-indexed)."""
    questions = calkit.load_calkit_info().get("questions", []) or []
    if json_output:
        echo_json(questions)
        return
    for n, question in enumerate(questions, start=1):
        _echo_question(n, question)


@list_app.command(name="publications|pubs")
def list_publications(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List publications in the project."""
    _list_objects("publications", json_output)


@list_app.command(name="misc")
def list_misc(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List misc artifacts in the project, i.e., attributed paths that
    aren't one of the typed kinds.
    """
    _list_objects("misc", json_output)


@list_app.command(name="references|refs")
def list_references(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List reference collections in the project."""
    _list_objects("references", json_output)


@list_app.command(name="environments|envs")
def list_environments(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List environments in the project."""
    envs = calkit.load_calkit_info().get("environments", {})
    if json_output:
        echo_json(envs)
        return
    for name, env in envs.items():
        typer.echo(name + ":")
        for k, v in env.items():
            typer.echo(f"    {k}: {v}")


@list_app.command(name="templates")
def list_templates(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List all available Calkit templates."""
    names = [
        f"{kind}/{name}"
        for kind, tpl_dict in calkit.templates.TEMPLATES.items()
        for name in tpl_dict
    ]
    if json_output:
        echo_json(names)
        return
    for name in names:
        typer.echo(name)


@list_app.command(name="installers")
def list_installers(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
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
    result: list[dict] = []
    for names in groups.values():
        names.sort()
        entry = calkit.install.INSTALLERS[names[0]]
        scripts = {}
        for platform in ("unix", "windows"):
            ins = entry.get(platform)  # type: ignore[call-overload]
            if ins is not None:
                scripts[platform] = ins["script"]
        result.append(
            {"name": names[0], "aliases": names[1:], "scripts": scripts}
        )
    if json_output:
        echo_json(result)
        return
    for installer in result:
        aliases = ", ".join(installer["aliases"])
        header = installer["name"] + (
            f"  (aliases: {aliases})" if aliases else ""
        )
        typer.echo(header)
        for platform, script in installer["scripts"].items():
            typer.echo(f"  {platform}: {script}")


@list_app.command(name="procedures")
def list_procedures(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List procedures in the current project."""
    ck_info = calkit.load_calkit_info()
    names = list(ck_info.get("procedures", {}))
    if json_output:
        echo_json(names)
        return
    for name in names:
        typer.echo(name)


@list_app.command(name="releases")
def list_releases(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List releases."""
    objs = calkit.load_calkit_info().get("releases", {})
    result = {}
    for name, obj in objs.items():
        # Figure out if the release is published. Internal releases are never
        # uploaded to an archival service, so skip the lookup for them.
        published = None
        if not obj.get("internal"):
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
                    warn(
                        f"Cannot tell if release {name} is published: {e}",
                        err=json_output,
                    )
        # The looked-up status wins over any stray 'published' key in
        # calkit.yaml, which isn't part of the release schema
        result[name] = {"published": published} | {
            k: v for k, v in obj.items() if k != "published"
        }
    if json_output:
        echo_json(result)
        return
    for name, obj in result.items():
        typer.echo(name + ":")
        for k, v in obj.items():
            # 'published' is only known when the lookup above succeeded
            if k == "published" and v is None:
                continue
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
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List pipeline stages."""
    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    # If we only want stale stages, we need to get the status first.
    # This compiles the pipeline, cleans notebooks, and checks environments,
    # all of which can affect whether a stage is stale, so we don't skip them.
    if stale_only:
        status = calkit.pipeline.get_status(ck_info=ck_info)
        if status.errors:
            raise_error(
                "Failed to determine stale stages: " + "; ".join(status.errors)
            )
        stale_stage_names = status.stale_stage_names
    result = {}
    for name, stage in stages.items():
        if kinds is not None and stage.get("kind") not in kinds:
            continue
        if stale_only and name not in stale_stage_names:
            continue
        result[name] = stage
    if json_output:
        echo_json(result)
        return
    for name in result:
        typer.echo(name)


@list_app.command(name="remotes")
def list_remotes(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """List Git and DVC remotes."""
    result: dict[str, dict] = {"git": {}, "dvc": {}}
    try:
        repo = calkit.git.get_repo()
        for remote in repo.remotes:
            result["git"][remote.name] = remote.url
    except Exception as e:
        warn(f"Could not list Git remotes: {e}", err=json_output)
    # Now DVC remotes
    try:
        result["dvc"] = calkit.dvc.get_remotes()
    except Exception as e:
        warn(f"Could not list DVC remotes: {e}", err=json_output)
    if json_output:
        echo_json(result)
        return
    for name, url in result["git"].items():
        typer.echo(f"(Git) {name}: {url}")
    for name, url in result["dvc"].items():
        typer.echo(f"(DVC) {name}: {url}")
