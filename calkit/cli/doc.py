"""Commands for working with documents, whatever tool they're written in.

Each shared verb finds the tool from the document's path and runs that
tool's command, e.g., ``calkit doc build paper.tex`` runs
``calkit doc latex build``, while tool-specific commands live under
``calkit doc latex`` and ``calkit doc quarto``.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import typer
from typer.core import TyperCommand
from typing_extensions import Annotated

from calkit.cli import AliasGroup, raise_error, warn
from calkit.cli.latex import latex_app
from calkit.cli.quarto import quarto_app

doc_app = typer.Typer(cls=AliasGroup, no_args_is_help=True)
doc_app.add_typer(latex_app, name="latex|tex", help="Work with LaTeX.")
doc_app.add_typer(quarto_app, name="quarto", help="Work with Quarto.")

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


class _PathFirstCommand(TyperCommand):
    """Command whose usage puts the document path before options."""

    def collect_usage_pieces(self, ctx: Any) -> list[str]:
        pieces = super().collect_usage_pieces(ctx)
        if self.options_metavar in pieces and len(pieces) > 1:
            pieces.remove(self.options_metavar)
            pieces.insert(1, self.options_metavar)
        return pieces


class _ToolArgsCommand(_PathFirstCommand):
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


def _get_command(app: typer.Typer, name: str) -> Any:
    """Build a tool's Click command with path-first usage."""
    import typer.main

    info = copy.copy(
        next(c for c in app.registered_commands if c.name == name)
    )
    if info.cls in (None, TyperCommand):
        info.cls = _PathFirstCommand
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
    return command


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
    from calkit.cli.export import export_app
    from calkit.cli.office import office_app

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
            if (verb, "Quarto" if t == "Quarto project" else t) in commands
        ]
        raise_error(
            f"Unknown document type: {path}; supported: "
            + ", ".join(supported)
        )
    if (verb, tool) not in commands:
        raise_error(f"{verb} not supported for {tool} yet")
    app, name = commands[(verb, tool)]
    command = _get_command(app, name)
    # 'latex to-docx' takes the compiled PDF, whereas 'doc to-docx' takes
    # the .tex source (or its PDF)
    if verb == "to-docx" and _wants_help(args) and command.params:
        command.params[0].name = "path"
        command.params[0].help = "LaTeX .tex file (or compiled PDF) to export."
    with command.make_context(
        ctx.info_name, args, parent=ctx.parent
    ) as sub_ctx:
        command.invoke(sub_ctx)


PathArg = Annotated[str, typer.Argument(help="Document path.")]
ToolArgs = Annotated[
    list[str] | None,
    typer.Argument(
        help="Options and arguments for the tool's command, e.g., "
        "`calkit doc latex build`, which `calkit doc <command> PATH --help` "
        "lists.",
        show_default=False,
    ),
]


@doc_app.command(name="build", cls=_ToolArgsCommand)
def build(
    ctx: typer.Context, path: PathArg, tool_args: ToolArgs = None
) -> None:
    """Build a document with its tool.

    A .tex file is built with `calkit doc latex build`, a Quarto document or
    notebook with `calkit doc quarto render`, a Word document with
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
    from calkit.models.pipeline import LatexStage, QuartoStage

    args = list(tool_args or [])
    tool = _get_tool(path)
    if _wants_help(args):
        tool = "Quarto" if tool == "Quarto project" else tool
        _run(ctx, "build", path, [path] + args, tool=tool)
        return
    _check_exists(path)
    # A Quarto project is the documents its stages render
    if tool == "Quarto project":
        from calkit.cli.quarto import render_stage

        project_dir, _, found = calkit.pipeline.find_document_stages(
            path, kinds=["quarto"], inside=True
        )
        stages = [s for _, s in found if isinstance(s, QuartoStage)]
        if project_dir is None or not stages:
            raise_error(f"No quarto stage renders a document in {path}")
        # Parse options once, then render each stage directly so multiple
        # stages targeting the same file (e.g., different formats) all run
        command = _get_command(quarto_app, "render")
        with command.make_context(
            ctx.info_name, [path] + args, parent=ctx.parent
        ) as sub_ctx:
            if (
                sub_ctx.params["environment"] is not None
                or sub_ctx.params["to"] is not None
            ):
                raise_error(
                    "Environment and format come from each stage in a Quarto "
                    "project"
                )
            extra_args = list(sub_ctx.params["quarto_args"] or [])
            allow_machine = bool(sub_ctx.params["allow_machine_quarto"])
            no_check = bool(sub_ctx.params["no_check"])
        for s in stages:
            render_stage(
                stage_dir=project_dir,
                stage=s,
                quarto_args=extra_args,
                allow_machine_quarto=allow_machine,
                no_check=no_check,
            )
        return
    # A LaTeX document with a pipeline stage builds as that stage unless
    # stage-controlled options are overridden
    if tool == "LaTeX":
        from calkit.cli.latex import build_stage

        project_dir, _, found = calkit.pipeline.find_document_stages(
            path, kinds=["latex"]
        )
        matches = [s for _, s in found if isinstance(s, LatexStage)]
        if project_dir is not None and matches:
            command = _get_command(latex_app, "build")
            with command.make_context(
                ctx.info_name, [path] + args, parent=ctx.parent
            ) as sub_ctx:
                p = sub_ctx.params
                if not p["as_stage"] and all(
                    p[k] is None
                    for k in (
                        "environment",
                        "latexmk_rc_path",
                        "output_dir",
                        "aux_dir",
                    )
                ):
                    if len(matches) > 1:
                        others = ", ".join(f"'{m.name}'" for m in matches[1:])
                        warn(
                            f"Stages '{matches[0].name}' and {others} all "
                            f"build {path}; building it as '{matches[0].name}'"
                        )
                    build_stage(
                        project_dir=project_dir,
                        stage=matches[0],
                        no_check=bool(p["no_check"]),
                        verbose=bool(p["verbose"]),
                        force=bool(p["force"]),
                        no_synctex=bool(p["no_synctex"]),
                        latexmk_args=list(p["latexmk_args"] or []),
                    )
                    return
                command.invoke(sub_ctx)
            return
    # A notebook executed by a jupyter-notebook stage rather than rendered
    # by Quarto points the user to 'calkit run'
    if tool == "Quarto" and path.lower().endswith(".ipynb"):
        _, _, found = calkit.pipeline.find_document_stages(
            path, kinds=["quarto", "jupyter-notebook"]
        )
        kinds = [s.kind for _, s in found]
        if "jupyter-notebook" in kinds and "quarto" not in kinds:
            command = _get_command(quarto_app, "render")
            with command.make_context(
                ctx.info_name, [path] + args, parent=ctx.parent
            ) as sub_ctx:
                if (
                    sub_ctx.params["environment"] is None
                    and sub_ctx.params["to"] is None
                ):
                    name = found[0][0]
                    raise_error(
                        f"Stage '{name}' executes {path} rather than "
                        f"rendering it; run it with 'calkit run {name}'"
                    )
                command.invoke(sub_ctx)
            return
    # A whole deck is the document; exporting slides as figures is up to
    # 'calkit export pptx' itself
    options = _get_options(args)
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

    A .tex file is compared with `calkit doc latex diff`, and options after
    the path are its own.
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
    stage, if any, makes sure is current, with `calkit doc latex to-docx`,
    and options after the path are its own. A PDF built from LaTeX can be
    given instead.
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
    A .tex source is merged with `calkit doc latex merge-docx`, and options
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
