#!/usr/bin/env python3
"""Generate docs/cli-reference.md from the Typer command tree."""

from __future__ import annotations

from pathlib import Path

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


def make_table(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "(none)\n"

    def _escape_cell(value: str) -> str:
        return value.replace("|", r"\|")

    header = ["Command", "Description"]
    body = [[f"`{cmd}`", desc] for cmd, desc in rows]
    table = [header, *body]
    col_widths = [
        max(len(_escape_cell(row[col])) for row in table) for col in range(2)
    ]

    def _format_row(values: list[str]) -> str:
        return (
            f"| {_escape_cell(values[0]).ljust(col_widths[0])} "
            f"| {_escape_cell(values[1]).ljust(col_widths[1])} |"
        )

    sep = f"| {'-' * col_widths[0]} | {'-' * col_widths[1]} |"
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
    lines.append(
        "This page is auto-generated from live CLI help output. "
        "To update it, run `make sync-docs` (or "
        "`uv run python scripts/generate-cli-reference.py`)."
    )
    lines.append("")
    if top_summary:
        lines.append(top_summary)
        lines.append("")

    lines.append("## Top-level commands")
    lines.append("")
    lines.append(make_table(top_commands).rstrip())
    lines.append("")

    lines.append("## Command groups")
    lines.append("")
    found_group = False
    for cmd_name, cmd_desc in top_commands:
        cmd_obj = root_cmd.commands[cmd_name]
        if not isinstance(cmd_obj, click.Group):
            continue
        subcommands = [
            (name, _command_desc(sub_cmd))
            for name, sub_cmd in _list_commands(cmd_obj)
        ]
        if not subcommands:
            continue
        found_group = True
        lines.append(f"### `calkit {cmd_name}`")
        lines.append("")
        if cmd_desc:
            lines.append(cmd_desc)
            lines.append("")
        lines.append(make_table(subcommands).rstrip())
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
