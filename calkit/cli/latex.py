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
    Each value is wrapped in ``\\ckvalue`` with the file and pipeline stage
    it came from, which calkit.sty can mark and log; without the package
    the values print as plain text.
    """
    import arithmetic_eval

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
    try:
        ck_info = calkit.load_calkit_info()
    except Exception:
        ck_info = {}
    data = {}
    source: dict[str, str] = {}
    for input_fpath in input_fpaths:
        if not os.path.isfile(input_fpath):
            raise_error(f"Input file {input_fpath} does not exist")
        if not input_fpath.endswith(".json"):
            raise_error("Input file must be a JSON file")
        with open(input_fpath) as f:
            try:
                data_i = json.load(f)
            except json.JSONDecodeError:
                raise_error("Input JSON file is not valid JSON")
        # Several files merged into one command can define the same key.
        # Taking the last silently means a number in the paper comes from
        # a file nobody would guess, so say so instead.
        for k in data_i:
            if k in source and data[k] != data_i[k]:
                raise_error(
                    f"Key '{k}' is defined differently in {source[k]} and "
                    f"{input_fpath}; rename one, or drop an input"
                )
            source[k] = input_fpath
        data.update(data_i)
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
            # A dotted key belongs to the file its first part came from
            source.setdefault(key, source.get(key.split(".")[0], ""))
        data = selected
    for output_fpath in output_fpaths:
        if not output_fpath.endswith(".tex"):
            raise_error("Output file must be a .tex file")
    # Format the data
    formatted: dict[str, str] = {
        k: calkit.latex.escape_tex(calkit.latex.format_value(v))
        for k, v in data.items()
    }
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
        try:
            rendered = fmt_string.format(
                **{
                    k: calkit.latex.unwrap_singleton(v)
                    for k, v in data_for_formatting.items()
                }
            )
        except (TypeError, ValueError) as e:
            raise_error(
                f"Cannot format '{tex_var_name}' with '{fmt_string}': {e}"
            )
        formatted[tex_var_name] = calkit.latex.escape_tex(rendered)
        # A formatted expression comes from whichever file its first
        # token came from
        for t in tokens:
            for k in source:
                if k in t:
                    source.setdefault(tex_var_name, source[k])
                    break
    stages = {
        p: calkit.latex.stage_for(p, ck_info) for p in set(source.values())
    }
    entries = {
        k: calkit.latex.value_macro(
            k,
            v,
            source.get(k, input_fpaths[0]),
            stages.get(source.get(k, input_fpaths[0])),
        )
        for k, v in formatted.items()
    }
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
            f.write(calkit.latex.PREAMBLE)
            f.write(calkit.latex.keyed_command(cmd_name, entries, formatted))


@latex_app.command(name="from-questions")
def from_questions(
    output_fpath: Annotated[
        str, typer.Option("--output", "-o", help="Output LaTeX file path.")
    ] = "generated-questions.tex",
):
    """Write the project's questions and answers as LaTeX commands.

    Gives ``\\ckquestion[n]``, ``\\ckanswer[n]``, ``\\ckevidence[n]``
    and friends, plus ``\\ckfindings`` for every answered question, with each
    ``{name}`` placeholder rendered as a provenance-marked value from the
    results file it points at.
    """
    ck_info = calkit.load_calkit_info()
    try:
        tex = calkit.latex.questions_tex(ck_info)
    except KeyError as e:
        raise_error(f"Placeholder {{{e.args[0]}}} names no value evidence")
    except (FileNotFoundError, ValueError) as e:
        raise_error(f"Cannot render questions: {e}")
    outdir = os.path.dirname(output_fpath)
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(output_fpath, "w", encoding="utf-8") as f:
        f.write(tex)


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
    provenance: Annotated[
        bool,
        typer.Option(
            "--provenance",
            help=(
                "Install calkit.sty beside the document, generate its "
                "artifact table, and write <document>.provenance.json "
                "from the build's log of injected content."
            ),
        ),
    ] = False,
):
    """Build a PDF of a LaTeX document with latexmk.

    If a Calkit environment is not specified, latexmk will be run in the
    system environment if available. If not available, a TeX Live Docker
    container will be used.
    """
    if provenance:
        ck_info = calkit.load_calkit_info()
        calkit.latex.install_style(tex_file)
        calkit.latex.write_provenance_tex(tex_file, ck_info)
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
    if not no_synctex:
        # A build in a container records the container's paths, which a
        # viewer's reverse search cannot open. Worth doing whether or not
        # provenance was asked for: jumping from the PDF to the source is
        # the thing people already expect from a LaTeX viewer.
        calkit.latex.localize_synctex(tex_file, os.getcwd())
    if provenance:
        # latexmk writes the PDF into --output-dir when one is given, so
        # the artifact the record describes is not always beside its source
        stem = os.path.splitext(os.path.basename(tex_file))[0]
        artifact_path = Path(
            os.path.join(output_dir or os.path.dirname(tex_file), stem)
            + ".pdf"
        ).as_posix()
        sidecar = calkit.latex.collect_provenance(
            tex_file, ck_info, artifact_path=artifact_path
        )
        n = len(sidecar["components"])
        typer.echo(
            f"Wrote {calkit.latex.provenance_sidecar_path(tex_file)} "
            f"({n} component(s))"
        )


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
