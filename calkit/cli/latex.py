"""Commands for working with LaTeX."""

from __future__ import annotations

import json
import os
import re
import shutil
import string
import subprocess
from copy import deepcopy
from pathlib import Path

import git
import typer
from typing_extensions import Annotated

import calkit
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


# Where the base revision is checked out and the marked-up document is
# built. Inside the project so a containerized TeX environment, which only
# sees the working directory, can read it; under .calkit/tmp so it's
# ignored rather than tracked alongside the diffs themselves.
DIFF_WORKTREE_DIR = os.path.join(".calkit", "tmp", "latex-diff", "base")
DIFF_AUX_DIR = os.path.join(".calkit", "tmp", "latex-diff", "aux")


# What a diff with no named base is called. Its base moves, so unlike a
# diff against a tag there's nothing stable to name it after.
MERGE_BASE_DIFF_NAME = "merge-base"


def get_diff_path(
    tex_file: str, base_ref: str | None = None, as_posix: bool = True
) -> str:
    """Return where a document's diff against ``base_ref`` is kept.

    Beside the other things Calkit derives from a project's files rather
    than next to the document, following executed notebooks: it's an
    output, and a PDF, so saving the project tracks it with DVC and its
    history comes along with the project's.

    Named after what it's a diff against, so a document can keep several
    -- the round it was first submitted in, the first revision, and so on
    -- and each says what it means.
    """
    name = MERGE_BASE_DIFF_NAME if base_ref is None else base_ref
    # Ref names can carry slashes (release/1, origin/main) and a name is
    # one path component here
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name.replace("/", "-")).strip("-")
    p = os.path.join(
        ".calkit",
        "latex-diff",
        os.path.dirname(tex_file),
        Path(tex_file).stem,
        f"{name or MERGE_BASE_DIFF_NAME}.pdf",
    )
    return Path(p).as_posix() if as_posix else p


def _default_base_ref(repo: git.Repo) -> str:
    """The ref a change is naturally read against: the merge base with the
    default branch.

    Not the default branch itself, since work that landed there after this
    branch started isn't part of this change and would otherwise show up
    as deletions.
    """
    from calkit.cli import warn

    candidates = []
    try:
        candidates.append(repo.remotes.origin.refs.HEAD.reference.name)
    except Exception:
        pass
    candidates += ["origin/main", "origin/master", "main", "master"]
    for candidate in candidates:
        try:
            base = str(repo.git.merge_base("HEAD", candidate)).strip()
        except Exception:
            continue
        if base:
            return base
    warn("Could not find a default branch; comparing against HEAD~1")
    return "HEAD~1"


@latex_app.command(name="diff")
def diff(
    tex_file: Annotated[str, typer.Argument(help="The .tex file to compare.")],
    from_ref: Annotated[
        str | None,
        typer.Option(
            "--from",
            help=(
                "Git ref to compare against. Defaults to the merge base "
                "with the default branch."
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
                ".calkit/latex-diff, keeping it with the project's other "
                "derived files."
            ),
        ),
    ] = None,
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
    """Build a PDF showing what a change did to a LaTeX document.

    Marks up the current document against an earlier revision with
    latexdiff, so additions and deletions are visible where they happen
    rather than as a list of files that changed. A `.dvc` pointer in a
    pull request says a paper was rebuilt; this says what it now reads.

    The diff is built in the working tree, so it uses the current figures
    and bibliography -- what changed in the text is what's marked.
    """
    repo = calkit.git.get_repo()
    if repo.bare:
        raise_error("This is not a working Git repo")
    if not os.path.isfile(tex_file):
        raise_error(f"{tex_file} does not exist")
    base_ref = from_ref or _default_base_ref(repo)
    try:
        base_sha = repo.git.rev_parse(base_ref).strip()
    except Exception:
        raise_error(f"Git ref '{base_ref}' was not found")
    tex_dir = os.path.dirname(tex_file) or "."
    stem = Path(tex_file).stem
    if output is None:
        output = get_diff_path(tex_file, base_ref=from_ref)
    # A worktree, not a temp directory: a document is rarely one file, and
    # \input needs the rest of them as they were at that revision
    worktree = DIFF_WORKTREE_DIR
    if os.path.exists(worktree):
        subprocess.call(
            ["git", "worktree", "remove", "--force", worktree],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(worktree, ignore_errors=True)
    os.makedirs(os.path.dirname(worktree), exist_ok=True)
    typer.echo(f"Checking out {base_ref} to compare against")
    try:
        repo.git.worktree("add", "--detach", worktree, base_sha)
    except Exception as e:
        raise_error(f"Failed to check out {base_ref}: {e}")
    diff_tex = os.path.join(tex_dir, f"{stem}-diff.tex")
    try:
        base_tex = os.path.join(worktree, tex_file)
        if not os.path.isfile(base_tex):
            raise_error(f"{tex_file} does not exist at {base_ref}")
        # --flatten pulls \input and \include files into one document on
        # each side, so a multi-file paper compares as a whole
        latexdiff_cmd = [
            "latexdiff",
            "--flatten",
            "--encoding=utf8",
            base_tex,
            tex_file,
        ]
        cmd = _tex_cmd(
            latexdiff_cmd,
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
        with open(diff_tex, "wb") as f:
            f.write(marked_up)
        # Built beside the original so \graphicspath, \bibliography, and
        # relative \includegraphics resolve the same way they do for the
        # real document
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
        typer.echo(f"Wrote {output}")
    finally:
        if not keep_tex and os.path.isfile(diff_tex):
            os.remove(diff_tex)
        subprocess.call(
            ["git", "worktree", "remove", "--force", worktree],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(worktree, ignore_errors=True)
