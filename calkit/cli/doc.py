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
        super().parse_args(ctx, args[:1])
        rest = args[1:]
        ctx.args = rest
        return rest


def _get_tool(path: str) -> str | None:
    """Get the name of the tool a document is written in, if known."""
    if os.path.isdir(path):
        for fname, tool in _FOLDER_TOOLS.items():
            if os.path.isfile(os.path.join(path, fname)):
                return tool
        return None
    return _SUFFIX_TOOLS.get(Path(path).suffix.lower())


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
    with command.make_context(
        ctx.info_name, args, parent=ctx.parent
    ) as sub_ctx:
        command.invoke(sub_ctx)


def _get_pdf_path(tex_path: str, ck_info: dict) -> str:
    """Get the path of the PDF a .tex file builds.

    That's where the pipeline's LaTeX stage for it writes it, or else
    beside it.
    """
    from calkit.models.pipeline import LatexStage

    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    for name, stage in stages.items():
        if not isinstance(stage, dict) or stage.get("kind") != "latex":
            continue
        try:
            s = LatexStage.model_validate(stage | {"name": name})
        except ValueError:
            continue
        wdir = s.wdir or ""
        if os.path.normpath(os.path.join(wdir, s.target_path)) == (
            os.path.normpath(tex_path)
        ):
            return Path(os.path.join(wdir, s.pdf_path)).as_posix()
    return Path(tex_path).with_suffix(".pdf").as_posix()


PathArg = Annotated[str, typer.Argument(help="Document path.")]


@doc_app.command(name="build", cls=_ToolArgsCommand)
def build(ctx: typer.Context, path: PathArg) -> None:
    """Build a document with its tool.

    A .tex file is built with `calkit latex build`, a Quarto document or
    notebook with `calkit quarto render`, a Word document with
    `calkit office word-to-pdf`, and a PowerPoint deck to a PDF beside it
    with `calkit export pptx`.

    Options after the path are that command's, e.g., `-e` in
    `calkit doc build paper.tex -e tex`, and
    `calkit doc build paper.tex --help` lists them.
    """
    args = list(ctx.args)
    # A whole deck is the document; exporting slides as figures is up to
    # 'calkit export pptx' itself
    if _get_tool(path) == "PowerPoint" and not any(
        a.startswith(("-o", "--output")) for a in args
    ):
        args += ["-o", Path(path).with_suffix(".pdf").as_posix()]
    _run(ctx, "build", path, [path] + args)


@doc_app.command(name="diff", cls=_ToolArgsCommand)
def diff(ctx: typer.Context, path: PathArg) -> None:
    """Build a PDF showing what changed in a document.

    A .tex file is compared with `calkit latex diff`, and options after the
    path are its own.
    """
    _run(ctx, "diff", path, [path] + ctx.args)


@doc_app.command(name="to-docx", cls=_ToolArgsCommand)
def to_docx(ctx: typer.Context, path: PathArg) -> None:
    """Export a Word copy of a document for review.

    A .tex file is exported from its compiled PDF with
    `calkit latex to-docx`, and options after the path are its own.
    """
    import calkit

    args = [path] + ctx.args
    if _get_tool(path) == "LaTeX":
        pdf_path = _get_pdf_path(path, calkit.load_calkit_info())
        args = [pdf_path, "--source", path] + ctx.args
    _run(ctx, "to-docx", path, args)


@doc_app.command(name="merge-docx", cls=_ToolArgsCommand)
def merge_docx(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Reviewed .docx to merge.")],
) -> None:
    """Merge a reviewed Word document back into its source.

    The source is the one it was exported from with `calkit doc to-docx`.
    A .tex source is merged with `calkit latex merge-docx`, and options
    after the path are its own.
    """
    import zipfile

    import calkit.docx

    if Path(path).suffix.lower() != ".docx":
        raise_error(f"Expected reviewed .docx, got {path}")
    if not os.path.isfile(path):
        raise_error(f"{path} doesn't exist")
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
        [path] + ctx.args,
        tool=None if source else "LaTeX",
    )
