"""Working with LaTeX documents."""

from __future__ import annotations

import bisect
import difflib
import hashlib
import os
import posixpath
import re
import shutil
import textwrap
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any

from calkit.core import LOCAL_DIR, ensure_local_dir

if TYPE_CHECKING:
    from collections.abc import Callable

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
DEFAULT_LATEX_IMAGE = "ghcr.io/calkit/latex:0.1.7"
# The environment created for a document that doesn't have one, wherever
# that happens: a new publication, an Overleaf import, or a stage whose
# environment is worked out from what it runs. Copied where it's used,
# since what's written into a project is the caller's to amend.
DEFAULT_LATEX_ENVIRONMENT = {
    "kind": "docker",
    "image": DEFAULT_LATEX_IMAGE,
    "description": "TeX Live via Calkit's LaTeX image.",
}


# TeX run before the document, leaving the dates and trailer ID out of the
# PDF. Even taken from a commit, the date changes when history is rewritten,
# e.g., by a squash merge, which changes the bytes of an identical document.
# The ID, which pdfTeX derives from the date, is put back from the content
# afterwards by ``set_content_id``. XeTeX's driver can't leave them out, so
# its PDF keeps the source date.
PDF_PRETEX = (
    r"\ifdefined\pdfinfoomitdate\pdfinfoomitdate=1 \pdftrailerid{}"
    # LuaTeX's flags for CreationDate (32), ModDate (64), and ID (512)
    r"\else\ifdefined\pdfvariable\pdfvariable suppressoptionalinfo 608 "
    r"\pdfvariable trailerid{}\fi\fi"
)


def set_content_id(pdf_path: str) -> bool:
    """Give a PDF with no trailer ID one hashed from its content.

    PDF/A and PDF 2.0 require an ID, and a viewer keeps its first half when
    it saves an annotated copy, so a PDF back from review can still be
    matched to its build. Hashing the bytes keeps the ID the same for the
    same content. Only the last cross-reference section's dictionary
    changes, which comes after every offset the file records, so they all
    stay valid. Returns whether an ID was added.
    """
    data = Path(pdf_path).read_bytes()
    pos = data.rfind(b"startxref")
    m = re.match(rb"startxref\s+(\d+)", data[pos:]) if pos >= 0 else None
    if m is None:
        return False
    section = int(m.group(1))
    tail = data[section:pos]
    # A table's dictionary follows the 'trailer' keyword, and a stream's is
    # its own, ending where the stream starts
    if tail.startswith(b"xref"):
        start = tail.find(b"trailer")
        end = len(tail)
    else:
        start = 0
        end = tail.find(b"stream")
    opening = tail.find(b"<<", start) if start >= 0 else -1
    if opening < 0 or end < 0 or re.search(rb"/ID\b", tail[opening:end]):
        return False
    digest = hashlib.md5(data).hexdigest().upper().encode()
    at = section + opening + 2
    entry = b" /ID [<" + digest + b"> <" + digest + b">]"
    Path(pdf_path).write_bytes(data[:at] + entry + data[at:])
    return True


def get_source_date_epoch(tex_file: str) -> str | None:
    """When to say the PDF was built, in seconds since the epoch.

    pdfTeX stamps the current time into the PDF's metadata and trailer
    ID, so two builds of identical source differ byte for byte, and every
    rebuild rewrites the output's hash in ``dvc.lock``. Taking the date
    from the last commit that touched the document keeps it meaningful
    while the bytes stay put until the document itself changes. Where
    ``PDF_PRETEX`` leaves the date out, it still sets ``\\today``.
    """
    import subprocess

    # Whoever set it knows better, e.g., for LaTeX generated from a source
    # that has the history
    if os.environ.get("SOURCE_DATE_EPOCH"):
        return os.environ["SOURCE_DATE_EPOCH"]
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


def _strip_comments_joined(tex: str) -> str:
    """Remove TeX comments as TeX reads them: a comment takes its line's
    end, so the next line joins on, without its leading spaces."""
    lines = tex.split("\n")
    out, joined = [], False
    for i, line in enumerate(lines):
        if joined:
            line = line.lstrip()
        m = re.search(r"(?<!\\)%", line)
        joined = m is not None
        out.append(line[: m.start()] if m else line)
        if i < len(lines) - 1 and not joined:
            out.append("\n")
    return "".join(out)


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


# Where Calkit puts the components that the documents in a folder include
# with calkit.sty's commands. Not hidden, since Overleaf drops dot-folders
# from an uploaded zip.
COMPONENTS_DIR = "_calkit"
VALUES_FNAME = "values.tex"
STYLE_FNAME = "calkit.sty"
# What Calkit writes in _calkit itself, which no component can replace
_CALKIT_OWN_FILES = (".gitignore", "README.md", VALUES_FNAME)
# calkit.sty's commands, each with an optional [...] and its {...} args, of
# which only \ckvalue has two, so a brace group after another is left alone
_CK_COMMAND_RE = re.compile(
    r"\\ck(?P<kind>(?P<value>v)alue|figure|table)"
    r"\s*(?:\[(?P<option>[^\]]*)\])?\s*\{(?P<first>[^}]*)\}"
    r"(?(value)\s*\{(?P<second>[^}]*)\})"
)
_PACKAGE_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}"
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


@dataclass(frozen=True)
class CkComponent:
    """A document component included with one of calkit.sty's commands,
    named by its path relative to the project root.

    Components can be integrated other ways, e.g., a stage writing into the
    document's folder, a map-paths copy, or json-to-latex; this is only the
    kind Calkit brings in itself.
    """

    kind: str
    path: str
    key: str | None = None
    # How calkit.sty formats a value: siunitx options, or a Python format
    # spec, e.g., .2f
    format: str = ""


def _read_leniently(path: str) -> str | None:
    """A source file's text, with anything that isn't UTF-8 replaced, since
    finding components mustn't fail on a document in another encoding.
    """
    p = Path(path)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def read_ck_usage(
    document: str, read: Callable[[str], str | None] = _read_leniently
) -> tuple[bool, list[CkComponent]]:
    """Whether a document loads calkit.sty, and the components it includes
    with its commands, including in the files it inputs, in order and
    without repeats.

    Files are read with ``read``, e.g., from the hub's copy of a repo.

    Commands in a document that doesn't load calkit.sty can't compile, so
    they aren't components. Nor are commands in a macro's definition, whose
    arguments are its parameters, e.g., ``#1``, until used, which can't be
    followed.
    """
    lines = flatten(document, read=read)
    text = "\n".join(_strip_comments(line.text) for line in lines)
    loads = any(
        "calkit" in (name.strip() for name in m.group(1).split(","))
        for m in _PACKAGE_RE.finditer(text)
    )
    if not loads:
        return False, []
    found: list[CkComponent] = []
    for match in _CK_COMMAND_RE.finditer(text):
        kind, option, first = match.group("kind", "option", "first")
        option, second = option or "", match.group("second") or ""
        if "#" in first + second:
            continue
        if kind == "value":
            found.append(
                CkComponent(
                    kind, first.strip(), second.strip(), option.strip()
                )
            )
        else:
            found.append(CkComponent(kind, first.strip()))
    return True, list(dict.fromkeys(found))


def component_candidates(
    component: CkComponent,
) -> tuple[list[str], str | None]:
    """The project paths a component's file could be at, in the order TeX
    tries them, or what's wrong with how it's named.

    A figure or table named without an extension is found the way TeX
    finds it, e.g., ``figures/plot`` as ``figures/plot.pdf`` or ``.png``,
    and so is one with a dot in its name, e.g., ``figures/fit_1.5``.
    """
    raw = component.path.replace("\\", "/")
    if raw.startswith("/") or PureWindowsPath(component.path).drive:
        return [], f"{component.path} is outside the project"
    rel = posixpath.normpath(raw)
    if rel == ".." or rel.startswith("../"):
        return [], f"{component.path} is outside the project"
    # TeX reads the path as written, so a copy at the normalized path
    # wouldn't be found
    if ".." in raw.split("/"):
        return [], f"{component.path} can't include '..'"
    if component.kind != "value":
        exts = _GRAPHICS_EXTS if component.kind == "figure" else [".tex"]
        if posixpath.splitext(rel)[1].lower() not in exts:
            return [rel + ext for ext in exts] + [rel], None
    return [rel], None


def component_path(
    component: CkComponent, exists: Callable[[str], bool]
) -> tuple[str | None, str | None]:
    """Where a component's file is, relative to the project, or what's
    wrong with it, with ``exists`` saying whether a project path is there.
    """
    candidates, problem = component_candidates(component)
    if problem is not None:
        return None, problem
    for candidate in candidates:
        if exists(candidate):
            return candidate, None
    return None, f"{component.path} is not in the project yet"


def find_shown(document: str, wdir: str | None = None) -> list[str]:
    """Project files a document shows, whether cited with calkit.sty's
    commands or included plainly, e.g., with ``\\includegraphics`` or
    ``\\input``, relative to ``wdir`` like ``document`` is.
    """
    _, components = read_ck_usage(os.path.join(wdir or ".", document))
    cited = []
    for c in components:
        rel, _ = component_path(
            c, lambda p: os.path.isfile(os.path.join(wdir or ".", p))
        )
        cited.append(rel or c.path)
    return list(dict.fromkeys(cited + detect_inputs(document, wdir=wdir)))


def root_documents(folder: str) -> list[str]:
    """The documents directly in a folder, i.e., ``.tex`` files with a
    ``\\documentclass``, rather than the files they input.
    """
    docs = []
    for name in sorted(os.listdir(folder or ".")):
        path = os.path.join(folder, name)
        if not name.endswith(".tex") or not os.path.isfile(path):
            continue
        text = _read_leniently(path) or ""
        if re.search(r"^\s*\\documentclass", _strip_comments(text), re.M):
            docs.append(path)
    return docs


def escape_tex(text: str) -> str:
    """Escape TeX's special characters in plain text."""
    return "".join(_TEX_SPECIALS.get(c, c) for c in str(text))


def tex_value(value: Any) -> tuple[str, str]:
    """A value's kind and text for ``_calkit/values.tex``: ``n`` for a
    number, written in full for calkit.sty to format, or ``t`` for text.
    """
    import math

    # MATLAB and NumPy write a scalar as a one-element array
    if isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "t", escape_tex(str(value))
    if isinstance(value, float) and not math.isfinite(value):
        return "t", escape_tex(str(value))
    return "n", repr(value)


def _write_if_changed(path: str, content: str | bytes) -> None:
    """Write a file only if its content differs, so latexmk, which goes by
    content and timestamps, doesn't rebuild for nothing.
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    if os.path.isfile(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _make_writable(path: str) -> None:
    """Let a file be overwritten or removed, e.g., one copied from DVC's
    cache, which is read-only, or on Windows, where read-only blocks
    removal. A link is left alone, since that would change what it points
    to.
    """
    import stat

    if (
        os.path.exists(path)
        and not os.path.islink(path)
        and not os.access(path, os.W_OK)
    ):
        os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)


def _is_within(path: str, base: str) -> bool:
    try:
        return os.path.commonpath([path, base]) == base
    except ValueError:
        return False


def _within_project(path: str, root: str) -> bool:
    """Whether a file is really in the project, rather than reached through
    a link out of it, e.g., a symlink committed to Git, so nothing outside
    is read and pushed to Overleaf. DVC's cache counts, since DVC can check
    files out as links to it.
    """
    real = os.path.realpath(path)
    real_root = os.path.realpath(root)
    if _is_within(real, real_root):
        return True
    # A cache kept elsewhere, only looked for when a link leaves the project
    dvc_dir = os.path.join(real_root, ".dvc")
    for name in ["config", "config.local"]:
        try:
            with open(os.path.join(dvc_dir, name), encoding="utf-8") as f:
                config = f.read()
        except OSError:
            continue
        section = re.search(
            r"^\[cache\]\s*$(.*?)(?=^\[|\Z)", config, re.M | re.S
        )
        match = section and re.search(
            r"^\s*dir\s*=\s*(.+?)\s*$", section.group(1), re.M
        )
        if match:
            cache = os.path.realpath(os.path.join(dvc_dir, match.group(1)))
            if _is_within(real, cache):
                return True
    return False


@dataclass
class CkMapping:
    """What goes in a ``_calkit`` folder for the components documents
    include: the project files copied in, each with whether it's there to
    copy rather than only stored with DVC, the text of ``values.tex``, and
    what couldn't be brought in.
    """

    files: dict[str, bool]
    values: str
    problems: list[str]


def plan_ck_components(
    components: list[CkComponent],
    is_file: Callable[[str], bool],
    read_data: Callable[[str], Any],
    is_tracked: Callable[[str], bool] | None = None,
    is_outside: Callable[[str], bool] | None = None,
    previous_values: str = "",
    link_base: str | None = None,
) -> CkMapping:
    """Work out what goes in ``_calkit`` for some components, reading the
    project only through the functions given, so it works wherever its
    files are, e.g., in the hub's copy of a repo.

    ``is_file`` says whether a project path is there, ``read_data`` reads a
    results file's data, and ``is_outside`` whether a path is reached
    through a link out of the project. ``is_tracked`` and
    ``previous_values`` are as for ``map_ck_components``. ``link_base`` is
    the project's URL on its hub, which components link to in the PDF.
    """
    from calkit.questions import resolve_key

    def find(c: CkComponent) -> tuple[str | None, str | None, bool]:
        """Where a component is, what's wrong with it, and whether it's
        here rather than only stored with DVC.
        """
        rel, problem = component_path(c, is_file)
        if rel is not None and is_outside is not None and is_outside(rel):
            return None, f"{c.path} links outside the project", False
        # Calkit's own files in _calkit can't be replaced by a copy
        if c.kind != "value" and rel in _CALKIT_OWN_FILES:
            return None, f"{c.path} has a name Calkit uses in _calkit", False
        if rel is None and is_tracked is not None:
            tracked, _ = component_path(c, is_tracked)
            if tracked is not None:
                return tracked, None, False
        return rel, problem, rel is not None

    files: dict[str, bool] = {}
    problems: list[str] = []
    lines = ["%% Written by Calkit from what the documents here include.\n"]
    if link_base:
        lines.append(f"\\cklinkbase{{{link_base}}}\n")
    for c in components:
        if c.kind == "value":
            continue
        rel, problem, here = find(c)
        if rel is None:
            problems.append(str(problem))
            continue
        files[rel] = files.get(rel, False) or here
        # Where TeX finds one named without an extension, and nothing for one
        # named in full, so values.tex is the same whether or not the file
        # could be copied
        if rel != c.path:
            lines.append(f"\\cksetfile{{{c.path}}}{{{rel}}}\n")
    loaded: dict[str, Any] = {}
    # Formats are applied by calkit.sty, so a value is written once however
    # many ways it's formatted
    written: set[tuple[str, str | None]] = set()
    for c in components:
        if c.kind != "value" or (c.path, c.key) in written:
            continue
        written.add((c.path, c.key))
        rel, problem, here = find(c)
        if rel is None:
            problems.append(str(problem))
            continue
        if not here:
            start = f"\\cksetvalue{{{c.path}}}{{{c.key}}}{{"
            kept_line = next(
                (
                    line + "\n"
                    for line in previous_values.splitlines()
                    if line.startswith(start)
                ),
                None,
            )
            if kept_line is None:
                problems.append(f"{c.path} is stored with DVC and not pulled")
            else:
                lines.append(kept_line)
            continue
        try:
            if rel not in loaded:
                loaded[rel] = read_data(rel)
            kind, text = tex_value(resolve_key(loaded[rel], c.key or ""))
        except KeyError:
            problems.append(f"{c.path} has no {c.key}")
            continue
        except Exception as e:
            problems.append(f"{c.key} from {c.path}: {e}")
            continue
        lines.append(
            f"\\cksetvalue{{{c.path}}}{{{c.key}}}{{{kind}}}{{{text}}}\n"
        )
    return CkMapping(files=files, values="".join(lines), problems=problems)


def map_ck_components(
    path: str,
    is_tracked: Callable[[str], bool] | None = None,
    previous_values: str | None = None,
) -> list[str]:
    """Bring the components a document, or the documents in a folder,
    include with calkit.sty's commands into the ``_calkit`` folder beside
    them, so they build without the rest of the project, e.g., on Overleaf.

    Only documents that load calkit.sty are mapped, so Calkit writes nothing
    beside one that doesn't. One that does gets ``calkit.sty`` and
    ``_calkit`` even before it includes anything, so it compiles.

    Every document directly in the folder is included, plus the document
    named, e.g., one whose ``\\documentclass`` is in a file it inputs, since
    they share the ``_calkit`` folder, and mapping one alone would remove
    the others' copies. Files are copied, values are written to
    ``_calkit/values.tex`` for calkit.sty to format, and ``calkit.sty`` is
    put beside the documents. Anything no longer included is removed, since
    nothing else writes there, as is ``calkit.sty`` once no document loads
    it.

    ``is_tracked`` says whether a project path is stored with DVC, so
    something that isn't pulled, e.g., on the hub, comes out as it would
    where it is: a figure or table named without an extension is found the
    same way, and a value is kept from ``previous_values``, e.g., Overleaf's
    ``values.tex``, or the one being replaced. It's only asked about what
    isn't here.

    Returns what couldn't be brought in, e.g., a file the pipeline hasn't
    produced yet. Those print as ``??`` rather than failing the build.
    """
    import calkit.git
    import calkit.resources
    from calkit.questions import read_evidence_file

    named = [] if os.path.isdir(path or ".") else [path]
    folder = os.path.dirname(path) if named else path
    docs = list(
        dict.fromkeys(
            os.path.normpath(d)
            for d in root_documents(folder) + named
            if os.path.isfile(d)
        )
    )
    usage = [read_ck_usage(doc) for doc in docs]
    components = list(dict.fromkeys(c for _, found in usage for c in found))
    out = os.path.join(folder, COMPONENTS_DIR)
    style_path = os.path.join(folder, STYLE_FNAME)
    # Nothing is written, changed, or removed through a link, e.g., one
    # committed to Git, which could point anywhere
    for path in [out, style_path]:
        if os.path.islink(path):
            return [f"{path} is a link, so Calkit won't write there"]
    real_out = os.path.realpath(out)

    def can_write(dest: str) -> bool:
        """Whether a file can go in _calkit without following a link out of
        it, removing a link where the file goes.
        """
        parent = os.path.realpath(os.path.dirname(dest))
        if not _is_within(parent, real_out):
            return False
        if os.path.islink(dest):
            os.remove(dest)
        return True

    if not any(loads for loads, _ in usage):
        if os.path.isdir(out):
            for dirpath, _, filenames in os.walk(out):
                for name in filenames:
                    _make_writable(os.path.join(dirpath, name))
            shutil.rmtree(out)
        # Only the one Calkit wrote, and never one that's committed
        if os.path.isfile(style_path):
            with open(style_path, encoding="utf-8", errors="replace") as f:
                ours = "Calkit project components" in f.read()
            try:
                repo = calkit.git.get_repo(folder or ".")
                committed = bool(
                    repo.git.ls_files(
                        "--",
                        os.path.relpath(
                            os.path.abspath(style_path), repo.working_dir
                        ),
                    )
                )
            except Exception:
                committed = False
            if ours and not committed:
                os.remove(style_path)
        return []
    # Component paths are relative to the project, wherever the document is
    root = os.path.abspath(folder or ".")
    while not os.path.isfile(os.path.join(root, "calkit.yaml")):
        parent = os.path.dirname(root)
        if parent == root:
            root = os.path.abspath(folder or ".")
            break
        root = parent
    # Components link to the project on its hub, when calkit.yaml says whose
    # it is, since a Git remote differs between clones
    link_base = None
    try:
        import calkit.config

        ck_info = calkit.load_calkit_info(wdir=root, read_only=True)
        if ck_info.get("owner") and ck_info.get("name"):
            hub = calkit.config.normalize_hub_url(
                str(ck_info.get("hub") or "calkit.io")
            )
            link_base = f"{hub}/{ck_info['owner']}/{ck_info['name']}"
    except Exception:
        pass
    if previous_values is None:
        try:
            with open(os.path.join(out, VALUES_FNAME), encoding="utf-8") as f:
                previous_values = f.read()
        except (OSError, UnicodeDecodeError):
            previous_values = ""
    plan = plan_ck_components(
        components,
        is_file=lambda rel: os.path.isfile(os.path.join(root, rel)),
        read_data=lambda rel: read_evidence_file(os.path.join(root, rel)),
        is_tracked=is_tracked,
        is_outside=lambda rel: (
            not _within_project(os.path.join(root, rel), root)
        ),
        previous_values=previous_values,
        link_base=link_base,
    )
    problems = list(plan.problems)
    kept = set(_CALKIT_OWN_FILES) | set(plan.files)
    for name in _CALKIT_OWN_FILES:
        can_write(os.path.join(out, name))
    _write_if_changed(
        os.path.join(out, ".gitignore"),
        "# Calkit copies the components the documents beside this folder\n"
        "# include into it\n"
        "*\n",
    )
    # Pushed to Overleaf with the rest, where the .gitignore isn't a hint
    _write_if_changed(
        os.path.join(out, "README.md"),
        "# Don't edit anything here\n\n"
        "Calkit writes this folder from the project, for the documents\n"
        "beside it to include with `\\ckvalue`, `\\ckfigure`, and\n"
        "`\\cktable`. It's rewritten whenever the pipeline runs or is\n"
        "checked and on every Overleaf sync, so edits here are lost and\n"
        "never reach the project.\n"
        "To change a value, figure, or table, change where it comes from.\n",
    )
    for rel, here in plan.files.items():
        # Skipped while size and timestamp match, since this runs before
        # every status check. Only the content is copied, so a read-only
        # file from DVC's cache leaves a copy that can be updated.
        src = os.path.join(root, rel)
        dest = os.path.join(out, rel)
        if not can_write(dest):
            problems.append(f"{rel} would be copied through a link")
            continue
        if here:
            src_stat = os.stat(src)
            if not os.path.isfile(dest) or (
                os.stat(dest).st_size,
                os.stat(dest).st_mtime_ns,
            ) != (src_stat.st_size, src_stat.st_mtime_ns):
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                _make_writable(dest)
                shutil.copyfile(src, dest)
                os.utime(dest, ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns))
    _write_if_changed(os.path.join(out, VALUES_FNAME), plan.values)
    for dirpath, _, filenames in os.walk(out, topdown=False):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if Path(os.path.relpath(path, out)).as_posix() not in kept:
                _make_writable(path)
                os.remove(path)
        if dirpath != out and not os.listdir(dirpath):
            os.rmdir(dirpath)
    new_style = not os.path.isfile(style_path)
    _write_if_changed(
        style_path, calkit.resources.read_text("latex", STYLE_FNAME)
    )
    # Written whenever it's needed, so kept out of Git, wherever this runs
    if new_style:
        try:
            repo = calkit.git.get_repo(root)
            rel_style = os.path.relpath(
                os.path.abspath(style_path), repo.working_dir
            )
            if not repo.git.ls_files("--", rel_style):
                calkit.git.ensure_path_is_ignored(repo, rel_style)
        except Exception:
            pass
    return problems


def expand_ck_components(
    source_root: str, data_root: str, document: str
) -> None:
    """Replace calkit.sty's commands in a document and the files it inputs
    with what they show, read from ``data_root``, so latexdiff can mark a
    changed value, figure, or table.

    The sources are rewritten under ``source_root``, e.g., a checkout of a
    revision, and ``document`` is relative to it. A figure becomes an
    ``\\includegraphics`` of its file and a table its contents, and a value
    a ``\\cknum`` of the number, which calkit.sty formats. A command whose
    component can't be found is left alone, to print as ``??``.
    """
    from calkit.questions import read_evidence_file, resolve_key

    doc_dir = os.path.dirname(document)

    def is_file(rel: str) -> bool:
        path = os.path.join(data_root, rel)
        return os.path.isfile(path) and _within_project(path, data_root)

    def replace(match: re.Match[str]) -> str:
        kind, option, first, second = match.group(
            "kind", "option", "first", "second"
        )
        if "#" in first + (second or ""):
            return match.group(0)
        c = CkComponent(kind, first.strip(), (second or "").strip() or None)
        rel, _ = component_path(c, is_file)
        if rel is None:
            return match.group(0)
        if kind == "figure":
            name = posixpath.relpath(rel, doc_dir or ".")
            return f"\\includegraphics[{option or ''}]{{{name}}}"
        if kind == "table":
            return _read_leniently(os.path.join(data_root, rel)) or ""
        try:
            value = resolve_key(
                read_evidence_file(os.path.join(data_root, rel)), c.key or ""
            )
        except Exception:
            return match.group(0)
        value_kind, text = tex_value(value)
        if value_kind == "t":
            return text
        return f"\\cknum[{(option or '').strip()}]{{{text}}}"

    sources = [document] + [
        path
        for path in detect_inputs(document, wdir=source_root)
        if Path(path).suffix in _SOURCE_EXTS
    ]
    for source in dict.fromkeys(sources):
        path = Path(source_root, source)
        text = _read_leniently(str(path))
        if text is None:
            continue
        # Comments are set aside, marked by their number, so a command split
        # across lines is still found, but none in a comment
        comments: list[str] = []
        code_lines = []
        for line in text.split("\n"):
            m = re.search(r"(?<!\\)%", line)
            if m:
                code_lines.append(f"{line[: m.start()]}\0{len(comments)}\0")
                comments.append(line[m.start() :])
            else:
                code_lines.append(line)
        new_text = re.sub(
            "\0(\\d+)\0",
            lambda m: comments[int(m.group(1))],
            _CK_COMMAND_RE.sub(replace, "\n".join(code_lines)),
        )
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")


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
# An author-year citation as rendered, e.g., "(Smith et al., 2020; Lee,
# 2021a)", or the year of a textual one
_CITATION_RE = re.compile(r"\((?=[^()]*\b(?:1[5-9]|20)\d\d[a-z]?\b)[^()]*\)")
# A sectioning command, which renders as a paragraph of its own
_HEADING_RE = re.compile(
    r"^\s*\\(part|chapter|section|subsection|subsubsection)\*?"
    r"(\[[^\]]*\])?\{"
)
# A macro defined without arguments, through its body's opening brace
_MACRO_DEF_RE = re.compile(
    r"\\(?:(?:re)?newcommand|providecommand|DeclareRobustCommand)\*?\s*"
    r"(?:\{\s*\\([A-Za-z@]+)\s*\}|\\([A-Za-z@]+))\s*\{"
    r"|\\def\s*\\([A-Za-z@]+)\s*\{"
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
# Markdown, where review comments can be kept too, in HTML comments
_MARKDOWN_EXTS = (".md", ".markdown")
_MD_COMMENT_RE = re.compile(r"^[ ]{0,3}<!--")
_MD_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
_MD_HEADING_RE = re.compile(r"^[ ]{0,3}#{1,6}(\s|$)")
# Inline math, $...$ or \\(...\\), but not $$
_INLINE_MATH_RE = re.compile(
    r"(?<![\\$])\$(?!\$)((?:\\.|[^$\\])+?)\$|\\\((.+?)\\\)", re.S
)
# Text-mode symbol commands, by name, and the characters they print
TEXT_SYMBOLS = {
    "textperthousand": "\u2030",
    "textdegree": "\u00b0",
    "textcelsius": "\u2103",
    "textmu": "\u00b5",
    "textpm": "\u00b1",
    "texttimes": "\u00d7",
    "textdiv": "\u00f7",
    "textendash": "\u2013",
    "textemdash": "\u2014",
    "textasciitilde": "~",
    "textbullet": "\u2022",
    "textsection": "\u00a7",
}
# And more that only print in text, e.g., \o, which isn't math
_DETEX_SYMBOLS = TEXT_SYMBOLS | {
    "textasciicircum": "^",
    "textbackslash": "\\",
    "textbar": "|",
    "textless": "<",
    "textgreater": ">",
    "textquoteleft": "\u2018",
    "textquoteright": "\u2019",
    "textquotedblleft": "\u201c",
    "textquotedblright": "\u201d",
    "textregistered": "\u00ae",
    "texttrademark": "\u2122",
    "textcopyright": "\u00a9",
    "copyright": "\u00a9",
    "textdagger": "\u2020",
    "dag": "\u2020",
    "textdaggerdbl": "\u2021",
    "ddag": "\u2021",
    "ldots": "\u2026",
    "dots": "\u2026",
    "textellipsis": "\u2026",
    "S": "\u00a7",
    "P": "\u00b6",
    "ss": "\u00df",
    "o": "\u00f8",
    "O": "\u00d8",
    "ae": "\u00e6",
    "AE": "\u00c6",
    "oe": "\u0153",
    "OE": "\u0152",
    "aa": "\u00e5",
    "AA": "\u00c5",
    "l": "\u0142",
    "L": "\u0141",
    "i": "\u0131",
    "LaTeX": "LaTeX",
    "TeX": "TeX",
}
# Accent commands, by the character naming them, as combining marks
_ACCENTS = {
    "`": "\u0300",
    "'": "\u0301",
    "^": "\u0302",
    "~": "\u0303",
    "=": "\u0304",
    "u": "\u0306",
    ".": "\u0307",
    '"': "\u0308",
    "r": "\u030a",
    "H": "\u030b",
    "v": "\u030c",
    "c": "\u0327",
    "k": "\u0328",
}
# siunitx unit and prefix macros, by name, as printed
_SI_PREFIXES = {
    "femto": "f",
    "pico": "p",
    "nano": "n",
    "micro": "\u00b5",
    "milli": "m",
    "centi": "c",
    "deci": "d",
    "kilo": "k",
    "mega": "M",
    "giga": "G",
}
_SI_UNITS = _SI_PREFIXES | {
    "kelvin": "K",
    "celsius": "\u00b0C",
    "degreeCelsius": "\u00b0C",
    "degree": "\u00b0",
    "percent": "%",
    "second": "s",
    "minute": "min",
    "hour": "h",
    "day": "d",
    "metre": "m",
    "meter": "m",
    "gram": "g",
    "kilogram": "kg",
    "mole": "mol",
    "ampere": "A",
    "hertz": "Hz",
    "newton": "N",
    "pascal": "Pa",
    "joule": "J",
    "watt": "W",
    "volt": "V",
    "ohm": "\u03a9",
    "litre": "L",
    "liter": "L",
    "electronvolt": "eV",
    "angstrom": "\u00c5",
    "dalton": "Da",
    "per": "/",
    "squared": "\u00b2",
    "cubed": "\u00b3",
}
# Where rendered text holds a reference or citation, e.g., "A.4" or "(Lee,
# 2020)", in prose from ``detex``
REF_MARK = "\ue010"
CITE_MARK = "\ue011"
# And a textual citation, e.g., "Lee (2020)"
TEXT_CITE_MARK = "\ue012"
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
    markdown: bool = False
    # The document's macros without arguments, by name, which render as
    # their text
    macros: dict[str, str] = field(default_factory=dict)
    # Before \begin{document}, so not rendered
    preamble: bool = False

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
        src = "\n".join(ln.text for ln in self.lines)
        if self.markdown:
            return demarkdown(src)
        return detex(expand_macros(src, self.macros))

    @property
    def inline_math(self) -> list[tuple[str, str, str]]:
        """Each piece of inline math, with the prose on either side of it as
        rendered: (before, LaTeX, after), the prose with a space next to
        the math where there's one in the source, and references and
        citations marked."""
        if self.display:
            return []
        src = _strip_comments_joined("\n".join(ln.text for ln in self.lines))
        found = list(_INLINE_MATH_RE.finditer(src))
        out = []
        for i, m in enumerate(found):
            start = found[i - 1].end() if i else 0
            end = found[i + 1].start() if i + 1 < len(found) else len(src)
            before, after = src[start : m.start()], src[m.end() : end]
            out.append(
                (
                    detex(expand_macros(before, self.macros), marks=True)
                    + (" " if re.search(r"[\s~]$", before) else ""),
                    m.group(1) or m.group(2),
                    (" " if re.match(r"[\s~]", after) else "")
                    + detex(expand_macros(after, self.macros), marks=True),
                )
            )
        return out

    @property
    def display(self) -> str | None:
        """The display math environment this block is, if any, e.g.,
        ``equation*``, or ``[`` for ``\\[``."""
        m = _DISPLAY_RE.match(self.lines[0].text)
        if m is None or self.markdown:
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
        src = "\n".join(_strip_comments(ln.text) for ln in self.lines)
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


def read_file(path: str) -> str | None:
    """A text file's contents, or None if there's no such file."""
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.is_file() else None


def is_markdown(path: str) -> bool:
    return path.lower().endswith(_MARKDOWN_EXTS)


def flatten(
    main_path: str, read: Callable[[str], str | None] = read_file
) -> list[SourceLine]:
    """Inline \\input and friends, keeping each line's file and number.

    Files are read with ``read``, e.g., to read them at a Git revision.
    Markdown inputs nothing.
    """
    main = Path(main_path)
    markdown = is_markdown(main_path)
    out: list[SourceLine] = []
    seen: set[str] = set()

    def visit(path: Path, base: Path) -> None:
        rel = path.as_posix()
        key = os.path.normpath(rel)
        text = None if key in seen else read(rel)
        if text is None:
            return
        seen.add(key)
        for i, line in enumerate(text.split("\n"), 1):
            m = None if markdown else _INCLUDE_RE.match(_strip_comments(line))
            if m:
                cmd, a, b = m.groups()
                target = Path(b) if cmd == "import" and b else Path(a)
                start = base / a if cmd == "import" else base
                child = start / target
                if child.suffix == "":
                    child = child.with_suffix(".tex")
                # TeX reads \input paths from where it compiles, and only
                # \import moves that to the imported file's folder
                visit(child, child.parent if cmd == "import" else base)
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


def macro_definitions(lines: list[SourceLine]) -> dict[str, str]:
    """The bodies of macros defined without arguments, by name, e.g.,
    ``{"tool": "Wake\\textendash Sim\\xspace"}``."""
    src = "\n".join(_strip_comments(ln.text) for ln in lines)
    out: dict[str, str] = {}
    for m in _MACRO_DEF_RE.finditer(src):
        name = m.group(1) or m.group(2) or m.group(3)
        # A later definition replaces an earlier one, but \providecommand
        # only defines what isn't yet
        provide = m.group(0).startswith("\\providecommand")
        # The body, through its matching brace
        depth, start = 0, m.end() - 1
        for i in range(start, len(src)):
            if src[i] == "{" and src[i - 1] != "\\":
                depth += 1
            elif src[i] == "}" and src[i - 1] != "\\":
                depth -= 1
                if depth == 0:
                    if not provide or name not in out:
                        out[name] = src[start + 1 : i]
                    break
    return out


def expand_macros(
    text: str, macros: dict[str, str], math: bool = False
) -> str:
    """``text`` with the macros in ``macros`` replaced by their bodies,
    outside math, which a converter expands itself, unless ``math``."""
    if not macros:
        return text
    pattern = re.compile(
        r"\\("
        + "|".join(re.escape(n) for n in sorted(macros, key=len, reverse=True))
        + r")(?![A-Za-z@])"
    )
    parts = [text] if math else re.split(r"(\$[^$]*\$)", text)
    for i in range(0, len(parts), 2):
        # Bodies can use other macros
        for _ in range(5):
            new = pattern.sub(lambda m: macros[m.group(1)], parts[i])
            if new == parts[i]:
                break
            parts[i] = new
    return "".join(parts)


def detex(text: str, marks: bool = False) -> str:
    """Roughly what LaTeX would print for a bit of source, with, if
    ``marks``, a reference as ``REF_MARK`` and a citation as ``CITE_MARK``,
    or ``TEXT_CITE_MARK`` for a textual one, since their text isn't
    known."""

    def render_units(tex: str) -> str:
        # Prefixes join the unit after them, e.g., \milli\second as "ms"
        out = re.sub(
            r"\\([A-Za-z]+)\s*",
            lambda m: (
                _SI_UNITS.get(m.group(1), m.group(1))
                + ("" if m.group(1) in _SI_PREFIXES else " ")
            ),
            tex,
        )
        return re.sub(r"[{}^~]", "", out).strip()

    text = _strip_comments_joined(text)
    # Line breaks first, so the word after one isn't taken for a command
    text = text.replace("\\\\", " ")
    # Escaped characters print as themselves, held aside from the math and
    # braces below
    text = re.sub(
        r"\\([$%&#_{}])",
        lambda m: chr(0xE000 + "$%&#_{}".index(m.group(1))),
        text,
    )
    text = re.sub(r"\$[^$]*\$|\\\(.*?\\\)", " ", text, flags=re.S)
    if marks:
        text = re.sub(r"\\eqref\s*\{[^}]*\}", f"({REF_MARK})", text)
        text = re.sub(
            r"\\(?:auto|c|C|page|name)?ref\*?\s*\{[^}]*\}", REF_MARK, text
        )
        text = re.sub(
            r"\\(?:[Cc]ite(?:t|alt|author)|[Tt]extcite)\*?\s*"
            r"(\[[^\]]*\]\s*){0,2}\{[^}]*\}",
            TEXT_CITE_MARK,
            text,
        )
        # Any other citation, e.g., biblatex's \parencite, but \nocite,
        # which prints nothing
        text = re.sub(
            r"\\(?!nocite)[A-Za-z]*[Cc]ite[A-Za-z]*\*?\s*(\[[^\]]*\]\s*){0,2}"
            r"\{[^}]*\}",
            CITE_MARK,
            text,
        )
    text = re.sub(
        r"\\([A-Za-z]*[Cc]ite[A-Za-z]*|ref|eqref|label|includegraphics|"
        r"usepackage|"
        r"documentclass|bibliography\w*|begin|end)\*?(\[[^\]]*\]){0,2}"
        r"\{[^}]*\}",
        " ",
        text,
    )
    arg = r"\{((?:[^{}]|\{[^{}]*\})*)\}"
    opt = r"\s*(?:\[[^\]]*\])?\s*"
    # Chemistry, e.g., \ce{^{13}C} as "13C", and siunitx quantities, e.g.,
    # \SI{20}{\kelvin} as "20 K"
    text = re.sub(
        r"\\ce" + opt + arg, lambda m: re.sub(r"[{}^_]", "", m[1]), text
    )
    text = re.sub(
        r"\\(?:SIrange|qtyrange)" + opt + arg + r"\s*" + arg + r"\s*" + arg,
        lambda m: (
            f"{m[1]} {render_units(m[3])} to {m[2]} {render_units(m[3])}"
        ),
        text,
    )
    text = re.sub(r"\\numrange" + opt + arg + r"\s*" + arg, r"\1 to \2", text)
    text = re.sub(
        r"\\(?:SI|qty)" + opt + arg + r"\s*" + arg,
        lambda m: f"{m[1]} {render_units(m[2])}",
        text,
    )
    text = re.sub(
        r"\\(?:si|unit)" + opt + arg, lambda m: render_units(m[1]), text
    )
    text = re.sub(r"\\num" + opt + arg, r"\1", text)
    text = re.sub(r"\\href" + opt + arg + r"\s*" + arg, r"\2", text)
    # Accents, e.g., \'e or \"{o}, on the letter they go over
    text = re.sub(
        r"\\([`'^\"~=.])\s*(?:\{\s*([A-Za-z])\s*\}|([A-Za-z]))"
        r"|\\([uvHckr])(?:\s*\{\s*([A-Za-z])\s*\}|\s+([A-Za-z]))",
        lambda m: unicodedata.normalize(
            "NFC",
            (m[2] or m[3] or m[5] or m[6]) + _ACCENTS[m[1] or m[4]],
        ),
        text,
    )
    # Symbols, through the space after a command word, which TeX skips
    text = re.sub(
        r"\\(" + "|".join(_DETEX_SYMBOLS) + r")(?![A-Za-z])(\{\}|\s*)",
        lambda m: _DETEX_SYMBOLS[m[1]],
        text,
    )
    # Styled text prints as itself, with no space around it, e.g.,
    # \textit{ad}-hoc
    styled = re.compile(
        r"\\(?:text(?:it|bf|rm|sf|tt|sc|up|md|sl|normal|superscript|"
        r"subscript)?|emph|mbox|underline|uline)\s*\{([^{}]*)\}"
    )
    while True:
        new = styled.sub(r"\1", text)
        if new == text:
            break
        text = new
    text = re.sub(r"\\xspace(?![A-Za-z])\s*(?=[.,;:!?)\]}/'-])", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\[,;:! ]", " ", text)
    text = re.sub(r"\\[-/@]", "", text)
    text = re.sub(r"[{}~]", " ", text)
    text = text.replace("---", "\u2014").replace("--", "\u2013")
    text = text.replace("``", "\u201c").replace("''", "\u201d")
    text = re.sub(
        r"[\uE000-\uE006]", lambda m: "$%&#_{}"[ord(m[0]) - 0xE000], text
    )
    return re.sub(r"\s+", " ", text).strip()


def demarkdown(text: str) -> str:
    """Roughly what Pandoc would print for a bit of Markdown."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"^[ ]{0,3}(`{3,}|~{3,}).*$", " ", text, flags=re.M)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"^\s*(#{1,6}|[-*+]|\d+[.)]|>)\s+", "", text, flags=re.M)
    text = re.sub(r"[*`]|\b_|_\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def markdown_blocks(lines: list[SourceLine]) -> list[Block]:
    """Split Markdown into paragraph-sized blocks: paragraphs, headings, and
    fenced code. A Calkit directive belongs to what it precedes; other HTML
    comments, e.g., comment threads, to none."""
    out: list[Block] = []
    cur: list[SourceLine] = []
    # The fence that closes the code being read, if any
    fence: str | None = None
    # Whether the HTML comment being read, if any, is part of a block
    keep: bool | None = None

    def end() -> None:
        nonlocal cur
        if cur:
            out.append(Block(cur, markdown=True))
        cur = []

    for ln in lines:
        text = ln.text
        if fence is not None:
            cur.append(ln)
            if re.match(
                rf"^[ ]{{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$", text
            ):
                end()
                fence = None
            continue
        if keep is not None:
            if keep:
                cur.append(ln)
            if "-->" in text:
                keep = None
            continue
        if not text.strip():
            end()
            continue
        # A comment that takes up whole lines, unless it's a directive, is
        # like a LaTeX comment: inside a paragraph without ending it
        whole = _MD_COMMENT_RE.match(text) and not re.match(
            r"^\s*<!--.*?-->\s*\S", text
        )
        if whole:
            directive = re.match(r"^\s*<!--\s*calkit\s", text) is not None
            if cur or directive:
                cur.append(ln)
            if "-->" not in text:
                keep = bool(cur) or directive
            continue
        m = _MD_FENCE_RE.match(text)
        if m:
            fence = m.group(1)
            cur.append(ln)
            continue
        if _MD_HEADING_RE.match(text):
            end()
            cur.append(ln)
            end()
            continue
        cur.append(ln)
    end()
    return [b for b in out if b.text]


def blocks(lines: list[SourceLine]) -> list[Block]:
    """Split flattened source into paragraph-sized blocks."""
    out: list[Block] = []
    cur: list[SourceLine] = []
    # The text that closes the display math being read, if any
    closing: str | None = None
    # Whether cur is a heading, which ends after it and any labels
    heading = False
    for ln in lines:
        stripped, rest = ln.text.strip(), ln.text
        if heading and not (
            stripped
            and re.fullmatch(r"(\\label\{[^}]*\}\s*)*(%.*)?", stripped)
        ):
            if cur:
                out.append(Block(cur))
            cur, heading = [], False
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
        # Through its closing brace, so prose right after it is its own
        if (
            _HEADING_RE.match(ln.text)
            and _brace_depth(_strip_comments(ln.text)) == 0
        ):
            heading = True
    if cur:
        out.append(Block(cur))
    macros = macro_definitions(lines)
    begin = next(
        (
            i
            for i, ln in enumerate(lines)
            if re.match(r"\s*\\begin\{document\}", ln.text)
        ),
        0,
    )
    before = {id(ln) for ln in lines[:begin]}
    in_float: set[tuple[str, int]] = set()
    depth = 0
    for ln in lines:
        for m in _FLOAT_RE.finditer(_strip_comments(ln.text)):
            depth = max(0, depth + (1 if m.group(1) == "begin" else -1))
            if m.group(1) == "begin":
                in_float.add((ln.path, ln.lineno))
        if depth:
            in_float.add((ln.path, ln.lineno))
    for b in out:
        b.floating = (b.path, b.lineno) in in_float
        b.macros = macros
        b.preamble = id(b.lines[0]) in before
    return [b for b in out if b.text or b.display]


def _brace_depth(text: str) -> int:
    """How many more braces ``text`` opens than closes."""
    return len(re.findall(r"(?<!\\)\{", text)) - len(
        re.findall(r"(?<!\\)\}", text)
    )


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]{3,}", text.lower()))


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa) if wa else 0.0


def equation_fragment(text: str) -> bool:
    """Whether rendered text is a short piece of a display: with its
    number ending it, or anywhere in it with math, e.g.,
    "L = a, if x < τ (6) otherwise,", else with hardly any words and math
    or an unclosed parenthesis, e.g., "f("."""
    words = _words(text)
    math = re.search(r"[=≈<>≤≥∈∑∫|≪≫]", text) is not None
    number = re.search(r"\(([A-Z]\.?)?\d+(\.\d+)*[a-z]?\)(\s*$)?", text)
    if number is not None and len(words) < 4:
        return number.group(3) is not None or math
    return len(words) < 3 and (math or text.count("(") != text.count(")"))


def align(
    texts: list[str], blks: list[Block], threshold: float = 0.5
) -> list[Block | None]:
    """Match rendered paragraphs to source blocks, in order."""

    def score(text: str, j: int) -> tuple[float, bool, int, int]:
        b = blks[j]
        # A match on a few words can't skip ahead past prose, e.g., an
        # equation's "otherwise" to a later paragraph saying it, nor
        # reach a figure or table more than a few pages off
        skipped = abs(
            bisect.bisect_left(prose, j) - bisect.bisect_left(prose, last)
        )
        if skipped > (8 if b.floating else 2) and (
            len(_words(text) & _words(b.text)) < 4
        ):
            return (0.0, False, 0, j)
        # Of the preamble, only the title and authors render
        if b.preamble and not any(
            re.match(r"\s*\\(title|author|date)\b", ln.text) for ln in b.lines
        ):
            return (0.0, False, 0, j)
        # On a tie, a block the paragraph is the whole of, e.g., a
        # heading over a caption using its words, then the nearest, so
        # a short heading can't jump ahead to a later paragraph, nor a
        # table's cell to another table
        return (
            similarity(text, b.text),
            similarity(b.text, text) >= 0.8,
            -min(abs(j - last), abs(j - recent)),
            j,
        )

    out: list[Block | None] = []
    # The block the prose has reached, and the last matched, which can be
    # a figure or table
    last = recent = 0
    floats = [j for j, b in enumerate(blks) if b.floating]
    # Prose blocks, by index, for how far a match jumps ahead, not counting
    # the preamble's, of which only the title and authors render
    prose = [
        j
        for j, b in enumerate(blks)
        if not b.floating and not b.preamble and b.text
    ]
    for text in texts:
        fragment = equation_fragment(text)
        # Author-year citations render as names the source doesn't have
        text = _CITATION_RE.sub(" ", text)
        # A figure or table can be anywhere, since it floats, and doesn't
        # move the place in the source the prose has reached
        candidates = sorted(set(range(last, len(blks))) | set(floats))
        best = max(
            (score(text, j) for j in candidates), default=(0.0, False, 0, 0)
        )
        # A display's fragment, even when it shares a word with the prose
        # around it, unless it's the whole of a block, e.g., a heading with
        # math
        if fragment and not (best[1] and best[0] >= threshold):
            out.append(None)
            continue
        # A table's rows or a caption's lines stay with it on a tie, e.g.,
        # a row "Growth rate k 0.05" beside prose about the growth rate,
        # unless the paragraph is the whole of the other, e.g., a heading
        prev = next((b for b in reversed(out) if b is not None), None)
        if (
            prev is not None
            and prev.floating
            and best[0] >= threshold
            and similarity(text, prev.text) >= best[0]
            and (not best[1] or similarity(prev.text, text) >= 0.8)
        ):
            out.append(prev)
            continue
        if best[0] >= threshold:
            out.append(blks[best[3]])
            recent = best[3]
            if not blks[best[3]].floating:
                last = best[3]
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


def keep_letters_and_digits(text: str) -> str:
    """Text without anything but its letters and digits, lowercased, to
    compare however words split, e.g., "300K" and "300 K"."""
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in text if c.isalnum())


# A citation as rendered in brackets, e.g., "[Lee, 2018]" or "[3, 4]"
_BRACKET_CITATION_RE = re.compile(
    r"\[(?:[^\[\]]*\b(?:1[5-9]|20)\d\d[a-z]?\b[^\[\]]*|"
    r"\d+(?:\s*[,\u2013-]\s*\d+)*)\]"
)


def already_applied(block: Block, old: str, new: str) -> bool:
    """Whether the block already reads as ``new`` rather than ``old``: each
    change, with a word or two either side, reads as new and not as old,
    since a common word, e.g., "the", is anywhere."""

    def holds(seq: list[str]) -> bool:
        return any(keep_letters_and_digits(" ".join(seq)) in h for h in have)

    # Without the rendered citations both have, which the source has as
    # commands, but with any that changed, e.g., "(June 2019)"
    cites = [
        c
        for r in (_CITATION_RE, _BRACKET_CITATION_RE)
        for c in r.findall(old)
        if c in new
    ]
    for c in cites:
        old, new = old.replace(c, " "), new.replace(c, " ")
    # As rendered, with its inline math as text or not, as Word may have it
    have = [keep_letters_and_digits(block.text)]
    if not block.markdown:
        src = _strip_comments_joined("\n".join(ln.text for ln in block.lines))
        src = _INLINE_MATH_RE.sub(
            lambda m: f" {get_math_text(m.group(1) or m.group(2))} ", src
        )
        have.append(
            keep_letters_and_digits(detex(expand_macros(src, block.macros)))
        )
    ow = re.findall(r"[A-Za-z0-9][\w.]*", old)
    nw = re.findall(r"[A-Za-z0-9][\w.]*", new)
    ops = difflib.SequenceMatcher(None, ow, nw, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if not any(
            holds(nw[max(0, j1 - n) : j2 + n])
            and not holds(ow[max(0, i1 - n) : i2 + n])
            for n in (2, 1)
        ):
            return False
    return True


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
            # Anchor on the words before, widened until unique, braces
            # allowed between them, else on the words after
            hits, after = None, True
            for phrases in (
                [ow[i1 - k : i1] for k in range(1, i1 + 1)],
                [ow[i1 : i1 + k] for k in range(1, len(ow) - i1 + 1)],
            ):
                for phrase in phrases:
                    pattern = (
                        r"(?<![A-Za-z])"
                        + r"[\s~{}]+".join(re.escape(w) for w in phrase)
                        + r"(?![A-Za-z])"
                    )
                    found = list(re.finditer(pattern, src))
                    if len(found) == 1:
                        hits = found
                        break
                    if not found:
                        break
                if hits is not None:
                    break
                after = False
            if hits is None:
                return None
            # Already there, as from merging this before
            there = r"[\s~{}]+".join(re.escape(w) for w in nw[j1:j2])
            if after:
                at = hits[0].end()
                if re.match(rf"[\s~{{}}]*{there}(?![A-Za-z])", src[at:]):
                    continue
                src = src[:at] + " " + new_span + src[at:]
            else:
                at = hits[0].start()
                if re.search(rf"(?<![A-Za-z]){there}[\s~{{}}]*$", src[:at]):
                    continue
                src = src[:at] + new_span + " " + src[at:]
            continue
        span = _find_span(src, ow[i1:i2])
        if span is not None:
            src = src[: span[0]] + new_span + src[span[1] :]
            continue
        through = _edit_through_markup(src, " ".join(ow[i1:i2]), new_span)
        if through is None:
            return None
        src = through
    # A line emptied by a deletion goes, since a blank line would split
    # the paragraph
    return [ln.rstrip() for ln in src.split("\n") if ln.strip()]


def _edit_through_markup(src: str, old: str, new: str) -> str | None:
    """``src`` with the one place reading as ``old`` once its markup is
    left out, e.g., \\ce{^{15}N} for "15N", changed to read as ``new``, where
    the changed characters sit together in the source, and not in math,
    which is edited as an equation."""
    markup = r"(?:\\[A-Za-z]+\*?\s*|[{}^_])*"
    pattern = "".join(
        r"[\s~]+" if c == " " else f"({re.escape(c)})" + markup
        for c in old.rstrip()
    )
    found = list(
        re.finditer(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", src)
    )
    if len(found) != 1 or old != old.rstrip():
        return None
    m, chars = found[0], [c for c in old if c != " "]
    if any(
        x.start() < m.end() and m.start() < x.end()
        for x in _INLINE_MATH_RE.finditer(src)
    ):
        return None
    at = [m.start(k + 1) for k in range(len(chars))]
    old_c, new_c = "".join(chars), new.replace(" ", "")
    if new.count(" ") != old.count(" "):
        return None
    ops = difflib.SequenceMatcher(None, old_c, new_c, autojunk=False)
    for tag, i1, i2, j1, j2 in reversed(ops.get_opcodes()):
        if tag == "equal":
            continue
        if tag == "insert":
            pos = at[i1 - 1] + 1 if i1 else at[0]
            src = src[:pos] + new_c[j1:j2] + src[pos:]
            continue
        # Only characters next to each other in the source
        if any(at[k + 1] != at[k] + 1 for k in range(i1, i2 - 1)):
            return None
        src = src[: at[i1]] + new_c[j1:j2] + src[at[i2 - 1] + 1 :]
    return src


_MATH_TOKEN_RE = re.compile(r"\\[a-zA-Z]+|\\.|\S")
_MATH_FUNCTIONS = (
    "arccos arcsin arctan arg cos cosh cot coth det exp lg lim ln log max "
    "min sec sin sinh sup tan tanh"
).split()
# A math alphabet command and the group it styles, without nested groups
_MATH_ALPHABET_RE = re.compile(
    r"\\(mathcal|mathbf|mathit|mathsf|mathtt|mathbb|mathfrak|mathscr|"
    r"boldsymbol|bm)\s*\{([^{}]*)\}"
)
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
        r"\\(" + "|".join(_MATH_FUNCTIONS) + r")(?![a-zA-Z])", r" \1 ", tex
    )
    tex = tex.replace("{}", "")
    # Pandoc versions read the same accent back differently
    for wide, accent in (
        ("widehat", "hat"),
        ("widetilde", "tilde"),
        ("overrightarrow", "vec"),
    ):
        tex = re.sub(rf"\\{wide}(?![a-zA-Z])", rf"\\{accent}", tex)

    def letters_only(m: re.Match[str]) -> str:
        # A math alphabet styles letters, so symbols at the ends of its
        # group, which Word joins it to on saving, e.g., \mathcal{\in E,},
        # go outside
        tokens = _MATH_TOKEN_RE.findall(m.group(2))
        letter = [
            bool(re.fullmatch(r"[A-Za-z0-9]", t))
            or t.lstrip("\\").lower().removeprefix("var") in _GREEK
            for t in tokens
        ]
        if not any(letter):
            return m.group(0)
        i, j = letter.index(True), len(letter) - letter[::-1].index(True)
        core = " ".join(tokens[i:j])
        return " ".join(
            tokens[:i] + [f"\\{m.group(1)}{{{core}}}"] + tokens[j:]
        )

    tex = _MATH_ALPHABET_RE.sub(letters_only, tex)
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

    The first entry is the comment itself, the rest are replies. In
    Markdown, the thread is an HTML comment, with the lines LaTeX would
    have after their ``%``.
    """

    entries: list[Entry]
    highlight: str | None = None
    highlight_occ: int = 0
    resolved: bool = False
    lineno: int = 0
    nlines: int = 0
    # Stable across edits, so other tools can refer to the thread
    id: str | None = None
    # Where the thread is tracked as an issue, e.g., on GitHub
    issue: str | None = None
    # Attributes this version doesn't know, kept so they survive a rewrite
    attrs: dict[str, Any] = field(default_factory=dict)
    markdown: bool = False

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

        # Text that would end a Markdown thread's HTML comment early
        def safe(text: str) -> str:
            return text.replace("-->", "-- >") if self.markdown else text

        def fmt(value: Any) -> str:
            if isinstance(value, dict):
                items = [f"{k}: {json.dumps(v)}" for k, v in value.items()]
                return "{" + ", ".join(items) + "}"
            if isinstance(value, bool):
                return str(value).lower()
            s = str(value)
            return s if re.fullmatch(r'[^\s"{}]+', s) else json.dumps(s)

        attrs = []
        if self.id:
            attrs.append(f"id={fmt(self.id)}")
        if self.resolved:
            attrs.append("resolved=true")
        if self.issue:
            attrs.append(f"issue={fmt(self.issue)}")
        if self.highlight:
            value = f"text: {json.dumps(self.highlight)}"
            if self.highlight_occ:
                value += f", occ: {self.highlight_occ}"
            attrs.append("highlight={" + value + "}")
        attrs += [f"{k}={fmt(v)}" for k, v in self.attrs.items()]
        first, indent = (
            ("<!-- COMMENT", "  ")
            if self.markdown
            else (
                "% COMMENT",
                "%   ",
            )
        )
        out = [first]
        # Attributes continue onto their own lines when they don't fit
        for attr in map(safe, attrs):
            if len(out[-1]) + 1 + len(attr) <= 79 or out[-1] == first:
                out[-1] += " " + attr
            else:
                out.append(indent + attr)
        for e in self.entries:
            out.append(indent + safe(e.header()))
            out += textwrap.wrap(
                safe(e.text),
                width=79,
                initial_indent=indent + "  ",
                subsequent_indent=indent + "  ",
            )
        if self.markdown:
            out.append("-->")
        return out


def parse_comments(lines: list[str]) -> list[TexComment]:
    """Comment blocks in a file's lines, with their position and extent,
    in LaTeX or Markdown."""
    out: list[TexComment] = []
    # The fence of the Markdown code being read, if any, where a thread is
    # only shown, e.g., as an example. LaTeX's are found regardless, so a
    # stray line of backticks can't hide them.
    fence: str | None = None
    i = 0
    while i < len(lines):
        if fence is None and (m := _MD_FENCE_RE.match(lines[i])):
            fence = m.group(1)
        elif fence is not None and re.match(
            rf"^[ ]{{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$",
            lines[i],
        ):
            fence = None
        markdown = (
            fence is None
            and re.match(r"<!-- COMMENT( |$)", lines[i]) is not None
        )
        if not markdown and not re.match(r"% COMMENT( |$)", lines[i]):
            i += 1
            continue
        start = i
        header = lines[i].split("COMMENT", 1)[1]
        # The lines after the marker, as LaTeX has them after its %
        body_lines = []
        i += 1
        if markdown:
            end = next(
                (j for j in range(i, len(lines)) if "-->" in lines[j]), None
            )
            if "-->" in header or end is None:
                continue
            body_lines = [" " + ln for ln in lines[i:end]]
            body_lines.append(" " + lines[end].split("-->")[0])
            i = end + 1
        else:
            while i < len(lines) and re.match(r"%(   |$)", lines[i]):
                body_lines.append(lines[i][1:])
                i += 1
        entries: list[Entry] = []
        for body in body_lines:
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
        if entries:
            attrs = _parse_header(header)
            highlight = attrs.pop("highlight", None)
            if isinstance(highlight, dict):
                text, occ = highlight.get("text"), highlight.get("occ", 0)
            else:
                text, occ = highlight, 0
            id_, issue = attrs.pop("id", None), attrs.pop("issue", None)
            out.append(
                TexComment(
                    entries,
                    str(text) if text else None,
                    int(occ or 0),
                    str(attrs.pop("resolved", "")).lower() == "true",
                    start + 1,
                    i - start,
                    id=str(id_) if id_ else None,
                    issue=str(issue) if issue else None,
                    attrs=attrs,
                    markdown=markdown,
                )
            )
    return out


def new_comment_id() -> str:
    import secrets

    return secrets.token_hex(4)


def find_comment(
    lines: list[str], id: str | None = None, lineno: int | None = None
) -> TexComment | None:
    """A thread by its ID or by the number of any line in it."""
    for tc in parse_comments(lines):
        if (id is not None and tc.id == id) or (
            lineno is not None and tc.lineno <= lineno < tc.lineno + tc.nlines
        ):
            return tc
    return None


def file_blocks(path: str, lines: list[str]) -> list[Block]:
    """The blocks of one file on its own, without following its inputs."""
    if is_markdown(path):
        return markdown_blocks(
            [SourceLine(path, i, text) for i, text in enumerate(lines, 1)]
        )
    return blocks(
        [
            SourceLine(path, i, text)
            for i, text in enumerate(lines, 1)
            if not _INCLUDE_RE.match(_strip_comments(text))
        ]
    )


def comment_anchor(blks: list[Block], tc: TexComment) -> Block | None:
    """The block a thread is about, from its file's blocks: the first one
    below it."""
    return next((b for b in blks if b.lineno >= tc.lineno + tc.nlines), None)


_GREEK = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu "
    "xi pi rho sigma tau upsilon phi chi psi omega"
).split()


def display_text(block: Block) -> str:
    """A display's math roughly as it reads in a PDF, e.g., to find it by
    what was selected there."""
    src = "\n".join(_strip_comments(ln.text) for ln in block.lines)
    return get_math_text(
        re.sub(r"\\(label|tag\*?|begin|end)\{[^}]*\}", " ", src)
    )


def get_math_text(tex: str) -> str:
    """Math roughly as it reads rendered: its symbols, without commands,
    grouping, or wrappers, and Greek letters and operator names, e.g.,
    \\ln, as themselves."""

    def greek(m: re.Match) -> str:
        name = m.group(1)
        case = "CAPITAL" if name[0].isupper() else "SMALL"
        # Unicode spells lambda without its b
        upper = name.upper().replace("LAMBDA", "LAMDA")
        return unicodedata.lookup(f"GREEK {case} LETTER {upper}")

    tex = re.sub(
        r"\\(" + "|".join(_GREEK + [g.capitalize() for g in _GREEK]) + r")"
        r"(?![A-Za-z])",
        greek,
        tex,
    )
    names = set(_MATH_FUNCTIONS) | {
        "inf",
        "liminf",
        "limsup",
        "deg",
        "dim",
        "ker",
        "gcd",
        "hom",
        "Pr",
    }
    tex = re.sub(
        r"\\("
        + "|".join(sorted(names, key=len, reverse=True))
        + r")(?![A-Za-z])",
        r" \1 ",
        tex,
    )
    tex = tex.replace("\\hbar", "\u210f").replace("\\ell", "\u2113")
    tex = re.sub(r"\\[a-zA-Z]+\*?|\\.|[{}^_&$]", " ", tex)
    return " ".join(tex.split())


def _math_chars(text: str) -> str:
    """Math text without spacing, and with what typesetting changes, e.g.,
    a minus sign for a hyphen, undone."""
    import unicodedata

    text = unicodedata.normalize("NFKC", text).replace("\u2212", "-")
    return "".join(text.split())


def comment_to_dict(
    path: str, tc: TexComment, blks: list[Block]
) -> dict[str, Any]:
    """A thread as `calkit list comments --json` reports it, with the
    paragraph it's about from its file's blocks."""
    anchor = comment_anchor(blks, tc)
    return {
        "id": tc.id,
        "path": path,
        "line": tc.lineno,
        "nlines": tc.nlines,
        "resolved": tc.resolved,
        "issue": tc.issue,
        "highlight": (
            {"text": tc.highlight, "occ": tc.highlight_occ}
            if tc.highlight
            else None
        ),
        "anchor": (
            {
                "line": anchor.lineno,
                "end_line": anchor.lines[-1].lineno,
                "text": anchor.text or display_text(anchor),
            }
            if anchor is not None
            else None
        ),
        "messages": [
            {
                "author": e.author,
                "email": e.email,
                "date": e.date,
                "text": e.text,
            }
            for e in tc.entries
        ],
        "attrs": tc.attrs,
    }


def list_comments(
    main_path: str, read: Callable[[str], str | None] = read_file
) -> list[dict[str, Any]]:
    """Every thread in a document and the files it inputs, in document
    order, so threads in an input come where it's input."""
    order = {
        (ln.path, ln.lineno): i
        for i, ln in enumerate(flatten(main_path, read))
    }
    out = []
    for path in dict.fromkeys(p for p, _ in order):
        lines = (read(path) or "").split("\n")
        blks = file_blocks(path, lines)
        out += [
            comment_to_dict(path, tc, blks) for tc in parse_comments(lines)
        ]
    out.sort(key=lambda c: order.get((c["path"], c["line"]), 0))
    return out


def comment_documents(ck_info: dict) -> list[str]:
    """The documents the pipeline builds into PDFs, whose threads, with
    those in the files they input, are the project's: each latex stage's,
    and each markdown stage's with a PDF."""
    out = []
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    for stage in stages.values():
        if not isinstance(stage, dict) or not stage.get("target_path"):
            continue
        if stage.get("kind") == "latex":
            target = Path(stage.get("wdir") or "", stage["target_path"])
        elif stage.get("kind") == "markdown" and stage.get("pdf"):
            target = Path(stage["target_path"])
        else:
            continue
        out.append(target.as_posix())
    return list(dict.fromkeys(out))


def find_comment_path(ck_info: dict, id: str) -> str | None:
    """The file with a thread, by its ID, among the project's documents and
    the files they input."""
    for doc in comment_documents(ck_info):
        for path in dict.fromkeys(ln.path for ln in flatten(doc)):
            lines = (read_file(path) or "").split("\n")
            if find_comment(lines, id=id) is not None:
                return path
    return None


def locate_block(
    main_path: str,
    text: str | None = None,
    path: str | None = None,
    lineno: int | None = None,
    read: Callable[[str], str | None] = read_file,
) -> Block | None:
    """The paragraph some rendered text is in, e.g., a line of a PDF, or
    the one a source line is in or just above.

    Each file is split into blocks on its own, as comments are added to
    them.
    """
    blks = [
        b
        for p in dict.fromkeys(ln.path for ln in flatten(main_path, read))
        for b in file_blocks(p, (read(p) or "").split("\n"))
    ]
    if text is not None:
        # The best share of its words, then the shortest paragraph, since
        # a long one shares words with anything
        scored = [(similarity(text, b.text), -len(b.text), b) for b in blks]
        best = max(scored, key=lambda x: x[:2], default=None)
        if best is not None and best[0] >= 0.5:
            return best[2]
        # Math has few words or none, so a display is matched by its
        # symbols, without its equation number
        want = _math_chars(
            re.sub(r"\(\s*([A-Z]\.)?\d+(\.\d+)*\s*\)\s*$", "", text)
        )
        if not want:
            return None
        math_scored = [
            (
                difflib.SequenceMatcher(
                    a=want, b=_math_chars(display_text(b)), autojunk=False
                ).ratio(),
                b,
            )
            for b in blks
            if b.display
        ]
        top = max(math_scored, key=lambda x: x[0], default=None)
        return top[1] if top is not None and top[0] >= 0.6 else None
    path = path or main_path
    return next(
        (
            b
            for b in blks
            if b.path == path and b.lines[-1].lineno >= (lineno or 0)
        ),
        None,
    )


def add_comment(lines: list[str], lineno: int, tc: TexComment) -> None:
    """Put a thread above the block at or after a line, below any threads
    already there, editing the lines in place."""
    blks = file_blocks(".md" if tc.markdown else "", lines)
    blk = next((b for b in blks if b.lines[-1].lineno >= lineno), None)
    if blk is None:
        raise ValueError(f"No paragraph at or after line {lineno}")
    rendered = tc.render()
    lines[blk.lineno - 1 : blk.lineno - 1] = rendered
    tc.lineno, tc.nlines = blk.lineno, len(rendered)


def write_comment(lines: list[str], tc: TexComment) -> None:
    """Write a parsed thread back over its own lines, in place."""
    rendered = tc.render()
    lines[tc.lineno - 1 : tc.lineno - 1 + tc.nlines] = rendered
    tc.nlines = len(rendered)


def localize_synctex(
    synctex_path: str, source_dir: str, wdir: str = "."
) -> bool:
    """Point a SyncTeX file at the sources as they sit here.

    A build in a container records the container's paths, e.g.,
    ``/work/paper/main.tex``, so reverse search in a viewer lands on a file
    that doesn't exist. Each such input is matched to a project file by its
    longest trailing part that exists, so nothing needs to know where the
    container mounted the project. A relative input is relative to
    ``source_dir``, where latexmk ran. Anything else, e.g., a class file
    from the TeX distribution, is left alone.

    Returns whether the file was changed.
    """
    import gzip

    if not os.path.isfile(synctex_path):
        return False
    root = Path(wdir).resolve()

    def local(raw: str) -> str | None:
        if not os.path.isabs(raw):
            candidate = Path(source_dir, raw).resolve()
            return candidate.as_posix() if candidate.is_file() else None
        if os.path.isfile(raw):
            return None
        parts = Path(os.path.normpath(raw)).as_posix().split("/")
        for i in range(len(parts)):
            rel = "/".join(parts[i:])
            if rel and not rel.startswith("..") and (root / rel).is_file():
                return (root / rel).as_posix()
        return None

    opener: Any = gzip.open if synctex_path.endswith(".gz") else open
    try:
        with opener(synctex_path, "rt", errors="replace") as f:
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
    with opener(synctex_path, "wt") as f:
        f.write("\n".join(lines))
    return True
