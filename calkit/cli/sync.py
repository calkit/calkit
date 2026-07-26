"""CLI for syncing."""

from __future__ import annotations

from typing import Callable

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup

sync_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)

SYNC_TARGETS: dict[str, dict[str, Callable]] = {}


def register_sync_target(
    name: str, sync_func: Callable, is_configured_func: Callable
) -> None:
    """Register a target to be included in 'calkit sync all'."""
    SYNC_TARGETS[name] = {
        "sync_func": sync_func,
        "is_configured_func": is_configured_func,
    }


@sync_app.command(name="all")
def sync_all() -> None:
    """Sync all configured systems."""
    order = ["git", "dvc", "overleaf"]
    targets_to_run = []
    # Put known targets first in a stable order, then append any others.
    for t in order:
        if t in SYNC_TARGETS:
            targets_to_run.append(t)
    for t in SYNC_TARGETS:
        if t not in targets_to_run:
            targets_to_run.append(t)
    # Run each configured target, reporting and collecting any failures.
    failures = []
    for target in targets_to_run:
        target_info = SYNC_TARGETS[target]
        if target_info["is_configured_func"]():
            typer.echo(f"Syncing {target}...")
            try:
                target_info["sync_func"]()
            except Exception as e:
                typer.echo(f"Failed to sync {target}: {e}", err=True)
                failures.append(target)
        else:
            typer.echo(f"Skipping {target}: not configured.")
    # Exit with an error if any target failed so callers can react.
    if failures:
        raise typer.Exit(1)


def _is_git_configured() -> bool:
    """Check whether the Git repository is configured for syncing."""
    try:
        repo = calkit.git.get_repo()
        return len(repo.remotes) > 0
    except Exception:
        return False


@sync_app.command(name="git")
def sync_git(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
) -> None:
    """Sync the Git repository by pulling and then pushing."""
    from calkit.cli.main.core import pull, push

    pull(no_dvc=True, no_check_auth=no_check_auth)
    push(no_dvc=True, no_check_auth=no_check_auth)


register_sync_target("git", sync_git, _is_git_configured)


def _is_dvc_configured() -> bool:
    """Check whether DVC is configured for syncing.

    A DVC repo alone is not enough to sync: pulling or pushing requires at
    least one remote. We therefore check both that a DVC repo exists and that
    it has remotes configured.
    """
    try:
        return len(calkit.dvc.get_remotes()) > 0
    except Exception:
        return False


@sync_app.command(name="dvc")
def sync_dvc(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
) -> None:
    """Sync the DVC repository by pulling and then pushing."""
    from calkit.cli.main.core import pull, push

    pull(no_git=True, no_check_auth=no_check_auth)
    push(no_git=True, no_check_auth=no_check_auth)


register_sync_target("dvc", sync_dvc, _is_dvc_configured)
