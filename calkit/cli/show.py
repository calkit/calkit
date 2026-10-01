"""CLI for showing objects."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from calkit.cli import AliasGroup, raise_error, warn

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
