"""Working with LaTeX documents."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from calkit.core import LOCAL_DIR, ensure_local_dir

if TYPE_CHECKING:
    # Only ever named in annotations here, which this module's
    # ``from __future__ import annotations`` leaves unevaluated. Importing
    # GitPython for real runs 'git version' twice as a side effect of the
    # import, and this module is reached from the CLI's own import chain --
    # so every 'calkit' invocation paid for two git subprocesses to satisfy
    # a type hint.
    import git

# Where revisions are checked out and the marked-up document is built.
# Inside the project so a containerized TeX environment, which only sees
# the working directory, can read them; under .calkit/local, which is
# private to the machine and gitignored wholesale, so none of it is
# mistaken for the diffs themselves.
DIFF_TMP_DIR = os.path.join(LOCAL_DIR, "latex-diff-build")
# Hashes of the marked-up source each diff was last built from, so a run
# that would produce the same document again can skip the build. Machine
# private, so a fresh clone simply builds once.
DIFF_STATE_DIR = os.path.join(DIFF_TMP_DIR, "state")
# Where the marked-up document's auxiliary files and PDF are written,
# inside the directory it's built in. TeX refuses to write outside the
# working directory or to dotfiles, and packages like glossaries run
# makeindex from inside TeX, so anywhere else leaves their lists empty.
DIFF_AUX_DIRNAME = "calkit-latex-diff-aux"
DIFF_DIR = os.path.join(".calkit", "latex-diffs")
# Revisions that mean something different tomorrow. A comparison with one
# of these at either end can't be settled by looking at files alone.
MOVING_REFS = frozenset({"HEAD"})
# Where a comparison against the working tree goes. It can't be
# reproduced from two commits, so it isn't something to track: it's a
# development aid with a lifetime of minutes, and .calkit/local is
# private to the machine.
LOCAL_DIFF_DIR = os.path.join(LOCAL_DIR, "latex-diffs")
# What the working tree is called when a comparison is named after its
# ends
WORKING_NAME = "working"

# The image a LaTeX stage builds in when the project doesn't name an
# environment of its own. Built from images/latex, and a ninth the size
# of a full TeX Live image. Pinned to an exact tag rather than :latest so
# a document keeps building against the same TeX until this is moved
# deliberately; what it carries is recorded in images/latex/README.md.
DEFAULT_LATEX_IMAGE = "ghcr.io/calkit/latex:0.1.5"
# The environment created for a document that doesn't have one, wherever
# that happens: a new publication, an Overleaf import, or a stage whose
# environment is worked out from what it runs. Copied where it's used,
# since what's written into a project is the caller's to amend.
DEFAULT_LATEX_ENVIRONMENT = {
    "kind": "docker",
    "image": DEFAULT_LATEX_IMAGE,
    "description": "TeX Live via Calkit's LaTeX image.",
}


def get_source_date_epoch(tex_file: str) -> str | None:
    """When to say the PDF was built, in seconds since the epoch.

    pdfTeX stamps the current time into the PDF's metadata and trailer
    ID, so two builds of identical source differ byte for byte, and every
    rebuild rewrites the output's hash in ``dvc.lock``. Taking the date
    from the last commit that touched the document keeps it meaningful
    while the bytes stay put until the document itself changes.
    """
    import subprocess

    tex_dir = os.path.dirname(os.path.abspath(tex_file)) or os.getcwd()
    # A commit's date describes what that commit holds, so it can only
    # speak for a document that has been saved. With edits still in the
    # working tree, the honest answer is now, which is what pdfTeX does
    # left alone.
    try:
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "-uno", "--", tex_dir],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if dirty:
        return None
    # A document with no commits of its own, e.g., one added but not yet
    # saved, falls back to the repository's last commit
    for pathspec in [["--", tex_dir], []]:
        try:
            out = subprocess.check_output(
                ["git", "log", "-1", "--format=%ct"] + pathspec,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
        if out:
            return out
    return None


# Where the project's TeX package cache is inside a container, with the
# working directory mounted at /work, as Calkit mounts it
CONTAINER_TEXMF_DIR = "/work/.calkit/local/texmf"
# LaTeX's messages for a file it couldn't find, and a font whose metrics it
# couldn't, e.g., "Font OT1/pcr/m/n/10=pcrr7t at 10.0pt not loadable"
_MISSING_FILE_RE = re.compile(r"File `([^']+)' not found")
_MISSING_TFM_RE = re.compile(
    r"Font \S+=(\S+?)(?: at \S+)? not loadable: Metric \(TFM\) file"
)


def get_texmf_cache_dir(wdir: str | None = None) -> str:
    """Where TeX packages fetched at run time are kept, per project.

    Inside the project's gitignored ``.calkit/local``, so the working
    directory a container mounts already covers it, whatever environment
    the container comes from, and nothing fetched can be committed. It is
    ``TEXMFHOME`` in the container, not the distribution's own tree, since
    mounting over that hides TinyTeX and leaves no TeX at all.
    """
    return os.path.join(ensure_local_dir(wdir), "texmf")


def find_missing_tex_files(log: str) -> list[str]:
    """The files a LaTeX log says it couldn't find, in the order it says.

    Style and class files are named as they are; a font whose metrics are
    missing is named as its ``.tfm`` file, which is what finds the package
    providing it.
    """
    found = _MISSING_FILE_RE.findall(log) + [
        f"{name}.tfm" for name in _MISSING_TFM_RE.findall(log)
    ]
    return list(dict.fromkeys(found))


def _ref_dirname(ref: str) -> str:
    """Turn a ref into something that can be one path component."""
    name = ref.lstrip("_").replace("_", "-").replace("/", "-")
    return re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-")


def get_diff_dir(from_ref: str, to_ref: str | None = None) -> str:
    """The directory holding a comparison, named for the pair as written.

    Named from the spec rather than what it resolved to, since a stage's
    outputs have to be the same paths on every branch.

    A comparison against the working tree lives under the machine-private
    directory instead: it can't be reproduced from two commits, so it
    isn't something to keep.
    """
    name = _ref_dirname(from_ref)
    if to_ref is None:
        # Against the working tree
        return Path(
            os.path.join(LOCAL_DIFF_DIR, f"{name}..{WORKING_NAME}")
        ).as_posix()
    if to_ref != "HEAD":
        # HEAD is what a comparison runs up to unless it says otherwise,
        # so naming it would only add noise
        name += f"..{_ref_dirname(to_ref)}"
    return Path(os.path.join(DIFF_DIR, name)).as_posix()


def get_diff_path(
    tex_file: str,
    from_ref: str,
    to_ref: str | None = None,
    as_posix: bool = True,
    output_dir: str | None = None,
) -> str:
    """Return where a document's diff between two revisions is kept.

    Beside the other things Calkit derives from a project's files rather
    than next to the document, following executed notebooks: it's an
    output, and a PDF, so saving the project tracks it with DVC and its
    history comes along with the project's.

    A directory per pair, named for the pair as written rather than what
    it resolved to, since a stage's outputs have to be the same paths on
    every branch. The document's own path lives inside it, so two
    documents both called main.tex don't collide, and so the inputs to a
    comparison have somewhere to sit later.
    """
    if output_dir is None:
        output_dir = get_diff_dir(from_ref, to_ref)
    p = os.path.join(
        output_dir, os.path.dirname(tex_file), Path(tex_file).stem + ".pdf"
    )
    return Path(p).as_posix() if as_posix else p


def diff_stage_suffix(from_ref: str, to_ref: str | None = None) -> str:
    """Name the DVC stage that builds a diff, from the pair as written."""
    suffix = _ref_dirname(from_ref)
    if to_ref is not None and to_ref != "HEAD":
        suffix += f"-{_ref_dirname(to_ref)}"
    return suffix


def get_diff_pairs(diffs: list) -> list[tuple[str, str]]:
    """The revisions a latex stage's ``diffs`` compare, oldest side first.

    A bare revision is paired with ``HEAD``, which is what the working tree
    it's compared with becomes once committed.
    """
    pairs: list[tuple[str, str]] = []
    for entry in diffs:
        if isinstance(entry, str):
            pairs.append((entry, "HEAD"))
        else:
            pairs.append((entry[0], entry[1]))
    return pairs


def get_diff_stage_name(stage_name: str, from_ref: str, to_ref: str) -> str:
    """The DVC stage a latex stage generates to build one of its diffs."""
    return f"{stage_name}-diff-{diff_stage_suffix(from_ref, to_ref)}"


# Appended to a latex stage's name to address all of its diffs at once,
# e.g., 'calkit run paper.diffs'
DIFFS_TARGET_SUFFIX = ".diffs"


def get_diff_stage_names(stage_name: str, stage: dict) -> list[str]:
    """Every diff stage a latex stage in calkit.yaml generates."""
    if stage.get("kind") != "latex":
        return []
    return [
        get_diff_stage_name(stage_name, from_ref, to_ref)
        for from_ref, to_ref in get_diff_pairs(stage.get("diffs") or [])
    ]


def get_pipeline_diffs(ck_info: dict, status: bool = False) -> list[dict]:
    """Every diff the project's latex stages keep, with where each is.

    ``to_ref`` is None for a bare revision, which is compared with the
    working tree. Paths are in the project's frame rather than a stage's
    ``wdir``.

    With ``status``, each also says whether it's ``up to date``, ``stale``,
    or ``not built``, which means compiling the pipeline and asking DVC.
    """
    diffs = []
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    for name, stage in stages.items():
        if not isinstance(stage, dict) or stage.get("kind") != "latex":
            continue
        wdir = stage.get("wdir") or ""
        target = stage.get("target_path") or ""
        for entry, (from_ref, to_ref) in zip(
            stage.get("diffs") or [], get_diff_pairs(stage.get("diffs") or [])
        ):
            diffs.append(
                {
                    "path": Path(
                        os.path.normpath(
                            os.path.join(
                                wdir, get_diff_path(target, from_ref, to_ref)
                            )
                        )
                    ).as_posix(),
                    "document": Path(
                        os.path.normpath(os.path.join(wdir, target))
                    ).as_posix(),
                    "latex_stage": name,
                    "stage": get_diff_stage_name(name, from_ref, to_ref),
                    "from_ref": from_ref,
                    "to_ref": None if isinstance(entry, str) else to_ref,
                }
            )
    if status and diffs:
        import calkit.pipeline

        # Environments and notebooks don't decide whether a diff is stale,
        # and checking them is the slow part
        result = calkit.pipeline.get_status(
            ck_info=ck_info,
            targets=[diff["stage"] for diff in diffs],
            check_environments=False,
            clean_notebooks=False,
        )
        if result.errors:
            raise RuntimeError("; ".join(result.errors))
        stale = set(result.stale_stage_names)
        for diff in diffs:
            if not os.path.isfile(diff["path"]):
                diff["status"] = "not built"
            elif diff["stage"] in stale:
                diff["status"] = "stale"
            else:
                diff["status"] = "up to date"
    return diffs


def diff_state_path(output: str) -> str:
    """Where the hash of a diff's marked-up source is remembered."""
    flat = Path(output).as_posix().replace("/", "-")
    return os.path.join(DIFF_STATE_DIR, f"{flat}.sha256")


def default_base_ref(repo: git.Repo) -> str:
    """What a change is naturally read against: the merge base with the
    default branch.

    Not the default branch itself, since work that landed there after this
    branch started isn't part of this change and would otherwise show up
    as deletions. Used when nobody says what to compare against; a
    pipeline names the branch itself, which is more readable and doesn't
    depend on which machine resolved it.
    """
    import warnings

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
    warnings.warn("Could not find a default branch; comparing against HEAD~1")
    return "HEAD~1"


# Extensions tried, in order, when a reference omits one. LaTeX resolves
# \includegraphics{fig} against the graphics extension list, and
# \input{sec}/\bibliography{refs} against .tex/.bib.
_GRAPHICS_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".gif"]
# Commands that name a local file, mapped to the extensions to try. Each
# takes a comma-separated list in its final braces group.
_INPUT_COMMANDS: dict[str, list[str]] = {
    "documentclass": [".cls"],
    "usepackage": [".sty"],
    "RequirePackage": [".sty"],
    "bibliographystyle": [".bst"],
    "bibliography": [".bib"],
    "addbibresource": [".bib"],
    "input": [".tex"],
    "include": [".tex"],
    "subfile": [".tex"],
    "includegraphics": _GRAPHICS_EXTS,
    # Provenance-marked equivalents from calkit.sty
    "ckfigure": _GRAPHICS_EXTS,
    "ckinput": [".tex"],
    "includesvg": [".svg", ".pdf"],
    "lstinputlisting": [""],
    "verbatiminput": [""],
}
# Files that are themselves LaTeX source, so their own inputs count too.
_SOURCE_EXTS = frozenset({".tex", ".cls", ".sty", ".clo", ".def", ".cfg"})
# One command with optional [...] args, then its {...} argument. TeX
# comments are stripped first, so a % here is a literal one.
_INPUT_RE = re.compile(
    r"\\(" + "|".join(_INPUT_COMMANDS) + r")\s*(?:\[[^\]]*\])*\s*\{([^}]*)\}"
)


def _strip_comments(tex: str) -> str:
    """Remove TeX comments, keeping escaped percent signs."""
    out = []
    for line in tex.splitlines():
        out.append(re.sub(r"(?<!\\)%.*$", "", line))
    return "\n".join(out)


def _project_has(base: Path, rel: str) -> bool:
    """Whether the project contains this file.

    A DVC-tracked figure isn't in the working tree until it's pulled, but
    its ``.dvc`` pointer is always in Git, and it's every bit as much a
    project file -- and a stage input -- as one stored directly. Without
    this, detection would depend on whether the caller had pulled, and a
    server working from a fresh clone would miss every DVC-tracked figure.
    """
    return (base / rel).is_file() or (base / f"{rel}.dvc").is_file()


def detect_inputs(target_path: str, wdir: str | None = None) -> list[str]:
    """Find the project files a LaTeX document reads.

    A document's class, style, bibliography, and figure files are inputs
    to building it, but LaTeX names them without paths or extensions and
    resolves them itself, so nothing in the pipeline sees them unless
    they're declared. Undeclared, a change to the class file doesn't
    rebuild the paper, and the in-browser preview -- which only has the
    files the stage declares -- can't compile at all.

    Only files that exist in the project are returned; everything else
    (``graphicx``, ``natbib``, and the rest of TeX Live) comes from the
    TeX installation and isn't ours to track. Source files found this way
    are read in turn, so a document split across files contributes its
    whole tree, and a journal class that loads its own style files (the
    JFM template's ``jfm.cls`` pulls in ``upmath.sty`` and
    ``lineno-FLM.sty``) contributes those too.

    Paths are returned relative to ``wdir`` -- the same frame as
    ``target_path`` and the rest of a stage's paths -- sorted, and with
    the target itself excluded (it's already a dependency).
    """
    base = Path(wdir) if wdir else Path(".")
    root = Path(target_path)
    found: set[str] = set()
    # Source files whose own inputs still need collecting, and everything
    # already visited, so a pair of files including each other terminates.
    queue = [root]
    seen = {root.as_posix()}
    while queue:
        current = queue.pop()
        try:
            tex = _strip_comments(
                (base / current).read_text(encoding="utf-8", errors="replace")
            )
        except (OSError, UnicodeDecodeError):
            continue
        for command, arg in _INPUT_RE.findall(tex):
            for raw in [n.strip() for n in arg.split(",")]:
                if not raw or raw.startswith(("http://", "https://")):
                    continue
                # TeX resolves a reference against the compile's working
                # directory, which is the root document's; a nested file
                # written as if paths were relative to itself is common
                # enough to try too. Names as written come first, since a
                # reference can already carry its extension.
                names = [raw] + [
                    raw + ext for ext in _INPUT_COMMANDS[command] if ext
                ]
                candidates = [
                    parent / name
                    for name in names
                    for parent in dict.fromkeys([root.parent, current.parent])
                ]
                for candidate in candidates:
                    rel = Path(os.path.normpath(candidate)).as_posix()
                    if rel.startswith("..") or not _project_has(base, rel):
                        continue
                    if rel != root.as_posix():
                        found.add(rel)
                    if Path(rel).suffix in _SOURCE_EXTS and rel not in seen:
                        seen.add(rel)
                        queue.append(Path(rel))
                    break
    return sorted(found)


# Records of Word exports and merges: always kept on this machine, like run
# logs, and in the project too when asked, e.g., with --log
DOCX_EXPORTS_DIR = os.path.join(".calkit", "latex", "docx-exports")
DOCX_MERGES_DIR = os.path.join(".calkit", "latex", "docx-merges")
LOCAL_DOCX_EXPORTS_DIR = os.path.join(LOCAL_DIR, "docx-exports")
LOCAL_DOCX_MERGES_DIR = os.path.join(LOCAL_DIR, "docx-merges")
# Where TeX4ht builds a Word export's source; machine-local, like the diffs
DOCX_BUILD_DIR = os.path.join(LOCAL_DIR, "latex-docx-build")
# Word bookmark names: 40 chars max, letters/digits/underscores
_INCLUDE_RE = re.compile(
    r"^\s*\\(input|include|subfile|import)\{([^}]*)\}(?:\{([^}]*)\})?"
)
_BLOCK_START_RE = re.compile(
    r"^\s*\\(begin|end|section|subsection|subsubsection|chapter|part|item|"
    r"caption|maketitle|documentclass)\b"
)
# Display math, which Word gets as equations rather than paragraphs
_DISPLAY_RE = re.compile(
    r"^\s*(?:\\begin\{(equation|align|gather|multline|eqnarray|flalign)"
    r"(\*?)\}|(\\\[)|(\$\$))"
)
_FLOAT_RE = re.compile(
    r"\\(begin|end)\{(figure|table|wrapfigure|sidewaysfigure|sidewaystable)"
    r"\*?\}"
)
# Inline math, $...$ or \\(...\\), but not $$
_INLINE_MATH_RE = re.compile(
    r"(?<![\\$])\$(?!\$)((?:\\.|[^$\\])+?)\$|\\\((.+?)\\\)", re.S
)
# Environments whose rows are numbered one by one
_MULTIROW_ENVS = frozenset({"align", "gather", "eqnarray", "flalign"})


@dataclass
class SourceLine:
    path: str
    lineno: int
    text: str


@dataclass
class Block:
    """A run of source lines that renders as one Word paragraph."""

    lines: list[SourceLine]
    # Inside a figure or table, which can float away from the prose around
    # it in the rendered document
    floating: bool = False

    @property
    def path(self) -> str:
        return self.lines[0].path

    @property
    def lineno(self) -> int:
        return self.lines[0].lineno

    @property
    def text(self) -> str:
        if self.display:
            return ""
        return detex("\n".join(ln.text for ln in self.lines))

    @property
    def inline_math(self) -> list[tuple[str, str, str]]:
        """Each piece of inline math, with the prose on either side of it as
        rendered: (before, LaTeX, after)."""
        if self.display:
            return []
        src = "\n".join(ln.text.split("%")[0] for ln in self.lines)
        found = list(_INLINE_MATH_RE.finditer(src))
        out = []
        for i, m in enumerate(found):
            start = found[i - 1].end() if i else 0
            end = found[i + 1].start() if i + 1 < len(found) else len(src)
            out.append(
                (
                    detex(src[start : m.start()]),
                    m.group(1) or m.group(2),
                    detex(src[m.end() : end]),
                )
            )
        return out

    @property
    def display(self) -> str | None:
        """The display math environment this block is, if any, e.g.,
        ``equation*``, or ``[`` for ``\\[``."""
        m = _DISPLAY_RE.match(self.lines[0].text)
        if m is None:
            return None
        if m.group(1):
            return m.group(1) + m.group(2)
        return "[" if m.group(3) else "$$"

    @property
    def rows(self) -> list[tuple[str, bool]]:
        """The display's math as LaTeX for a converter, with whether each
        piece is numbered: one piece per row when rows are numbered one by
        one, else one for the whole display."""
        env = self.display
        if env is None:
            return []
        src = "\n".join(ln.text.split("%")[0] for ln in self.lines)
        src = re.sub(r"\\(label|tag\*?)\{[^}]*\}", "", src)
        body = re.sub(
            r"^\s*(\\begin\{[^}]*\}|\\\[|\$\$)|(\\end\{[^}]*\}|\\\]|\$\$)\s*$",
            "",
            src.strip(),
        )
        name, starred = env.rstrip("*"), env.endswith("*")
        numbered = not starred and env not in ("[", "$$")
        if name not in _MULTIROW_ENVS:
            unnumbered = re.search(r"\\(nonumber|notag)\b", body)
            body = re.sub(r"\\(nonumber|notag)\b", "", body)
            wrapped = f"\\begin{{{name}*}}{body}\\end{{{name}*}}"
            if name in ("[", "$$", "equation"):
                wrapped = f"\\[{body}\\]"
            return [(wrapped, numbered and not unnumbered)]
        # Split on top-level row breaks, not those in nested environments
        rows, depth, start = [], 0, 0
        for m in re.finditer(r"\\(begin|end)\{[^}]*\}|\\\\", body):
            if m.group(1) == "begin":
                depth += 1
            elif m.group(1) == "end":
                depth -= 1
            elif depth == 0:
                rows.append(body[start : m.start()])
                start = m.end()
        rows.append(body[start:])
        rows = [r for r in rows if r.strip()]
        inner = (
            "aligned"
            if name in ("align", "flalign", "eqnarray")
            else ("gathered")
        )

        def wrap(r: str) -> str:
            return f"\\[\\begin{{{inner}}}{r}\\end{{{inner}}}\\]"

        flags = [
            numbered and not re.search(r"\\(nonumber|notag)\b", r)
            for r in rows
        ]
        rows = [re.sub(r"\\(nonumber|notag)\b", "", r) for r in rows]
        if sum(flags) <= 1:
            return [(wrap("\\\\".join(rows)), any(flags))]
        return [(wrap(r), f) for r, f in zip(rows, flags)]


def flatten(main_path: str) -> list[SourceLine]:
    """Inline \\input and friends, keeping each line's file and number."""
    main = Path(main_path)
    out: list[SourceLine] = []
    seen: set[str] = set()

    def visit(path: Path, base: Path) -> None:
        key = path.resolve().as_posix()
        if key in seen or not path.is_file():
            return
        seen.add(key)
        rel = path.as_posix()
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.split("\n"), 1):
            m = _INCLUDE_RE.match(line.split("%")[0])
            if m:
                cmd, a, b = m.groups()
                target = Path(b) if cmd == "import" and b else Path(a)
                start = base / a if cmd == "import" else base
                child = start / target
                if child.suffix == "":
                    child = child.with_suffix(".tex")
                visit(child, child.parent)
                continue
            out.append(SourceLine(rel, i, line))

    visit(main, main.parent)
    return out


_WORD_TO_TEX = str.maketrans(
    {
        "\u2019": "'",
        "\u2018": "`",
        "\u201c": "``",
        "\u201d": "''",
        "\u2013": "--",
        "\u2014": "---",
        "\u00a0": "~",
    }
)


def from_word_text(text: str) -> str:
    """Rendered text in LaTeX source conventions: straight quotes,
    dashes as hyphens, non-breaking spaces as ties."""
    return text.translate(_WORD_TO_TEX)


def detex(text: str) -> str:
    """Roughly what LaTeX would print for a bit of source."""
    text = "\n".join(ln.split("%")[0] for ln in text.split("\n"))
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(
        r"\\(cite[pt]?|ref|eqref|label|includegraphics|usepackage|"
        r"documentclass|bibliography\w*|begin|end)\*?(\[[^\]]*\])?\{[^}]*\}",
        " ",
        text,
    )
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}~]", " ", text).replace("---", " ").replace("--", " ")
    text = text.replace("``", "").replace("''", "")
    return re.sub(r"\s+", " ", text).strip()


def blocks(lines: list[SourceLine]) -> list[Block]:
    """Split flattened source into paragraph-sized blocks."""
    out: list[Block] = []
    cur: list[SourceLine] = []
    # The text that closes the display math being read, if any
    closing: str | None = None
    for ln in lines:
        stripped, rest = ln.text.strip(), ln.text
        # Display math is a block of its own, through its closing line
        m = _DISPLAY_RE.match(ln.text) if closing is None else None
        if m is not None:
            if cur:
                out.append(Block(cur))
            cur = []
            closing = (
                f"\\end{{{m.group(1)}{m.group(2)}}}"
                if m.group(1)
                else ("\\]" if m.group(3) else "$$")
            )
            rest = ln.text[m.end() :]
        if closing is not None:
            cur.append(ln)
            if closing in rest:
                out.append(Block(cur))
                cur, closing = [], None
            continue
        if not stripped:
            if cur:
                out.append(Block(cur))
                cur = []
            continue
        # A comment line inside a paragraph doesn't end it; one before it
        # isn't part of it
        if stripped.startswith("%"):
            if cur:
                cur.append(ln)
            continue
        if cur and _BLOCK_START_RE.match(ln.text):
            out.append(Block(cur))
            cur = []
        cur.append(ln)
    if cur:
        out.append(Block(cur))
    in_float: set[tuple[str, int]] = set()
    depth = 0
    for ln in lines:
        for m in _FLOAT_RE.finditer(ln.text.split("%")[0]):
            depth = max(0, depth + (1 if m.group(1) == "begin" else -1))
            if m.group(1) == "begin":
                in_float.add((ln.path, ln.lineno))
        if depth:
            in_float.add((ln.path, ln.lineno))
    for b in out:
        b.floating = (b.path, b.lineno) in in_float
    return [b for b in out if b.text or b.display]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]{3,}", text.lower()))


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa) if wa else 0.0


def align(
    texts: list[str], blks: list[Block], threshold: float = 0.5
) -> list[Block | None]:
    """Match rendered paragraphs to source blocks, in order."""
    out: list[Block | None] = []
    last = 0
    floats = [j for j, b in enumerate(blks) if b.floating]
    for text in texts:
        # A short line ending in an equation number is a display's
        # fragment, even when it shares a word with the prose around it
        if re.search(r"\(([A-Z]\.)?\d+(\.\d+)*\)\s*$", text) and (
            len(_words(text)) < 4
        ):
            out.append(None)
            continue
        # On a tie the nearest block wins, so a short heading can't jump
        # ahead to a later paragraph sharing its words. A figure or table
        # can be anywhere, since it floats, and doesn't move the place in
        # the source the prose has reached.
        candidates = sorted(set(range(last, len(blks))) | set(floats))
        scores = [(similarity(text, blks[j].text), -j) for j in candidates]
        best = max(scores, default=(0.0, 1))
        # A table's rows or a caption's lines stay with it on a tie, e.g.,
        # a row "Growth rate k 0.05" beside prose about the growth rate
        prev = next((b for b in reversed(out) if b is not None), None)
        if (
            prev is not None
            and prev.floating
            and best[0] >= threshold
            and similarity(text, prev.text) >= best[0]
        ):
            out.append(prev)
            continue
        if best[0] >= threshold:
            out.append(blks[-best[1]])
            if not blks[-best[1]].floating:
                last = -best[1]
        else:
            out.append(None)
    return out


def make_bookmark_name(path: str, lineno: int) -> str:
    digest = hashlib.sha1(path.encode()).hexdigest()[:8]
    return f"ck_{digest}_{lineno}"


def find_block(
    blks: list[Block], path: str, lineno: int, text: str
) -> Block | None:
    """The block a bookmark points at, by line first and text second."""
    same_file = [b for b in blks if b.path == path]
    for b in same_file:
        if b.lineno == lineno and (
            b.display or similarity(text, b.text) >= 0.5
        ):
            return b
    scored = [
        (similarity(text, b.text), -abs(b.lineno - lineno), b)
        for b in same_file
    ]
    best = max(scored, key=lambda s: s[:2], default=None)
    return best[2] if best and best[0] >= 0.6 else None


def math_similarity(block: Block, math: str) -> float:
    """How much a display block's source reads like ``math``, as a
    converter spells it, ignoring grouping and wrappers."""
    want = [t for t in math_tokens(math) if t not in _MATH_NOISE]
    have = _MATH_TOKEN_RE.findall("\n".join(ln.text for ln in block.lines))
    have = [t for t in have if t not in _MATH_NOISE]
    return difflib.SequenceMatcher(a=want, b=have, autojunk=False).ratio()


def find_display(
    blks: list[Block], path: str, lineno: int, math: str
) -> Block | None:
    """The display block a bookmark points at, by line first, else the one
    in the file whose math reads most like ``math``, as a converter spells
    it, e.g., after edits above it moved it."""
    same_file = [b for b in blks if b.path == path and b.display]
    for b in same_file:
        if b.lineno == lineno:
            return b
    scored = [
        (math_similarity(b, math), -abs(b.lineno - lineno), b)
        for b in same_file
    ]
    best = max(scored, key=lambda s: s[:2], default=None)
    return best[2] if best and best[0] >= 0.6 else None


def _tokens(text: str) -> set[str]:
    """Words and numbers, so a change to a value counts as a change."""
    return set(re.findall(r"[A-Za-z0-9][\w.]*", text))


def already_applied(block: Block, old: str, new: str) -> bool:
    """Whether the block already reads as ``new`` rather than ``old``."""
    have = _tokens("\n".join(ln.text for ln in block.lines))
    inserted = _tokens(new) - _tokens(old)
    deleted = _tokens(old) - _tokens(new)
    if not inserted <= have:
        return False
    return not deleted or len(deleted & have) / len(deleted) <= 0.5


def _find_span(src: str, words: list[str]) -> tuple[int, int] | None:
    """Where ``words`` sit in the source: verbatim, else by their edges,
    so a span whose middle holds markup can still be replaced."""

    def once(ws: list[str]) -> re.Match | None:
        pattern = (
            r"(?<![A-Za-z])"
            + r"[\s~]+".join(re.escape(w) for w in ws)
            + r"(?![A-Za-z])"
        )
        found = list(re.finditer(pattern, src))
        return found[0] if len(found) == 1 else None

    m = once(words)
    if m is not None:
        return m.start(), m.end()
    if len(words) < 4:
        return None
    head, tail = once(words[:2]), once(words[-2:])
    if head is None or tail is None or tail.start() < head.end():
        return None
    return head.start(), tail.end()


def apply_edit(block: Block, old: str, new: str) -> list[str] | None:
    """The block's lines rewritten so ``old`` reads as ``new``.

    Works at the word level: each changed span must be findable in the
    source, else the edit touches markup and None is returned.
    """
    ow, nw = old.split(), new.split()
    sm = difflib.SequenceMatcher(a=ow, b=nw, autojunk=False)
    src = "\n".join(ln.text for ln in block.lines)
    for tag, i1, i2, j1, j2 in reversed(sm.get_opcodes()):
        if tag == "equal":
            continue
        new_span = " ".join(nw[j1:j2])
        if tag == "insert":
            # Anchor on the preceding word(s), widening the phrase until
            # it's unique -- a single preceding word is often repeated
            # elsewhere in the block even when the insertion point isn't
            # anywhere near markup.
            if i1 == 0:
                return None
            hits = None
            for k in range(1, i1 + 1):
                phrase = ow[i1 - k : i1]
                pattern = (
                    r"(?<![A-Za-z])"
                    + r"[\s~]+".join(re.escape(w) for w in phrase)
                    + r"(?![A-Za-z])"
                )
                found = list(re.finditer(pattern, src))
                if len(found) == 1:
                    hits = found
                    break
                if not found:
                    break
            if hits is None:
                return None
            at = hits[0].end()
            src = src[:at] + " " + new_span + src[at:]
            continue
        span = _find_span(src, ow[i1:i2])
        if span is None:
            return None
        src = src[: span[0]] + new_span + src[span[1] :]
    # A line emptied by a deletion goes, since a blank line would split
    # the paragraph
    return [ln.rstrip() for ln in src.split("\n") if ln.strip()]


_MATH_TOKEN_RE = re.compile(r"\\[a-zA-Z]+|\\.|\S")
_MATH_FUNCTIONS = (
    "arccos arcsin arctan arg cos cosh cot coth det exp lg lim ln log max "
    "min sec sin sinh sup tan tanh"
).split()
# Grouping and wrappers that the source and a converter may disagree on
_MATH_NOISE = frozenset(
    ["{", "}", "\\mathrm", "\\text", "\\operatorname", "\\left", "\\right"]
)


def normalize_math(tex: str) -> str:
    """Math as a converter reads it back, without what LibreOffice
    respells on saving an equation it hasn't changed: operators as text,
    spacing, empty groups, and aligned rows as arrays."""
    tex = re.sub(r"\\text\{(\\&|[^{}\\a-zA-Z0-9\s])\}", r"\1", tex)
    tex = tex.replace("\\&", "&")
    tex = re.sub(r"\\begin\{array\}\{[lcr]*\}", r"\\begin{aligned}", tex)
    tex = tex.replace("\\end{array}", "\\end{aligned}")
    tex = re.sub(r"\\(quad|qquad)\b|\\[,;:! ]", " ", tex)
    # Word may save a function name as plain letters
    tex = re.sub(
        r"\\(" + "|".join(_MATH_FUNCTIONS) + r")(?![a-zA-Z])", r"\1 ", tex
    )
    tex = tex.replace("{}", "")
    return " ".join(tex.split())


def math_tokens(tex: str) -> list[str]:
    """Normalized math as tokens, so spacing doesn't count as a change."""
    return _MATH_TOKEN_RE.findall(normalize_math(tex))


def apply_math_edit(block: Block, old: str, new: str) -> list[str] | None:
    """The display block's lines rewritten so math that read as ``old``
    reads as ``new``.

    ``old`` and ``new`` are a converter's LaTeX for the equation as sent
    and as returned, so they share its spelling, which the source may not,
    e.g., where it uses its own macros or ``\\mathrm``. The converter's
    tokens are aligned with the source's, ignoring grouping and wrappers,
    and each change goes to the source span its tokens align with. If a
    change's tokens don't all align, None is returned.
    """
    ot, nt = math_tokens(old), math_tokens(new)
    src = "\n".join(ln.text for ln in block.lines)
    # Source tokens with their spans, function names spelled out as the
    # converter may read them back
    st: list[tuple[str, int, int]] = []
    for m in _MATH_TOKEN_RE.finditer(src):
        t = m.group(0)
        if t.lstrip("\\") in _MATH_FUNCTIONS and t.startswith("\\"):
            st += [(c, m.start(), m.end()) for c in t[1:]]
        else:
            st.append((t, m.start(), m.end()))

    def content(t: str) -> bool:
        return t not in _MATH_NOISE

    oi = [i for i, t in enumerate(ot) if content(t)]
    si = [k for k, (t, _, _) in enumerate(st) if content(t)]
    to_src: dict[int, int] = {}
    matcher = difflib.SequenceMatcher(
        a=[ot[i] for i in oi], b=[st[k][0] for k in si], autojunk=False
    )
    for blk in matcher.get_matching_blocks():
        for n in range(blk.size):
            to_src[oi[blk.a + n]] = si[blk.b + n]
    edits: list[tuple[int, int, str]] = []
    sm = difflib.SequenceMatcher(a=ot, b=nt, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        text = ""
        for t in nt[j1:j2]:
            # Space a command name from what follows, as people write it
            if re.search(r"\\[a-zA-Z]+$", text) and t[0].isalnum():
                text += " "
            text += t
        changed = [i for i in range(i1, i2) if content(ot[i])]
        if changed:
            if not all(i in to_src for i in changed):
                return None
            k1, k2 = to_src[changed[0]], to_src[changed[-1]]
            # Take in the braces that close groups the span opens, and
            # open groups it closes
            depth = sum((t == "{") - (t == "}") for t, _, _ in st[k1 : k2 + 1])
            while depth > 0 and k2 + 1 < len(st) and st[k2 + 1][0] == "}":
                k2, depth = k2 + 1, depth - 1
            while depth < 0 and k1 > 0 and st[k1 - 1][0] == "{":
                k1, depth = k1 - 1, depth + 1
            start, end = st[k1][1], st[k2][2]
        else:
            # An insertion goes after the aligned token before it, past
            # as many closing braces as the converter has between them
            prev = next(
                (i for i in range(i1 - 1, -1, -1) if content(ot[i])), None
            )
            if prev is None or prev not in to_src:
                return None
            k = to_src[prev]
            for t in ot[prev + 1 : i1]:
                if t == "}" and k + 1 < len(st) and st[k + 1][0] == "}":
                    k += 1
            start = end = st[k][2]
        if re.search(r"\\[a-zA-Z]+$", src[:start]) and text[:1].isalpha():
            text = " " + text
        edits.append((start, end, text))
    for start, end, text in sorted(edits, reverse=True):
        src = src[:start] + text + src[end:]

    def balance(text: str) -> int:
        return len(re.findall(r"(?<!\\)\{", text)) - len(
            re.findall(r"(?<!\\)\}", text)
        )

    if balance(src) != balance("\n".join(ln.text for ln in block.lines)):
        return None
    return src.split("\n")


_AUTHOR_RE = re.compile(
    r"^(?P<name>.*?)\s*(?:<(?P<email>[^>]*)>)?\s*(?:\((?P<date>[^)]*)\))?:$"
)


def _parse_header(text: str) -> dict[str, Any]:
    """The key=value attributes on a COMMENT line; a value is a bare word,
    a quoted string, or a YAML flow mapping like {text: "x", occ: 0}."""
    import json

    from calkit import ryaml

    out: dict[str, Any] = {}
    i = 0
    while True:
        m = re.compile(r"\s*(\w+)=").match(text, i)
        if not m:
            return out
        key, i = m.group(1), m.end()
        if i < len(text) and text[i] == "{":
            depth, j, quoted = 0, i, False
            while j < len(text):
                ch = text[j]
                if ch == '"' and text[j - 1] != "\\":
                    quoted = not quoted
                elif not quoted and ch == "{":
                    depth += 1
                elif not quoted and ch == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out[key] = ryaml.load(text[i : j + 1])
            i = j + 1
        elif i < len(text) and text[i] == '"':
            m2 = re.compile(r'"((?:[^"\\]|\\.)*)"').match(text, i)
            if not m2:
                return out
            out[key], i = json.loads(m2.group(0)), m2.end()
        else:
            m3 = re.compile(r"\S*").match(text, i)
            assert m3 is not None
            out[key], i = m3.group(0), m3.end()


def word_date(value: str | None) -> str | None:
    """A Word timestamp like 2026-09-06T08:44:00Z as 2026-09-06 08:44."""
    if not value:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})", value)
    return f"{m.group(1)} {m.group(2)}" if m else value


@dataclass
class Entry:
    """One message in a thread."""

    author: str
    text: str
    email: str | None = None
    date: str | None = None

    def header(self) -> str:
        out = self.author
        if self.email:
            out += f" <{self.email}>"
        if self.date:
            out += f" ({self.date})"
        return out + ":"


@dataclass
class TexComment:
    """A comment thread in the source, above the paragraph it's about.

    The first entry is the comment itself, the rest are replies.
    """

    entries: list[Entry]
    highlight: str | None = None
    highlight_occ: int = 0
    resolved: bool = False
    lineno: int = 0
    nlines: int = 0

    @property
    def author(self) -> str:
        return self.entries[0].author

    @property
    def text(self) -> str:
        return self.entries[0].text

    @property
    def replies(self) -> list[Entry]:
        return self.entries[1:]

    def messages(self) -> list[tuple[str, str]]:
        return [(e.author, e.text) for e in self.entries]

    def render(self) -> list[str]:
        import json

        attrs = []
        if self.resolved:
            attrs.append("resolved=true")
        if self.highlight:
            value = f"text: {json.dumps(self.highlight)}"
            if self.highlight_occ:
                value += f", occ: {self.highlight_occ}"
            attrs.append("highlight={" + value + "}")
        out = ["% COMMENT"]
        # Attributes continue onto their own lines when they don't fit
        for attr in attrs:
            if len(out[-1]) + 1 + len(attr) <= 79 or out[-1] == "% COMMENT":
                out[-1] += " " + attr
            else:
                out.append(f"%   {attr}")
        for e in self.entries:
            out.append(f"%   {e.header()}")
            out += textwrap.wrap(
                e.text,
                width=79,
                initial_indent="%     ",
                subsequent_indent="%     ",
            )
        return out


def parse_comments(lines: list[str]) -> list[TexComment]:
    """Comment blocks in a file's lines, with their position and extent."""
    out: list[TexComment] = []
    i = 0
    while i < len(lines):
        if not re.match(r"% COMMENT( |$)", lines[i]):
            i += 1
            continue
        start = i
        header = lines[i][len("% COMMENT") :]
        entries: list[Entry] = []
        i += 1
        while i < len(lines) and re.match(r"%(   |$)", lines[i]):
            body = lines[i][1:]
            indent = len(body) - len(body.lstrip())
            author = _AUTHOR_RE.match(body.strip()) if indent == 3 else None
            if not entries and indent == 3 and re.match(r"\s*\w+=", body):
                header += " " + body.strip()
            elif author is not None:
                entries.append(
                    Entry(
                        author["name"].strip(),
                        "",
                        author["email"] or None,
                        author["date"] or None,
                    )
                )
            elif indent > 3 and entries:
                e = entries[-1]
                e.text = (e.text + " " + body.strip()).strip()
            i += 1
        if entries:
            attrs = _parse_header(header)
            highlight = attrs.get("highlight")
            if isinstance(highlight, dict):
                text, occ = highlight.get("text"), highlight.get("occ", 0)
            else:
                text, occ = highlight, 0
            out.append(
                TexComment(
                    entries,
                    str(text) if text else None,
                    int(occ or 0),
                    str(attrs.get("resolved", "")).lower() == "true",
                    start + 1,
                    i - start,
                )
            )
    return out


# -- provenance -------------------------------------------------------------
#
# Content injected into a document from elsewhere in the project -- a value
# from a results file, a figure, a generated block of text -- is marked with
# macros from calkit.sty so a reader of the TeX or the PDF can see it came
# from somewhere and follow the trail back. The generated commands below
# expand to those macros; the style file makes them invisible in final mode
# and colored, hyperlinked and logged in provenance mode.

STYLE_FNAME = "calkit.sty"
PROVENANCE_TEX_FNAME = "calkit-provenance.tex"
PROVENANCE_LOG_EXT = ".ckprov"
#: Published alongside the calkit.yaml schema, so an editor validates a
#: provenance record the same way it validates the project file
PROVENANCE_SCHEMA_URL = "https://docs.calkit.org/schemas/provenance.json"
#: JSON carries no comments, so the warning that belongs at the top of a
#: file nothing should hand-edit goes in a field of its own
PROVENANCE_NOTE = (
    "Written by 'calkit latex build --provenance'. Do not edit. These "
    "hashes and values are evidence of what a build actually used; "
    "changing them to resolve an error or make a check pass falsifies "
    "that evidence. If something here looks wrong, say so rather than "
    "correcting it: regenerate the artifact instead."
)
_TEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_tex(text: str) -> str:
    """Escape TeX special characters in plain text."""
    return "".join(_TEX_SPECIALS.get(c, c) for c in str(text))


def unwrap_singleton(value: Any) -> Any:
    """A one-element list of a scalar, as that scalar.

    MATLAB and NumPy write a scalar as a one-element array, so a results
    file exported from either has ``[3.54]`` where the author means 3.54.
    Left alone it prints with its brackets into the prose, and a numeric
    format spec raises rather than formatting it.
    """
    if isinstance(value, (list, tuple)) and len(value) == 1:
        inner = value[0]
        if isinstance(inner, (int, float, str, bool)):
            return inner
    return value


def format_value(value: Any, spec: str | None = None) -> str:
    """A value as plain text for a document, with an optional format spec.

    Not escaped for TeX: callers escape once, after formatting, so a
    string value is not escaped twice.
    """
    value = unwrap_singleton(value)
    if spec:
        return format(value, spec)
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def keyed_command(
    name: str, entries: dict[str, str], listing: dict[str, str] | None = None
) -> str:
    """Define ``\\name[key]``, expanding to the TeX in ``entries[key]``.

    ``\\name`` alone, or ``\\name[all]``, prints every key (and its plain
    value, if ``listing`` gives one), which is handy for checking what a
    document has available. The structure is a chain of ``\\pdfstrcmp``
    tests, so it works in any engine that has ``\\pdfstrcmp`` (pdfTeX,
    XeTeX, LuaTeX via pdftexcmds).
    """
    lines = [
        "\\makeatletter%",
        f"\\newcommand\\{name}[1][all]{{%",
        "  \\ifnum\\pdfstrcmp{#1}{all}=0%",
        f"    \\def\\{name}@out{{%",
    ]
    listing = listing or {}
    listed = ", ".join(
        escape_tex(k) + (f": {listing[k]}" if k in listing else "")
        for k in entries
    )
    lines.append(f"      {listed}}}%")
    for key, tex in entries.items():
        lines.append(f"  \\else\\ifnum\\pdfstrcmp{{#1}}{{{key}}}=0%")
        lines.append(f"    \\def\\{name}@out{{%")
        lines.append(f"      {tex}}}%")
    lines.append(
        "  \\else\\PackageError{calkit}{Unknown key '#1' for \\string\\"
        + name
        + "}{}%"
    )
    lines.append("  " + "\\fi" * (len(entries) + 1) + "%")
    lines.append(f"  \\{name}@out}}%")
    lines.append("\\makeatother%")
    return "\n".join(lines) + "\n"


def value_macro(key: str, value: str, path: str, stage: str | None) -> str:
    """The provenance-carrying expansion of one injected value."""
    return (
        f"\\ckvalue{{{escape_tex(key)}}}{{{value}}}"
        f"{{{escape_tex(path)}}}{{{escape_tex(stage or '')}}}"
    )


PREAMBLE = (
    "%% Generated by Calkit. Do not edit.\n"
    "%% Values are wrapped in \\ckvalue so calkit.sty can mark and log where\n"
    "%% they came from; without the package they print as plain text.\n"
    "\\providecommand\\ckvalue[4]{#2}%\n"
)


def stage_for(path: str, ck_info: dict) -> str | None:
    from calkit.pipeline import get_stage_for_output

    return get_stage_for_output(path, ck_info)


def _lock_hashes(wdir: str) -> dict[str, str]:
    """Output path -> hash, from ``dvc.lock`` if there is one."""
    import calkit

    lock_path = os.path.join(wdir, "dvc.lock")
    if not os.path.isfile(lock_path):
        return {}
    try:
        with open(lock_path, encoding="utf-8") as f:
            lock = calkit.ryaml.load(f)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for stage in ((lock or {}).get("stages") or {}).values():
        for o in (stage or {}).get("outs") or []:
            if isinstance(o, dict) and o.get("path"):
                out[o["path"]] = str(o.get("md5") or o.get("hash") or "")
    return out


def artifact_records(paths: list[str], ck_info: dict, wdir: str) -> list[dict]:
    """Provenance of project paths: producing stage, its inputs, hash."""
    hashes = _lock_hashes(wdir)
    stages = ck_info.get("pipeline", {}).get("stages", {})
    records = []
    for path in paths:
        stage_name = stage_for(path, ck_info)
        stage = stages.get(stage_name) if stage_name else None
        inputs: list[str] = []
        if isinstance(stage, dict):
            for inp in stage.get("inputs") or []:
                inputs.append(inp if isinstance(inp, str) else json.dumps(inp))
        records.append(
            {
                "path": path,
                "stage": stage_name,
                "stage_inputs": inputs,
                "hash": hashes.get(path),
            }
        )
    return records


def write_provenance_tex(
    target_path: str, ck_info: dict, wdir: str | None = None
) -> str:
    """Write the artifact table calkit.sty reads, beside the document.

    One ``\\ckartifact{path}{stage}{hash}{project path}`` per project file
    the document references, keyed by the path as TeX sees it (relative to
    the document), so a caption can name the stage that produced a figure
    and a link can point at the file's place in the project.
    """
    wdir = wdir or os.getcwd()
    tex_dir = os.path.dirname(target_path)
    lines = ["%% Generated by Calkit for each build. Do not edit or commit."]
    for rel in detect_inputs(target_path, wdir):
        rec = artifact_records([rel], ck_info, wdir)[0]
        if rec["stage"] is None:
            continue
        as_written = Path(os.path.relpath(rel, tex_dir or ".")).as_posix()
        lines.append(
            f"\\ckartifact{{{as_written}}}{{{rec['stage']}}}"
            f"{{{rec['hash'] or ''}}}{{{rel}}}"
        )
    out_path = os.path.join(wdir, tex_dir, PROVENANCE_TEX_FNAME)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def install_style(target_path: str, wdir: str | None = None) -> str:
    """Put calkit.sty beside the document if it is missing or outdated.

    A copy in the project rather than a TEXINPUTS trick, so the document
    builds the same way on Overleaf, in a container, or on a laptop, and so
    the style is under version control with the paper that uses it.
    """
    import calkit.resources

    wdir = wdir or os.getcwd()
    src = os.path.join(calkit.resources.get_dir(), "latex", STYLE_FNAME)
    dest = os.path.join(wdir, os.path.dirname(target_path), STYLE_FNAME)
    with open(src, encoding="utf-8") as f:
        wanted = f.read()
    current = None
    if os.path.isfile(dest):
        with open(dest, encoding="utf-8") as f:
            current = f.read()
    if current != wanted:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(wanted)
    return dest


def provenance_sidecar_path(target_path: str) -> str:
    return os.path.splitext(target_path)[0] + ".provenance.json"


def synctex_pages(
    target_path: str, wdir: str, artifact_path: str | None = None
) -> dict[str, dict[int, list[int]]]:
    """Which page of the built PDF each line of each source ended up on.

    Read out of the ``.synctex.gz`` latexmk already writes, so a document
    needs nothing in it for its components to be placed on pages. TeX
    records where material was shipped out rather than where it was
    written, so a float that moved is reported on the page it landed on,
    which is the whole reason to ask TeX rather than to guess.

    Parsed here rather than shelled out to the ``synctex`` binary, which
    lives wherever the project's TeX does: for a container environment
    that is a container start per lookup, where one file read answers
    every component at once. Keyed by the path TeX recorded, which for a
    container build is absolute and inside the container, so
    :func:`pages_at` matches it by suffix rather than by equality.
    """
    import gzip

    stem = os.path.splitext(os.path.join(wdir, artifact_path or target_path))[
        0
    ]
    path = next(
        (
            p
            for p in (stem + ".synctex.gz", stem + ".synctex")
            if os.path.isfile(p)
        ),
        None,
    )
    if path is None:
        return {}
    inputs: dict[int, str] = {}
    by_tag: dict[int, dict[int, set[int]]] = {}
    page: int | None = None
    # Every record naming a place in the source starts with its type, then
    # the input's tag and the line
    record = re.compile(r"^[\[(vhxkg$]\s*(\d+),(\d+)")
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                named = re.match(r"^Input:(\d+):(.*)$", line)
                if named:
                    inputs[int(named.group(1))] = named.group(2)
                    continue
                if line.startswith("{"):
                    try:
                        page = int(line[1:])
                    except ValueError:
                        page = None
                    continue
                if line.startswith("}"):
                    page = None
                    continue
                found = record.match(line)
                if found and page is not None:
                    tag, at = int(found.group(1)), int(found.group(2))
                    by_tag.setdefault(tag, {}).setdefault(at, set()).add(page)
    except OSError:
        return {}
    out: dict[str, dict[int, list[int]]] = {}
    for tag, lines in by_tag.items():
        raw = inputs.get(tag)
        if raw is None or not raw.endswith(".tex"):
            continue
        norm = Path(os.path.normpath(raw)).as_posix()
        into = out.setdefault(norm, {})
        for at, pages in lines.items():
            into[at] = sorted(set(into.get(at, [])) | pages)
    return out


def localize_synctex(
    target_path: str, wdir: str, artifact_path: str | None = None
) -> bool:
    """Point a build's SyncTeX at where its sources actually are.

    TeX records the paths it saw, so a build in a container records the
    container's: ``/work/paper/main.tex``, which nothing outside it can
    open. Reverse search in a PDF viewer then finds the right line of a
    file that does not exist, which looks like the feature being broken
    rather than the path being someone else's.

    Each recorded input that names a file this project has is rewritten to
    that file's path here. Matched by the longest trailing part that
    exists, so it needs to know nothing about where the container mounted
    anything. Anything else, such as a class file from the TeX
    distribution, is left as it was.

    Returns whether the file was changed.
    """
    import gzip

    stem = os.path.splitext(os.path.join(wdir, artifact_path or target_path))[
        0
    ]
    path = next(
        (
            p
            for p in (stem + ".synctex.gz", stem + ".synctex")
            if os.path.isfile(p)
        ),
        None,
    )
    if path is None:
        return False
    root = Path(wdir).resolve()

    def local(raw: str) -> str | None:
        parts = Path(os.path.normpath(raw)).as_posix().split("/")
        for i in range(len(parts)):
            rel = "/".join(parts[i:])
            if not rel or rel.startswith(".."):
                continue
            if (root / rel).is_file():
                return (root / rel).as_posix()
        return None

    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return False
    changed = False
    for i, line in enumerate(lines):
        named = re.match(r"^(Input:\d+:)(.*)$", line)
        if named is None:
            continue
        found = local(named.group(2))
        if found is not None and found != named.group(2):
            lines[i] = named.group(1) + found
            changed = True
    if not changed:
        return False
    try:
        with opener(path, "wt") as f:
            f.write("\n".join(lines))
    except OSError:
        return False
    return True


def pages_at(
    mapping: dict[str, dict[int, list[int]]], source: str, line: int
) -> list[int]:
    """The page one line of a project-relative source landed on.

    TeX records a box against the line it started on, so a line in the
    middle of a paragraph often has no record of its own. The nearest
    recorded line at or before it is the box that carried it, which is
    where it was typeset.

    The first page only. A line whose material spans a break is recorded
    on both, and naming the second would put the component on a page a
    reader looking for it would not find it on.
    """
    wanted = Path(source).as_posix()
    base = os.path.basename(wanted)
    for suffix in ("/" + wanted, "/" + base):
        for norm, lines in mapping.items():
            if norm != wanted and not norm.endswith(suffix):
                continue
            at = max((n for n in lines if n <= line), default=None)
            if at is not None and lines[at]:
                return lines[at][:1]
    return []


def collect_provenance(
    target_path: str,
    ck_info: dict,
    wdir: str | None = None,
    artifact_path: str | None = None,
    kind: str = "publication",
) -> dict:
    r"""Record what a document takes from the project, and where it landed.

    Every component the document uses, with the pages it appears on and
    the stage, inputs and hash of what it came from, so a reader or a tool
    can follow any number or figure in the PDF back through the pipeline.
    Written beside the PDF as ``<document>.provenance.json``.

    Nothing in the document is required for this. What it uses is read
    from its source, the same way ``calkit describe components`` reads it,
    so a paper that includes figures with a plain ``\includegraphics``
    gets a record like any other. Pages come from the ``.synctex.gz`` the
    build already writes. ``calkit.sty``'s log is folded in when the
    package was used, since it catches what no parse can see: a path built
    by a macro, or content inside a conditional.
    """
    from calkit.components import LocalProject, source_components

    wdir = wdir or os.getcwd()
    tex_dir = os.path.dirname(target_path)
    uses: dict[tuple[str, str, str | None], dict] = {}
    # What the source names, and where each of it is written
    for rec in source_components(target_path, wdir):
        key = (rec["kind"], rec["path"], rec.get("key"))
        uses[key] = {
            "kind": key[0],
            "path": key[1],
            "key": key[2],
            "pages": [],
            "locations": rec.get("locations", []),
        }
    # What the build logged, for a document that loaded the package
    log_path = os.path.join(
        wdir, os.path.splitext(target_path)[0] + PROVENANCE_LOG_EXT
    )
    if os.path.isfile(log_path):
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                path_as_written = str(entry.get("path", ""))
                # Generated value commands carry project-relative paths;
                # figures and inputs are written as TeX resolves them,
                # relative to the document
                if entry.get("kind") in ("value", "block"):
                    rel = Path(os.path.normpath(path_as_written)).as_posix()
                else:
                    rel = Path(
                        os.path.normpath(
                            os.path.join(tex_dir, path_as_written)
                        )
                    ).as_posix()
                key = (
                    entry.get("kind", ""),
                    rel,
                    str(entry.get("key", "")) or None,
                )
                use = uses.setdefault(
                    key,
                    {
                        "kind": key[0],
                        "path": key[1],
                        "key": key[2],
                        "pages": [],
                        "locations": [],
                    },
                )
                page = entry.get("page")
                if page is not None and page not in use["pages"]:
                    use["pages"].append(page)
    # Where the source said each thing is, turned into where TeX put it
    mapping = synctex_pages(target_path, wdir, artifact_path)
    for use in uses.values():
        if use["pages"]:
            continue
        pages: list[int] = []
        for location in use.pop("locations", []) or []:
            source = getattr(location, "source", None) or location["source"]
            at = getattr(location, "line", None) or location["line"]
            for page in pages_at(mapping, source, at):
                if page not in pages:
                    pages.append(page)
        use["pages"] = sorted(pages)
    records = {
        r["path"]: r
        for r in artifact_records(
            sorted({u["path"] for u in uses.values()}), ck_info, wdir
        )
    }
    view = LocalProject(ck_info, wdir, check_stages=False)
    components = []
    for use in uses.values():
        use.pop("locations", None)
        rec = records.get(use["path"], {})
        entry = {
            **use,
            "stage": rec.get("stage"),
            "stage_inputs": rec.get("stage_inputs", []),
            "hash": rec.get("hash"),
        }
        # What each value read as in this build. A results file can change
        # in a key the document never cites, so its hash says nothing about
        # whether the page is out of date; the value itself does. Recorded
        # raw, since one value can be typeset several ways in one document
        # and a difference in formatting is not a difference in the result.
        if use["kind"] == "value":
            entry["value"] = view.current_value(use["path"], use["key"])
        components.append(entry)
    components.sort(key=lambda u: (u["kind"], u["path"], u["key"] or ""))
    # The artifact is what the build produced and what a reader reads; the
    # source is where a person edits it and where a position resolves. A
    # figure or a dataset has only the first, which is why they are named
    # apart rather than one standing in for the other.
    from calkit.components import ProvenanceRecord

    sidecar = ProvenanceRecord(
        artifact=artifact_path or (os.path.splitext(target_path)[0] + ".pdf"),
        source=target_path,
        kind=kind,
        components=components,
    ).model_dump(mode="json", by_alias=True)
    with open(
        os.path.join(wdir, provenance_sidecar_path(target_path)),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(sidecar, f, indent=2)
        f.write("\n")
    # The log is scratch: LaTeX appends to it a line at a time during the
    # build, and once it has been read there is nothing in it the sidecar
    # does not hold. Left behind it litters the document's folder and
    # syncs to Overleaf along with everything else there.
    if os.path.isfile(log_path):
        try:
            os.remove(log_path)
        except OSError:
            pass
    return sidecar


def questions_tex(ck_info: dict, wdir: str | None = None) -> str:
    """LaTeX commands that inject the project's questions and answers.

    ``\\ckquestion[n]``, ``\\ckhypothesis[n]``, ``\\ckanswer[n]``,
    ``\\cknotes[n]`` give one question's fields with every ``{name}``
    placeholder rendered as a provenance-marked value, ``\\ckevidence[n]``
    lists its evidence with section references where a publication entry
    carries a label, and ``\\ckfindings`` typesets every answered question.
    Numbers reach the document by the same route as ``calkit.yaml``'s own
    rendering, so the paper and the project cannot disagree.
    """
    import string

    from calkit.questions import (
        TEMPLATED_FIELDS,
        is_conditional,
        is_value_evidence,
        named_keys,
        read_evidence_file,
        resolve_key,
        select_branch,
    )

    wdir = wdir or os.getcwd()
    questions = ck_info.get("questions", []) or []
    fields: dict[str, dict[str, str]] = {
        f: {} for f in ("question", *TEMPLATED_FIELDS, "evidence")
    }
    answered: list[int] = []
    formatter = string.Formatter()
    for n, q in enumerate(questions, start=1):
        key = str(n)
        if isinstance(q, str):
            fields["question"][key] = escape_tex(q)
            continue
        fields["question"][key] = escape_tex(q.get("question", ""))
        values: dict[str, tuple[Any, str, str | None]] = {}
        for ev in q.get("evidence") or []:
            keys = named_keys(ev)
            if not keys:
                continue
            data = read_evidence_file(os.path.join(wdir, ev["path"]))
            stage = stage_for(ev["path"], ck_info)
            for name, value_key in keys.items():
                values[name] = (
                    resolve_key(data, value_key),
                    ev["path"],
                    stage,
                )

        def render_tex(text: str | dict | None) -> str:
            # A conditional answer is typeset as the clause the evidence
            # selects, as `calkit list questions` shows it
            if is_conditional(text):
                text = select_branch(
                    text, {n: v[0] for n, v in values.items()}
                )
            out = []
            for literal, name, spec, conv in formatter.parse(text or ""):
                out.append(escape_tex(literal))
                if name is None:
                    continue
                if name not in values:
                    raise KeyError(name)
                value, path, stage = values[name]
                shown = escape_tex(format_value(value, spec))
                out.append(value_macro(name, shown, path, stage))
            return "".join(out)

        for f in TEMPLATED_FIELDS:
            if q.get(f):
                fields[f][key] = render_tex(q[f])
        if q.get("answer"):
            answered.append(n)
        items = []
        for ev in q.get("evidence") or []:
            kind = ev.get("kind", "result")
            path = escape_tex(ev.get("path", ""))
            if is_value_evidence(ev):
                items.append(
                    f"\\item value \\texttt{{{path}}}: "
                    f"\\texttt{{{escape_tex(ev.get('key', ''))}}}"
                )
            elif kind == "publication" and ev.get("label"):
                items.append(
                    f"\\item Section~\\ref{{{ev['label']}}}"
                    + (
                        f" ({escape_tex(ev['section'])})"
                        if ev.get("section")
                        else ""
                    )
                )
            else:
                items.append(f"\\item {kind} \\texttt{{{path}}}")
            if ev.get("explanation"):
                items[-1] += " -- " + render_tex(ev["explanation"])
        if items:
            fields["evidence"][key] = (
                "\\begin{itemize}" + "".join(items) + "\\end{itemize}"
            )
    out = [PREAMBLE, "\\providecommand\\ckblock[2]{}%\n"]
    for f, name in (
        ("question", "ckquestion"),
        ("hypothesis", "ckhypothesis"),
        ("answer", "ckanswer"),
        ("notes", "cknotes"),
        ("evidence", "ckevidence"),
    ):
        out.append(keyed_command(name, fields[f]))
    # Every answered question, as a paragraph the document can drop in
    # Plain paragraphs rather than \\paragraph, which not every document
    # class defines
    body = []
    for n in answered:
        body.append(
            f"\\par\\noindent\\textbf{{Q{n}. \\ckquestion[{n}]}}"
            f"\\ckblock{{{n}}}{{calkit.yaml}}\\par\\noindent"
            f"\\ckanswer[{n}]"
            + (f"\\ckevidence[{n}]" if str(n) in fields["evidence"] else "")
            + "\\par"
        )
    out.append("\\newcommand\\ckfindings{" + "\n".join(body) + "}%\n")
    return "".join(out)
