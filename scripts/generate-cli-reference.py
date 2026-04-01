#!/usr/bin/env python3
"""Generate docs/cli-reference.md from the Typer command tree."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click
import typer

from calkit.cli.main.core import app


def _command_text(cmd: click.Command) -> str:
    """Return help text for a command."""
    return (cmd.help or cmd.short_help or "").strip()


def _command_desc(cmd: click.Command) -> str:
    """Return a concise summary description (first sentence only)."""
    text = _command_text(cmd)
    if not text:
        return ""
    first_para = re.split(r"\n\s*\n", text, maxsplit=1)[0]
    first_para = " ".join(first_para.split())
    m = re.match(r"^(.+?[.!?])(?:\s|$)", first_para)
    return m.group(1) if m else first_para


def _command_desc_full(cmd: click.Command) -> str:
    """Return full command description, preserving paragraph breaks."""
    text = _command_text(cmd)
    if not text:
        return ""
    paragraphs = [
        " ".join(para.split())
        for para in re.split(r"\n\s*\n", text)
        if para.strip()
    ]
    return "\n\n".join(paragraphs)


def _list_commands(group: click.Group) -> list[tuple[str, click.Command]]:
    """Get commands in display order for a Click/Typer group."""
    names = list(group.commands.keys())
    return [(name, group.commands[name]) for name in names]


def _list_unique_commands(
    group: click.Group,
) -> list[tuple[list[str], click.Command]]:
    """Get canonical commands, excluding aliases."""
    alias_re = re.compile(r"\balias for ['\"]([^'\"]+)['\"]", re.IGNORECASE)
    commands: list[tuple[list[str], click.Command]] = []
    for name, cmd in _list_commands(group):
        desc = _command_text(cmd)
        if alias_re.search(desc):
            continue
        commands.append(([name], cmd))
    return commands


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

    if isinstance(cmd_obj, click.Group) and cmd_obj.commands:
        parts.extend(["COMMAND", "[ARGS]..."])

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


def _append_command_details(
    lines: list[str],
    command_path: str,
    cmd_obj: click.Command,
    heading: str = "###",
    anchor: str | None = None,
) -> None:
    """Append command detail markdown (usage, args, options)."""
    if anchor:
        lines.append(f'<a id="{anchor}"></a>')
        lines.append("")
    lines.append(f"{heading} `{command_path}`")
    lines.append("")
    cmd_desc = _command_desc_full(cmd_obj)
    if cmd_desc:
        lines.append(cmd_desc)
        lines.append("")
    lines.append("Usage:")
    lines.append("")
    lines.append("```text")
    lines.append(_usage(command_path, cmd_obj))
    lines.append("```")
    lines.append("")
    if _has_args(cmd_obj):
        lines.append("Arguments:")
        lines.append("")
        lines.append(_args_table(cmd_obj).rstrip())
        lines.append("")
    if _has_visible_options(cmd_obj):
        lines.append("Options:")
        lines.append("")
        lines.append(_opts_table(cmd_obj).rstrip())
        lines.append("")


def _command_label(names: list[str]) -> str:
    """Render a canonical command name for display in docs."""
    return f"`{names[0]}`"


def _command_path_label(prefix: str, names: list[str]) -> str:
    """Render a canonical full command path for a section header."""
    return f"{prefix} {names[0]}"


def _slug(text: str) -> str:
    """Generate a stable, URL-friendly slug."""
    lowered = text.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return cleaned or "command"


def _top_command_anchor(names: list[str]) -> str:
    """Build anchor ID for a top-level command detail section."""
    return "top-command-" + _slug(names[0])


def _group_anchor(names: list[str]) -> str:
    """Build anchor ID for a top-level command-group section."""
    return "command-group-" + _slug(names[0])


def _subcommand_anchor(group_names: list[str], sub_names: list[str]) -> str:
    """Build anchor ID for a subcommand detail section within a group."""
    group_part = _slug(group_names[0])
    sub_part = _slug(sub_names[0])
    return f"subcommand-{group_part}-{sub_part}"


def _command_link_label(names: list[str], anchor: str) -> str:
    """Render one or more command names as a link label."""
    return f"[{_command_label(names)}](#{anchor})"


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
        (names, cmd_obj, _command_desc(cmd_obj))
        for names, cmd_obj in _list_unique_commands(root_cmd)
    ]
    lines: list[str] = []
    lines.append("# CLI reference")
    lines.append("")
    if top_summary:
        lines.append(top_summary)
        lines.append("")
    lines.append("## Top-level commands")
    lines.append("")

    def _top_table_anchor(names: list[str], cmd_obj: click.Command) -> str:
        is_group_with_subcommands = isinstance(cmd_obj, click.Group) and bool(
            cmd_obj.commands
        )
        return (
            _group_anchor(names)
            if is_group_with_subcommands
            else _top_command_anchor(names)
        )

    lines.append(
        make_table(
            [
                (
                    _command_link_label(
                        names, _top_table_anchor(names, cmd_obj)
                    ),
                    desc,
                )
                for names, cmd_obj, desc in top_commands
            ],
            ["Command", "Description"],
        ).rstrip()
    )
    lines.append("")
    lines.append("## Top-level command details")
    lines.append("")
    for cmd_names, cmd_obj, _ in top_commands:
        if isinstance(cmd_obj, click.Group) and cmd_obj.commands:
            continue
        _append_command_details(
            lines,
            _command_path_label("calkit", cmd_names),
            cmd_obj,
            heading="###",
            anchor=_top_command_anchor(cmd_names),
        )
    lines.append("## Command groups")
    lines.append("")
    found_group = False
    for cmd_names, cmd_obj, cmd_desc in top_commands:
        if not isinstance(cmd_obj, click.Group):
            continue
        subcommands = _list_unique_commands(cmd_obj)
        if not subcommands:
            continue
        found_group = True
        lines.append(f'<a id="{_group_anchor(cmd_names)}"></a>')
        lines.append("")
        lines.append(f"### `{_command_path_label('calkit', cmd_names)}`")
        lines.append("")
        if cmd_desc:
            lines.append(cmd_desc)
            lines.append("")
        lines.append(
            make_table(
                [
                    (
                        _command_link_label(
                            names, _subcommand_anchor(cmd_names, names)
                        ),
                        _command_desc(sub_cmd),
                    )
                    for names, sub_cmd in subcommands
                ],
                ["Command", "Description"],
            ).rstrip()
        )
        lines.append("")
        for sub_names, sub_obj in subcommands:
            _append_command_details(
                lines,
                _command_path_label(
                    _command_path_label("calkit", cmd_names), sub_names
                ),
                sub_obj,
                heading="####",
                anchor=_subcommand_anchor(cmd_names, sub_names),
            )
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
