"""Working with LaTeX documents."""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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


DOCX_EXPORTS_DIR = os.path.join(".calkit", "latex", "docx-exports")
DOCX_MERGES_DIR = os.path.join(".calkit", "latex", "docx-merges")
# Word bookmark names: 40 chars max, letters/digits/underscores
_INCLUDE_RE = re.compile(
    r"^\s*\\(input|include|subfile|import)\{([^}]*)\}(?:\{([^}]*)\})?"
)
_BLOCK_START_RE = re.compile(
    r"^\s*\\(begin|end|section|subsection|subsubsection|chapter|part|item|"
    r"caption|maketitle|documentclass)\b"
)


@dataclass
class SourceLine:
    path: str
    lineno: int
    text: str


@dataclass
class Block:
    """A run of source lines that renders as one Word paragraph."""

    lines: list[SourceLine]

    @property
    def path(self) -> str:
        return self.lines[0].path

    @property
    def lineno(self) -> int:
        return self.lines[0].lineno

    @property
    def text(self) -> str:
        return detex("\n".join(ln.text for ln in self.lines))


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
    for ln in lines:
        stripped = ln.text.strip()
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
    return [b for b in out if b.text]


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
    for text in texts:
        scores = [
            (similarity(text, b.text), j)
            for j, b in enumerate(blks[last:], last)
        ]
        best = max(scores, default=(0.0, -1))
        if best[0] >= threshold:
            out.append(blks[best[1]])
            last = best[1]
        else:
            out.append(None)
    return out


def bookmark_name(path: str, lineno: int) -> str:
    digest = hashlib.sha1(path.encode()).hexdigest()[:8]
    return f"ck_{digest}_{lineno}"


def find_block(
    blks: list[Block], path: str, lineno: int, text: str
) -> Block | None:
    """The block a bookmark points at, by line first and text second."""
    same_file = [b for b in blks if b.path == path]
    for b in same_file:
        if b.lineno == lineno and similarity(text, b.text) >= 0.5:
            return b
    scored = [
        (similarity(text, b.text), -abs(b.lineno - lineno), b)
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


_ATTR_RE = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')


def _attrs(line: str) -> dict[str, str]:
    return {k: q or bare for k, q, bare in _ATTR_RE.findall(line)}


@dataclass
class TexComment:
    """A comment thread in the source: entries of (author, text), the
    first being the comment itself, above the paragraph it's about."""

    entries: list[tuple[str, str]]
    highlight: str | None = None
    resolved: bool = False
    lineno: int = 0
    nlines: int = 0

    @property
    def author(self) -> str:
        return self.entries[0][0]

    @property
    def text(self) -> str:
        return self.entries[0][1]

    @property
    def replies(self) -> list[tuple[str, str]]:
        return self.entries[1:]

    def render(self) -> list[str]:
        head = "% COMMENT"
        if self.highlight:
            head += ' highlight="%s"' % self.highlight.replace('"', "'")
        if self.resolved:
            head += " resolved=true"
        out = [head]
        for author, text in self.entries:
            out.append(f"%   {author}:")
            out += textwrap.wrap(
                text,
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
        attrs = _attrs(lines[i])
        entries: list[tuple[str, str]] = []
        i += 1
        while i < len(lines) and re.match(r"%(   |$)", lines[i]):
            body = lines[i][1:]
            indent = len(body) - len(body.lstrip())
            if indent == 3 and body.rstrip().endswith(":"):
                entries.append((body.strip()[:-1], ""))
            elif indent > 3 and entries:
                author, text = entries[-1]
                entries[-1] = (author, (text + " " + body.strip()).strip())
            i += 1
        if entries:
            out.append(
                TexComment(
                    entries,
                    attrs.get("highlight"),
                    attrs.get("resolved") == "true",
                    start + 1,
                    i - start,
                )
            )
    return out
