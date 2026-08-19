"""Functionality for working with runnable Markdown files.

A Markdown file can declare pipeline stages and environments by annotating
its code blocks, so a README can be the source of truth for what it
documents. An annotated block looks like::

    ```python calkit stage name=example environment=main
    print("hello")
    ```

The first token of a fence's info string stays the language, since
Markdown renderers use it for syntax highlighting and ignore the rest.
Annotations can also be written as an HTML comment directive immediately
preceding a block, which keeps long attribute lists out of the info string
and lets a plain bulleted list declare an environment's dependencies::

    <!-- calkit environment name=main python=3.13 -->
    - numpy
    - matplotlib
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import ruamel.yaml

DirectiveKind = Literal["stage", "environment"]
DIRECTIVE_KINDS: tuple[str, ...] = ("stage", "environment")
BlockSource = Literal["fence", "list"]

# A fence is at least three backticks or tildes, optionally indented. Only
# the run of fence characters and the info string that follows are captured;
# the run's length matters because a longer fence can contain shorter ones,
# which is how a Markdown file documents this very feature without
# declaring the examples it shows.
_FENCE_RE = re.compile(
    r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$"
)
_LIST_ITEM_RE = re.compile(r"^[ ]{0,3}[-*+][ ]+(?P<item>.*?)\s*$")
_COMMENT_OPEN_RE = re.compile(r"^[ ]{0,3}<!--\s*(?P<body>.*)$")

_yaml = ruamel.yaml.YAML(typ="safe")


class MarkdownParseError(ValueError):
    """Raised when a Calkit annotation in a Markdown file can't be read."""

    def __init__(self, message: str, path: str | None = None, line: int = 0):
        self.path = path
        self.line = line
        where = f"{path}:{line}" if path else f"line {line}"
        super().__init__(f"{where}: {message}")


@dataclass
class MarkdownBlock:
    """A Calkit-annotated block extracted from a Markdown file."""

    kind: DirectiveKind
    attrs: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    language: str | None = None
    source: BlockSource = "fence"
    # 1-indexed line at which the block's annotation starts, for error
    # messages that point back at what the author wrote.
    line: int = 0

    @property
    def name(self) -> str | None:
        name = self.attrs.get("name")
        return None if name is None else str(name)


def _split_value(text: str, i: int) -> tuple[str, int]:
    """Read one attribute value out of ``text`` starting at index ``i``.

    Values may be bracketed or braced (and so contain whitespace, as in
    ``outputs=[{path: fig.png, storage: git}]``), quoted, or a bare token
    running to the next whitespace.
    """
    openers = {"[": "]", "{": "}", "(": ")"}
    if text[i] in openers:
        depth = 0
        quote: str | None = None
        start = i
        while i < len(text):
            c = text[i]
            if quote is not None:
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c in openers:
                depth += 1
            elif c in openers.values():
                depth -= 1
                if depth == 0:
                    return text[start : i + 1], i + 1
            i += 1
        raise ValueError(f"Unbalanced '{text[start]}' in attribute value")
    if text[i] in "\"'":
        quote = text[i]
        start = i
        i += 1
        while i < len(text):
            if text[i] == quote:
                return text[start : i + 1], i + 1
            i += 1
        raise ValueError("Unterminated quote in attribute value")
    start = i
    while i < len(text) and not text[i].isspace():
        i += 1
    return text[start:i], i


def parse_attrs(text: str) -> dict[str, Any]:
    """Parse ``key=value`` attributes from an annotation.

    Values are read as YAML flow scalars, so ``outputs=[{path: fig.png,
    storage: git}]`` becomes real data without a bespoke grammar. A bare
    key with no ``=`` is a flag and parses as ``True``.
    """
    attrs: dict[str, Any] = {}
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        key_start = i
        while i < len(text) and not text[i].isspace() and text[i] != "=":
            i += 1
        key = text[key_start:i]
        if not key:
            raise ValueError(f"Empty attribute name near '{text[i:][:20]}'")
        if i < len(text) and text[i] == "=":
            i += 1
            if i >= len(text) or text[i].isspace():
                raise ValueError(f"Attribute '{key}' has no value")
            raw, i = _split_value(text, i)
            try:
                value = _yaml.load(raw)
            except Exception as e:
                raise ValueError(
                    f"Failed to parse value for attribute '{key}': {raw}"
                ) from e
        else:
            value = True
        if key in attrs:
            raise ValueError(f"Duplicate attribute '{key}'")
        attrs[key] = value
    return attrs


def parse_annotation(text: str) -> tuple[DirectiveKind, dict[str, Any]] | None:
    """Parse a ``calkit <kind> ...`` annotation, if ``text`` is one.

    Returns ``None`` when the text isn't a Calkit annotation at all, which
    is the common case: an ordinary fence info string like ``python`` or a
    normal HTML comment.
    """
    tokens = text.strip().split(None, 1)
    if not tokens:
        return None
    if tokens[0] != "calkit":
        return None
    rest = tokens[1] if len(tokens) > 1 else ""
    parts = rest.split(None, 1)
    if not parts or parts[0] not in DIRECTIVE_KINDS:
        raise ValueError(
            "Calkit annotation must name a directive "
            f"({', '.join(DIRECTIVE_KINDS)}), got: {rest or '(nothing)'}"
        )
    kind: DirectiveKind = "stage" if parts[0] == "stage" else "environment"
    return kind, parse_attrs(parts[1] if len(parts) > 1 else "")


def _parse_fence_info(
    info: str,
) -> tuple[str | None, tuple[DirectiveKind, dict[str, Any]] | None]:
    """Split a fence info string into its language and Calkit annotation.

    Renderers take the first token as the language and ignore the rest, so
    ``python calkit stage name=x`` still highlights as Python on GitHub.
    """
    info = info.strip()
    if not info:
        return None, None
    tokens = info.split(None, 1)
    if tokens[0] == "calkit":
        return None, parse_annotation(info)
    language = tokens[0]
    rest = tokens[1] if len(tokens) > 1 else ""
    return language, parse_annotation(rest)


def _read_comment_directive(
    lines: list[str], i: int
) -> tuple[tuple[DirectiveKind, dict[str, Any]] | None, int]:
    """Read an HTML comment directive starting at line ``i``.

    Returns the parsed annotation (or ``None`` if this comment isn't one)
    and the index of the first line after the comment. Comments may span
    multiple lines so a long attribute list doesn't have to.
    """
    m = _COMMENT_OPEN_RE.match(lines[i])
    if m is None:
        return None, i
    body_parts = []
    j = i
    body = m.group("body")
    while True:
        end = body.find("-->")
        if end != -1:
            body_parts.append(body[:end])
            j += 1
            break
        body_parts.append(body)
        j += 1
        if j >= len(lines):
            # An unterminated comment isn't ours to complain about; the file
            # is just Markdown with a typo, and every renderer swallows it.
            return None, i + 1
        body = lines[j]
    return parse_annotation(" ".join(body_parts)), j


def _read_list_items(lines: list[str], i: int) -> tuple[list[str], int]:
    """Read a run of bullet list items starting at line ``i``."""
    items = []
    while i < len(lines):
        m = _LIST_ITEM_RE.match(lines[i])
        if m is None:
            break
        items.append(m.group("item"))
        i += 1
    return items, i


def parse_markdown(text: str, path: str | None = None) -> list[MarkdownBlock]:
    """Extract Calkit-annotated blocks from Markdown text.

    Unannotated fences are inert, which is what makes it safe to keep
    shell snippets and deliberately-wrong examples in the same file.
    """
    lines = text.splitlines()
    blocks: list[MarkdownBlock] = []
    pending: tuple[DirectiveKind, dict[str, Any]] | None = None
    pending_line = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        fence_match = _FENCE_RE.match(line)
        if fence_match is not None:
            fence = fence_match.group("fence")
            indent = len(fence_match.group("indent"))
            try:
                language, annotation = _parse_fence_info(
                    fence_match.group("info")
                )
            except ValueError as e:
                raise MarkdownParseError(str(e), path=path, line=i + 1)
            # Collect the body, closing only on a fence of the same
            # character that is at least as long as the opening one. A
            # shorter run inside is content, which is how this feature gets
            # documented in Markdown without the examples going live.
            body: list[str] = []
            j = i + 1
            while j < len(lines):
                close = _FENCE_RE.match(lines[j])
                if (
                    close is not None
                    and close.group("fence")[0] == fence[0]
                    and len(close.group("fence")) >= len(fence)
                    and not close.group("info").strip()
                ):
                    break
                body.append(lines[j][indent:] if indent else lines[j])
                j += 1
            if annotation is not None or pending is not None:
                try:
                    kind, attrs = _merge(pending, annotation)
                except ValueError as e:
                    raise MarkdownParseError(str(e), path=path, line=i + 1)
                blocks.append(
                    MarkdownBlock(
                        kind=kind,
                        attrs=attrs,
                        content="\n".join(body),
                        language=language,
                        source="fence",
                        line=pending_line if pending is not None else i + 1,
                    )
                )
            pending = None
            i = j + 1
            continue
        if pending is not None:
            if not line.strip():
                i += 1
                continue
            items, end = _read_list_items(lines, i)
            if items:
                blocks.append(
                    MarkdownBlock(
                        kind=pending[0],
                        attrs=pending[1],
                        content="\n".join(items),
                        language=None,
                        source="list",
                        line=pending_line,
                    )
                )
                pending = None
                i = end
                continue
            raise MarkdownParseError(
                "A Calkit directive comment must be followed by a fenced "
                "code block or a bulleted list",
                path=path,
                line=pending_line,
            )
        try:
            annotation, end = _read_comment_directive(lines, i)
        except ValueError as e:
            raise MarkdownParseError(str(e), path=path, line=i + 1)
        if annotation is not None:
            pending = annotation
            pending_line = i + 1
            i = end
            continue
        i += 1
    if pending is not None:
        raise MarkdownParseError(
            "A Calkit directive comment must be followed by a fenced code "
            "block or a bulleted list",
            path=path,
            line=pending_line,
        )
    return blocks


def _merge(
    pending: tuple[DirectiveKind, dict[str, Any]] | None,
    annotation: tuple[DirectiveKind, dict[str, Any]] | None,
) -> tuple[DirectiveKind, dict[str, Any]]:
    """Combine a preceding comment directive with a fence's own annotation.

    The comment exists to carry attributes too long for an info string, so
    the two are additive; a key given twice is an authoring mistake rather
    than something to silently resolve.
    """
    if pending is None:
        assert annotation is not None
        return annotation
    if annotation is None:
        return pending
    if pending[0] != annotation[0]:
        raise ValueError(
            f"Directive comment declares a '{pending[0]}' but the code "
            f"block declares a '{annotation[0]}'"
        )
    attrs = dict(pending[1])
    for key, value in annotation[1].items():
        if key in attrs:
            raise ValueError(
                f"Attribute '{key}' is set in both the directive comment "
                "and the code block"
            )
        attrs[key] = value
    return pending[0], attrs


def parse_markdown_file(path: str) -> list[MarkdownBlock]:
    """Extract Calkit-annotated blocks from a Markdown file."""
    with open(path, encoding="utf-8") as f:
        return parse_markdown(f.read(), path=Path(path).as_posix())


# Fence languages Calkit knows how to run, and the extension its extracted
# script needs so the ordinary script-stage machinery can execute it.
LANGUAGE_EXTENSIONS: dict[str, str] = {
    "python": ".py",
    "py": ".py",
    "r": ".R",
    "julia": ".jl",
    "jl": ".jl",
    "sh": ".sh",
    "bash": ".sh",
    "zsh": ".sh",
    "matlab": ".m",
    "octave": ".m",
}

# The stage kind each language compiles to. A Markdown stage is extracted
# to a real script, so it reuses the existing script stages rather than
# needing a runtime of its own.
LANGUAGE_STAGE_KINDS: dict[str, str] = {
    ".py": "python-script",
    ".R": "r-script",
    ".jl": "julia-script",
    ".sh": "shell-script",
    ".m": "matlab-script",
}


@dataclass
class MarkdownStageSpec:
    """One stage declared across a Markdown file's annotated blocks."""

    name: str
    language: str
    attrs: dict[str, Any]
    content: str
    script_path: str
    # 1-indexed line of the stage's first block, for error messages
    line: int = 0

    @property
    def stage_kind(self) -> str:
        return LANGUAGE_STAGE_KINDS[LANGUAGE_EXTENSIONS[self.language]]


def get_stage_script_path(
    markdown_path: str, stage_name: str, language: str, as_posix: bool = True
) -> str:
    """Return the path of the script extracted for a Markdown stage.

    Stages depend on this derived file rather than on the Markdown itself,
    so editing prose doesn't invalidate anything and editing a code block
    invalidates only the stage that block belongs to.
    """
    ext = LANGUAGE_EXTENSIONS[language]
    md_dir = os.path.dirname(markdown_path)
    md_stem = os.path.basename(markdown_path).removesuffix(".md")
    p = os.path.join(".calkit", "markdown", md_dir, md_stem, stage_name + ext)
    if as_posix:
        p = Path(p).as_posix()
    return p


def extract_stages(
    blocks: list[MarkdownBlock], markdown_path: str
) -> dict[str, MarkdownStageSpec]:
    """Group annotated blocks into stages, concatenating by name.

    Blocks sharing a name join in document order, which is what lets one
    example be narrated across several code blocks and still run as a
    single script.
    """
    path = Path(markdown_path).as_posix()
    specs: dict[str, MarkdownStageSpec] = {}
    for block in blocks:
        if block.kind != "stage":
            continue
        name = block.name
        if not name:
            raise MarkdownParseError(
                "A stage block must declare a name", path=path, line=block.line
            )
        if block.language is None:
            raise MarkdownParseError(
                f"Stage '{name}' has a code block with no language, so "
                "Calkit can't tell how to run it",
                path=path,
                line=block.line,
            )
        language = block.language.lower()
        if language not in LANGUAGE_EXTENSIONS:
            raise MarkdownParseError(
                f"Stage '{name}' uses language '{block.language}', which "
                "Calkit can't run; supported languages are "
                f"{', '.join(sorted(set(LANGUAGE_EXTENSIONS)))}",
                path=path,
                line=block.line,
            )
        attrs = {k: v for k, v in block.attrs.items() if k != "name"}
        spec = specs.get(name)
        if spec is None:
            specs[name] = MarkdownStageSpec(
                name=name,
                language=language,
                attrs=attrs,
                content=block.content,
                script_path=get_stage_script_path(path, name, language),
                line=block.line,
            )
            continue
        if language != spec.language:
            raise MarkdownParseError(
                f"Stage '{name}' mixes languages '{spec.language}' and "
                f"'{language}'; a stage becomes one script, so its blocks "
                "must share a language",
                path=path,
                line=block.line,
            )
        for key, value in attrs.items():
            if key in spec.attrs and spec.attrs[key] != value:
                raise MarkdownParseError(
                    f"Stage '{name}' sets attribute '{key}' to conflicting "
                    f"values ({spec.attrs[key]!r} and {value!r})",
                    path=path,
                    line=block.line,
                )
            spec.attrs[key] = value
        spec.content += "\n\n" + block.content
    return specs


def write_stage_scripts(
    specs: dict[str, MarkdownStageSpec], wdir: str | None = None
) -> list[str]:
    """Write out each stage's extracted script, returning changed paths.

    Only files whose content actually differs are rewritten, since these
    are stage dependencies and a needless touch is a needless rerun.
    """
    changed = []
    for spec in specs.values():
        fpath = spec.script_path
        if wdir is not None:
            fpath = os.path.join(wdir, fpath)
        content = spec.content
        if not content.endswith("\n"):
            content += "\n"
        if os.path.isfile(fpath):
            with open(fpath, encoding="utf-8") as f:
                if f.read() == content:
                    continue
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        changed.append(spec.script_path)
    return changed
