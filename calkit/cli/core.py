"""Core CLI functionality."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    import click


def complete_stage_names(
    ctx: "click.Context",
    param: "click.Parameter",
    incomplete: str,
) -> list:
    """Return pipeline stage names for shell tab-completion."""
    if not os.path.isfile("calkit.yaml"):
        return []
    try:
        import ruamel.yaml
        from click.shell_completion import CompletionItem

        ryaml = ruamel.yaml.YAML()
        with open("calkit.yaml") as f:
            info = ryaml.load(f) or {}
        stages = info.get("pipeline", {}).get("stages", {})
        return [
            CompletionItem(name)
            for name in stages
            if name.startswith(incomplete)
        ]
    except Exception:
        return []


def print_sep(name: str):
    width = 66
    txt_width = len(name) + 2
    buffer_width = (width - txt_width) // 2
    buffer = "-" * buffer_width
    line = f"{buffer} {name} {buffer}"
    if len(line) == (width - 1):
        line += "-"
    typer.echo(line)


def run_cmd(cmd: list[str]):
    if os.name == "nt":
        subprocess.call(cmd)
    else:
        import pty

        pty.spawn(cmd, lambda fd: os.read(fd, 1024))


def raise_error(txt: str):
    typer.echo(typer.style("Error: " + str(txt), fg="red"), err=True)
    raise typer.Exit(1)


def warn(txt: str, prefix: str = "Warning: "):
    typer.echo(typer.style(prefix + str(txt), fg="yellow"))
