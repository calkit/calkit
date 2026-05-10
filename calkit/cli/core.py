"""Core CLI functionality."""

from __future__ import annotations

import os
import re
import subprocess
from typing import TYPE_CHECKING

import typer
from typer.core import TyperGroup

if TYPE_CHECKING:
    import click


class AliasGroup(TyperGroup):
    """TyperGroup that resolves command aliases defined with '|' in the name."""

    _CMD_SPLIT_P = re.compile(r" ?[,|] ?")

    def get_command(self, ctx, cmd_name):
        cmd_name = self._group_cmd_name(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _group_cmd_name(self, default_name):
        for cmd in self.commands.values():
            name = cmd.name
            if name and default_name in self._CMD_SPLIT_P.split(name):
                return name
        return default_name


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
        candidates: list[str] = []
        stages = info.get("pipeline", {}).get("stages", {})
        candidates.extend(stages.keys())
        for sp_cfg in info.get("subprojects", []):
            if not isinstance(sp_cfg, dict) or not sp_cfg.get("path"):
                continue
            sp_path = sp_cfg["path"]
            sp_calkit = os.path.join(sp_path, "calkit.yaml")
            sp_name = os.path.basename(sp_path.rstrip("/"))
            candidates.append(sp_name)
            if os.path.isfile(sp_calkit):
                with open(sp_calkit) as f:
                    sp_info = ryaml.load(f) or {}
                sp_stages = sp_info.get("pipeline", {}).get("stages", {})
                for stage in sp_stages:
                    candidates.append(f"{sp_name}:{stage}")
        return [
            CompletionItem(name)
            for name in candidates
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
