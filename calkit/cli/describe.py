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
    which: Annotated[
        str,
        typer.Option(
            "--for",
            help=(
                "Which schema: 'calkit.yaml', or 'provenance' for the "
                "record a build writes beside each artifact."
            ),
        ),
    ] = "calkit.yaml",
) -> None:
    """Print a JSON schema.

    Editors can use these to validate and autocomplete the files they
    describe. See https://docs.calkit.org/calkit-yaml for how to set that
    up.
    """
    if which not in ("calkit.yaml", "provenance"):
        raise_error(
            f"Unknown schema: {which}. Choose calkit.yaml or provenance."
        )
    txt = (
        calkit.schema.generate_json()
        if which == "calkit.yaml"
        else calkit.schema.generate_provenance_json()
    )
    if output is None:
        typer.echo(txt, nl=False)
        return
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(txt)
    typer.echo(f"Wrote schema to {output}")


def _component_line(c) -> str:
    """One component as a line someone can read."""
    marks = {
        "ok": "ok",
        "stale": "STALE",
        "missing": "MISSING",
        "unknown": "unchecked",
    }
    head = f"{c.kind} {c.location}"
    bits = [marks[c.status]]
    if c.stage:
        bits.append(f"stage {c.stage}")
    elif c.provenance == "undeclared":
        # Nothing produced it and nobody has said where it came from,
        # which is the one thing about a component no check can catch
        bits.append("NO PROVENANCE")
    elif c.provenance in ("imported", "attested"):
        bits.append(c.provenance)
    if c.script:
        bits.append(c.script)
    if c.pages:
        bits.append("p. " + ", ".join(str(p) for p in c.pages))
    if c.stale_reasons:
        bits.append("; ".join(c.stale_reasons))
    if c.kind == "value" and c.current_value is not None:
        drifted = (
            c.build_value is not None and c.build_value != c.current_value
        )
        bits.append(
            f"{c.build_value} -> {c.current_value}"
            if drifted
            else f"= {c.current_value}"
        )
    return f"{head}\n    " + " · ".join(bits)


@describe_app.command(name="components|component")
def describe_components(
    document: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Document to describe. The LaTeX source, the built PDF, or "
                "the provenance sidecar all name the same document. Left "
                "out, it is worked out from --source, or from the project "
                "if it builds only one document."
            )
        ),
    ] = None,
    line: Annotated[
        int | None,
        typer.Option(
            "--line",
            help=(
                "Describe only what is on this line of the source "
                "(1-based), rather than the whole document."
            ),
        ),
    ] = None,
    column: Annotated[
        int | None,
        typer.Option(
            "--column",
            "--col",
            help="Narrow a --line to the component under this column.",
        ),
    ] = None,
    source: Annotated[
        str | None,
        typer.Option(
            "--source",
            help=(
                "File the --line refers to, if the cursor is in a file the "
                "document inputs rather than the document itself."
            ),
        ),
    ] = None,
    page: Annotated[
        int | None,
        typer.Option("--page", help="Only components appearing on this page."),
    ] = None,
    stale_only: Annotated[
        bool,
        typer.Option(
            "--stale",
            help=(
                "Only components known to be out of date or missing. A "
                "component nothing could be checked about is not one of "
                "them; it reads as unknown in the full listing."
            ),
        ),
    ] = False,
    no_stage_check: Annotated[
        bool,
        typer.Option(
            "--no-stage-check",
            help=(
                "Skip the pipeline status check, which is the slow part. "
                "Drift between the document and the project is still "
                "reported; a stage needing a rerun is not."
            ),
        ),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
):
    """Describe the project content a document uses.

    Every value, figure and generated block the document takes from the
    project, with the file it came from, the stage and script that produce
    it, the pages it lands on, and whether it is still current -- either
    because its stage needs a rerun, or because the project has moved on
    since the document was built.

    With --line (and optionally --column) this answers "what is under my
    cursor?", which is what an editor asks on hover or go-to-definition.
    """
    import calkit.components

    if column is not None and line is None:
        raise_error("--column needs a --line")
    if line is not None and page is not None:
        raise_error("--page and --line select different things; use one")
    if document is None:
        ck_info = calkit.load_calkit_info()
        documents = calkit.components.latex_documents(ck_info)
        if source:
            document = calkit.components.document_for_source(source, ck_info)
        elif len(documents) == 1:
            document = documents[0]
        if document is None:
            raise_error(
                "No document given, and the project builds none. "
                "Name the document to describe."
                if not documents
                else (
                    "Could not tell which document to describe; the project "
                    "builds " + ", ".join(sorted(documents)) + ". Name one."
                )
            )
    check_stages = not no_stage_check
    if line is not None:
        components = calkit.components.resolve_position(
            source=source or calkit.components.source_path(document),
            line=line,
            col=column,
            document=document,
            check_stages=check_stages,
        )
        result = {"source": document, "components": components}
    else:
        described = calkit.components.describe_document(
            document, check_stages=check_stages
        )
        components = described.components
        if page is not None:
            components = [c for c in components if page in c.pages]
        result = {
            "artifact": described.artifact,
            "source": described.source,
            "kind": described.kind,
            "built": described.built,
            "components": components,
        }
    if stale_only:
        components = [
            c for c in components if c.status in ("stale", "missing")
        ]
        result["components"] = components
    if json_output:
        echo_json(
            {
                **result,
                "components": [c.model_dump(mode="json") for c in components],
            }
        )
        return
    if not components:
        typer.echo("No components found")
        return
    for c in components:
        typer.echo(_component_line(c))
