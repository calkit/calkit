#!/usr/bin/env python3
"""Generate docs/cli-reference.md from the Typer command tree."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import typer

from calkit.cli.main.core import app


def _command_desc(cmd: click.Command) -> str:
    """Return a concise, single-line command description."""
    desc = (cmd.short_help or cmd.help or "").strip()
    desc = " ".join(desc.split())
    return desc


def _list_commands(group: click.Group) -> list[tuple[str, click.Command]]:
    """Get commands in display order for a Click/Typer group."""
    names = list(group.commands.keys())
    return [(name, group.commands[name]) for name in names]


def _type_name(param_type: click.ParamType) -> str:
    """Get a readable type name for a Click parameter."""
    if isinstance(param_type, click.types.Choice):
        return "choice(" + ", ".join(str(c) for c in param_type.choices) + ")"
    return getattr(param_type, "name", str(param_type))


def _default_value(param: click.Parameter) -> str:
    """Get a readable default value for a Click parameter."""
    default = getattr(param, "default", None)
    if default is None:
        return ""
    if callable(default):
        return "<dynamic>"
    if isinstance(default, (list, tuple)):
        return ", ".join(str(v) for v in default)
    return str(default)


def _param_help(param: click.Parameter) -> str:
    """Get help text for either option or argument parameters."""
    help_text = getattr(param, "help", "") or ""
    return " ".join(help_text.split())


def _usage(command_path: str, cmd_obj: click.Command) -> str:
    """Build usage text for a command."""
    parts = [command_path]

    has_visible_options = any(
        isinstance(param, click.Option) and not getattr(param, "hidden", False)
        for param in cmd_obj.params
    )
    if has_visible_options:
        parts.append("[OPTIONS]")

    for param in cmd_obj.params:
        if not isinstance(param, click.Argument):
            continue
        arg_name = (param.name or "arg").upper().replace("_", "-")
        if param.nargs != 1:
            arg_name += "..."
        if not param.required:
            arg_name = f"[{arg_name}]"
        parts.append(arg_name)

    return " ".join(parts)


def _args_table(cmd_obj: click.Command) -> str:
    """Build an arguments table for a command."""
    rows: list[list[str]] = []
    for param in cmd_obj.params:
        if not isinstance(param, click.Argument):
            continue
        name = f"`{param.name}`"
        ptype = _type_name(param.type)
        required = "yes" if param.required else "no"
        default = _default_value(param)
        help_txt = _param_help(param)
        rows.append([name, ptype, required, default, help_txt])
    return (
        make_table(
            [tuple(r) for r in rows],
            ["Argument", "Type", "Required", "Default", "Description"],
        )
        if rows
        else "(none)\n"
    )


def _has_args(cmd_obj: click.Command) -> bool:
    """Return whether the command has any positional arguments."""
    return any(isinstance(param, click.Argument) for param in cmd_obj.params)


def _opts_table(cmd_obj: click.Command) -> str:
    """Build an options table for a command."""
    rows: list[list[str]] = []
    for param in cmd_obj.params:
        if not isinstance(param, click.Option):
            continue
        if getattr(param, "hidden", False):
            continue
        option_names = [*param.opts, *param.secondary_opts]
        options = ", ".join(f"`{opt}`" for opt in option_names)
        ptype = _type_name(param.type)
        required = "yes" if param.required else "no"
        default = _default_value(param)
        help_txt = _param_help(param)
        rows.append([options, ptype, required, default, help_txt])
    return (
        make_table(
            [tuple(r) for r in rows],
            ["Option", "Type", "Required", "Default", "Description"],
        )
        if rows
        else "(none)\n"
    )


def _has_visible_options(cmd_obj: click.Command) -> bool:
    """Return whether the command has any non-help visible options."""
    for param in cmd_obj.params:
        if not isinstance(param, click.Option):
            continue
        if getattr(param, "hidden", False):
            continue
        option_names = [*param.opts, *param.secondary_opts]
        if set(option_names) <= {"--help", "-h"}:
            continue
        return True
    return False


def make_table(rows: list[tuple[Any, ...]], header: list[str]) -> str:
    if not rows:
        return "(none)\n"

    def _escape_cell(value: str) -> str:
        return value.replace("|", r"\|")

    body = [[str(c) for c in row] for row in rows]
    table = [header, *body]
    col_widths = [
        max(len(_escape_cell(row[col])) for row in table)
        for col in range(len(header))
    ]

    def _format_row(values: list[str]) -> str:
        cells = [
            f" {_escape_cell(values[i]).ljust(col_widths[i])} "
            for i in range(len(values))
        ]
        return "|" + "|".join(cells) + "|"

    sep = "|" + "|".join(f" {'-' * w} " for w in col_widths) + "|"
    out = [_format_row(header), sep]
    for row in body:
        out.append(_format_row(row))
    return "\n".join(out) + "\n"


def generate_markdown() -> str:
    root_cmd = typer.main.get_command(app)
    if not isinstance(root_cmd, click.Group):
        raise TypeError("Expected root CLI command to be a Click Group")
    top_summary = _command_desc(root_cmd)
    top_commands = [
        (name, _command_desc(cmd)) for name, cmd in _list_commands(root_cmd)
    ]
    lines: list[str] = []
    lines.append("# CLI reference")
    lines.append("")
    if top_summary:
        lines.append(top_summary)
        lines.append("")
    lines.append("## Top-level commands")
    lines.append("")
    lines.append(
        make_table(
            [(f"`{name}`", desc) for name, desc in top_commands],
            ["Command", "Description"],
        ).rstrip()
    )
    lines.append("")
    lines.append("## Command groups")
    lines.append("")
    found_group = False
    for cmd_name, cmd_desc in top_commands:
        cmd_obj = root_cmd.commands[cmd_name]
        if not isinstance(cmd_obj, click.Group):
            continue
        subcommands = _list_commands(cmd_obj)
        if not subcommands:
            continue
        found_group = True
        lines.append(f"### `calkit {cmd_name}`")
        lines.append("")
        if cmd_desc:
            lines.append(cmd_desc)
            lines.append("")
        lines.append(
            make_table(
                [
                    (f"`{name}`", _command_desc(sub_cmd))
                    for name, sub_cmd in subcommands
                ],
                ["Command", "Description"],
            ).rstrip()
        )
        lines.append("")
        for sub_name, sub_obj in subcommands:
            command_path = f"calkit {cmd_name} {sub_name}"
            lines.append(f"#### `{command_path}`")
            lines.append("")
            sub_desc = _command_desc(sub_obj)
            if sub_desc:
                lines.append(sub_desc)
                lines.append("")
            lines.append("Usage:")
            lines.append("")
            lines.append("```text")
            lines.append(_usage(command_path, sub_obj))
            lines.append("```")
            lines.append("")
            if _has_args(sub_obj):
                lines.append("Arguments:")
                lines.append("")
                lines.append(_args_table(sub_obj).rstrip())
                lines.append("")
            if _has_visible_options(sub_obj):
                lines.append("Options:")
                lines.append("")
                lines.append(_opts_table(sub_obj).rstrip())
                lines.append("")
    if not found_group:
        lines.append("No command groups were detected.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_path = repo_root / "docs" / "cli-reference.md"
    out_path.write_text(generate_markdown(), encoding="utf-8")


if __name__ == "__main__":
    main()
