#!/usr/bin/env python3
"""Generate auto-reference docs for CLI, environments, and pipeline stages."""

from __future__ import annotations

import re
import types
from pathlib import Path
from typing import Any, get_args, get_origin

import click
import typer
from pydantic.fields import PydanticUndefined

from calkit.cli.main.core import app
from calkit.models.core import (
    CondaEnvironment,
    DockerEnvironment,
    Environment,
    JuliaEnvironment,
    MatlabEnvironment,
    PixiEnvironment,
    REnvironment,
    SlurmEnvironment,
    SSHEnvironment,
    UvEnvironment,
    UvVenvEnvironment,
    VenvEnvironment,
)
from calkit.models.pipeline import Stage

ENV_START = "<!-- AUTO-GENERATED: ENV-KINDS:START -->"
ENV_END = "<!-- AUTO-GENERATED: ENV-KINDS:END -->"
STAGE_START = "<!-- AUTO-GENERATED: PIPELINE-STAGE-KINDS:START -->"
STAGE_END = "<!-- AUTO-GENERATED: PIPELINE-STAGE-KINDS:END -->"
LEGACY_START = "<!-- AUTO-GENERATED: ENV-AND-STAGE-KINDS:START -->"
LEGACY_END = "<!-- AUTO-GENERATED: ENV-AND-STAGE-KINDS:END -->"


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


def _command_text(cmd: click.Command) -> str:
    return (cmd.help or cmd.short_help or "").strip()


def _command_desc(cmd: click.Command) -> str:
    text = _command_text(cmd)
    if not text:
        return ""
    first_para = re.split(r"\n\s*\n", text, maxsplit=1)[0]
    first_para = " ".join(first_para.split())
    m = re.match(r"^(.+?[.!?])(?:\s|$)", first_para)
    return m.group(1) if m else first_para


def _command_desc_full(cmd: click.Command) -> str:
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
    names = list(group.commands.keys())
    return [(name, group.commands[name]) for name in names]


def _list_unique_commands(
    group: click.Group,
) -> list[tuple[list[str], click.Command]]:
    alias_re = re.compile(r"\balias for ['\"]([^'\"]+)['\"]", re.IGNORECASE)
    commands: list[tuple[list[str], click.Command]] = []
    for name, cmd in _list_commands(group):
        desc = _command_text(cmd)
        if alias_re.search(desc):
            continue
        commands.append(([name], cmd))
    return commands


def _type_name(param_type: click.ParamType) -> str:
    if isinstance(param_type, click.types.Choice):
        return "choice(" + ", ".join(str(c) for c in param_type.choices) + ")"
    return getattr(param_type, "name", str(param_type))


def _default_value(param: click.Parameter) -> str:
    default = getattr(param, "default", None)
    if default is None:
        return ""
    if callable(default):
        return "<dynamic>"
    if isinstance(default, (list, tuple)):
        return ", ".join(str(v) for v in default)
    return str(default)


def _param_help(param: click.Parameter) -> str:
    help_text = getattr(param, "help", "") or ""
    return " ".join(help_text.split())


def _usage(command_path: str, cmd_obj: click.Command) -> str:
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
    return any(isinstance(param, click.Argument) for param in cmd_obj.params)


def _opts_table(cmd_obj: click.Command) -> str:
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
    return f"`{names[0]}`"


def _command_path_label(prefix: str, names: list[str]) -> str:
    return f"{prefix} {names[0]}"


def _slug(text: str) -> str:
    lowered = text.lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return cleaned or "command"


def _top_command_anchor(names: list[str]) -> str:
    return "top-command-" + _slug(names[0])


def _group_anchor(names: list[str]) -> str:
    return "command-group-" + _slug(names[0])


def _subcommand_anchor(group_names: list[str], sub_names: list[str]) -> str:
    return f"subcommand-{_slug(group_names[0])}-{_slug(sub_names[0])}"


def _command_link_label(names: list[str], anchor: str) -> str:
    return f"[{_command_label(names)}](#{anchor})"


def generate_cli_markdown() -> str:
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


def _annotation_to_text(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is None:
        if annotation is type(None):
            return "None"
        if hasattr(annotation, "__name__"):
            return annotation.__name__
        return str(annotation).replace("typing.", "")
    if str(origin).endswith("Annotated"):
        args = get_args(annotation)
        return _annotation_to_text(args[0]) if args else "Any"
    args = get_args(annotation)
    if origin is list:
        return f"list[{_annotation_to_text(args[0]) if args else 'Any'}]"
    if origin is dict:
        k = _annotation_to_text(args[0]) if len(args) > 0 else "Any"
        v = _annotation_to_text(args[1]) if len(args) > 1 else "Any"
        return f"dict[{k}, {v}]"
    if str(origin).endswith("Literal"):
        return "Literal[" + ", ".join(repr(a) for a in args) + "]"
    if str(origin).endswith("Union"):
        return " | ".join(_annotation_to_text(a) for a in args)
    if origin is types.UnionType:
        return " | ".join(_annotation_to_text(a) for a in args)
    txt = str(annotation).replace("typing.", "")
    txt = re.sub(r" at 0x[0-9a-fA-F]+", "", txt)
    return txt


def _default_to_text(default: Any) -> str:
    if default is PydanticUndefined:
        return ""
    if default is None:
        return "null"
    if default == "":
        return '""'
    if isinstance(default, str):
        return repr(default).replace("_", r"\_")
    if isinstance(default, (list, dict, tuple)):
        return ""
    return repr(default)


def _is_required(field: Any) -> bool:
    is_required = getattr(field, "is_required", None)
    if callable(is_required):
        return bool(is_required())
    return field.default is PydanticUndefined


def _docstring_text(obj: Any) -> str:
    doc = getattr(obj, "__doc__", None)
    if not doc:
        return ""
    lines = [line.strip() for line in doc.strip().splitlines()]
    cleaned: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if prev_blank:
                continue
            cleaned.append("")
            prev_blank = True
            continue
        cleaned.append(line)
        prev_blank = False
    text = "\n".join(cleaned).strip()
    # Convert common RST-style inline code markup to markdown.
    return text.replace("``", "`")


def _kind_for_model_class(cls: type[Any]) -> str:
    fields = getattr(cls, "model_fields", {})
    kind_field = fields.get("kind")
    if kind_field is None:
        return ""
    if kind_field.default is not PydanticUndefined:
        return str(kind_field.default)
    ann = kind_field.annotation
    origin = get_origin(ann)
    if str(origin).endswith("Literal"):
        args = get_args(ann)
        if len(args) == 1:
            return str(args[0])
    return ""


def _class_doc_lines(cls: type[Any] | None) -> list[str]:
    if cls is None:
        return ["Model class: _(not available)_", ""]
    lines = [f"Model class: `{cls.__name__}`", ""]
    docstring = _docstring_text(cls)
    if docstring:
        lines.append(docstring)
        lines.append("")
    return lines


def generate_environment_kinds_markdown() -> str:
    env_classes = [
        Environment,
        CondaEnvironment,
        UvEnvironment,
        VenvEnvironment,
        UvVenvEnvironment,
        PixiEnvironment,
        DockerEnvironment,
        JuliaEnvironment,
        MatlabEnvironment,
        SlurmEnvironment,
        REnvironment,
        SSHEnvironment,
    ]
    env_classes_by_kind = {
        _kind_for_model_class(cls): cls
        for cls in env_classes
        if _kind_for_model_class(cls)
    }

    env_kinds: dict[str, list[tuple[str, str, str]]] = {
        "conda": [
            ("kind", "Literal['conda']", "required"),
            ("path", "str", "required"),
            ("prefix", "str", "optional"),
            ("description", "str", "optional"),
        ],
        "uv": [
            ("kind", "Literal['uv']", "required"),
            ("path", "str", "required"),
            ("description", "str", "optional"),
        ],
        "venv": [
            ("kind", "Literal['venv']", "required"),
            ("path", "str", "required"),
            ("prefix", "str", "required"),
            ("python", "str", "optional"),
            ("description", "str", "optional"),
        ],
        "uv-venv": [
            ("kind", "Literal['uv-venv']", "required"),
            ("path", "str", "required"),
            ("prefix", "str", "required"),
            ("python", "str", "optional"),
            ("description", "str", "optional"),
        ],
        "pixi": [
            ("kind", "Literal['pixi']", "required"),
            ("path", "str", "required"),
            ("name", "str", "optional"),
            ("description", "str", "optional"),
        ],
        "docker": [
            ("kind", "Literal['docker']", "required"),
            ("image", "str", "required"),
            ("path", "str", "optional"),
            ("platform", "str", "optional"),
            ("command_mode", "Literal['shell'|'entrypoint']", "optional"),
            ("shell", "str", "optional"),
            ("deps", "list[str]", "optional"),
            ("env_vars", "dict[str, str]", "optional"),
            ("ports", "list[str]", "optional"),
            ("gpus", "str", "optional"),
            ("user", "str", "optional"),
            ("wdir", "str", "optional"),
            ("args", "list[str]", "optional"),
            ("description", "str", "optional"),
        ],
        "renv": [
            ("kind", "Literal['renv']", "required"),
            ("path", "str", "required"),
            ("description", "str", "optional"),
        ],
        "julia": [
            ("kind", "Literal['julia']", "required"),
            ("path", "str", "required"),
            ("julia", "str", "required"),
            ("description", "str", "optional"),
        ],
        "matlab": [
            ("kind", "Literal['matlab']", "required"),
            ("products", "list[str]", "optional"),
            ("description", "str", "optional"),
        ],
        "slurm": [
            ("kind", "Literal['slurm']", "required"),
            ("host", "str", "optional (default: localhost)"),
            ("default_options", "list[str]", "optional"),
            ("default_setup", "list[str]", "optional"),
            ("description", "str", "optional"),
        ],
        "ssh": [
            ("kind", "Literal['ssh']", "required"),
            ("host", "str", "required"),
            ("user", "str", "required"),
            ("wdir", "str", "required"),
            ("key", "str", "optional"),
            ("send_paths", "list[str]", "optional"),
            ("get_paths", "list[str]", "optional"),
            ("description", "str", "optional"),
        ],
    }
    lines = [
        "### Environment kind reference",
        "",
        "Environment definitions belong in the `environments` section of `calkit.yaml`.",
        "",
    ]
    for kind, rows in env_kinds.items():
        lines.append(f"#### `{kind}`")
        lines.append("")
        lines.extend(_class_doc_lines(env_classes_by_kind.get(kind)))
        normalized_rows = [
            (
                param,
                typ,
                "yes" if requirement.strip().lower() == "required" else "no",
            )
            for param, typ, requirement in rows
        ]
        lines.append(
            make_table(
                normalized_rows,
                ["Parameter", "Type", "Required"],
            ).rstrip()
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_stage_kinds_markdown() -> str:
    base_fields = Stage.model_fields

    stage_classes = [
        cls for cls in Stage.__subclasses__() if _kind_for_model_class(cls)
    ]
    stage_classes = sorted(stage_classes, key=_kind_for_model_class)

    lines = [
        "## Pipeline stage kind reference",
        "",
        "Stage definitions belong in `pipeline.stages` in `calkit.yaml`.",
        "",
        "Common stage parameters:",
        "",
    ]

    common_rows: list[tuple[str, str, str]] = []
    for name, field in base_fields.items():
        if name in {"kind", "name"}:
            continue
        common_rows.append(
            (
                f"`{name}`",
                _annotation_to_text(field.annotation),
                "yes" if _is_required(field) else "no",
                _default_to_text(field.default),
            )
        )
    lines.append(
        make_table(
            common_rows,
            ["Parameter", "Type", "Required", "Default"],
        ).rstrip()
    )
    lines.append("")

    for cls in stage_classes:
        kind = _kind_for_model_class(cls)
        lines.append(f"### `{kind}`")
        lines.append("")
        lines.extend(_class_doc_lines(cls))
        extra_rows: list[tuple[str, str, str]] = []
        for name, field in cls.model_fields.items():
            if name == "kind":
                continue
            base_field = base_fields.get(name)
            is_new = base_field is None
            changed_default = (
                base_field is not None and base_field.default != field.default
            )
            changed_type = (
                base_field is not None
                and base_field.annotation != field.annotation
            )
            if not (is_new or changed_default or changed_type):
                continue
            extra_rows.append(
                (
                    f"`{name}`",
                    _annotation_to_text(field.annotation),
                    "yes" if _is_required(field) else "no",
                    _default_to_text(field.default),
                )
            )
        if extra_rows:
            lines.append(
                make_table(
                    extra_rows,
                    [
                        "Kind-specific parameter",
                        "Type",
                        "Required",
                        "Default",
                    ],
                ).rstrip()
            )
        else:
            lines.append("No additional kind-specific parameters.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _replace_marked_block(
    content: str,
    start_marker: str,
    end_marker: str,
    block: str,
) -> str:
    replacement = f"{start_marker}\n\n{block.rstrip()}\n\n{end_marker}"
    if start_marker in content and end_marker in content:
        start = content.index(start_marker)
        end = content.index(end_marker) + len(end_marker)
        return content[:start] + replacement + content[end:]
    return content.rstrip() + "\n\n" + replacement + "\n"


def _remove_legacy_combined_block(content: str) -> str:
    if LEGACY_START in content and LEGACY_END in content:
        start = content.index(LEGACY_START)
        end = content.index(LEGACY_END) + len(LEGACY_END)
        content = content[:start].rstrip() + "\n\n" + content[end:].lstrip()
    return content


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent

    cli_doc = repo_root / "docs" / "cli-reference.md"
    cli_doc.write_text(generate_cli_markdown(), encoding="utf-8")

    env_doc = repo_root / "docs" / "environments.md"
    env_content = _remove_legacy_combined_block(
        env_doc.read_text(encoding="utf-8")
    )
    env_content = _replace_marked_block(
        env_content,
        ENV_START,
        ENV_END,
        generate_environment_kinds_markdown(),
    )
    env_doc.write_text(env_content, encoding="utf-8")

    pipeline_doc = repo_root / "docs" / "pipeline" / "index.md"
    pipeline_content = _replace_marked_block(
        pipeline_doc.read_text(encoding="utf-8"),
        STAGE_START,
        STAGE_END,
        generate_stage_kinds_markdown(),
    )
    pipeline_doc.write_text(pipeline_content, encoding="utf-8")


if __name__ == "__main__":
    main()
