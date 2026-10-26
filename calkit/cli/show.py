"""CLI for showing objects."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from calkit.cli import AliasGroup, echo_json, raise_error, warn

show_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


@show_app.command(name="latex-diff")
def show_latex_diff(
    target: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Which diff: its stage or PDF, the document or its PDF, the "
                "latex stage, or the revision it compares against. Can be "
                "omitted if the project keeps only one."
            )
        ),
    ] = None,
    run: Annotated[
        bool,
        typer.Option(
            "--run", help="Build the diff first if it's stale or not built."
        ),
    ] = False,
) -> None:
    """Open a LaTeX diff the pipeline keeps.

    From VS Code's terminal it opens in the editor, otherwise in the
    system's PDF viewer.
    """
    import calkit.latex

    def norm(path: str) -> str:
        return Path(os.path.normpath(path)).as_posix()

    ck_info = calkit.load_calkit_info()
    try:
        diffs = calkit.latex.get_pipeline_diffs(ck_info, status=True)
    except RuntimeError as e:
        raise_error(f"Failed to determine diff status: {e}")
    if target is not None:
        diffs = [
            diff
            for diff in diffs
            if target in (diff["stage"], diff["latex_stage"], diff["from_ref"])
            or norm(target)
            in (
                diff["path"],
                diff["document"],
                norm(str(Path(diff["document"]).with_suffix(".pdf"))),
            )
        ]
    if not diffs:
        raise_error(
            "No LaTeX diff"
            + (f" matches '{target}'" if target is not None else "s are kept")
            + "; see 'calkit list latex-diffs'"
        )
    if len(diffs) > 1:
        names = ", ".join(diff["stage"] for diff in diffs)
        raise_error(f"More than one diff matches; name one of: {names}")
    diff = diffs[0]
    if diff["status"] != "up to date":
        if run:
            # Its own process, so the run reports what it did the usual way
            status = subprocess.call(
                [sys.executable, "-m", "calkit", "run", diff["stage"]]
            )
            if status:
                raise_error(f"Failed to build {diff['path']}")
        elif diff["status"] == "not built":
            raise_error(
                f"{diff['path']} hasn't been built; run 'calkit run "
                f"{diff['stage']}' or pass --run"
            )
        else:
            warn(
                f"{diff['path']} is stale; run 'calkit run {diff['stage']}' "
                "or pass --run to update it"
            )
    # The editor's CLI opens it in the window the terminal belongs to
    code = shutil.which("code")
    if os.environ.get("TERM_PROGRAM") == "vscode" and code is not None:
        subprocess.call([code, diff["path"]])
    else:
        typer.launch(diff["path"])


@show_app.command(name="table|tbl")
def show_table(
    path: Annotated[str, typer.Argument(help="Path to the table.")],
    columns: Annotated[
        list[str] | None,
        typer.Option(
            "--column",
            "-c",
            help="Only show these columns, in this order. Can be a glob, "
            "e.g., `*_mod`, and can be given more than once.",
        ),
    ] = None,
    filters: Annotated[
        list[str] | None,
        typer.Option(
            "--filter",
            "-f",
            help="Only show rows matching COLUMN=VALUE, COLUMN~TEXT "
            "(contains, ignoring case), or COLUMN>NUMBER. Can be given "
            "more than once, and all must match.",
        ),
    ] = None,
    rows: Annotated[
        str | None,
        typer.Option(
            "--rows",
            "-r",
            help="Only show these rows, 1-based, e.g., '1-20', '5,9', '40-'.",
        ),
    ] = None,
    head: Annotated[
        int | None,
        typer.Option("--head", "-n", help="Only show the first N rows."),
    ] = None,
    tail: Annotated[
        int | None,
        typer.Option("--tail", help="Only show the last N rows."),
    ] = None,
    git_ref: Annotated[
        str | None,
        typer.Option(
            "--git-ref",
            help="Show the table as of this Git branch, tag, or commit "
            "instead of the working tree.",
        ),
    ] = None,
    status: Annotated[
        bool,
        typer.Option(
            "--status",
            "-s",
            help="Also say whether the table is up to date.",
        ),
    ] = False,
    vscode: Annotated[
        bool,
        typer.Option(
            "--vscode",
            help="Open the table in VS Code instead of printing it.",
        ),
    ] = False,
    engine: Annotated[
        str | None,
        typer.Option(
            "--engine",
            help="Dataframe engine for formats the standard library can't "
            "read, e.g., Parquet. Defaults to the configured one.",
        ),
    ] = None,
) -> None:
    """Show a table, or part of one.

    With --status, says whether the stage that writes the table has been
    run since its inputs last changed. At a --git-ref that's reconstructed
    from the dvc.lock committed there, since there is nothing on disk at an
    old commit for DVC to hash, and what it couldn't check is reported
    rather than assumed current.
    """
    import calkit.pipeline
    import calkit.tables

    content = None
    if git_ref is not None:
        try:
            content = calkit.pipeline.read_artifact_at_ref(path, git_ref)
        except FileNotFoundError as e:
            raise_error(str(e))
    elif not os.path.isfile(path):
        raise_error(
            f"{path} does not exist; see 'calkit list tables' for what the "
            "project has"
        )
    if status:
        _echo_artifact_status(path, git_ref)
    if vscode:
        _open_in_vscode(path, git_ref, content)
        return
    selected = [
        name.strip()
        for value in columns or []
        for name in value.split(",")
        if name.strip()
    ]
    try:
        table = calkit.tables.read_table(
            path,
            content=content,
            columns=selected or None,
            filters=filters,
            rows=rows,
            head=head,
            tail=tail,
            engine=engine,  # type: ignore[arg-type]
        )
    except (ValueError, ImportError) as e:
        raise_error(str(e))
    _echo_table(path, table, git_ref)


def _echo_artifact_status(path: str, git_ref: str | None) -> None:
    import calkit.pipeline

    if git_ref is not None:
        try:
            state = calkit.pipeline.artifact_status_at_ref(path, git_ref)
        except FileNotFoundError as e:
            warn(str(e))
            return
        line = f"{state['status']} at {git_ref}"
        if state["unverifiable"]:
            line += f" ({state['unverifiable']} input(s) not checkable)"
        typer.echo(line)
        for reason in state["reasons"]:
            typer.echo(f"  {reason}")
        return
    norm = Path(os.path.normpath(path)).as_posix()
    try:
        annotated = calkit.pipeline.annotate_artifacts(
            [{"path": norm}], status=True
        )[0]
    except RuntimeError as e:
        warn(f"Failed to determine status: {e}")
        return
    stages = ", ".join(annotated.get("stages") or [])
    typer.echo(annotated["status"] + (f" (stage: {stages})" if stages else ""))


def _open_in_vscode(
    path: str, git_ref: str | None, content: bytes | None
) -> None:
    import tempfile

    code = shutil.which("code")
    if code is None:
        raise_error(
            "The 'code' command isn't on PATH; install VS Code's shell "
            "command from its command palette"
        )
    target = path
    if content is not None:
        # The ref's contents aren't on disk, so give the editor a file
        # named for what it holds
        stem, ext = os.path.splitext(os.path.basename(path))
        safe_ref = git_ref.replace("/", "-") if git_ref else "ref"
        target = os.path.join(
            tempfile.mkdtemp(prefix="calkit-table-"),
            f"{stem}@{safe_ref}{ext}",
        )
        with open(target, "wb") as f:
            f.write(content)
    subprocess.call([code, target])


def _echo_table(path: str, table: dict, git_ref: str | None) -> None:
    from rich import box
    from rich.console import Console
    from rich.table import Table

    columns, rows = table["columns"], table["rows"]
    # Named on its own line rather than as the table's title, which a
    # narrow table wraps a character at a time
    typer.echo(path + (f" @ {git_ref}" if git_ref else ""))
    rendered = Table(header_style="bold", box=box.SIMPLE, pad_edge=False)
    for i, column in enumerate(columns):
        # Right-align a column whose every value is a number, so figures
        # line up on the decimal point
        values = [row[i] for row in rows if row[i] != ""]
        numeric = bool(values) and all(_is_number(v) for v in values)
        rendered.add_column(column, justify="right" if numeric else "left")
    for row in rows:
        rendered.add_row(*row)
    console = Console()
    squeezed = console.measure(rendered).maximum > console.width
    console.print(rendered)
    shown = len(rows)
    matching, total = table["n_rows_matching"], table["n_rows"]
    if shown != total:
        line = f"{shown} of {total} rows"
        if matching != total:
            line += f", {matching} matching the filter"
        typer.echo(line)
    if squeezed:
        typer.echo(
            f"{len(columns)} columns don't fit; name the ones you want with "
            "-c, which takes globs, e.g., -c '*_mod'"
        )


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


@show_app.command(name="result|res")
def show_result(
    path: Annotated[str, typer.Argument(help="Path to the result.")],
    keys: Annotated[
        list[str] | None,
        typer.Option(
            "--key",
            "-k",
            help="Only show these keys, dotted as a question's evidence "
            "writes them, e.g., `steady_state.saved_pct`. Can be given "
            "more than once.",
        ),
    ] = None,
    depth: Annotated[
        int | None,
        typer.Option(
            "--depth",
            "-d",
            help="Stop flattening this many levels in and show the rest "
            "of each value as JSON.",
        ),
    ] = None,
    git_ref: Annotated[
        str | None,
        typer.Option(
            "--git-ref",
            help="Show the result as of this Git branch, tag, or commit "
            "instead of the working tree.",
        ),
    ] = None,
    status: Annotated[
        bool,
        typer.Option(
            "--status",
            "-s",
            help="Also say whether the result is up to date.",
        ),
    ] = False,
    vscode: Annotated[
        bool,
        typer.Option(
            "--vscode",
            help="Open the result in VS Code instead of printing it.",
        ),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output result as JSON.")
    ] = False,
) -> None:
    """Show a result's keys and values.

    Keys are shown dotted, the way a question's value evidence names them,
    so what's printed is what an answer can cite. With --status, says
    whether the stage that writes the result has been run since its inputs
    last changed.
    """
    import calkit.pipeline
    import calkit.results

    content = None
    if git_ref is not None:
        try:
            content = calkit.pipeline.read_artifact_at_ref(path, git_ref)
        except FileNotFoundError as e:
            raise_error(str(e))
    elif not os.path.isfile(path):
        raise_error(
            f"{path} does not exist; see 'calkit list results' for what the "
            "project has"
        )
    if status:
        _echo_artifact_status(path, git_ref)
    if vscode:
        _open_in_vscode(path, git_ref, content)
        return
    selected = [
        key.strip()
        for value in keys or []
        for key in value.split(",")
        if key.strip()
    ]
    try:
        result = calkit.results.read_result(
            path, content=content, keys=selected or None, depth=depth
        )
    except ValueError as e:
        raise_error(str(e))
    if json_output:
        echo_json(result["items"])
        return
    _echo_result(path, result, git_ref)


def _echo_result(path: str, result: dict, git_ref: str | None) -> None:
    from rich import box
    from rich.console import Console
    from rich.table import Table

    typer.echo(path + (f" @ {git_ref}" if git_ref else ""))
    rendered = Table(header_style="bold", box=box.SIMPLE, pad_edge=False)
    rendered.add_column("key")
    rendered.add_column(
        "value",
        justify="right"
        if all(
            _is_number(item["value"])
            for item in result["items"]
            if item["value"] != ""
        )
        else "left",
    )
    for item in result["items"]:
        rendered.add_row(item["key"], item["value"])
    Console().print(rendered)
