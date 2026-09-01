"""Core CLI functionality."""

from __future__ import annotations

import os
import re
import subprocess
from enum import Enum
from typing import TYPE_CHECKING, Any, NoReturn

import typer
from typer.core import TyperCommand, TyperGroup


class EnvDefaultsModeChoice(str, Enum):
    """How a stage's own list combines with an environment's defaults.

    The same three values as ``calkit.models.pipeline.EnvDefaultsMode``,
    which stays a ``Literal`` because that is what puts them inline in the
    published JSON schema. Typer needs an ``Enum`` to list them in
    ``--help`` and reject anything else itself, and it has to be importable
    without pulling in the models, which are loaded lazily to keep CLI
    startup fast. A test holds the two spellings together.
    """

    ignore = "ignore"
    replace = "replace"
    merge = "merge"


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


class OptionalValueCommand(TyperCommand):
    """TyperCommand allowing certain options to be passed without a value.

    Click no longer supports options with optional values (a bare
    ``--opt`` either errors or, worse, swallows the next token), so
    subclasses declare ``optional_value_options`` mapping option names to
    the value to assume when the option appears bare, i.e., followed by
    another option or by nothing. Everything after a ``--`` separator is
    left untouched.
    """

    optional_value_options: dict[str, str] = {}

    def parse_args(self, ctx: "click.Context", args: list[str]) -> list[str]:
        new_args = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--":
                new_args += args[i:]
                break
            if arg in self.optional_value_options:
                nxt = args[i + 1] if i + 1 < len(args) else None
                if nxt is None or nxt.startswith("-"):
                    value = self.optional_value_options[arg]
                    new_args.append(f"{arg}={value}")
                    i += 1
                    continue
            new_args.append(arg)
            i += 1
        return super().parse_args(ctx, new_args)


def complete_stage_names(
    ctx: "click.Context | None",
    param: "click.Parameter | None",
    incomplete: str,
) -> list:
    """Return pipeline stage names for shell tab-completion.

    ``ctx`` and ``param`` are part of the Click completion-callback signature
    but are unused here, so they accept ``None`` (e.g. when called directly in
    tests).
    """
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


def echo_json(obj: Any) -> None:
    """Print an object as a single line of JSON.

    Values that aren't JSON-native are stringified, since YAML parsing can
    produce things like dates from ``calkit.yaml``.
    """
    import json

    typer.echo(json.dumps(obj, default=str))


def raise_error(txt: str) -> NoReturn:
    typer.echo(typer.style("Error: " + str(txt), fg="red"), err=True)
    raise typer.Exit(1)


def warn(txt: str, prefix: str = "Warning: ", err: bool = False):
    # Callers emitting machine-readable output on stdout should set err=True
    # so warnings don't corrupt it
    typer.echo(typer.style(prefix + str(txt), fg="yellow"), err=err)
