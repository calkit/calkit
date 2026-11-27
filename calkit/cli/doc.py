"""Commands for working with documents, whatever tool they're written in.

Each verb finds the tool from the document's path and runs that tool's own
command, e.g., ``calkit doc build paper.tex`` runs ``calkit latex build``,
so the tool-specific commands stay the implementation and the reference for
their options.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import typer
from typer.core import TyperCommand
from typing_extensions import Annotated

from calkit.cli import raise_error

doc_app = typer.Typer(no_args_is_help=True)

# The tool a document is written in, from its extension, or for a folder,
# from the project file in it
_SUFFIX_TOOLS = {
    ".tex": "LaTeX",
    ".qmd": "Quarto",
    ".ipynb": "Quarto",
    ".md": "Markdown",
    ".docx": "Word",
    ".pptx": "PowerPoint",
}
_FOLDER_TOOLS = {
    "_quarto.yml": "Quarto project",
    "_quarto.yaml": "Quarto project",
    "myst.yml": "MyST",
}
# Options a tool's command takes that its stage sets, so given one, the
# document is built as told rather than as its stage
_STAGE_OPTIONS = {
    "LaTeX": [
        "-e",
        "--env",
        "-r",
        "--latexmk-rc",
        "--output-dir",
        "--aux-dir",
    ],
    "Quarto": ["-e", "--environment", "--to"],
}


class _ToolArgsCommand(TyperCommand):
    """Command taking a document's path, then its tool's command's arguments.

    Everything after the path is left for the tool's command to parse,
    including ``--help`` and a ``--`` separator, so its options work as
    they do there.
    """

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        if not args or args[0] in ctx.help_option_names:
            return super().parse_args(ctx, args)
        if args[0].startswith("-"):
            ctx.fail(f"Put document path before {args[0]}")
        # Everything after a '--' is positional, even another '--'
        return super().parse_args(ctx, [args[0], "--", *args[1:]])


def _get_tool(path: str) -> str | None:
    """Get the name of the tool a document is written in, if known."""
    if os.path.isdir(path):
        for fname, tool in _FOLDER_TOOLS.items():
            if os.path.isfile(os.path.join(path, fname)):
                return tool
        return None
    return _SUFFIX_TOOLS.get(Path(path).suffix.lower())


def _get_options(args: list[str]) -> list[str]:
    """Get the options in a tool's arguments, i.e., those before any '--'."""
    return args[: args.index("--")] if "--" in args else args


def _wants_help(args: list[str]) -> bool:
    return any(a in ("-h", "--help") for a in _get_options(args))


def _check_exists(path: str) -> None:
    if not os.path.exists(path):
        raise_error(f"{path} doesn't exist")


def _run(
    ctx: typer.Context,
    verb: str,
    path: str,
    args: list[str],
    tool: str | None = None,
) -> None:
    """Run the command that does ``verb`` for the document at ``path``.

    It runs as this command, with ``args``, so its usage and errors read
    as ``calkit doc <verb>``. The tool is the one ``path`` is written in,
    unless given.
    """
    import typer.main

    from calkit.cli.export import export_app
    from calkit.cli.latex import latex_app
    from calkit.cli.office import office_app
    from calkit.cli.quarto import quarto_app

    # Each tool's command for each verb; another tool, e.g., MyST, plugs in
    # with its own rows
    commands: dict[tuple[str, str], tuple[typer.Typer, str]] = {
        ("build", "LaTeX"): (latex_app, "build"),
        ("build", "Quarto"): (quarto_app, "render"),
        ("build", "Word"): (office_app, "word-to-pdf"),
        ("build", "PowerPoint"): (export_app, "pptx"),
        ("diff", "LaTeX"): (latex_app, "diff"),
        ("to-docx", "LaTeX"): (latex_app, "to-docx"),
        ("merge-docx", "LaTeX"): (latex_app, "merge-docx"),
    }
    tool = tool or _get_tool(path)
    if tool is None:
        supported = [
            s for s, t in _SUFFIX_TOOLS.items() if (verb, t) in commands
        ] + [
            f"folder with {f}"
            for f, t in _FOLDER_TOOLS.items()
            if (verb, t) in commands
        ]
        raise_error(
            f"Unknown document type: {path}; supported: "
            + ", ".join(supported)
        )
    if (verb, tool) not in commands:
        raise_error(f"{verb} not supported for {tool} yet")
    app, name = commands[(verb, tool)]
    info = next(c for c in app.registered_commands if c.name == name)
    command = typer.main.get_command_from_info(
        info,
        pretty_exceptions_short=app.pretty_exceptions_short,
        rich_markup_mode=app.rich_markup_mode,
    )
    # Its help says it's also this one, which here goes without saying
    command.help = "\n\n".join(
        p
        for p in (command.help or "").split("\n\n")
        if "`calkit doc " not in p
    )
    with command.make_context(
        ctx.info_name, args, parent=ctx.parent
    ) as sub_ctx:
        command.invoke(sub_ctx)


PathArg = Annotated[str, typer.Argument(help="Document path.")]
ToolArgs = Annotated[
    list[str] | None,
    typer.Argument(
        help="Options and arguments for the tool's command, e.g., "
        "`calkit latex build`, which `calkit doc <command> PATH --help` "
        "lists.",
        show_default=False,
    ),
]


@doc_app.command(name="build", cls=_ToolArgsCommand)
def build(
    ctx: typer.Context, path: PathArg, tool_args: ToolArgs = None
) -> None:
    """Build a document with its tool.

    A .tex file is built with `calkit latex build`, a Quarto document or
    notebook with `calkit quarto render`, a Word document with
    `calkit office word-to-pdf`, and a PowerPoint deck to a PDF beside it
    with `calkit export pptx`.

    A document a pipeline stage builds is built as that stage does, i.e.,
    in its environment and with its options, unless options for those are
    given, and a Quarto project folder builds each document a stage renders
    in it.

    Options after the path are the tool's command's, e.g., `-e` in
    `calkit doc build paper.tex -e tex`, and
    `calkit doc build paper.tex --help` lists them.
    """
    import calkit.pipeline
    from calkit.models.pipeline import QuartoStage

    def sets_stage_option(arg: str) -> bool:
        return any(
            arg == o
            or arg.startswith(o + "=")
            or (len(o) == 2 and arg.startswith(o))
            for o in _STAGE_OPTIONS.get(tool or "", [])
        )

    args = list(tool_args or [])
    tool = _get_tool(path)
    if _wants_help(args):
        tool = "Quarto" if tool == "Quarto project" else tool
        _run(ctx, "build", path, [path] + args, tool=tool)
        return
    _check_exists(path)
    # A Quarto project is the documents its stages render
    if tool == "Quarto project":
        project_dir, _, found = calkit.pipeline.find_document_stages(
            path, kinds=["quarto"], inside=True
        )
        if project_dir is None or not found:
            raise_error(f"No quarto stage renders a document in {path}")
        for _, s in found:
            if not isinstance(s, QuartoStage):
                continue
            doc_path = Path(
                os.path.relpath(
                    os.path.join(project_dir, s.wdir or "", s.target_path)
                )
            ).as_posix()
            _run(ctx, "build", doc_path, [doc_path, "--as-stage"] + args)
        return
    # Otherwise as its stage, if one builds it and nothing says otherwise
    options = _get_options(args)
    if (
        tool in _STAGE_OPTIONS
        and "--as-stage" not in options
        and not any(sets_stage_option(a) for a in options)
    ):
        _, _, found = calkit.pipeline.find_document_stages(path)
        kinds = [s.kind for _, s in found]
        if "latex" in kinds or "quarto" in kinds:
            args = ["--as-stage"] + args
        elif "jupyter-notebook" in kinds:
            name = found[0][0]
            raise_error(
                f"Stage '{name}' executes {path} rather than rendering it; "
                f"run it with 'calkit run {name}'"
            )
    # A whole deck is the document; exporting slides as figures is up to
    # 'calkit export pptx' itself
    if tool == "PowerPoint" and not any(
        a.startswith(("-o", "--output")) for a in options
    ):
        args += ["-o", Path(path).with_suffix(".pdf").as_posix()]
    _run(ctx, "build", path, [path] + args)


@doc_app.command(name="diff", cls=_ToolArgsCommand)
def diff(
    ctx: typer.Context, path: PathArg, tool_args: ToolArgs = None
) -> None:
    """Build a PDF showing what changed in a document.

    A .tex file is compared with `calkit latex diff`, and options after the
    path are its own.
    """
    args = list(tool_args or [])
    if not _wants_help(args):
        _check_exists(path)
    _run(ctx, "diff", path, [path] + args)


@doc_app.command(name="to-docx", cls=_ToolArgsCommand)
def to_docx(
    ctx: typer.Context, path: PathArg, tool_args: ToolArgs = None
) -> None:
    """Export a Word copy of a document for review.

    A .tex file is exported from the PDF it builds, which its pipeline
    stage, if any, makes sure is current, with `calkit latex to-docx`, and
    options after the path are its own. A PDF built from LaTeX can be given
    instead.
    """
    import calkit.pipeline
    from calkit.models.pipeline import LatexStage

    args = list(tool_args or [])
    # The PDF needn't exist yet, since its stage makes it
    if Path(path).suffix.lower() == ".pdf":
        _run(ctx, "to-docx", path, [path] + args, tool="LaTeX")
        return
    if _wants_help(args):
        _run(ctx, "to-docx", path, [path] + args)
        return
    _check_exists(path)
    if _get_tool(path) == "LaTeX":
        project_dir, _, found = calkit.pipeline.find_document_stages(
            path, kinds=["latex"]
        )
        pdf_path = Path(path).with_suffix(".pdf").as_posix()
        stages = [s for _, s in found if isinstance(s, LatexStage)]
        if project_dir is not None and stages:
            pdf_path = Path(
                os.path.relpath(
                    os.path.join(
                        project_dir, stages[0].wdir or "", stages[0].pdf_path
                    )
                )
            ).as_posix()
        args = [pdf_path, "--source", path] + args
    else:
        args = [path] + args
    _run(ctx, "to-docx", path, args)


@doc_app.command(name="merge-docx", cls=_ToolArgsCommand)
def merge_docx(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Reviewed .docx to merge.")],
    tool_args: ToolArgs = None,
) -> None:
    """Merge a reviewed Word document back into its source.

    The source is the one it was exported from with `calkit doc to-docx`.
    A .tex source is merged with `calkit latex merge-docx`, and options
    after the path are its own.
    """
    import zipfile

    import calkit.docx

    args = list(tool_args or [])
    if _wants_help(args):
        _run(ctx, "merge-docx", path, [path] + args, tool="LaTeX")
        return
    if Path(path).suffix.lower() != ".docx":
        raise_error(f"Expected reviewed .docx, got {path}")
    _check_exists(path)
    # The tool is the source's, which the export recorded in the file
    source = None
    try:
        original = calkit.docx.Document(path).read_original()
        source = None if original is None else original.source
    except (KeyError, SyntaxError, zipfile.BadZipFile):
        pass
    # Without a record, LaTeX's, the only one exporting yet, says what's
    # wrong with the file
    _run(
        ctx,
        "merge-docx",
        source or path,
        [path] + args,
        tool=None if source else "LaTeX",
    )
