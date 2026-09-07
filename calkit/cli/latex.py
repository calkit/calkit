"""Commands for working with LaTeX."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import string
import subprocess
from copy import deepcopy
from pathlib import Path

import typer
from typing_extensions import Annotated

import calkit
import calkit.latex
from calkit.cli import raise_error

latex_app = typer.Typer(no_args_is_help=True)


@latex_app.command(name="from-json")
def from_json(
    input_fpaths: Annotated[
        list[str], typer.Argument(help="Input JSON file path(s).")
    ],
    output_fpaths: Annotated[
        list[str],
        typer.Option("--output", "-o", help="Output LaTeX file path(s)."),
    ],
    command_name: Annotated[
        str | None,
        typer.Option("--command", help="Command name to use in LaTeX output."),
    ] = None,
    keys: Annotated[
        list[str] | None,
        typer.Option(
            "--key",
            help=(
                "Key to expose, dotted to reach into nested output, e.g., "
                "'cases.a.cp'. Repeatable. Without any, every top-level key "
                "is exposed."
            ),
        ),
    ] = None,
    fmt_json: Annotated[
        str | None,
        typer.Option(
            "--format-json",
            help=(
                "Additional JSON input to use for formatting. "
                "Can be used to add extra keys with simple expressions, etc."
            ),
        ),
    ] = None,
):
    """Convert a JSON file to LaTeX.

    This is useful for referencing calculated values in LaTeX documents.
    """
    import arithmetic_eval
    import json2latex

    def tokens_from_format_string(fmt: str):
        return [
            field.strip()
            for _, field, _, _ in string.Formatter().parse(fmt)
            if field
        ]

    # Validate some stuff
    if fmt_json is not None:
        try:
            fmt_dict = json.loads(fmt_json)
        except json.JSONDecodeError:
            raise_error("Format JSON is not valid JSON")
    else:
        fmt_dict = {}
    data = {}
    for input_fpath in input_fpaths:
        if not os.path.isfile(input_fpath):
            raise_error(f"Input file {input_fpath} does not exist")
        if not input_fpath.endswith(".json"):
            raise_error("Input file must be a JSON file")
        with open(input_fpath) as f:
            try:
                data_i = json.load(f)
                data.update(data_i)
            except json.JSONDecodeError:
                raise_error("Input JSON file is not valid JSON")
    # Named keys are looked up wherever they are, so a nested value can
    # reach the document without exposing everything around it
    if keys:
        from calkit.questions import resolve_key

        selected = {}
        for key in keys:
            try:
                selected[key] = resolve_key(data, key)
            except (KeyError, ValueError, IndexError, TypeError):
                raise_error(
                    f"Key '{key}' is not in " + ", ".join(input_fpaths)
                )
        data = selected
    for output_fpath in output_fpaths:
        if not output_fpath.endswith(".tex"):
            raise_error("Output file must be a .tex file")
    # Format the data
    formatted = deepcopy(data)
    for tex_var_name, fmt_string in fmt_dict.items():
        fmt_string = str(fmt_string)
        data_for_formatting = deepcopy(data)
        # Do any relevant evals and add them to the data for formatting
        tokens = tokens_from_format_string(fmt_string)
        for t in tokens:
            try:
                data_for_formatting[t] = arithmetic_eval.evaluate(t, data)
            except Exception:
                raise_error(
                    f"Error evaluating expression '{t}' for formatting"
                )
        formatted[tex_var_name] = fmt_string.format(**data_for_formatting)
    for out_path in output_fpaths:
        # If no command is provided, use the output file name without extension
        if command_name is None:
            cmd_name = os.path.splitext(os.path.basename(out_path))[0]
        else:
            cmd_name = command_name
        # Create output directory if it doesn't exist
        outdir = os.path.dirname(out_path)
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        with open(out_path, "w") as f:
            json2latex.dump(cmd_name, formatted, f)


def _tex_cmd(
    tex_cmd: list[str],
    environment: str | None,
    no_check: bool,
    verbose: bool,
    dep: str,
) -> list[str]:
    """Wrap a TeX command so it runs wherever the project's TeX lives.

    In the project's Calkit environment if one was named, else directly if
    the tool is installed, else in a TeX Live container. The container
    mounts the working directory, so anything the command reads has to be
    inside the project -- which is why the diff builds its copy of the
    base revision there rather than in a temp directory.
    """
    if environment is not None:
        cmd = (
            ["calkit", "xenv", "--name", environment]
            + (["--no-check"] if no_check else [])
            + ["--"]
            + tex_cmd
        )
    elif calkit.check_dep_exists(dep):
        cmd = tex_cmd
    else:
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{os.getcwd()}:/work",
            "-w",
            "/work",
            "texlive/texlive:latest-full",
        ] + tex_cmd
    if verbose:
        typer.echo(f"Running command: {cmd}")
    return cmd


@latex_app.command(name="build")
def build(
    tex_file: Annotated[str, typer.Argument(help="The .tex file to compile.")],
    environment: Annotated[
        str | None,
        typer.Option(
            "--env",
            "-e",
            help=("Environment in which to run latexmk, if applicable."),
        ),
    ] = None,
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help=(
                "Don't check the environment is valid before running latexmk."
            ),
        ),
    ] = False,
    latexmk_rc_path: Annotated[
        str | None,
        typer.Option(
            "--latexmk-rc",
            "-r",
            help="Path to a latexmkrc file to use for compilation.",
        ),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option(
            "--output-dir",
            help=(
                "Directory for the compiled PDF, relative to the current "
                "directory. Passed to latexmk as -outdir."
            ),
        ),
    ] = None,
    aux_dir: Annotated[
        str | None,
        typer.Option(
            "--aux-dir",
            help=(
                "Directory for auxiliary files, relative to the current "
                "directory. Passed to latexmk as -auxdir."
            ),
        ),
    ] = None,
    latexmk_args: Annotated[
        list[str],
        typer.Option(
            "--latexmk-arg",
            help=(
                "Extra argument to pass through to latexmk. Repeat the option "
                "to pass more than one."
            ),
        ),
    ] = [],
    no_synctex: Annotated[
        bool,
        typer.Option(
            "--no-synctex",
            help="Don't generate synctex file for source-to-pdf mapping.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Force latexmk to recompile all files, even if they are up to "
                "date."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
):
    """Build a PDF of a LaTeX document with latexmk.

    If a Calkit environment is not specified, latexmk will be run in the
    system environment if available. If not available, a TeX Live Docker
    container will be used.
    """
    # Now formulate the command
    latexmk_cmd = ["latexmk", "-pdf", "-cd"]
    if latexmk_rc_path is not None:
        latexmk_cmd += ["-r", latexmk_rc_path]
    if not no_synctex:
        latexmk_cmd.append("-synctex=1")
    if not verbose:
        latexmk_cmd.append("-silent")
    if force:
        latexmk_cmd.append("-f")
    # latexmk runs with -cd, so its -outdir/-auxdir are relative to the .tex
    # file's directory; convert the (current-directory-relative) Calkit paths
    # into that frame.
    tex_dir = os.path.dirname(tex_file) or "."
    if output_dir is not None:
        rel = Path(os.path.relpath(output_dir, tex_dir)).as_posix()
        latexmk_cmd.append(f"-outdir={rel}")
    if aux_dir is not None:
        rel = Path(os.path.relpath(aux_dir, tex_dir)).as_posix()
        latexmk_cmd.append(f"-auxdir={rel}")
    latexmk_cmd.append("-interaction=nonstopmode")
    # User pass-through args come last so they can override Calkit's defaults.
    latexmk_cmd += latexmk_args
    latexmk_cmd.append(tex_file)
    cmd = _tex_cmd(
        latexmk_cmd,
        environment=environment,
        no_check=no_check,
        verbose=verbose,
        dep="latexmk",
    )
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        raise_error("latexmk failed")


DIFF_TMP_DIR = calkit.latex.DIFF_TMP_DIR
DIFF_AUX_DIR = calkit.latex.DIFF_AUX_DIR
get_diff_path = calkit.latex.get_diff_path
_is_immutable_ref = calkit.latex._is_immutable_ref
_default_base_ref = calkit.latex.default_base_ref


@latex_app.command(name="diff")
def diff(
    tex_file: Annotated[str, typer.Argument(help="The .tex file to compare.")],
    from_ref: Annotated[
        str | None,
        typer.Option(
            "--from",
            help=(
                "Older revision, whose removed text is struck through. "
                "Defaults to the merge base with the default branch."
            ),
        ),
    ] = None,
    to_ref: Annotated[
        str | None,
        typer.Option(
            "--to",
            help=(
                "Newer revision, whose additions are marked. Defaults to "
                "the working tree."
            ),
        ),
    ] = None,
    environment: Annotated[
        str | None,
        typer.Option(
            "--env",
            "-e",
            help="Environment in which to run latexdiff and latexmk.",
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Where to write the diff PDF. Defaults to a path under "
                ".calkit/latex-diffs, keeping it with the project's other "
                "derived files."
            ),
        ),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option(
            "--output-dir",
            help=(
                "Directory to write the diff into, keeping the document's "
                "own path inside it. Lets a pipeline name the location "
                "after the revisions as written while passing resolved "
                "commits to --from and --to."
            ),
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Rebuild even if this comparison can't have changed and "
                "has already been built."
            ),
        ),
    ] = False,
    keep_tex: Annotated[
        bool,
        typer.Option(
            "--keep-tex",
            help="Keep the generated diff .tex file for inspection.",
        ),
    ] = False,
    no_check: Annotated[
        bool,
        typer.Option(
            "--no-check",
            help="Don't check the environment is valid before running.",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print verbose output.")
    ] = False,
) -> None:
    """Build a PDF showing what changed in a LaTeX document.

    Two revisions that turn out to be the same is a result rather than an
    error: the marked-up document comes out unmarked, which is what "this
    branch hasn't changed the paper" looks like. A pipeline shouldn't fail
    depending on which branch it runs from.

    Marks up one revision of a document against another with latexdiff, so
    additions and deletions are visible where they happen rather than as a
    list of files that changed. A `.dvc` pointer in a pull request says a
    paper was rebuilt; this says what it now reads.

    With the default `--to`, the newer side is the working tree, so the
    marked-up document is built with the current figures and bibliography
    and what's marked is what changed in the text.
    """
    repo = calkit.git.get_repo()
    if repo.bare:
        raise_error("This is not a working Git repo")
    # Named for what was asked for, not what it resolved to: a merge base
    # is a different commit on every branch, and a directory per commit
    # would pile up for something nobody keeps
    from_label = from_ref if from_ref is not None else "default-branch"
    if from_ref is None:
        from_ref = _default_base_ref(repo)
    if to_ref is None and not os.path.isfile(tex_file):
        raise_error(f"{tex_file} does not exist")
    if output is None:
        output = get_diff_path(
            tex_file,
            from_ref=from_label,
            to_ref=to_ref,
            output_dir=output_dir,
        )
    # A comparison between two revisions that can't move is the same
    # comparison forever, and LaTeX writes a timestamp into every PDF, so
    # rebuilding one would change the file without changing what it says
    fixed = _is_immutable_ref(repo, from_ref) and _is_immutable_ref(
        repo, to_ref
    )
    if fixed and os.path.isfile(output) and not force:
        typer.echo(f"{output} is already built; use --force to rebuild it")
        return
    checkouts: dict[str, str] = {}
    try:
        for name, ref in [("base", from_ref), ("head", to_ref)]:
            if ref is None:
                continue
            sha = calkit.git.resolve_ref(repo, ref)
            if sha is None:
                raise_error(f"Git ref '{ref}' was not found")
            # A worktree, not a temp directory: a document is rarely one
            # file, and \input needs the rest of them as they were then
            path = os.path.join(DIFF_TMP_DIR, name)
            _remove_worktree(path)
            # Writes the .gitignore that keeps everything below it out of
            # version control
            calkit.ensure_local_dir()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            typer.echo(f"Checking out {ref} to compare")
            try:
                repo.git.worktree("add", "--detach", path, sha)
            except Exception as e:
                raise_error(f"Failed to check out {ref}: {e}")
            checkouts[name] = path
        sides = {}
        for name, ref in [("base", from_ref), ("head", to_ref)]:
            side = (
                tex_file
                if ref is None
                else os.path.join(checkouts[name], tex_file)
            )
            if not os.path.isfile(side):
                raise_error(f"{tex_file} does not exist at {ref}")
            sides[name] = side
        _build_diff(
            base_tex=sides["base"],
            head_tex=sides["head"],
            tex_file=tex_file,
            output=output,
            environment=environment,
            no_check=no_check,
            keep_tex=keep_tex,
            force=force,
            verbose=verbose,
        )
    finally:
        for path in checkouts.values():
            _remove_worktree(path)


def _marked_up_digest(marked_up: bytes) -> str:
    """Hash a marked-up document by what actually determines the PDF.

    latexdiff writes the two inputs' paths and modification times into a
    header comment, and the older side is a fresh checkout every time, so
    hashing the file as-is would say "changed" on every run when nothing
    had. Those lines are comments; the PDF doesn't depend on them.
    """
    kept = [
        line
        for line in marked_up.splitlines(keepends=True)
        if not line.startswith((b"%DIF DEL ", b"%DIF ADD "))
    ]
    return hashlib.sha256(b"".join(kept)).hexdigest()


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _remove_worktree(path: str) -> None:
    if os.path.exists(path):
        subprocess.call(
            ["git", "worktree", "remove", "--force", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(path, ignore_errors=True)


def _build_diff(
    base_tex: str,
    head_tex: str,
    tex_file: str,
    output: str,
    environment: str | None,
    no_check: bool,
    keep_tex: bool,
    force: bool,
    verbose: bool,
) -> None:
    """Mark up one document against another and build the result."""
    # Built beside the working copy of the document, so \graphicspath,
    # \bibliography, and relative \includegraphics resolve the way they do
    # for the real thing. A checked-out revision would be the tidier place
    # for it, but a DVC-tracked figure isn't in Git: a checkout has the
    # pointer file and not the image, and the marked-up document would
    # come out with its figures missing.
    tex_dir = os.path.dirname(tex_file) or "."
    stem = Path(tex_file).stem
    diff_tex = os.path.join(tex_dir, f"{stem}-diff.tex")
    try:
        # --flatten pulls \input and \include files into one document on
        # each side, so a multi-file paper compares as a whole
        cmd = _tex_cmd(
            ["latexdiff", "--flatten", "--encoding=utf8", base_tex, head_tex],
            environment=environment,
            no_check=no_check,
            verbose=verbose,
            dep="latexdiff",
        )
        typer.echo("Marking up the document with latexdiff")
        try:
            marked_up = subprocess.check_output(cmd)
        except FileNotFoundError:
            raise_error(
                "latexdiff was not found; it ships with TeX Live, so a "
                "minimal install may not have it"
            )
        except subprocess.CalledProcessError:
            raise_error("latexdiff failed")
        # The PDF is a function of this marked-up source, so if it hasn't
        # changed there's nothing to build. Worth checking because the
        # common case produces nothing at all: on the default branch the
        # merge base is usually HEAD, so the comparison is empty, and
        # latexmk is the expensive half of this.
        digest = _marked_up_digest(marked_up)
        state_path = calkit.latex.diff_state_path(output)
        if (
            not force
            and os.path.isfile(output)
            and _read(state_path) == digest
        ):
            typer.echo(f"{output} is up to date")
            return
        with open(diff_tex, "wb") as f:
            f.write(marked_up)
        aux_dir = DIFF_AUX_DIR
        os.makedirs(aux_dir, exist_ok=True)
        rel_aux = Path(os.path.relpath(aux_dir, tex_dir)).as_posix()
        latexmk_cmd = [
            "latexmk",
            "-pdf",
            "-cd",
            "-interaction=nonstopmode",
            f"-auxdir={rel_aux}",
            f"-outdir={rel_aux}",
        ]
        if not verbose:
            latexmk_cmd.append("-silent")
        latexmk_cmd.append(diff_tex)
        cmd = _tex_cmd(
            latexmk_cmd,
            environment=environment,
            no_check=no_check,
            verbose=verbose,
            dep="latexmk",
        )
        typer.echo("Building the marked-up document")
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            raise_error(
                "latexmk failed on the marked-up document; rerun with "
                "--keep-tex to inspect it"
            )
        built = os.path.join(aux_dir, f"{stem}-diff.pdf")
        if not os.path.isfile(built):
            raise_error("latexmk did not produce a PDF")
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        shutil.move(built, output)
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            f.write(digest)
        typer.echo(f"Wrote {output}")
    finally:
        if not keep_tex and os.path.isfile(diff_tex):
            os.remove(diff_tex)


@latex_app.command(name="to-docx")
def to_docx(
    pdf_path: Annotated[str, typer.Argument(help="Compiled PDF to export.")],
    source: Annotated[
        str | None,
        typer.Option(
            "--source",
            help=(
                "Main .tex file. Defaults to the pipeline stage's target, "
                "else the .tex next to the PDF."
            ),
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help="Where to write the .docx. Defaults to <pdf>-for-review.docx.",
        ),
    ] = None,
    comment_only: Annotated[
        bool,
        typer.Option("--comment-only", help="Lock the document to comments."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite an existing export."),
    ] = False,
) -> None:
    """Export a Word copy of a LaTeX document for review.

    Uses Word's own PDF import, so the copy looks like the PDF, then records
    inside the file which source line each paragraph came from and the text
    as sent, so ``merge-docx`` can bring edits and comments back.
    """
    import datetime
    import sys
    import uuid
    from typing import Any

    import calkit.docx
    import calkit.git
    import calkit.pipeline
    from calkit.models.docx import DocxExport
    from calkit.models.pipeline import LatexStage

    ck_info = calkit.load_calkit_info()
    stages = ck_info.get("pipeline", {}).get("stages", {})
    stage_name = calkit.pipeline.get_stage_for_output(pdf_path, ck_info)
    # A latex stage's PDF is implied by its target, not listed as an output
    if stage_name is None:
        for name, stage in stages.items():
            if isinstance(stage, dict) and stage.get("kind") == "latex":
                pdf = LatexStage.model_validate(stage).pdf_path
                if pdf == Path(pdf_path).as_posix():
                    stage_name = name
                    break
    if source is None and stage_name is not None:
        source = stages[stage_name].get("target_path")
    if source is None:
        source = Path(pdf_path).with_suffix(".tex").as_posix()
    source = Path(source).as_posix()
    if not os.path.isfile(source):
        raise_error(f"Source {source} does not exist; pass --source")
    if stage_name is not None:
        typer.echo(f"Running stage {stage_name} to make sure the PDF is fresh")
        subprocess.run(
            [sys.executable, "-m", "calkit", "run", stage_name], check=True
        )
    if not os.path.isfile(pdf_path):
        raise_error(f"{pdf_path} does not exist")
    if output is None:
        output = (
            Path(pdf_path)
            .with_name(Path(pdf_path).stem + "-for-review.docx")
            .as_posix()
        )
    if os.path.exists(output) and not force:
        raise_error(f"{output} already exists; use --force to overwrite it")
    typer.echo("Converting the PDF with Word")
    try:
        calkit.docx.pdf_to_docx(pdf_path, output)
    except RuntimeError as e:
        raise_error(str(e))
    doc = calkit.docx.Document(output)
    lines = calkit.latex.flatten(source)
    blks = calkit.latex.blocks(lines)
    paras = doc.paragraphs()
    matched = calkit.latex.align([p.text for p in paras], blks)
    # Bookmark each anchored paragraph; a block rendering as several
    # paragraphs gets numbered suffixes
    original: dict[str, str] = {}
    para_for_block: dict[int, Any] = {}
    seen: dict[str, int] = {}
    for i, (para, blk) in enumerate(zip(paras, matched)):
        if blk is None or para.element is None:
            continue
        name = calkit.latex.bookmark_name(blk.path, blk.lineno)
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        doc.add_bookmark(para.element, name, 9000 + i)
        original[name] = para.text
        para_for_block.setdefault(id(blk), para.element)
    # Existing comment blocks in the source go out as Word comments
    threads, anchors, highlights, resolved = [], [], [], []
    for path in sorted({ln.path for ln in lines}):
        file_lines = Path(path).read_text(encoding="utf-8").split("\n")
        for tc in calkit.latex.parse_comments(file_lines):
            after = tc.lineno + tc.nlines
            blk = next(
                (b for b in blks if b.path == path and b.lineno >= after), None
            )
            if blk is not None and id(blk) in para_for_block:
                threads.append(tc.messages())
                anchors.append(para_for_block[id(blk)])
                highlights.append(
                    (tc.highlight, tc.highlight_occ) if tc.highlight else None
                )
                resolved.append(tc.resolved)
    doc.add_comments(threads, anchors, highlights, resolved)
    if comment_only:
        doc.protect("comments")
    else:
        doc.track_changes()
    doc.show_all_markup()
    rev, dirty = None, False
    try:
        repo = calkit.git.get_repo()
        rev = repo.head.commit.hexsha
        dirty = any(repo.is_dirty(path=p) for p in {ln.path for ln in lines})
    except Exception:
        pass
    export_id = str(uuid.uuid4())
    doc.write_original(
        calkit.docx.Original(
            export_id, rev, source, original, doc.media_hashes()
        )
    )
    doc.set_identifier(f"calkit-review:{export_id}:{rev or ''}:{source}")
    doc.save()
    record = DocxExport(
        uuid=export_id,
        created=datetime.datetime.now(datetime.timezone.utc),
        source=source,
        pdf=Path(pdf_path).as_posix(),
        docx=Path(output).as_posix(),
        rev=rev,
        dirty=dirty,
        permission="comment" if comment_only else "suggest",
        paragraphs=len(original),
        unanchored=sum(
            1 for p, m in zip(paras, matched) if m is None and p.text
        ),
        comments_exported=len(threads),
    )
    os.makedirs(calkit.latex.DOCX_EXPORTS_DIR, exist_ok=True)
    with open(
        os.path.join(calkit.latex.DOCX_EXPORTS_DIR, f"{export_id}.json"),
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:
        f.write(record.model_dump_json(indent=2))
    typer.echo(
        f"Wrote {output} ({record.paragraphs} paragraphs anchored, "
        f"{record.unanchored} not, {len(threads)} comments)"
    )


@latex_app.command(name="merge-docx")
def merge_docx(
    docx_path: Annotated[str, typer.Argument(help="Reviewed .docx to merge.")],
    no_comments: Annotated[
        bool,
        typer.Option(
            "--no-comments", help="Don't write comments to the .tex."
        ),
    ] = False,
) -> None:
    """Merge a reviewed Word document back into the LaTeX source.

    Accepted changes are applied. Tracked changes not yet accepted or
    rejected, and edits that no longer fit the source, are left alone with
    a warning: deal with them in Word and merge again. Comments become
    comment blocks above the paragraph; threads resolved in Word are
    marked resolved.
    """
    import datetime

    import calkit.docx
    import calkit.git
    from calkit.cli.core import warn
    from calkit.models.docx import DocxMerge, DocxMergeChange

    doc = calkit.docx.Document(docx_path)
    original = doc.read_original()
    if original is None:
        raise_error(
            f"{docx_path} was not exported by Calkit, or its metadata was "
            "stripped by another application"
        )
    if not os.path.isfile(original.source):
        raise_error(f"Source {original.source} does not exist")
    # Figures come from the pipeline, so a picture swapped or edited in
    # Word can't be merged
    media = doc.media_hashes()
    changed = sorted(
        name
        for name in set(media) | set(original.media)
        if media.get(name) != original.media.get(name)
    )
    if changed:
        warn(
            "Figures were changed in Word and can't be merged; edit the "
            "pipeline instead: " + ", ".join(changed)
        )
    lines = calkit.latex.flatten(original.source)
    blks = calkit.latex.blocks(lines)
    path_for_hash = {
        calkit.latex.bookmark_name(p, 0).split("_")[1]: p
        for p in {ln.path for ln in lines}
    }
    edits: dict[str, list[tuple[int, int, list[str]]]] = {}
    changes: list[DocxMergeChange] = []
    for para in doc.paragraphs():
        if para.bookmark is None or para.bookmark not in original.paragraphs:
            continue
        sent = original.paragraphs[para.bookmark]
        if para.text == sent:
            continue
        parts = para.bookmark.split("_")
        path, lineno = path_for_hash.get(parts[1], ""), int(parts[2])
        blk = calkit.latex.find_block(
            blks, path, lineno, sent
        ) or calkit.latex.find_block(blks, path, lineno, para.text)
        if blk is None:
            warn(f"Can't place an edit from {path}:{lineno}: {para.text[:60]}")
            changes.append(
                DocxMergeChange(path=path, lineno=lineno, status="unplaced")
            )
            continue
        loc = f"{blk.path}:{blk.lineno}"
        if para.pending:
            warn(f"Tracked change at {loc} not yet accepted or rejected")
            changes.append(
                DocxMergeChange(
                    path=blk.path,
                    lineno=blk.lineno,
                    status="pending",
                    author=", ".join(para.authors) or None,
                )
            )
            continue
        sent_tex = calkit.latex.from_word_text(sent)
        new_tex = calkit.latex.from_word_text(para.text)
        if calkit.latex.already_applied(blk, sent_tex, new_tex):
            changes.append(
                DocxMergeChange(
                    path=blk.path, lineno=blk.lineno, status="already-applied"
                )
            )
            continue
        new_lines = calkit.latex.apply_edit(blk, sent_tex, new_tex)
        if new_lines is None:
            warn(
                f"Edit at {loc} touches markup; apply it by hand: {para.text[:60]}"
            )
            changes.append(
                DocxMergeChange(
                    path=blk.path, lineno=blk.lineno, status="unplaced"
                )
            )
            continue
        edits.setdefault(blk.path, []).append(
            (blk.lineno, len(blk.lines), new_lines)
        )
        changes.append(
            DocxMergeChange(path=blk.path, lineno=blk.lineno, status="applied")
        )
        typer.echo(f"Applied edit at {loc}")
    files = {
        p: Path(p).read_text(encoding="utf-8").split("\n")
        for p in {ln.path for ln in lines}
    }
    for path, updates in edits.items():
        for lineno, count, new_lines in sorted(updates, reverse=True):
            files[path][lineno - 1 : lineno - 1 + count] = new_lines
    added = updated = 0
    if not no_comments:
        # Threads keyed by root, anchored through the root's bookmark
        comments = doc.comments()
        by_id = {c.para_id: c for c in comments}
        roots = [c for c in comments if not c.parent_id]
        # Resolve every thread to a block first, then edit each file from
        # the bottom up so earlier line numbers stay valid
        placed: list[tuple[calkit.latex.Block, calkit.latex.TexComment]] = []
        for root in roots:
            thread = [root] + [
                c
                for c in comments
                if c.parent_id and by_id.get(c.parent_id) is root
            ]
            tc = calkit.latex.TexComment(
                [
                    calkit.latex.Entry(
                        c.author, c.text, date=calkit.latex.word_date(c.date)
                    )
                    for c in thread
                ],
                highlight=root.highlight,
                highlight_occ=root.highlight_occ,
                resolved=root.done,
            )
            if root.bookmark is None:
                warn(
                    f"Comment by {root.author} has no anchor: {root.text[:60]}"
                )
                continue
            parts = root.bookmark.split("_")
            path, lineno = path_for_hash.get(parts[1], ""), int(parts[2])
            blk = calkit.latex.find_block(
                blks, path, lineno, original.paragraphs.get(root.bookmark, "")
            )
            if blk is None:
                warn(
                    f"Can't place a comment by {root.author}: {root.text[:60]}"
                )
                continue
            placed.append((blk, tc))
        for blk, tc in sorted(
            placed, key=lambda x: (x[0].path, x[0].lineno), reverse=True
        ):
            content = files[blk.path]
            at = blk.lineno
            existing = next(
                (
                    e
                    for e in calkit.latex.parse_comments(content)
                    if e.author == tc.author and e.text == tc.text
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.messages() == tc.messages()
                    and existing.resolved == tc.resolved
                ):
                    continue
                # Word knows neither emails nor what the source already
                # recorded, so carry those over for unchanged messages
                known = {(e.author, e.text): e for e in existing.entries}
                for e in tc.entries:
                    old_e = known.get((e.author, e.text))
                    if old_e is not None:
                        e.email = old_e.email
                        e.date = old_e.date or e.date
                del content[
                    existing.lineno - 1 : existing.lineno - 1 + existing.nlines
                ]
                if existing.lineno < at:
                    at -= existing.nlines
            content[at - 1 : at - 1] = tc.render()
            added += existing is None
            updated += existing is not None
    for path, content in files.items():
        new = "\n".join(content)
        if new != Path(path).read_text(encoding="utf-8"):
            Path(path).write_text(new, encoding="utf-8")
    rev = None
    try:
        rev = calkit.git.get_repo().head.commit.hexsha
    except Exception:
        pass
    seen = {a for p in doc.paragraphs() for a in p.authors}
    seen |= {c.author for c in doc.comments()}
    record = DocxMerge(
        uuid=original.uuid,
        created=datetime.datetime.now(datetime.timezone.utc),
        docx=Path(docx_path).as_posix(),
        rev=rev,
        authors=sorted(seen),
        last_modified_by=doc.last_modified_by(),
        changes=changes,
        comments_added=added,
        comments_updated=updated,
    )
    os.makedirs(calkit.latex.DOCX_MERGES_DIR, exist_ok=True)
    stamp = record.created.strftime("%Y%m%dT%H%M%S.%fZ")
    with open(
        os.path.join(
            calkit.latex.DOCX_MERGES_DIR, f"{original.uuid}-{stamp}.json"
        ),
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:
        f.write(record.model_dump_json(indent=2))
    counts = {
        s: sum(1 for c in changes if c.status == s)
        for s in ("applied", "already-applied", "pending", "unplaced")
    }
    typer.echo(
        f"Applied {counts['applied']} edits ({counts['already-applied']} "
        f"already there, {counts['pending']} pending, {counts['unplaced']} "
        f"unplaced); {added} comments added, {updated} updated"
    )
