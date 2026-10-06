"""Commands for working with LaTeX."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import string
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import typer
from typing_extensions import Annotated

import calkit
import calkit.latex
from calkit.cli import raise_error, warn

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


def _tex_env_vars(source_date_epoch: str | None) -> dict[str, str]:
    r"""The environmental variables a TeX command needs, beyond the ambient.

    ``FORCE_SOURCE_DATE`` is what makes pdfTeX apply the date to
    ``\pdfcreationdate`` and friends, not only to the trailer ID.
    """
    if source_date_epoch is None:
        return {}
    return {
        "SOURCE_DATE_EPOCH": source_date_epoch,
        "FORCE_SOURCE_DATE": "1",
    }


@latex_app.command(name="from-questions")
def from_questions(
    output_fpaths: Annotated[
        list[str],
        typer.Option("--output", "-o", help="Output LaTeX file path(s)."),
    ],
    command_name: Annotated[
        str,
        typer.Option("--command", help="Command name to use in LaTeX output."),
    ] = "questions",
) -> None:
    """Write the project's questions and answers as a LaTeX command.

    Each question's text, hypothesis, answer, and notes are rendered from
    their evidence and exposed as, e.g., ``\\questions[staging.answer]``,
    keyed by the question's ``name`` or its 1-based position.
    """
    import json2latex

    import calkit.questions

    for out_path in output_fpaths:
        if not out_path.endswith(".tex"):
            raise_error("Output file must be a .tex file")
    ck_info = calkit.load_calkit_info()
    try:
        values = calkit.questions.latex_values(ck_info)
    except ValueError as e:
        raise_error(str(e))
    for out_path in output_fpaths:
        outdir = os.path.dirname(out_path)
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        with open(out_path, "w") as f:
            json2latex.dump(command_name, values, f)


@latex_app.command(name="from-markdown")
def from_markdown(
    md_path: Annotated[
        str, typer.Argument(help="The Markdown file to build.")
    ],
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Where to write the PDF, or the LaTeX with a .tex extension.",
        ),
    ],
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            "-e",
            help="Environment to run pandoc and LaTeX in, e.g., one using "
            "Calkit's LaTeX image, which includes both.",
        ),
    ] = None,
    template: Annotated[
        str | None, typer.Option("--template", help="Pandoc template.")
    ] = None,
    filters: Annotated[
        list[str] | None,
        typer.Option(
            "--filter", help="Pandoc Lua filter; can be given more than once."
        ),
    ] = None,
    pandoc_args: Annotated[
        list[str] | None,
        typer.Option(
            "--pandoc-arg",
            help="Another argument for pandoc; can be given more than once.",
        ),
    ] = None,
    no_check: Annotated[
        bool,
        typer.Option("--no-check", help="Don't check the environment first."),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print commands.")
    ] = False,
) -> None:
    """Build a Markdown file into a PDF with pandoc and LaTeX.

    Value markers are filled from their results files, which keeps the
    Markdown itself current too, and each value links to the question on
    the project's hub whose evidence cites it. The template gets the Calkit
    version and the project's URL as the ``calkit-version``,
    ``project-url``, and ``project`` variables.
    """
    import calkit.docx
    import calkit.markdown

    def question_url(value: calkit.markdown.MarkdownValue) -> str | None:
        # The question whose evidence cites this value, or failing that,
        # the first to cite its file
        if project_url is None:
            return None
        first = None
        for n, q in enumerate(ck_info.get("questions") or [], start=1):
            evidence = q.get("evidence") if isinstance(q, dict) else None
            for ev in evidence or []:
                if not isinstance(ev, dict) or ev.get("path") != value.path:
                    continue
                keys = [ev.get("key"), *(ev.get("values") or {}).values()]
                if value.key in keys:
                    return f"{project_url}/questions/{n}"
                first = first or n
        return f"{project_url}/questions/{first}" if first else None

    if not output.endswith((".pdf", ".tex")):
        raise_error("Output must be a .pdf or .tex file")
    ck_info = calkit.load_calkit_info()
    project_url = None
    if ck_info.get("owner") and ck_info.get("name"):
        hub = str(ck_info.get("hub") or "calkit.io").rstrip("/")
        if "://" not in hub:
            hub = "https://" + hub
        project_url = f"{hub}/{ck_info['owner']}/{ck_info['name']}"
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    try:
        text, changed = calkit.markdown.set_values(text, md_path)
    except calkit.markdown.MarkdownParseError as e:
        raise_error(str(e))
    if changed:
        with open(md_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    # A PDF is built where Calkit keeps what it derives from the file; LaTeX
    # is written where it's asked for
    to_pdf = output.endswith(".pdf")
    stem = Path(md_path).stem
    if to_pdf:
        build_dir = Path(".calkit", "markdown", md_path, "pdf").as_posix()
        tex_path = f"{build_dir}/{stem}.tex"
    else:
        build_dir = os.path.dirname(output) or "."
        tex_path = output
    os.makedirs(build_dir, exist_ok=True)
    src_path = f"{build_dir}/{stem}.pandoc.md"
    with open(src_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            calkit.markdown.prepare_for_pdf(
                text, md_path, build_dir, link=question_url
            )
        )
    args = [src_path, "-o", tex_path, "--standalone"]
    if template is not None:
        args += ["--template", template]
    for path in filters or []:
        args += ["--lua-filter", path]
    # A local version's commit is the project's own, which isn't Calkit's
    version = calkit.__version__.split("+")[0]
    args += [f"--variable=calkit-version:{version}"]
    if project_url is not None:
        args += [
            f"--variable=project-url:{project_url}",
            f"--variable=project:{project_url.split('://', 1)[1]}",
        ]
    args += pandoc_args or []
    if environment is not None:
        cmd = _tex_cmd(
            ["pandoc", *args], environment, no_check, verbose, dep="pandoc"
        )
    else:
        pandoc = calkit.docx.find_pandoc()
        if pandoc is None:
            raise_error(
                "Pandoc is needed; name an environment that has it, e.g., "
                "one using Calkit's LaTeX image, or install it"
            )
        cmd = [pandoc, *args]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        raise_error(f"Pandoc failed to convert {md_path}")
    if not to_pdf:
        return
    cmd = [sys.executable, "-m", "calkit", "latex", "build"]
    if environment is not None:
        cmd += ["-e", environment]
    if no_check:
        cmd += ["--no-check"]
    try:
        subprocess.check_call(cmd + [tex_path])
    except subprocess.CalledProcessError:
        raise_error(f"LaTeX failed to build {tex_path}")
    out_dir = os.path.dirname(output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    shutil.copyfile(f"{build_dir}/{stem}.pdf", output)


def _tex_cmd(
    tex_cmd: list[str],
    environment: str | None,
    no_check: bool,
    verbose: bool,
    dep: str,
    env_vars: dict[str, str] | None = None,
) -> list[str]:
    """Wrap a TeX command so it runs wherever the project's TeX lives.

    In the project's Calkit environment if one was named, else directly if
    the tool is installed, else in a TeX Live container. The container
    mounts the working directory, so anything the command reads has to be
    inside the project -- which is why the diff builds its copy of the
    base revision there rather than in a temp directory.
    """
    env_vars = env_vars or {}
    if environment is not None:
        cmd = (
            ["calkit", "xenv", "--name", environment]
            + (["--no-check"] if no_check else [])
            # Named rather than inherited: the environment may run in a
            # container, which inherits nothing from here
            + [f"--env-var={k}={v}" for k, v in env_vars.items()]
            + ["--"]
            + tex_cmd
        )
    elif calkit.check_dep_exists(dep):
        cmd = tex_cmd
    else:
        # Pulled deliberately, since docker run's implicit pull of an
        # image that isn't there can stall rather than report it
        try:
            calkit.docker.ensure_image_available(
                calkit.latex.DEFAULT_LATEX_IMAGE
            )
        except ValueError as e:
            raise_error(str(e))
        # Packages fetched at run time go to the project's cache, which
        # the working directory mount already covers, rather than over
        # the image's own tree, which would hide the distribution entirely
        os.makedirs(calkit.latex.get_texmf_cache_dir(), exist_ok=True)
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{os.getcwd()}:/work",
            "-e",
            f"TEXMFHOME={calkit.latex.CONTAINER_TEXMF_DIR}",
            "-w",
            "/work",
        ]
        # As the user, so a PDF doesn't come back owned by root
        try:
            cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
        except AttributeError:
            # Windows has no UID to map
            pass
        # The container gets its own environment, so anything the command
        # needs has to be handed to it rather than inherited
        for key, value in env_vars.items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [calkit.latex.DEFAULT_LATEX_IMAGE] + tex_cmd
    if verbose:
        typer.echo(f"Running command: {cmd}")
    return cmd


def _run_latexmk(
    cmd: list[str],
    env: dict[str, str] | None,
    log_path: str,
    fdb_path: str,
    environment: str | None,
    verbose: bool,
    quiet: bool = False,
) -> int:
    """Run latexmk, fetching the TeX packages it's missing and retrying.

    Only where what's fetched is kept with the project, i.e., Calkit's
    LaTeX image, run directly or as a Docker environment built on it. A
    system TeX is the user's to manage, and anything installed in another
    container is gone when it exits. Returns latexmk's exit status.

    ``quiet`` hides latexmk's output, for a caller that reports what went
    wrong from the log itself.
    """
    import shlex

    def in_tex(tex_cmd: list[str]) -> list[str]:
        # Where the build runs, so what's installed is what it sees
        return _tex_cmd(
            tex_cmd,
            environment=environment,
            no_check=True,
            verbose=verbose,
            dep="latexmk",
        )

    def can_fetch() -> bool:
        if environment is None:
            return not calkit.check_dep_exists("latexmk")
        envs = calkit.load_calkit_info().get("environments", {})
        if envs.get(environment, {}).get("kind") != "docker":
            return False
        # The image switches to the project's cache when it's there
        os.makedirs(calkit.latex.get_texmf_cache_dir(), exist_ok=True)
        out = subprocess.run(
            in_tex(["printenv", "TEXMFHOME"]), capture_output=True, text=True
        ).stdout.strip()
        return out.endswith("/.calkit/local/texmf")

    fetched: set[str] = set()
    fetchable = None
    while True:
        try:
            subprocess.run(cmd, env=env, check=True, capture_output=quiet)
            return 0
        except subprocess.CalledProcessError as e:
            status = e.returncode
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                log = f.read()
        except OSError:
            return status
        # A file still missing after fetching it is one fetching can't fix
        missing = [
            f
            for f in calkit.latex.find_missing_tex_files(log)
            if f not in fetched
        ]
        if not missing:
            return status
        if fetchable is None:
            fetchable = can_fetch()
        if not fetchable:
            return status
        packages = []
        for name in missing:
            out = subprocess.run(
                in_tex(["tlmgr", "search", "--global", "--file", f"/{name}"]),
                capture_output=True,
                text=True,
            ).stdout
            # Package names end with a colon; the paths under them are
            # indented, and the first one ending in the file is its owner
            owner = None
            for line in out.splitlines():
                if line.endswith(":") and not line.startswith((" ", "\t")):
                    owner = line[:-1]
                elif owner and line.strip().endswith(f"/{name}"):
                    packages.append(owner)
                    break
        packages = list(dict.fromkeys(packages))
        if not packages:
            return status
        typer.echo(
            f"Fetching TeX packages for {', '.join(missing)}: "
            f"{', '.join(packages)}"
        )
        install = in_tex(["tlmgr", "--usermode", "install", *packages])
        if verbose:
            typer.echo(f"Running command: {shlex.join(install)}")
        # A font's install fails at its last step, updating the font map,
        # which user mode can't do in this image, with the files already in
        # place and usable. Whether it worked is the retry's to say.
        if subprocess.run(install, capture_output=not verbose).returncode:
            if verbose:
                warn(f"tlmgr reported an error installing {packages}")
        fetched.update(missing)
        # Otherwise latexmk remembers the failure and won't try again
        if os.path.isfile(fdb_path):
            os.remove(fdb_path)


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
    # latexmk records a failed run in its file database and then refuses
    # to try again, reporting "Nothing to do" and exiting non-zero with no
    # PDF. Running it again is the first thing anyone does after a
    # failure, so the record is cleared when there is no PDF to show for
    # it, which makes a retry a real retry.
    tex_dir = os.path.dirname(tex_file) or "."
    stem = Path(tex_file).stem
    pdf_dir = output_dir if output_dir is not None else tex_dir
    if not os.path.isfile(os.path.join(pdf_dir, stem + ".pdf")):
        fdb_dir = aux_dir if aux_dir is not None else tex_dir
        fdb_fpath = os.path.join(fdb_dir, stem + ".fdb_latexmk")
        if os.path.isfile(fdb_fpath):
            if verbose:
                typer.echo(f"Removing {fdb_fpath} so latexmk will retry")
            os.remove(fdb_fpath)
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
    tex_env_vars = _tex_env_vars(calkit.latex.get_source_date_epoch(tex_file))
    cmd = _tex_cmd(
        latexmk_cmd,
        environment=environment,
        no_check=no_check,
        verbose=verbose,
        dep="latexmk",
        env_vars=tex_env_vars,
    )
    log_dir = aux_dir or output_dir or tex_dir
    if _run_latexmk(
        cmd,
        env=(os.environ | tex_env_vars) if tex_env_vars else None,
        log_path=os.path.join(log_dir, stem + ".log"),
        fdb_path=os.path.join(log_dir, stem + ".fdb_latexmk"),
        environment=environment,
        verbose=verbose,
    ):
        raise_error("latexmk failed")


DIFF_TMP_DIR = calkit.latex.DIFF_TMP_DIR
# A verbatim input named by a macro parameter, e.g., \verbatiminput{#1.wcsum}
# in a \newcommand, which latexdiff dies trying to open. Breaking the line
# after the command reads the same to TeX, but not to latexdiff's pattern.
_VERBATIM_PARAM_RE = re.compile(
    r"(\\(?:verbatiminput\*?|lstinputlisting))"
    r"(?=\s*(?:\[[^\]\n]*\])?\s*\{[^}\n]*#[0-9])"
)
# latexdiff's figure markup makes its markers assignments, which can't
# come before anything that has to start a table row or cell
_ALIGN_MARKERS_RE = re.compile(
    rb"(?:\\DIF(?:add|del)(?:begin|end)(?:FL)?(?:\s|%[^\n]*\n)*)+"
    rb"(?=\\(?:hline|cline|multicolumn|multispan|omit|noalign|caption"
    rb"|toprule|midrule|bottomrule|cmidrule|specialrule|addlinespace|endhead"
    rb"|endfirsthead|endfoot|endlastfoot)(?![A-Za-z]))"
)
# latexdiff marking up the macro an \ifdefined tests for
_IFDEFINED_MARKUP_RE = re.compile(
    rb"\\ifdefined\s*\\DIF(add|del)(FL)?\{(\\[A-Za-z@]+)"
)
# A one-argument macro's definition, up to its body's opening brace
_ONE_ARG_MACRO_DEF_RE = re.compile(
    r"\\(?:(?:re|provide)?newcommand\*?\s*(?:\{\s*\\([A-Za-z@]+)\s*\}"
    r"|\\([A-Za-z@]+))\s*\[1\]|def\s*\\([A-Za-z@]+)#1)\s*(?=\{)"
)
get_diff_path = calkit.latex.get_diff_path
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
    latexmk_rc_path: Annotated[
        str | None,
        typer.Option(
            "--latexmk-rc",
            "-r",
            help=(
                "Path to a latexmkrc file to build the marked-up document with."
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
    latexdiff_args: Annotated[
        list[str],
        typer.Option(
            "--latexdiff-arg",
            help=(
                "Extra argument to pass through to latexdiff, e.g., "
                "'--type=CFONT'. Changed figures are shown old and new by "
                "default; pass '--graphics-markup=new-only' to show only the "
                "new. Repeat the option to pass more "
                "than one."
            ),
        ),
    ] = [],
    inputs: Annotated[
        list[str],
        typer.Option(
            "--input",
            help=(
                "File or directory the document reads. Anything in it "
                "tracked with DVC is fetched as it was at each revision. "
                "Defaults to the inputs detected in the document. Repeat "
                "the option to pass more than one."
            ),
        ),
    ] = [],
    revision_key: Annotated[
        str | None,
        typer.Option(
            "--revision-key",
            hidden=True,
            help=(
                "Set by the pipeline so a diff's stage reruns when either "
                "revision's inputs change. Not used by the command."
            ),
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help=(
                "Rebuild even if nothing the diff depends on has changed "
                "since it was last built."
            ),
        ),
    ] = False,
    keep_tex: Annotated[
        bool,
        typer.Option(
            "--keep-tex",
            help=(
                "Keep the old, new, and diff .tex files beside the diff "
                "PDF for inspection, e.g., "
                ".calkit/latex-diffs/v1/paper/main-old.tex."
            ),
        ),
    ] = False,
    filter_script: Annotated[
        str | None,
        typer.Option(
            "--filter-script",
            help=(
                "Python script to pipe the marked-up document through "
                "before it's built, e.g., to drop changes that don't change "
                "the rendered text. It reads the document on stdin and "
                "writes the result to stdout."
            ),
        ),
    ] = None,
    filter_env: Annotated[
        str | None,
        typer.Option(
            "--filter-env",
            help=(
                "Environment to run the filter script in. Defaults to "
                "Calkit's own Python."
            ),
        ),
    ] = None,
    filter_args: Annotated[
        list[str],
        typer.Option(
            "--filter-arg",
            help=(
                "Argument to pass to the filter script. Repeat the option "
                "to pass more than one."
            ),
        ),
    ] = [],
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

    A revision's DVC-tracked inputs, e.g., figures and tables a pipeline
    generates, are fetched as they were at that revision, so each side of
    the comparison shows its own.
    """

    def stage_path(stage: dict, path: str) -> str:
        """A stage's path in the project's frame rather than its wdir's."""
        return Path(
            os.path.normpath(os.path.join(stage.get("wdir") or "", path))
        ).as_posix()

    def find_latex_stage() -> tuple[str | None, dict | None]:
        """The pipeline stage that builds the document, if any."""
        ck_info = calkit.load_calkit_info()
        stages = (ck_info.get("pipeline") or {}).get("stages") or {}
        target = Path(os.path.normpath(tex_file)).as_posix()
        for name, stage in stages.items():
            if (
                isinstance(stage, dict)
                and stage.get("kind") == "latex"
                and stage_path(stage, stage.get("target_path") or "") == target
            ):
                return name, stage
        return None, None

    def stage_inputs(name: str, stage: dict) -> list[str]:
        """What a stage's diffs fetch at each revision.

        Its dependencies in the compiled pipeline, which include other
        stages' outputs it reads, found there since calkit.yaml only names
        the stages they come from.
        """
        from calkit.models.pipeline import LatexStage

        try:
            dvc_stage = calkit.ryaml.load(Path("dvc.yaml").read_text())[
                "stages"
            ][name]
            deps = [
                dep if isinstance(dep, str) else next(iter(dep))
                for dep in dvc_stage.get("deps") or []
            ]
        except Exception:
            deps = LatexStage.model_validate(stage | {"name": name}).dvc_deps
        skip = {tex_file, latexmk_rc_path}
        return [
            path
            for dep in deps
            if (path := stage_path(stage, dep)) not in skip
            and not path.startswith(".calkit/")
        ]

    def fetch_dvc_inputs(root: str, rev: str, paths: list[str]) -> list[str]:
        """Fetch the DVC-tracked content of ``paths`` at ``rev`` into ``root``.

        Through the project's cache, so only the first comparison against a
        revision downloads anything: reading a revision's files straight
        from a remote leaves nothing behind for the next one.

        Returns each fetched path with its hash, since that content changes
        the PDF without changing the marked-up source.
        """
        from concurrent.futures import ThreadPoolExecutor

        from dvc.exceptions import NotDvcRepoError
        from dvc.fs import DVCFileSystem

        import calkit.dvc

        def reason(e: BaseException) -> str:
            # DVC wraps a remote's own error, e.g., needing to log in, in
            # several layers that each say less
            while e.__cause__ is not None:
                e = e.__cause__
            return str(e)

        fetched: list[str] = []
        targets = list(dict.fromkeys(p.rstrip("/") for p in paths))
        try:
            dvc_repo = calkit.dvc.get_dvc_repo()
        except NotDvcRepoError:
            return fetched
        # The remotes configured now rather than then, since one added or
        # moved since a revision is where its data is
        default_remote = dvc_repo.config["core"].get("remote")
        remotes = (
            {
                "core": {"remote": default_remote},
                "remote": dict(dvc_repo.config.get("remote", {})),
            }
            if default_remote
            else None
        )
        fs = DVCFileSystem(url=".", rev=rev, config=remotes)
        found: list[str] = []
        failed: list[tuple[str, Exception]] = []
        for path in targets:
            try:
                found += list(fs.find(path))
            except FileNotFoundError:
                continue
            except Exception as e:
                failed.append((path, e))
        files = []
        for rpath in dict.fromkeys(found):
            md5 = (fs.info(rpath).get("dvc_info") or {}).get("md5")
            if md5:
                files.append((rpath, md5))
        # Into the project's cache, all at once, then copied from there. Via
        # a temporary directory, so an interrupted download can't leave a
        # truncated file in the cache under the name of its content.
        cache = dvc_repo.cache.local
        missing = [
            (rpath, md5)
            for rpath, md5 in files
            if not os.path.exists(cache.oid_to_path(md5))
        ]
        if missing:
            download_dir = os.path.join(os.path.dirname(root), "download")
            downloads = [
                os.path.join(download_dir, str(n)) for n in range(len(missing))
            ]
            os.makedirs(download_dir, exist_ok=True)

            def fetch_one(rpath: str, dest: str) -> None:
                # What fails here is fetched, or reported, one by one below
                try:
                    fs.get_file(rpath, dest)
                except Exception:
                    pass

            # A remote serves a file at a time, often slowly, so many at once
            with ThreadPoolExecutor(16) as pool:
                list(
                    pool.map(
                        fetch_one, [rpath for rpath, _ in missing], downloads
                    )
                )
            for (_, md5), download in zip(missing, downloads):
                if os.path.isfile(download):
                    cache_path = cache.oid_to_path(md5)
                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                    os.replace(download, cache_path)
            shutil.rmtree(download_dir, ignore_errors=True)
        for path, error in failed:
            # A directory whose listing is in neither the cache nor a
            # reachable remote can't be expanded, but the rest of the
            # comparison can still be built
            warn(
                f"Can't list {path} at {rev[:7]}, so the diff will be "
                f"missing it: {reason(error)}. Its data is in neither the "
                "local cache nor the DVC remote, so it was likely never "
                "pushed; push it from a machine that has it"
            )
        for rpath, md5 in files:
            fetched.append(f"{rpath} {md5}")
            dest = os.path.join(root, rpath)
            if os.path.exists(dest):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                fs.get_file(rpath, dest)
            except Exception as e:
                warn(
                    f"Can't fetch {rpath} at {rev[:7]}, so the diff will be "
                    f"missing it: {reason(e)}"
                )
        return fetched

    def copy_uncached_outputs(
        root: str, rev: str, paths: list[str]
    ) -> list[str]:
        """Copy outputs DVC records but doesn't store from the working tree.

        An output with caching off, e.g., a copy another stage makes, has
        only its hash in ``dvc.lock``, so no revision's checkout can have
        it. The working tree's copy stands in when it's the same content.
        Returns each copied path with its hash.
        """
        try:
            lock = calkit.ryaml.load(repo.git.show(f"{rev}:dvc.lock")) or {}
        except Exception:
            return []
        prefixes = [p.rstrip("/") for p in paths]
        copied: list[str] = []
        for stage in (lock.get("stages") or {}).values():
            for out in stage.get("outs") or []:
                path, md5 = out.get("path"), out.get("md5")
                if not path or not md5 or str(md5).endswith(".dir"):
                    continue
                if not any(
                    path == p or path.startswith(p + "/") for p in prefixes
                ):
                    continue
                dest = os.path.join(root, path)
                if os.path.exists(dest) or not os.path.isfile(path):
                    continue
                if hashlib.md5(Path(path).read_bytes()).hexdigest() != md5:
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(path, dest)
                copied.append(f"{path} {md5}")
        return copied

    def break_verbatim_params(root: str) -> None:
        """Break verbatim inputs named by macro parameters in a checkout.

        Done to the checked-out files directly rather than with latexdiff's
        --filter-script, which hands text to the script and reads it back
        with no encoding, mangling anything outside Latin-1, e.g., a curly
        apostrophe.
        """
        sources = [tex_file] + [
            path
            for path in calkit.latex.detect_inputs(tex_file, wdir=root)
            if Path(path).suffix in calkit.latex._SOURCE_EXTS
        ]
        for source in sources:
            source_path = Path(root, source)
            try:
                text = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            new_text = _VERBATIM_PARAM_RE.sub("\\1%\n", text)
            if new_text != text:
                source_path.write_text(new_text, encoding="utf-8")

    def expand_wrapper_macros(root: str) -> None:
        """Replace each use of a macro wrapping a block with its body.

        latexdiff reads a command's argument as one token, or with
        --append-textcmd as text, and neither survives an argument holding a
        table or a whole \\include: the block shows as deleted and re-added,
        or its table breaks. Expanded, what it wraps is compared like the
        rest of the document. Only one-argument macros used with an argument
        spanning lines are expanded, which inline macros rarely are.
        """

        def group_end(text: str, start: int) -> int | None:
            """Where the brace group opening at ``start`` ends."""
            depth = 0
            i = start
            while i < len(text):
                c = text[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "%":
                    newline = text.find("\n", i)
                    if newline == -1:
                        return None
                    i = newline
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return i + 1
                i += 1
            return None

        def in_comment(text: str, pos: int) -> bool:
            line = text[text.rfind("\n", 0, pos) + 1 : pos]
            return re.search(r"(?<!\\)%", line) is not None

        sources = [tex_file] + [
            path
            for path in calkit.latex.detect_inputs(tex_file, wdir=root)
            if Path(path).suffix in calkit.latex._SOURCE_EXTS
        ]
        texts: dict[Path, str] = {}
        for source in dict.fromkeys(sources):
            try:
                texts[Path(root, source)] = Path(root, source).read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError):
                continue
        bodies: dict[str, str] = {}
        for text in texts.values():
            for match in _ONE_ARG_MACRO_DEF_RE.finditer(text):
                if in_comment(text, match.start()):
                    continue
                end = group_end(text, match.end())
                if end is None:
                    continue
                body = text[match.end() + 1 : end - 1]
                if body.count("#1") == 1 and not re.search(r"#[2-9#]", body):
                    bodies[
                        match.group(1) or match.group(2) or match.group(3)
                    ] = body
        if not bodies:
            return
        use_re = re.compile(
            r"\\("
            + "|".join(map(re.escape, bodies))
            + r")(?![A-Za-z@])\s*(?=\{)"
        )
        expanded: set[str] = set()
        for source_path, text in texts.items():
            new_text = text
            # Again for a wrapper inside another's argument
            for _ in range(5):
                parts = []
                pos = 0
                for match in use_re.finditer(new_text):
                    if match.start() < pos or in_comment(
                        new_text, match.start()
                    ):
                        continue
                    end = group_end(new_text, match.end())
                    if end is None:
                        continue
                    arg = new_text[match.end() + 1 : end - 1]
                    if "\n" not in arg:
                        continue
                    body = bodies[match.group(1)]
                    # A group of its own would be one token to latexdiff
                    if "{#1}" in body:
                        body = body.replace(
                            "{#1}", "\\begingroup " + arg + "\\endgroup "
                        )
                    else:
                        body = body.replace("#1", arg)
                    parts += [new_text[pos : match.start()], body]
                    pos = end
                    expanded.add(match.group(1))
                if not parts:
                    break
                new_text = "".join(parts) + new_text[pos:]
            if new_text != text:
                source_path.write_text(new_text, encoding="utf-8")
        for name in sorted(expanded - expanded_names):
            typer.echo(
                f"Expanding \\{name} so latexdiff can mark up what it wraps"
            )
        expanded_names.update(expanded)

    def copy_working_sources(dest: str) -> None:
        """Copy the working tree's sources, so they can be prepared the way
        a checkout's are without touching the user's files."""
        exts = calkit.latex._SOURCE_EXTS | {".tikz", ".pgf"}
        doc_dir = Path(os.path.dirname(tex_file) or ".")
        found = [
            p.as_posix()
            for p in doc_dir.rglob("*")
            if p.suffix in exts
            and not any(part.startswith(".") for part in p.parts)
            and p.is_file()
        ]
        found += [
            path
            for path in calkit.latex.detect_inputs(tex_file)
            if Path(path).suffix in calkit.latex._SOURCE_EXTS
        ]
        for path in dict.fromkeys([tex_file] + found):
            if not os.path.isfile(path):
                continue
            target = os.path.join(dest, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(path, target)

    def default_inputs(root: str) -> list[str]:
        """What to fetch or note for a side when no inputs were given.

        Detection finds a file by its own name or pointer, but a file in a
        directory DVC tracks as a whole has only the directory's pointer,
        which can't say what's inside, so those directories beside the
        document are included whole. Neither finds another stage's output
        DVC doesn't cache, so the pipeline's inputs for the document are
        added too.
        """
        doc_dir = Path(root, os.path.dirname(tex_file))
        pointed = [
            Path(os.path.relpath(p, root)).as_posix().removesuffix(".dvc")
            for p in sorted(doc_dir.rglob("*.dvc"))
            if p.is_file()
        ]
        detected = calkit.latex.detect_inputs(tex_file, wdir=root)
        return detected + pointed + pipeline_inputs

    def point_changed_figures_at_base(base_root: str, head_root: str) -> None:
        """Make the older side's changed figures refer to its own copies.

        The marked-up document is built beside the newer side, where the
        older side's figure names find the newer figures. Left alone, a
        figure that changed would show as it is now on both sides, and
        latexdiff wouldn't mark it, since its name didn't change.
        """
        import filecmp

        tex_dir = os.path.dirname(tex_file)
        build_dir = os.path.join(head_root, tex_dir)
        graphic_re = re.compile(
            r"(\\includegraphics\*?\s*(?:\[[^\]]*\])*\s*\{)([^}#\\]+)(\})"
        )

        def repoint(match: re.Match[str]) -> str:
            name = match.group(2).strip()
            exts = calkit.latex._GRAPHICS_EXTS
            for candidate in [name] + [name + ext for ext in exts]:
                rel = os.path.normpath(os.path.join(tex_dir, candidate))
                base_path = os.path.join(base_root, rel)
                if not os.path.isfile(base_path):
                    continue
                head_path = os.path.join(head_root, rel)
                if os.path.isfile(head_path) and filecmp.cmp(
                    base_path, head_path, shallow=False
                ):
                    return match.group(0)
                new_name = Path(os.path.relpath(base_path, build_dir))
                return match.group(1) + new_name.as_posix() + match.group(3)
            return match.group(0)

        sources = [tex_file] + [
            path
            for path in calkit.latex.detect_inputs(tex_file, wdir=base_root)
            if Path(path).suffix in calkit.latex._SOURCE_EXTS
        ]
        for source in sources:
            source_path = Path(base_root, source)
            try:
                text = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            new_text = graphic_re.sub(repoint, text)
            if new_text != text:
                source_path.write_text(new_text, encoding="utf-8")

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
    # A document the pipeline builds is diffed the way it's built, with its
    # stage's environment, settings, and inputs, unless told otherwise
    stage_name, stage = find_latex_stage()
    pipeline_inputs: list[str] = []
    if stage is not None:
        if environment is None:
            environment = stage.get("environment")
        if latexmk_rc_path is None and stage.get("latexmkrc_path"):
            latexmk_rc_path = stage_path(stage, stage["latexmkrc_path"])
        latexmk_args = latexmk_args or list(stage.get("latexmk_args") or [])
        latexdiff_args = latexdiff_args or list(
            stage.get("latexdiff_args") or []
        )
        pipeline_inputs = stage_inputs(str(stage_name), stage)
        diff_filter = stage.get("diff_filter")
        if filter_script is None and isinstance(diff_filter, dict):
            filter_script = stage_path(stage, diff_filter["script_path"])
            filter_env = diff_filter.get("environment")
            filter_args = list(diff_filter.get("args") or [])
    filter_cmd: list[str] | None = None
    if filter_script is not None:
        # Calkit's own interpreter unless told otherwise, since there may be
        # no python on the PATH, or not one with what the script needs
        if filter_env is None:
            filter_cmd = [sys.executable, filter_script]
        else:
            filter_cmd = (
                ["calkit", "xenv", "--name", filter_env]
                + (["--no-check"] if no_check else [])
                + ["--", "python", filter_script]
            )
        filter_cmd += filter_args
    if output is None:
        output = get_diff_path(
            tex_file,
            from_ref=from_label,
            to_ref=to_ref,
            output_dir=output_dir,
        )
    checkouts: dict[str, str] = {}
    shas: dict[str, str] = {}
    expanded_names: set[str] = set()
    # Per run, so diffs run at the same time, e.g., from the editor while
    # the pipeline runs, don't check out over each other
    run_dir = os.path.join(DIFF_TMP_DIR, str(os.getpid()))
    # A run that was killed leaves its checkouts behind
    import psutil

    if os.path.isdir(DIFF_TMP_DIR):
        for name in os.listdir(DIFF_TMP_DIR):
            if name.isdigit() and not psutil.pid_exists(int(name)):
                for side in ("base", "head"):
                    _remove_worktree(os.path.join(DIFF_TMP_DIR, name, side))
                shutil.rmtree(
                    os.path.join(DIFF_TMP_DIR, name), ignore_errors=True
                )
        subprocess.call(
            ["git", "worktree", "prune"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    working_copy = os.path.join(run_dir, "working")
    try:
        for name, ref in [("base", from_ref), ("head", to_ref)]:
            if ref is None:
                continue
            sha = calkit.git.resolve_ref(repo, ref)
            if sha is None:
                raise_error(f"Git ref '{ref}' was not found")
            shas[name] = sha
            # A worktree, not a temp directory: a document is rarely one
            # file, and \input needs the rest of them as they were then
            path = os.path.join(run_dir, name)
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
        # The working tree already has its DVC-tracked files, if pulled
        head_root = checkouts.get("head", ".")
        context: list[str] = []
        for name, root in checkouts.items():
            paths = inputs or default_inputs(root)
            context += fetch_dvc_inputs(root, rev=shas[name], paths=paths)
            context += copy_uncached_outputs(root, rev=shas[name], paths=paths)
        if "head" not in checkouts:
            # The working tree has no revision to name its files by, so
            # note what's there instead
            for path in inputs or default_inputs("."):
                if os.path.isfile(path):
                    files = [Path(path)]
                else:
                    files = sorted(
                        p for p in Path(path).rglob("*") if p.is_file()
                    )
                for file_path in files:
                    stat = file_path.stat()
                    context.append(
                        f"{file_path.as_posix()} {stat.st_size} "
                        f"{stat.st_mtime_ns}"
                    )
        prepared = list(checkouts.values())
        if "head" not in checkouts:
            shutil.rmtree(working_copy, ignore_errors=True)
            copy_working_sources(working_copy)
            sides["head"] = os.path.join(working_copy, tex_file)
            prepared.append(working_copy)
        for root in prepared:
            break_verbatim_params(root)
            expand_wrapper_macros(root)
        point_changed_figures_at_base(checkouts["base"], head_root)
        _build_diff(
            base_tex_fpath=sides["base"],
            head_tex_fpath=sides["head"],
            tex_file_fpath=tex_file,
            head_root=head_root,
            output=output,
            environment=environment,
            latexmk_rc_path=latexmk_rc_path,
            latexmk_args=latexmk_args,
            latexdiff_args=latexdiff_args,
            context=context,
            no_check=no_check,
            keep_tex=keep_tex,
            filter_cmd=filter_cmd,
            force=force,
            verbose=verbose,
        )
    finally:
        for path in checkouts.values():
            _remove_worktree(path)
        shutil.rmtree(run_dir, ignore_errors=True)


def _marked_up_digest(marked_up: bytes, context: list[str] = []) -> str:
    """Hash a marked-up document by what actually determines the PDF.

    latexdiff writes the two inputs' paths and modification times into a
    header comment, and the older side is a fresh checkout every time, so
    hashing the file as-is would say "changed" on every run when nothing
    had. Those lines are comments; the PDF doesn't depend on them.

    ``context`` is anything else the PDF depends on, e.g., the hashes of
    DVC-tracked figures and the options it's built with.
    """
    kept = [
        line
        for line in marked_up.splitlines(keepends=True)
        if not line.startswith((b"%DIF DEL ", b"%DIF ADD "))
    ]
    kept += [f"{item}\n".encode() for item in context]
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
    base_tex_fpath: str,
    head_tex_fpath: str,
    tex_file_fpath: str,
    head_root: str,
    output: str,
    environment: str | None,
    latexmk_rc_path: str | None,
    latexmk_args: list[str],
    latexdiff_args: list[str],
    context: list[str],
    no_check: bool,
    keep_tex: bool,
    force: bool,
    verbose: bool,
    filter_cmd: list[str] | None = None,
) -> None:
    """Mark up one document against another and build the result.

    base_tex_fpath is the older revision's document, head_tex_fpath the
    newer revision's, and tex_file_fpath the document as named on the
    command line. head_root is where the newer side lives: a checkout,
    or the working tree, beside which the marked-up document is built
    so its relative inputs resolve.
    """
    # Built beside the newer side, so \graphicspath, \bibliography, and
    # relative \includegraphics resolve the way they do for the real thing,
    # against that revision's own files
    tex_dir = os.path.dirname(tex_file_fpath) or "."
    build_dir = os.path.normpath(os.path.join(head_root, tex_dir))
    stem = Path(tex_file_fpath).stem
    job = f"{stem}-diff"
    aux_name = calkit.latex.DIFF_AUX_DIRNAME
    # Beside the working tree's document, named for this run, so neither a
    # file of the user's nor another diff built there at the same time is
    # overwritten
    if os.path.abspath(head_root) == os.path.abspath("."):
        job += f"-{os.getpid()}"
        aux_name += f"-{os.getpid()}"
    diff_tex_fpath = os.path.join(build_dir, f"{job}.tex")
    # Where --keep-tex leaves its copies: beside the diff PDF, since a
    # checkout is removed afterwards. The old and new files are what
    # latexdiff saw, after verbatim fixes and figure repointing, so a
    # --flatten or macro expansion failure can be inspected.
    kept_stem = os.path.splitext(output)[0]
    kept_diff_fpath = f"{kept_stem}-diff.tex"
    kept_old_fpath = f"{kept_stem}-old.tex"
    kept_new_fpath = f"{kept_stem}-new.tex"
    marked_up: bytes | None = None
    aux_dir = os.path.join(build_dir, aux_name)
    try:
        # The newer side's copy, which is what the document was built with
        # at that revision
        rc_path = None
        rc_hash = None
        if latexmk_rc_path is not None:
            rc_path = os.path.join(head_root, latexmk_rc_path)
            if not os.path.isfile(rc_path):
                rc_path = latexmk_rc_path
            rc_path = Path(os.path.normpath(rc_path)).as_posix()
            if os.path.isfile(rc_path):
                rc_hash = hashlib.sha256(
                    Path(rc_path).read_bytes()
                ).hexdigest()
        # Paths into this run's checkouts name the run, which says nothing
        # about the PDF
        run_prefix = Path(DIFF_TMP_DIR, str(os.getpid())).as_posix()
        stable_prefix = Path(DIFF_TMP_DIR, "run").as_posix()
        build_context = [
            item.replace(run_prefix, stable_prefix)
            for item in context
            + [f"latexmkrc {rc_path} {rc_hash}"]
            + latexmk_args
        ]
        # Everything the diff is made from, checked before latexdiff, which
        # takes a minute or more on a long document, so asking for one
        # that's already built returns straight away
        inputs = hashlib.sha256(calkit.__version__.encode())
        for item in build_context + latexdiff_args + (filter_cmd or []):
            inputs.update(f"{item}\n".encode())
            if item != sys.executable and os.path.isfile(item):
                inputs.update(Path(item).read_bytes())
        for n, side in enumerate((base_tex_fpath, head_tex_fpath)):
            side_root = side[: -len(tex_file_fpath)] or "."
            sources = [tex_file_fpath] + [
                path
                for path in calkit.latex.detect_inputs(
                    tex_file_fpath, wdir=side_root
                )
                if Path(path).suffix in calkit.latex._SOURCE_EXTS
            ]
            for source in sources:
                try:
                    text = Path(side_root, source).read_bytes()
                except OSError:
                    continue
                text = text.replace(
                    run_prefix.encode(), stable_prefix.encode()
                )
                inputs.update(f"{n} {source}\n".encode() + text)
        inputs_digest = inputs.hexdigest()
        state_path = calkit.latex.diff_state_path(output)
        inputs_state_path = f"{state_path}.inputs"
        if (
            not force
            and os.path.isfile(output)
            and _read(inputs_state_path) == inputs_digest
        ):
            typer.echo(f"{output} is up to date")
            return
        # --flatten pulls \input and \include files into one document on
        # each side, so a multi-file paper compares as a whole
        latexdiff_cmd = ["latexdiff", "--flatten", "--encoding=utf8"]
        # Each side has its own revision's figures, so a changed one is
        # shown both ways rather than only as it is now, unless the user
        # chose otherwise
        if not any(a.startswith("--graphics-markup") for a in latexdiff_args):
            latexdiff_cmd.append("--graphics-markup=both")
        # User pass-through args come last so they can override Calkit's
        # defaults
        latexdiff_cmd += latexdiff_args
        cmd = _tex_cmd(
            latexdiff_cmd + [base_tex_fpath, head_tex_fpath],
            environment=environment,
            no_check=no_check,
            verbose=verbose,
            dep="latexdiff",
        )
        typer.echo("Marking up the document with latexdiff")
        try:
            # No stdin, so an environment's container isn't given a TTY,
            # which would merge latexdiff's warnings into the document
            # Its warnings are mostly about markup it chose not to make, so
            # they're only shown when asked for or when it fails
            marked_up = subprocess.check_output(
                cmd,
                stdin=subprocess.DEVNULL,
                stderr=None if verbose else subprocess.PIPE,
            )
        except FileNotFoundError:
            raise_error(
                "latexdiff was not found; it ships with TeX Live, so a "
                "minimal install may not have it"
            )
        except subprocess.CalledProcessError as e:
            if e.stderr:
                typer.echo(e.stderr.decode(errors="replace"), err=True)
            raise_error(f"latexdiff failed with exit status {e.returncode}")
        # They only switch how figures are marked, so dropping them is safe
        marked_up = _ALIGN_MARKERS_RE.sub(b"", marked_up)
        # latexdiff takes the macro \ifdefined tests for as text, which
        # makes the test always pass
        marked_up = _IFDEFINED_MARKUP_RE.sub(
            rb"\\ifdefined\3\\DIF\1\2{", marked_up
        )
        if filter_cmd is not None:
            typer.echo("Filtering the marked-up document")
            try:
                marked_up = subprocess.run(
                    filter_cmd,
                    input=marked_up,
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout
            except subprocess.CalledProcessError as e:
                raise_error(
                    f"Diff filter failed with exit status {e.returncode}"
                )
        # The PDF is a function of this marked-up source and how it's built,
        # so if neither has changed there's nothing to build. Worth checking
        # because the common case produces nothing at all: on the default
        # branch the merge base is usually HEAD, so the comparison is empty,
        # and latexmk is the expensive half of this.
        digest = _marked_up_digest(
            marked_up.replace(run_prefix.encode(), stable_prefix.encode()),
            context=build_context,
        )
        if (
            not force
            and os.path.isfile(output)
            and _read(state_path) == digest
        ):
            Path(inputs_state_path).write_text(inputs_digest)
            typer.echo(f"{output} is up to date")
            return
        Path(diff_tex_fpath).write_bytes(marked_up)
        # From scratch, since one a failed build left beside the working
        # tree's document can be corrupt, and every build is of a new
        # document anyway
        shutil.rmtree(aux_dir, ignore_errors=True)
        os.makedirs(aux_dir)
        rel_aux = aux_name
        latexmk_cmd = ["latexmk"]
        # First, since latexmk reads an rc file where it appears, so the
        # directories below override any the rc file sets
        if rc_path is not None:
            latexmk_cmd += ["-r", rc_path]
        # Through errors, since a diff that's mostly right is more use to
        # a reader than none, and what went wrong is reported below
        latexmk_cmd += [
            "-pdf",
            "-cd",
            "-f",
            "-interaction=nonstopmode",
            f"-auxdir={rel_aux}",
            f"-outdir={rel_aux}",
        ]
        if not verbose:
            latexmk_cmd.append("-silent")
        # User pass-through args come last so they can override Calkit's
        # defaults
        latexmk_cmd += latexmk_args
        latexmk_cmd.append(diff_tex_fpath)
        tex_env_vars = _tex_env_vars(
            calkit.latex.get_source_date_epoch(tex_file_fpath)
        )
        cmd = _tex_cmd(
            latexmk_cmd,
            environment=environment,
            no_check=no_check,
            verbose=verbose,
            dep="latexmk",
            env_vars=tex_env_vars,
        )
        typer.echo("Building the marked-up document")
        built = os.path.join(aux_dir, f"{job}.pdf")
        try:
            status = _run_latexmk(
                cmd,
                env=(os.environ | tex_env_vars) if tex_env_vars else None,
                log_path=os.path.join(aux_dir, f"{job}.log"),
                fdb_path=os.path.join(aux_dir, f"{job}.fdb_latexmk"),
                environment=environment,
                verbose=verbose,
                # The log's errors are shown if it fails, and a document
                # with glossaries and a bibliography says a lot otherwise
                quiet=not verbose,
            )
            if status:
                raise subprocess.CalledProcessError(status, cmd)
        except subprocess.CalledProcessError as e:
            # -silent hides why, so show the errors LaTeX logged
            log_path = Path(aux_dir, f"{job}.log")
            try:
                log_lines = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                log_lines = []
            shown: list[str] = []
            for i, line in enumerate(log_lines):
                if line.startswith("!"):
                    shown += log_lines[i : i + 3]
            excerpt = shown[:60] or log_lines[-20:]
            if excerpt:
                typer.echo(f"From {log_path.as_posix()}:", err=True)
                typer.echo("\n".join(excerpt), err=True)
            inspect = "" if keep_tex else "; rerun with --keep-tex to inspect"
            if not os.path.isfile(built):
                raise_error(
                    "latexmk failed on the diff document with exit code "
                    f"{e.returncode}{inspect}"
                )
            # An error the document itself has when built from scratch,
            # e.g., one a kept aux directory hides, should be fixed there
            warn(
                "The diff PDF was built despite the LaTeX errors above, so "
                "parts of it may be wrong. Check whether the document "
                "itself builds cleanly from an empty aux directory"
                f"{inspect}",
                err=True,
            )
        if not os.path.isfile(built):
            raise_error("latexmk did not produce a PDF")
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        shutil.move(built, output)
        # A checkout is removed afterwards, but the working tree's document
        # directory is the user's, so nothing is left behind in it
        if os.path.abspath(head_root) == os.path.abspath("."):
            shutil.rmtree(aux_dir, ignore_errors=True)
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        Path(state_path).write_text(digest)
        Path(inputs_state_path).write_text(inputs_digest)
        typer.echo(f"Wrote {output}")
    finally:
        if keep_tex:
            os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
            if marked_up is not None:
                Path(kept_diff_fpath).write_bytes(marked_up)
            for src, kept_fpath in (
                (base_tex_fpath, kept_old_fpath),
                (head_tex_fpath, kept_new_fpath),
            ):
                if os.path.isfile(src):
                    shutil.copy(src, kept_fpath)
            for kept_fpath in (
                kept_old_fpath,
                kept_new_fpath,
                kept_diff_fpath,
            ):
                if os.path.isfile(kept_fpath):
                    typer.echo(f"Kept {kept_fpath} for inspection")
        if os.path.isfile(diff_tex_fpath):
            os.remove(diff_tex_fpath)


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
    engine: Annotated[
        str | None,
        typer.Option(
            "--engine",
            help=(
                "What makes the Word copy: 'word', which imports the "
                "compiled PDF so the copy looks like it, or 'libreoffice', "
                "which converts the source with TeX4ht's make4ht and then "
                "LibreOffice. Defaults to Word where it's installed."
            ),
        ),
    ] = None,
    log: Annotated[
        bool,
        typer.Option(
            "--log",
            "-l",
            help=(
                "Also keep the export record in the project, under "
                ".calkit/latex/docx-exports, rather than only on this "
                "machine."
            ),
        ),
    ] = False,
) -> None:
    """Export a Word copy of a LaTeX document for review.

    Uses Word's own PDF import where Word is installed, so the copy looks
    like the PDF, else TeX4ht and LibreOffice. Then records inside the file
    which source line each paragraph came from and the text as sent, so
    ``merge-docx`` can bring edits and comments back.
    """
    import datetime
    import sys
    import uuid
    from typing import Any

    import calkit.docx
    import calkit.git
    import calkit.pipeline
    from calkit.models.docx import LatexDocxExport
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
    if engine is None:
        engine = "word" if calkit.docx.word_installed() else "libreoffice"
    if engine == "word":
        typer.echo("Converting the PDF with Word")
        try:
            calkit.docx.pdf_to_docx(pdf_path, output)
        except RuntimeError as e:
            raise_error(str(e))
    elif engine == "libreoffice":
        import shlex

        if calkit.docx.find_soffice() is None:
            raise_error(
                "Converting without Word requires LibreOffice; install it "
                "from https://www.libreoffice.org"
            )
        typer.echo("Converting the source with TeX4ht and LibreOffice")
        # TeX4ht runs beside the source, since its ODT misses equations
        # when built elsewhere, under a job name of its own so it leaves
        # the PDF build's files alone. What it adds there is cleared up.
        # The result goes in the project, where a containerized TeX can
        # write it.
        src_dir = os.path.dirname(source) or "."
        job = Path(source).stem + "-calkit-docx"
        build = os.path.join(calkit.latex.DOCX_BUILD_DIR, Path(source).stem)
        shutil.rmtree(build, ignore_errors=True)
        os.makedirs(build)
        # The PDF build's bibliography, since TeX4ht doesn't run BibTeX
        bbl = Path(source).with_suffix(".bbl")
        if bbl.is_file():
            shutil.copy(bbl, os.path.join(src_dir, job + ".bbl"))
        m4h = [
            "make4ht",
            "--format",
            "odt",
            "--jobname",
            job,
            "--output-dir",
            os.path.relpath(build, src_dir),
            os.path.basename(source),
            "mathml",
        ]
        environment = (
            stages[stage_name].get("environment") if stage_name else None
        )

        def listing() -> set[str]:
            # Files under the source's directory, not under hidden ones
            out: set[str] = set()
            for d, dirs, files in os.walk(src_dir):
                dirs[:] = [x for x in dirs if not x.startswith(".")]
                out.update(
                    os.path.relpath(os.path.join(d, f), src_dir) for f in files
                )
            return out

        existing = listing() - {job + ".bbl"}
        # TeX can loop forever, e.g., older TeX4ht on a cases environment,
        # so a run gets a time limit, and loses its LaTeX child with it
        import time

        limit = 600
        timed_out = False
        try:
            if environment is None and calkit.check_dep_exists("make4ht"):
                import signal

                proc = subprocess.Popen(
                    m4h,
                    cwd=src_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=sys.platform != "win32",
                )
                try:
                    out, _ = proc.communicate(timeout=limit)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                            capture_output=True,
                        )
                    else:
                        os.killpg(proc.pid, signal.SIGKILL)
                    out, _ = proc.communicate()
            else:
                # Inside the environment, e.g., a container, which stops
                # with everything in it when the shell exits
                run = shlex.join(m4h)
                cd = (
                    f"cd {shlex.quote(src_dir)} && if command -v timeout "
                    f">/dev/null; then timeout {limit} {run}; else {run}; fi"
                )
                started = time.monotonic()
                res = subprocess.run(
                    _tex_cmd(
                        ["sh", "-c", cd],
                        environment=environment,
                        no_check=True,
                        verbose=False,
                        dep="make4ht",
                    ),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                # By the time, since the environment may not pass on the
                # timeout's exit code
                out = res.stdout
                timed_out = bool(res.returncode) and (
                    time.monotonic() - started >= limit
                )
            Path(build, "make4ht.log").write_bytes(out)
        finally:
            # TeX's log is kept with the build, for when something's wrong
            tex_log = os.path.join(src_dir, job + ".log")
            if os.path.isfile(tex_log):
                shutil.move(tex_log, build)
            # It also writes figures converted to images beside them, named
            # after them
            for leftover in listing() - existing:
                name = os.path.basename(leftover)
                if name.startswith(job) or re.search(
                    r"-\.(png|svg|jpe?g)(\.4og)?$", name
                ):
                    os.remove(os.path.join(src_dir, leftover))
        odt = os.path.join(build, job + ".odt")
        has_text = False
        if os.path.isfile(odt):
            import zipfile

            with zipfile.ZipFile(odt) as z:
                content = z.read("content.xml")
                has_text = b"<text:p" in content or b"<text:h" in content
        if timed_out:
            raise_error(
                f"TeX4ht didn't finish converting the source in {limit} "
                f"seconds; see the logs in {build}. An older TeX Live's "
                "TeX4ht can loop on some math, e.g., cases."
            )
        if not has_text:
            raise_error(
                "TeX4ht could not convert the source; see the logs in "
                f"{build}. Its make4ht comes with TeX Live's tex4ht package."
            )
        try:
            calkit.docx.odt_to_docx(odt, output)
        except RuntimeError as e:
            raise_error(f"{e}\nTeX4ht's logs are in {build}")
    else:
        raise_error("--engine must be 'word' or 'libreoffice'")
    doc = calkit.docx.Document(output)
    lines = calkit.latex.flatten(source)
    blks = calkit.latex.blocks(lines)
    paras = doc.paragraphs
    matched = calkit.latex.align([p.text for p in paras], blks)
    # Bookmark each anchored paragraph; a block rendering as several
    # paragraphs gets numbered suffixes
    original: dict[str, str] = {}
    para_for_block: dict[int, Any] = {}
    seen: dict[str, int] = {}
    for i, (para, blk) in enumerate(zip(paras, matched)):
        if blk is None or para.element is None:
            continue
        name = calkit.latex.make_bookmark_name(blk.path, blk.lineno)
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        doc.add_bookmark(para.element, name, 9000 + i)
        original[name] = para.text
        para_for_block.setdefault(id(blk), para.element)
    # Display math goes in as Word equations converted from the source,
    # replacing what Word's PDF import or TeX4ht made of it
    equations: dict[str, str] = {}
    left_as_imported = 0
    has_display = any(b.display for b in blks)
    # Word's PDF import leaves inline math as text and pictures, which
    # TeX4ht doesn't, so only then does it need converting too
    has_inline = engine == "word" and any(b.inline_math for b in blks)
    inline_count = 0
    if (has_display or has_inline) and calkit.docx.find_pandoc() is None:
        import calkit.install

        typer.echo("Pandoc converts equations from the source to Word's")
        calkit.install.prompt_and_install(
            "pandoc", interactive=sys.stdin.isatty()
        )
    if (has_display or has_inline) and calkit.docx.find_pandoc() is None:
        warn(
            "Pandoc isn't installed, so equations are as converted "
            "with the document; run 'calkit install pandoc' to fix that"
        )
    elif has_display or has_inline:
        from xml.etree import ElementTree as ET

        eq_num = r"\(([A-Z]?\.?\d+(?:\.\d+)*[a-z]?)\)"
        first: dict[int, int] = {}
        last: dict[int, int] = {}
        for i, blk in enumerate(matched):
            if blk is not None:
                first.setdefault(id(blk), i)
                last[id(blk)] = i
        # Displays grouped by the anchored prose paragraphs around them,
        # only where nothing but displays sits between those in the source,
        # so no unanchored prose is taken for equation fragments
        groups: dict[tuple[int, int], list[calkit.latex.Block]] = {}
        for j, blk in enumerate(blks):
            if not blk.display:
                continue
            jb = next(
                (k for k in range(j - 1, -1, -1) if id(blks[k]) in last), None
            )
            # The next prose after, skipping figures and tables, which can
            # float in between
            ja = next(
                (
                    k
                    for k in range(j + 1, len(blks))
                    if not blks[k].floating
                    and jb is not None
                    and first.get(id(blks[k]), -1) > last[id(blks[jb])]
                ),
                None,
            )
            if (
                jb is None
                or ja is None
                or not all(b.display or b.floating for b in blks[jb + 1 : ja])
            ):
                left_as_imported += 1
                continue
            key = (last[id(blks[jb])], first[id(blks[ja])])
            groups.setdefault(key, []).append(blk)
        # What goes: what the gap holds that's too short or small to be
        # anything but equation fragments, by the body element it's in.
        # Word lays some displays out in tables of its own, which go too
        # if all else they hold is the prose on either side, moved out.
        emu_limit = int(1.5 * 914400)
        w_body = doc.doc.find(calkit.docx._tag(calkit.docx.W, "body"))
        assert w_body is not None
        w_p = calkit.docx._tag(calkit.docx.W, "p")
        w_tbl = calkit.docx._tag(calkit.docx.W, "tbl")

        def text_of(el: Any) -> str:
            return "".join(
                t.text or ""
                for t in el.iter(calkit.docx._tag(calkit.docx.W, "t"))
            )

        anchored = {p.element for p, b in zip(paras, matched) if b is not None}

        def fragment(el: Any, context: str) -> bool:
            # Never prose: anything anchored to the source, e.g., a caption
            # that floated in, or reading like the prose around it, e.g.,
            # the rest of a paragraph broken across a column. Equation
            # fragments have few words, e.g., "Q(σprodβprod)νprod".
            text = text_of(el)
            words = set(re.findall(r"[a-zA-Z]{3,}", text.lower()))
            # A single shared word is often a symbol, e.g., "RPFR =, (2)"
            # after prose defining RPFR, and a number ends a display
            prose_like = (
                len(words) >= 2
                and calkit.latex.similarity(text, context) >= 0.5
                and not re.search(eq_num + r"\s*$", text)
            )
            if el in anchored or len(words) > 3 or prose_like:
                return False
            tall = any(
                int(e.get("cy", "0")) > emu_limit
                for e in el.iter(
                    "{http://schemas.openxmlformats.org/drawingml/2006/"
                    "wordprocessingDrawing}extent"
                )
            )
            return not tall

        def unit_of(el: Any) -> Any:
            while doc._parents.get(el) is not w_body:
                el = doc._parents[el]
            return el

        # Paragraphs in text boxes aren't listed, e.g., a drawn fraction bar
        listed = {p.element for p in paras}
        claimed: set[Any] = set()
        plans = []
        for (before, after), group in groups.items():
            ends = {paras[before].element, paras[after].element}
            context = " ".join(
                b.text for b in (matched[before], matched[after]) if b
            )
            # Everything in the body from the one anchor to the other,
            # since a paragraph of only math or a picture isn't listed
            children = list(w_body)
            lo = children.index(unit_of(paras[before].element))
            hi = children.index(unit_of(paras[after].element))
            gap: list[Any] = []
            for unit in children[lo : hi + 1]:
                if (
                    unit in ends
                    or unit in claimed
                    or unit.tag
                    not in (
                        w_p,
                        w_tbl,
                    )
                ):
                    continue
                held = [
                    q
                    for q in unit.iter(w_p)
                    if q not in ends and (q in listed or unit.tag == w_p)
                ]
                if held and all(fragment(q, context) for q in held):
                    gap.append(unit)
            claimed.update(gap)
            if not gap:
                left_as_imported += len(group)
                continue
            numbers = re.findall(
                eq_num,
                " ".join(
                    text_of(q)
                    for u in gap
                    for q in u.iter(w_p)
                    if q not in ends
                ),
            )
            # Word sometimes runs the last number into the next paragraph
            lead = re.match(r"\s*" + eq_num + r"\s*", paras[after].text)
            if lead is not None:
                numbers.append(lead.group(1))
            plans.append(
                (group, gap, numbers, lead, paras[before], paras[after])
            )
        pieces = [
            (blk, k, tex, numbered)
            for group, *_ in plans
            for blk in group
            for k, (tex, numbered) in enumerate(blk.rows)
        ]
        preamble = "\n".join(
            ln.text
            for ln in lines
            if re.match(
                r"\s*\\(newcommand|renewcommand|providecommand|"
                r"DeclareMathOperator|def)\b",
                ln.text,
            )
        )
        maths = calkit.docx.latex_to_omml([p[2] for p in pieces], preamble)
        converted = dict(zip([(id(p[0]), p[1]) for p in pieces], maths))
        bid = 100000
        last_number: str | None = None
        for group, gap, numbers, lead, before_para, after_para in plans:
            if any(
                converted.get((id(blk), k)) is None
                for blk in group
                for k in range(len(blk.rows))
            ):
                left_as_imported += len(group)
                continue
            rows: list[tuple[Any, str | None, str]] = []
            for blk in group:
                name = calkit.latex.make_bookmark_name(blk.path, blk.lineno)
                for k, (tex, numbered) in enumerate(blk.rows):
                    number = numbers.pop(0) if numbered and numbers else None
                    # TeX4ht doesn't write every number out as text, so a
                    # missing one follows on from the one before
                    prev = re.fullmatch(r"(.*?)(\d+)", last_number or "")
                    if numbered and number is None and prev is not None:
                        number = prev.group(1) + str(int(prev.group(2)) + 1)
                    last_number = number or last_number
                    rows.append(
                        (
                            converted[(id(blk), k)],
                            number,
                            name if k == 0 else f"{name}_r{k + 1}",
                        )
                    )
            # Prose inside a table of Word's that's going moves out of it
            for para, unit, end in (
                (before_para, gap[0], False),
                (after_para, gap[-1], True),
            ):
                if para.element is not None and para.element in unit.iter(w_p):
                    doc.move_out(para.element, unit, after=end)
            doc.insert_equations(gap[0], rows, bid)
            bid += len(rows)
            for el in gap:
                doc.remove(el)
            if lead is not None and after_para.element is not None:
                doc.trim_start(after_para.element, lead.end())
            for math, _, name in rows:
                equations[name] = ET.tostring(math, encoding="unicode")
        # Inline math: in each anchored paragraph, what's between the words
        # of prose on either side of it in the source, which may be text,
        # pictures or both, goes in as an equation

        def tokens(prose: str) -> list[str]:
            # Numbers count, e.g., a table cell "0.05" after the math
            return re.findall(r"[A-Za-z0-9]+", prose)

        def find_start(text: str, cursor: int, before: str) -> int | None:
            start = cursor
            bw = tokens(before)[-2:]
            tail = before
            if bw:
                m = re.compile(
                    r"(?<![A-Za-z0-9])"
                    + r"[^A-Za-z0-9]+".join(map(re.escape, bw))
                    + r"(?![A-Za-z0-9])"
                ).search(text, cursor)
                if m is None:
                    return None
                start = m.end()
                tail = before[before.rfind(bw[-1]) + len(bw[-1]) :]
            # Past the prose's own punctuation, e.g., "(" before the math
            for ch in tail.replace(" ", ""):
                while start < len(text) and text[start].isspace():
                    start += 1
                if text[start : start + 1] != ch:
                    break
                start += 1
            while start < len(text) and text[start].isspace():
                start += 1
            return start

        def find_end(text: str, start: int, after: str) -> int | None:
            aw = tokens(after)[:2]
            head = (after[: after.find(aw[0])] if aw else after).replace(
                " ", ""
            )
            end = len(text)
            if aw:
                m = re.compile(
                    r"(?<![A-Za-z0-9])"
                    + r"[^A-Za-z0-9]+".join(map(re.escape, aw))
                    + r"(?![A-Za-z0-9])"
                ).search(text, start)
                if m is None:
                    return None
                end = m.start()
            # Back before the prose's punctuation, e.g., ")" after the math
            for ch in reversed(head):
                while end > start and text[end - 1].isspace():
                    end -= 1
                if text[end - 1 : end] != ch:
                    break
                end -= 1
            while end > start and text[end - 1].isspace():
                end -= 1
            return end

        def mathlike(region: str, tex: str) -> bool:
            # Math as Word renders it has no prose words in it
            words = re.findall(r"[A-Za-z]{4,}", region)
            return bool(region.strip()) and all(
                w.lower() in tex.lower() for w in words
            )

        # Each as (paragraph, start, end, LaTeX), and for math Word broke
        # across paragraphs, the rest in the next one as (paragraph, 0,
        # end, None)
        inline: list[tuple[Any, int, int, str | None]] = []
        if has_inline:
            by_block: dict[int, list[Any]] = {}
            for p, b in zip(paras, matched):
                if b is not None and p.element is not None:
                    by_block.setdefault(id(b), []).append(p.element)
            for b in blks:
                els = by_block.get(id(b), [])
                texts = [doc.linear_text(el) for el in els]
                pi, cursor = 0, 0
                for pre, tex, post in b.inline_math if els else []:
                    # In the paragraph where the last one was, or a later
                    # one when the block continues past a page or float
                    for k in range(pi, len(els)):
                        s0 = find_start(
                            texts[k], cursor if k == pi else 0, pre
                        )
                        if s0 is None:
                            continue
                        e0 = find_end(texts[k], s0, post)
                        if e0 is not None and mathlike(texts[k][s0:e0], tex):
                            inline.append((els[k], s0, e0, tex))
                            pi, cursor = k, e0
                            break
                        e1 = (
                            find_end(texts[k + 1], 0, post)
                            if e0 is None and k + 1 < len(els)
                            else None
                        )
                        if (
                            e1 is not None
                            and mathlike(texts[k][s0:], tex)
                            and mathlike(texts[k + 1][:e1], tex)
                        ):
                            inline.append((els[k], s0, len(texts[k]), tex))
                            inline.append((els[k + 1], 0, e1, None))
                            pi, cursor = k + 1, e1
                            break
            inline_maths = iter(
                calkit.docx.latex_to_omml(
                    [f"${t}$" for *_, t in inline if t is not None], preamble
                )
            )
            inline_omml = [
                next(inline_maths) if t is not None else None
                for *_, t in inline
            ]
            # From the end of each paragraph, so earlier offsets still hold
            order = sorted(
                range(len(inline)),
                key=lambda i: (id(inline[i][0]), -inline[i][1]),
            )
            for i in order:
                el, s0, e0, itex = inline[i]
                math = inline_omml[i]
                if itex is not None and math is None:
                    continue
                if doc.replace_range(el, s0, e0, math) and itex is not None:
                    inline_count += 1
            # A paragraph Word broke inside the math is whole again, under
            # the first one's bookmark
            for i in range(1, len(inline)):
                first_el, second_el = inline[i - 1][0], inline[i][0]
                if (
                    inline[i][3] is not None
                    or second_el.find(
                        f"{calkit.docx._tag(calkit.docx.W, 'pPr')}/"
                        f"{calkit.docx._tag(calkit.docx.W, 'sectPr')}"
                    )
                    is not None
                ):
                    continue
                skip = {
                    calkit.docx._tag(calkit.docx.W, t)
                    for t in ("pPr", "bookmarkStart", "bookmarkEnd")
                }
                for child in list(second_el):
                    if child.tag not in skip:
                        second_el.remove(child)
                        first_el.append(child)
                doc.remove(second_el)
        doc.prune_media()
        # Keep the equations as the converter reads them back, so a merge
        # can tell what a reviewer changed
        names = list(equations)
        read_back = calkit.docx.omml_to_latex(
            [ET.fromstring(equations[n]) for n in names]
        )
        equations = {n: t for n, t in zip(names, read_back) if t is not None}
        # Trimming a stray number changed a paragraph's text
        original = {
            p.bookmark: p.text
            for p in doc.paragraphs
            if p.bookmark and p.bookmark in original
        }
    doc.even_margins()
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
            export_id,
            rev,
            source,
            original,
            doc.media_hashes,
            equations=equations,
        )
    )
    doc.set_identifier(f"calkit-latex-export:{export_id}:{rev or ''}:{source}")
    doc.save()
    record = LatexDocxExport(
        id=export_id,
        created=datetime.datetime.now(datetime.timezone.utc),
        source=source,
        pdf=Path(pdf_path).as_posix(),
        docx=Path(output).as_posix(),
        rev=rev,
        dirty=dirty,
        engine=engine,
        permission="comment" if comment_only else "suggest",
        paragraphs=len(original),
        unanchored=sum(
            1 for p, m in zip(paras, matched) if m is None and p.text
        ),
        comments_exported=len(threads),
        equations=len(equations),
        inline_equations=inline_count,
        files={
            p: "md5:" + calkit.get_md5(p)
            for p in sorted(
                {ln.path for ln in lines}
                | {Path(pdf_path).as_posix(), Path(output).as_posix()}
            )
        },
    )
    # Named by time first, like run logs, so the records list in order
    stamp = (
        record.created.replace(tzinfo=None)
        .isoformat(timespec="seconds")
        .replace(":", "-")
    )
    dirs = [calkit.latex.LOCAL_DOCX_EXPORTS_DIR]
    if log:
        dirs.append(calkit.latex.DOCX_EXPORTS_DIR)
    name = f"{stamp}-{export_id}"
    # Within the same second, e.g., merging the same file twice, a count
    # after the seconds keeps them in order
    n = 1
    while any(os.path.exists(os.path.join(d, name + ".json")) for d in dirs):
        n += 1
        name = f"{stamp}.{n}-{export_id}"
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        with open(
            os.path.join(d, name + ".json"),
            "w",
            encoding="utf-8",
            newline="\n",
        ) as f:
            f.write(record.model_dump_json(indent=2))
    typer.echo(
        f"Wrote {output} ({record.paragraphs} paragraphs anchored, "
        f"{record.unanchored} not, {len(threads)} comments, "
        f"{len(equations)} equations, {inline_count} inline)"
    )
    if left_as_imported:
        warn(
            f"{left_as_imported} displayed equations couldn't be placed and "
            "are as converted with the document"
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
    log: Annotated[
        bool,
        typer.Option(
            "--log",
            "-l",
            help=(
                "Also keep the merge record in the project, under "
                ".calkit/latex/docx-merges, rather than only on this "
                "machine."
            ),
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
    from calkit.models.docx import LatexDocxMerge, LatexDocxMergeChange

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
    # By content, since Word renumbers images when it saves
    media = doc.media_hashes
    changed = sorted(
        {n for n, h in media.items() if h not in original.media.values()}
        | {n for n, h in original.media.items() if h not in media.values()}
    )
    if changed:
        warn(
            "Figures were changed in Word and can't be merged; edit the "
            "pipeline instead: " + ", ".join(changed)
        )
    lines = calkit.latex.flatten(original.source)
    blks = calkit.latex.blocks(lines)
    path_for_hash = {
        calkit.latex.make_bookmark_name(p, 0).split("_")[1]: p
        for p in {ln.path for ln in lines}
    }
    edits: dict[str, list[tuple[int, int, list[str]]]] = {}
    changes: list[LatexDocxMergeChange] = []
    for para in doc.paragraphs:
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
                LatexDocxMergeChange(
                    path=path, lineno=lineno, status="unplaced"
                )
            )
            continue
        loc = f"{blk.path}:{blk.lineno}"
        if para.pending:
            warn(f"Tracked change at {loc} not yet accepted or rejected")
            changes.append(
                LatexDocxMergeChange(
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
                LatexDocxMergeChange(
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
                LatexDocxMergeChange(
                    path=blk.path, lineno=blk.lineno, status="unplaced"
                )
            )
            continue
        edits.setdefault(blk.path, []).append(
            (blk.lineno, len(blk.lines), new_lines)
        )
        changes.append(
            LatexDocxMergeChange(
                path=blk.path, lineno=blk.lineno, status="applied"
            )
        )
        typer.echo(f"Applied edit at {loc}")
    # Equations edited in Word go back through the LaTeX the converter
    # reads them as, applied to the source's own spelling; one that can't
    # be placed that way goes in as a comment on the equation
    eq_comments: list[tuple[calkit.latex.Block, calkit.latex.TexComment]] = []
    found = doc.equations(list(original.equations))
    if found and calkit.docx.find_pandoc() is None:
        warn(
            "Pandoc isn't installed, so edits to equations aren't merged; "
            "run 'calkit install pandoc'"
        )
    elif found:
        present = [m for m, _ in found.values() if m is not None]
        it = iter(calkit.docx.omml_to_latex(present))
        now = {
            n: (next(it) if m is not None else None, authors)
            for n, (m, authors) in found.items()
        }
        working: dict[int, calkit.latex.Block] = {}
        for name, (eq_tex, pending) in now.items():
            sent_eq = original.equations[name]
            if eq_tex is not None and calkit.latex.math_tokens(
                eq_tex
            ) == calkit.latex.math_tokens(sent_eq):
                continue
            parts = name.split("_")
            path, lineno = path_for_hash.get(parts[1], ""), int(parts[2])
            blk = calkit.latex.find_display(blks, path, lineno, sent_eq)
            if blk is None:
                warn(f"Can't place an equation edit from {path}:{lineno}")
                changes.append(
                    LatexDocxMergeChange(
                        path=path, lineno=lineno, status="unplaced"
                    )
                )
                continue
            loc = f"{blk.path}:{blk.lineno}"
            if pending is not None:
                warn(f"Tracked change at {loc} not yet accepted or rejected")
                changes.append(
                    LatexDocxMergeChange(
                        path=blk.path,
                        lineno=blk.lineno,
                        status="pending",
                        author=", ".join(pending) or None,
                    )
                )
                continue
            if eq_tex is None:
                warn(f"The equation at {loc} was removed in Word")
                changes.append(
                    LatexDocxMergeChange(
                        path=blk.path, lineno=blk.lineno, status="unplaced"
                    )
                )
                continue
            # Rows of one display are edited in turn on the same lines
            current = working.get(id(blk), blk)
            if calkit.latex.math_similarity(
                current, eq_tex
            ) > calkit.latex.math_similarity(current, sent_eq):
                changes.append(
                    LatexDocxMergeChange(
                        path=blk.path,
                        lineno=blk.lineno,
                        status="already-applied",
                    )
                )
                continue
            new_lines = calkit.latex.apply_math_edit(current, sent_eq, eq_tex)
            if new_lines is None:
                warn(f"Equation edit at {loc} goes in as a comment")
                eq_comments.append(
                    (
                        blk,
                        calkit.latex.TexComment(
                            [
                                calkit.latex.Entry(
                                    doc.last_modified_by or "Word",
                                    "Edited this equation to read: "
                                    + " ".join(eq_tex.split()),
                                )
                            ]
                        ),
                    )
                )
                changes.append(
                    LatexDocxMergeChange(
                        path=blk.path, lineno=blk.lineno, status="unplaced"
                    )
                )
                continue
            working[id(blk)] = calkit.latex.Block(
                [
                    calkit.latex.SourceLine(blk.path, blk.lineno + i, text)
                    for i, text in enumerate(new_lines)
                ]
            )
            changes.append(
                LatexDocxMergeChange(
                    path=blk.path, lineno=blk.lineno, status="applied"
                )
            )
            typer.echo(f"Applied equation edit at {loc}")
        for blk in blks:
            if id(blk) in working:
                edits.setdefault(blk.path, []).append(
                    (
                        blk.lineno,
                        len(blk.lines),
                        [ln.text for ln in working[id(blk)].lines],
                    )
                )
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
        comments = doc.comments
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
        placed += eq_comments
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
    seen = {a for p in doc.paragraphs for a in p.authors}
    seen |= {c.author for c in doc.comments}
    record = LatexDocxMerge(
        export_id=original.id,
        created=datetime.datetime.now(datetime.timezone.utc),
        docx=Path(docx_path).as_posix(),
        rev=rev,
        authors=sorted(seen),
        last_modified_by=doc.last_modified_by,
        changes=changes,
        comments_added=added,
        comments_updated=updated,
        files={
            p: "md5:" + calkit.get_md5(p)
            for p in sorted(
                {ln.path for ln in lines} | {Path(docx_path).as_posix()}
            )
        },
    )
    stamp = (
        record.created.replace(tzinfo=None)
        .isoformat(timespec="seconds")
        .replace(":", "-")
    )
    dirs = [calkit.latex.LOCAL_DOCX_MERGES_DIR]
    if log:
        dirs.append(calkit.latex.DOCX_MERGES_DIR)
    name = f"{stamp}-{original.id}"
    # Within the same second, e.g., merging the same file twice, a count
    # after the seconds keeps them in order
    n = 1
    while any(os.path.exists(os.path.join(d, name + ".json")) for d in dirs):
        n += 1
        name = f"{stamp}.{n}-{original.id}"
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        with open(
            os.path.join(d, name + ".json"),
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
