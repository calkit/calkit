"""CLI for syncing."""

from __future__ import annotations

from typing import Callable

import typer
from typing_extensions import Annotated

import calkit
from calkit.cli import AliasGroup, raise_error

sync_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)


def sync_overleaf() -> None:
    """Sync folders with Overleaf."""
    from calkit.cli.overleaf import sync as overleaf_sync

    overleaf_sync()


@sync_app.command(name="git")
def sync_git(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
) -> None:
    """Sync the Git repository by pulling and then pushing."""
    from calkit.cli.main.core import pull, push

    try:
        repo = calkit.git.get_repo()
    except Exception:
        raise_error("No Git repository found. Run 'git init' first.")
    if not repo.remotes:
        raise_error(
            "No Git remotes configured. Add a remote with "
            "'git remote add <name> <url>'."
        )
    pull(no_dvc=True, no_check_auth=no_check_auth)
    push(no_dvc=True, no_check_auth=no_check_auth)


@sync_app.command(name="dvc")
def sync_dvc(
    no_check_auth: Annotated[bool, typer.Option("--no-check-auth")] = False,
) -> None:
    """Sync the DVC repository by pulling and then pushing."""
    from calkit.cli.main.core import pull, push

    try:
        calkit.dvc.get_dvc_repo()
    except Exception:
        raise_error("No DVC repository found. Run 'calkit init' first.")
    if not calkit.dvc.get_remotes():
        raise_error(
            "No DVC remotes configured. Add a remote with "
            "'dvc remote add <name> <url>'."
        )
    pull(no_git=True, no_check_auth=no_check_auth)
    push(no_git=True, no_check_auth=no_check_auth)


@sync_app.command(name="all")
def sync_all() -> None:
    """Sync all registered systems."""
    # Run each known target in a stable order, reporting and collecting any
    # failures. Each target is responsible for raising a clear error if it is
    # not configured, so users calling 'calkit sync <target>' directly get a
    # helpful message.
    sync_funcs: list[tuple[str, Callable[[], None]]] = [
        ("git", sync_git),
        ("dvc", sync_dvc),
        ("overleaf", sync_overleaf),
    ]
    failures = []
    for target_name, sync_func in sync_funcs:
        typer.echo(f"Syncing {target_name}...")
        try:
            sync_func()
        except Exception as e:
            typer.echo(f"Failed to sync {target_name}: {e}", err=True)
            failures.append(target_name)
    # Exit with an error if any target failed so callers can react.
    if failures:
        raise typer.Exit(1)
