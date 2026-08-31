"""Working with LaTeX documents."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from calkit.core import LOCAL_DIR

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
DIFF_AUX_DIR = os.path.join(DIFF_TMP_DIR, "aux")
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


def _is_immutable_ref(repo: git.Repo, ref: str | None) -> bool:
    """Whether a ref names something that can't change under us.

    A tag or a commit hash pins content; a branch or the working tree
    doesn't. Only a diff between two of the former can be built once and
    left alone.
    """
    if ref is None:
        return False
    if ref in [tag.name for tag in repo.tags]:
        return True
    if ref in [head.name for head in repo.heads]:
        return False
    if not re.fullmatch(r"[0-9a-f]{7,40}", ref):
        return False
    try:
        repo.commit(ref)
    except Exception:
        return False
    return True


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


def collect_provenance(
    target_path: str,
    ck_info: dict,
    wdir: str | None = None,
    artifact_path: str | None = None,
    kind: str = "publication",
) -> dict:
    """Turn the build's ``.ckprov`` log into the document's provenance record.

    Every component the document took from the project, with the pages it
    appears on and the stage, inputs and hash of what it came from, so a
    reader or a tool can follow any number or figure in the PDF back
    through the pipeline. Written beside the PDF as
    ``<document>.provenance.json``.
    """
    wdir = wdir or os.getcwd()
    tex_dir = os.path.dirname(target_path)
    log_path = os.path.join(
        wdir, os.path.splitext(target_path)[0] + PROVENANCE_LOG_EXT
    )
    uses: dict[tuple[str, str, str], dict] = {}
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
                key = (entry.get("kind", ""), rel, str(entry.get("key", "")))
                use = uses.setdefault(
                    key,
                    {
                        "kind": key[0],
                        "path": rel,
                        "key": key[2] or None,
                        "pages": [],
                    },
                )
                page = entry.get("page")
                if page is not None and page not in use["pages"]:
                    use["pages"].append(page)
    records = {
        r["path"]: r
        for r in artifact_records(
            sorted({u["path"] for u in uses.values()}), ck_info, wdir
        )
    }
    from calkit.components import LocalProject

    view = LocalProject(ck_info, wdir, check_stages=False)
    components = []
    for use in uses.values():
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
        evidence_name,
        is_value_evidence,
        read_evidence_file,
        resolve_key,
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
            if not is_value_evidence(ev):
                continue
            data = read_evidence_file(os.path.join(wdir, ev["path"]))
            values[evidence_name(ev) or ""] = (
                resolve_key(data, ev["key"]),
                ev["path"],
                stage_for(ev["path"], ck_info),
            )

        def render_tex(text: str | None) -> str:
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
