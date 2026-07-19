"""CLI for syncing."""

from __future__ import annotations

import sys
from typing import Callable

import typer

from calkit.cli import AliasGroup

sync_app = typer.Typer(
    cls=AliasGroup, no_args_is_help=True, help="Sync with disparate systems."
)

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

    for t in order:
        if t in SYNC_TARGETS:
            targets_to_run.append(t)
    for t in SYNC_TARGETS:
        if t not in targets_to_run:
            targets_to_run.append(t)

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

    if failures:
        sys.exit(1)
