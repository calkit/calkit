"""CLI for fixing things."""

from __future__ import annotations

import sys

import click
import typer
from typing_extensions import Annotated

from calkit.cli import AliasGroup, raise_error, warn

fix_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)

OursOpt = Annotated[
    list[str],
    typer.Option(
        "--ours",
        "-o",
        help="Keep our side of this stage (repeatable).",
        show_default=False,
    ),
]
TheirsOpt = Annotated[
    list[str],
    typer.Option(
        "--theirs",
        "-t",
        help="Keep their side of this stage (repeatable).",
        show_default=False,
    ),
]
RerunOpt = Annotated[
    list[str],
    typer.Option(
        "--rerun",
        "-r",
        help="Keep neither side of this stage, so it reruns (repeatable).",
        show_default=False,
    ),
]
PreferOpt = Annotated[
    str | None,
    typer.Option(
        "--prefer",
        help="Choice for every other stage changed on both sides "
        "(ours, theirs, or rerun).",
    ),
]


def resolve_merge_conflicts(
    ours: list[str] | None = None,
    theirs: list[str] | None = None,
    rerun: list[str] | None = None,
    prefer: str | None = None,
) -> dict:
    """Resolve conflicts in the files Calkit merges, asking for choices.

    Returns what ``calkit.merge.resolve_conflicts`` does.
    """
    import calkit.git
    import calkit.merge

    if prefer is not None and prefer not in calkit.merge.CHOICES:
        raise_error(
            f"--prefer must be one of {', '.join(calkit.merge.CHOICES)}"
        )
    choices: dict[str, str] = {}
    for choice, names in [
        (calkit.merge.OURS, ours),
        (calkit.merge.THEIRS, theirs),
        (calkit.merge.RERUN, rerun),
    ]:
        for name in names or []:
            if name in choices and choices[name] != choice:
                raise_error(f"Stage '{name}' was given more than one choice")
            choices[name] = choice
    repo = calkit.git.get_repo()
    operation = calkit.merge.get_operation(repo)
    if operation is None:
        raise_error("No merge, rebase, or cherry-pick is in progress")
    assert operation is not None
    labels = {}
    for side, ref in [("ours", "HEAD"), ("theirs", operation[1])]:
        labels[side] = repo.git.log("-1", "--format=%h %s", ref)

    def choose(name: str, info: dict) -> str:
        if not sys.stdin.isatty():
            raise_error(
                f"Stage '{name}' changed on both sides; choose with --ours, "
                "--theirs, --rerun, or --prefer"
            )
        typer.echo(f"\nStage '{name}' changed on both sides:")
        for side in ("ours", "theirs"):
            typer.echo(f"  {side} ({labels[side]}): {info[side]}")
        if info["changed_deps"]:
            typer.echo(
                "  Inputs that differ: " + ", ".join(info["changed_deps"])
            )
        answer = typer.prompt(
            "Keep [o]urs, [t]heirs, or [r]erun it",
            type=click.Choice(["o", "t", "r"]),
            show_choices=False,
        )
        return {"o": "ours", "t": "theirs", "r": "rerun"}[answer]

    try:
        result = calkit.merge.resolve_conflicts(
            repo, choices=choices, prefer=prefer, choose=choose
        )
    except calkit.merge.MergeError as e:
        raise_error(str(e))
    unknown = sorted(set(choices) - set(result["choices"]))
    for name in unknown:
        warn(
            f"Stage '{name}' wasn't changed on both sides; ignoring its choice"
        )
    for path in result["resolved"]:
        typer.echo(f"Resolved {path}")
    rerun_names = [
        n for n, c in result["choices"].items() if c == calkit.merge.RERUN
    ]
    if rerun_names:
        typer.echo(
            "Run 'calkit run' to rerun " + ", ".join(sorted(rerun_names))
        )
    if result["unmerged"]:
        typer.echo("Still in conflict:")
        for path in result["unmerged"]:
            typer.echo(f"  {path}")
    return result


@fix_app.command(name="merge-conflicts")
def fix_merge_conflicts(
    ours: OursOpt = [],
    theirs: TheirsOpt = [],
    rerun: RerunOpt = [],
    prefer: PreferOpt = None,
) -> None:
    """Resolve merge conflicts in dvc.lock and stage run records.

    Each stage is merged whole. A stage changed on one side takes that side,
    and one changed on both needs a choice, which also decides its run record
    and Git-tracked outputs. Stages are named as in 'calkit check
    stage-runs', e.g., 'sub/dvc.yaml:stage' for a subproject's.
    """
    import calkit.dvc
    import calkit.dvc.zip

    result = resolve_merge_conflicts(
        ours=ours, theirs=theirs, rerun=rerun, prefer=prefer
    )
    if result["unmerged"]:
        raise typer.Exit(1)
    # Outputs in DVC to match the merged dvc.lock
    calkit.dvc.run_dvc_command(["checkout"])
    calkit.dvc.zip.sync_all(direction="to-workspace")
    finish = {
        "merge": "git commit",
        "rebase": "git rebase --continue",
        "cherry-pick": "git cherry-pick --continue",
    }[result["operation"]]
    typer.echo(f"Run '{finish}' to finish")


@fix_app.command(name="storage")
def fix_storage() -> None:
    """Move each path to where it's declared to be stored.

    Same as 'calkit check storage --fix'.
    """
    from calkit.cli.check import check_storage

    check_storage(fix=True, as_json=False)
