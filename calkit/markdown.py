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

DirectiveKind = Literal["stage", "environment", "output"]
# ``output`` blocks are written to, never read: a stage's extracted script
# must not include what that stage printed, or injecting output would make
# the stage stale, which would rerun it, which would inject again.
DIRECTIVE_KINDS: tuple[str, ...] = ("stage", "environment", "output")
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
    kind: DirectiveKind
    if parts[0] == "stage":
        kind = "stage"
    elif parts[0] == "environment":
        kind = "environment"
    else:
        kind = "output"
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


# Parsed blocks, keyed by path and what the file looked like when read.
# Project info is expanded several times over a single status---once to
# check environments, once to compile, once for the status itself---and
# parsing dominates that work, so the same unchanged file would otherwise
# be read and scanned each time.
_PARSE_CACHE: dict[str, tuple[tuple[int, int], list[MarkdownBlock]]] = {}


def parse_markdown_file(path: str) -> list[MarkdownBlock]:
    """Extract Calkit-annotated blocks from a Markdown file.

    The returned blocks are shared between callers, so they must be read
    rather than modified.
    """
    key = Path(path).as_posix()
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    if stamp is not None:
        cached = _PARSE_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    with open(path, encoding="utf-8") as f:
        blocks = parse_markdown(f.read(), path=key)
    if stamp is not None:
        _PARSE_CACHE[key] = (stamp, blocks)
    return blocks


# Separator between a Markdown stage's own name and the name of a stage it
# declares, e.g. ``README.md/example``. DVC reserves ``@`` for the names it
# generates from a matrix, and a hand-written one is unaddressable: even
# ``dvc stage list`` refuses the file. ``:`` is no good either, since DVC
# splits a target on the first colon to find the dvc.yaml it belongs to.
STAGE_NAME_SEPARATOR = "/"


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
    # The extension is kept, so 'README.md' and 'README.markdown' don't
    # both derive into a directory named 'README'
    md_name = os.path.basename(markdown_path)
    p = os.path.join(".calkit", "markdown", md_dir, md_name, stage_name + ext)
    if as_posix:
        p = Path(p).as_posix()
    return p


def get_output_cache_path(
    markdown_path: str, stage_name: str, as_posix: bool = True
) -> str:
    """Return the path caching what a stage's output block claims.

    Stages depend on this rather than on it being an output, because
    output is injected after the pipeline has already run---nothing the
    stage command itself writes could satisfy an output declaration. As a
    dependency, an output block edited by hand makes its stage stale,
    which is what stops the file from quietly claiming something untrue.
    """
    md_dir = os.path.dirname(markdown_path)
    md_name = os.path.basename(markdown_path)
    p = os.path.join(
        ".calkit", "markdown", "outputs", md_dir, md_name, stage_name + ".txt"
    )
    if as_posix:
        p = Path(p).as_posix()
    return p


def extract_outputs(
    blocks: list[MarkdownBlock], markdown_path: str
) -> dict[str, str]:
    """Collect the output blocks in a Markdown file, keyed by stage name."""
    path = Path(markdown_path).as_posix()
    outputs: dict[str, str] = {}
    for block in blocks:
        if block.kind != "output":
            continue
        # 'stage' reads better on an output block than 'name' would, since
        # the block is not itself the stage
        name = block.attrs.get("stage") or block.attrs.get("name")
        if not name:
            raise MarkdownParseError(
                "An output block must name the stage it belongs to, e.g. "
                "'calkit output stage=my-stage'",
                path=path,
                line=block.line,
            )
        if str(name) in outputs:
            raise MarkdownParseError(
                f"Stage '{name}' has more than one output block",
                path=path,
                line=block.line,
            )
        outputs[str(name)] = block.content
    return outputs


def write_output_caches(
    outputs: dict[str, str], markdown_path: str, wdir: str | None = None
) -> dict[str, str]:
    """Write each output block's content to its cache file.

    Returns a map of stage name -> cache path.
    """
    paths = {}
    for stage_name, content in outputs.items():
        rel = get_output_cache_path(markdown_path, stage_name)
        paths[stage_name] = rel
        fpath = os.path.join(wdir, rel) if wdir is not None else rel
        text = (
            content
            if content.endswith("\n") or not content
            else (content + "\n")
        )
        if os.path.isfile(fpath):
            with open(fpath, encoding="utf-8") as f:
                if f.read() == text:
                    continue
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return paths


def prune_derived_files(
    markdown_path: str,
    stage_names: list[str],
    output_stage_names: list[str],
    wdir: str | None = None,
) -> list[str]:
    """Delete derived files for stages the Markdown no longer declares.

    Renaming or removing a stage would otherwise leave its extracted
    script and cached output behind, where they look like part of the
    project.
    """
    md_dir = os.path.dirname(markdown_path)
    md_name = os.path.basename(markdown_path)
    expected = {
        os.path.join(".calkit", "markdown", md_dir, md_name): {
            name + ext
            for name in stage_names
            for ext in set(LANGUAGE_EXTENSIONS.values())
        },
        os.path.join(".calkit", "markdown", "outputs", md_dir, md_name): {
            name + ".txt" for name in output_stage_names
        },
    }
    removed = []
    for rel_dir, keep in expected.items():
        dpath = os.path.join(wdir, rel_dir) if wdir is not None else rel_dir
        if not os.path.isdir(dpath):
            continue
        for fname in sorted(os.listdir(dpath)):
            fpath = os.path.join(dpath, fname)
            if not os.path.isfile(fpath) or fname in keep:
                continue
            os.remove(fpath)
            removed.append(Path(os.path.join(rel_dir, fname)).as_posix())
    return removed


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


def get_stage_names(markdown_path: str, stage_name: str) -> list[str]:
    """Return the names of the pipeline stages a Markdown file declares.

    Used to resolve a target naming the file as a whole (``calkit run
    README.md``) into the stages it stands for, since those are what DVC
    knows about.
    """
    blocks = parse_markdown_file(markdown_path)
    specs = extract_stages(blocks, Path(markdown_path).as_posix())
    return [stage_name + STAGE_NAME_SEPARATOR + name for name in specs]


def get_markdown_stage_targets(ck_info: dict) -> dict[str, tuple[str, str]]:
    """Map what a user might type at a markdown stage to that stage.

    Keys are both the stage's name and the Markdown file's path, so a
    stage keyed by something other than its path can be named either way.
    Values are ``(stage_name, markdown_path)``.
    """
    targets: dict[str, tuple[str, str]] = {}
    stages = ck_info.get("pipeline", {}).get("stages", {})
    if not isinstance(stages, dict):
        return targets
    for name, cfg in stages.items():
        if not isinstance(cfg, dict) or cfg.get("kind") != "markdown":
            continue
        path = Path(str(cfg.get("target_path") or name)).as_posix()
        targets[name] = (name, path)
        targets[path] = (name, path)
    return targets


# Environment kinds that can be declared in Markdown, and the spec file
# each one is written to. A list of packages means something different to
# each toolchain, so the kind decides how the list is rendered.
ENV_SPEC_FILENAMES: dict[str, str] = {
    "uv-venv": "requirements.txt",
    "uv": "pyproject.toml",
    "conda": "environment.yml",
    "renv": "DESCRIPTION",
    "julia": "Project.toml",
}

# Which environment kind a stage's language implies, so a Markdown file
# declaring one environment for R or Julia code needn't spell it out.
LANGUAGE_ENV_KINDS: dict[str, str] = {
    # uv over uv-venv for Python: near enough the same interface, with a
    # better lock file
    "python": "uv",
    "py": "uv",
    "r": "renv",
    "julia": "julia",
    "jl": "julia",
}


def _env_definition(env: dict) -> dict:
    """Return the parts of an environment that define it.

    The description is a generated annotation saying where the
    environment came from, so two entries differing only there are the
    same environment.
    """
    return {k: v for k, v in dict(env).items() if k != "description"}


def get_env_spec_path(
    env_name: str, kind: str = "uv-venv", as_posix: bool = True
) -> str:
    """Return the path of the spec file written for a Markdown environment.

    This lives alongside the specs Calkit already generates when it
    detects an environment for a stage, so the environment is an ordinary
    one by the time anything else looks at it.
    """
    p = os.path.join(".calkit", "envs", env_name, ENV_SPEC_FILENAMES[kind])
    if as_posix:
        p = Path(p).as_posix()
    return p


def render_env_spec(
    kind: str, content: str, env_name: str, python: str | None = None
) -> str:
    """Render a Markdown environment block into its spec file's content.

    A fenced block is taken verbatim, since that's the escape hatch for
    anything the list form can't say. A bulleted list is a list of
    package names, which each toolchain spells differently, so it's
    rendered through the same builders Calkit uses when it detects
    dependencies itself.
    """
    import calkit.environments

    if kind == "uv-venv":
        return content
    deps = [line.strip() for line in content.splitlines() if line.strip()]
    if kind == "uv":
        kwargs = {} if python is None else {"python_version": python}
        return calkit.environments.create_uv_pyproject_content(
            deps, project_name=env_name, **kwargs
        )
    if kind == "conda":
        return calkit.environments.create_conda_environment_content(
            deps, project_name=env_name
        )
    if kind == "renv":
        return calkit.environments.create_r_description_content(
            deps, project_name=env_name
        )
    if kind == "julia":
        return calkit.environments.create_julia_project_file_content(
            deps, project_name=env_name
        )
    raise ValueError(f"Unsupported environment kind: {kind}")


def extract_environments(
    blocks: list[MarkdownBlock], markdown_path: str
) -> dict[str, dict]:
    """Collect the environment declarations in a Markdown file.

    The result is deliberately unfinished: an environment's kind can be
    left out and inferred from the language of the stages that use it, so
    the spec path and content aren't known until the stages are read too.
    Call ``resolve_environments`` to finish them.
    """
    path = Path(markdown_path).as_posix()
    envs: dict[str, dict] = {}
    for block in blocks:
        if block.kind != "environment":
            continue
        name = block.name
        if not name:
            raise MarkdownParseError(
                "An environment block must declare a name",
                path=path,
                line=block.line,
            )
        install = (
            parse_install_block(block.content, block.language)
            if block.source == "fence"
            else None
        )
        if name in envs:
            # Two blocks of install commands under one name are additive:
            # a README often installs in stages, or shows the same package
            # fetched two ways, and both describe one environment.
            previous = envs[name].get("_install")
            if install is None or previous is None:
                raise MarkdownParseError(
                    f"Environment '{name}' is declared more than once",
                    path=path,
                    line=block.line,
                )
            if install.kind == previous.kind:
                install = merge_install_specs([previous, install])
            else:
                install = previous
            envs[name]["_install"] = install
            envs[name]["_content"] = "\n".join(install.packages)
            continue
        attrs = {k: v for k, v in block.attrs.items() if k != "name"}
        kind = attrs.pop("kind", None)
        if kind is not None and str(kind) not in ENV_SPEC_FILENAMES:
            raise MarkdownParseError(
                f"Environment '{name}' has kind '{kind}'; environments "
                "declared in Markdown must be one of "
                f"{', '.join(sorted(ENV_SPEC_FILENAMES))}",
                path=path,
                line=block.line,
            )
        env: dict = {"_kind": None if kind is None else str(kind)}
        python = attrs.pop("python", None)
        if python is not None:
            env["python"] = str(python)
        julia = attrs.pop("julia", None)
        if julia is not None:
            env["_julia"] = str(julia)
        description = attrs.pop("description", None)
        if description is not None:
            env["description"] = str(description)
        if attrs:
            raise MarkdownParseError(
                f"Environment '{name}' has unrecognized attribute(s): "
                f"{', '.join(sorted(attrs))}",
                path=path,
                line=block.line,
            )
        # A fence is the escape hatch for anything the list form can't
        # say, so it's kept verbatim whatever the kind.
        env["_verbatim"] = block.source == "fence"
        env["_content"] = block.content
        env["_line"] = block.line
        # ...unless the fence is a command that installs the packages,
        # which is how a README normally says what its code needs. That
        # states the same thing imperatively, so it's read as a package
        # list, and the installer chosen says which kind of environment
        # it is.
        if install is not None:
            env["_install"] = install
            env["_verbatim"] = False
            env["_content"] = "\n".join(install.packages)
            if kind is None:
                env["_kind"] = install.kind
        envs[name] = env
    return envs


def resolve_environments(
    envs: dict[str, dict],
    specs: dict[str, MarkdownStageSpec],
    markdown_path: str,
    default_env: str | None = None,
    wdir: str | None = None,
) -> dict[str, dict]:
    """Finish environment declarations, inferring kinds where they're absent.

    An R or Julia README shouldn't have to name its environment's kind
    when the code blocks using it already say what language they are.
    """
    path = Path(markdown_path).as_posix()
    # Which languages each environment is used by
    langs_by_env: dict[str, set[str]] = {}
    for spec in specs.values():
        env_name = spec.attrs.get("environment", default_env)
        if env_name is None:
            continue
        langs_by_env.setdefault(str(env_name), set()).add(spec.language)
    for name, env in envs.items():
        kind = env["_kind"]
        if kind is None:
            langs = langs_by_env.get(name, set())
            kinds = {
                LANGUAGE_ENV_KINDS[lang]
                for lang in langs
                if lang in LANGUAGE_ENV_KINDS
            }
            if len(kinds) > 1:
                raise MarkdownParseError(
                    f"Environment '{name}' is used by stages in more than "
                    f"one language ({', '.join(sorted(langs))}); give it an "
                    "explicit kind",
                    path=path,
                    line=env["_line"],
                )
            kind = kinds.pop() if kinds else "uv"
            env["_kind"] = kind
        python = env.pop("python", None)
        if python is not None and kind not in ("uv-venv", "uv"):
            raise MarkdownParseError(
                f"Environment '{name}' is a '{kind}' environment, which "
                "takes no 'python' version",
                path=path,
                line=env["_line"],
            )
        # A uv environment has no 'python' field; its version is declared
        # by the pyproject.toml the spec is rendered into.
        if python is not None and kind == "uv-venv":
            env["python"] = python
        if python is not None and kind == "uv":
            env["_python"] = python
        julia = env.pop("_julia", None)
        if julia is not None and kind != "julia":
            raise MarkdownParseError(
                f"Environment '{name}' is a '{kind}' environment, which "
                "takes no 'julia' version",
                path=path,
                line=env["_line"],
            )
        if kind == "julia":
            if julia is None:
                raise MarkdownParseError(
                    f"Environment '{name}' is a Julia environment, which "
                    "needs a version, e.g. 'calkit environment "
                    f"name={name} julia=1.12'",
                    path=path,
                    line=env["_line"],
                )
            env["julia"] = julia
        install = env.pop("_install", None)
        # A dev install says the environment is this project, which some
        # spec file in the project directory already describes---so point
        # at that file rather than generating a second description of it
        is_dev = install is not None and (
            install.dev or installs_local_package(install, wdir=wdir)
        )
        dev_spec = resolve_dev_install(install, wdir=wdir) if is_dev else None
        if dev_spec is not None:
            kind, env["kind"] = dev_spec[0], dev_spec[0]
            env["path"] = dev_spec[1]
        elif install is not None and install.spec_path:
            # ...as does a command naming a spec file, when it is there
            spec_path = install.spec_path
            full = os.path.join(wdir, spec_path) if wdir else spec_path
            if os.path.isfile(full):
                env["path"] = Path(spec_path).as_posix()
            else:
                env["path"] = get_env_spec_path(name, kind=kind)
        else:
            env["path"] = get_env_spec_path(name, kind=kind)
        env["kind"] = kind
        if dev_spec is not None or env["path"] != get_env_spec_path(
            name, kind=kind
        ):
            # The spec is a file the project already keeps, so leave it be
            env["_spec_content"] = None
            env.setdefault("description", f"Declared in {path}.")
        elif env["_verbatim"]:
            env["_spec_content"] = env["_content"]
        else:
            env["_spec_content"] = render_env_spec(
                kind, env["_content"], name, python=python
            )
        if env["_spec_content"] is not None:
            # Say where this came from in the environment itself rather
            # than a YAML comment, which a user could delete without the
            # notice being restored. This mirrors the 'desc' Calkit
            # writes on DVC stages.
            env.setdefault(
                "description",
                f"Generated from {path}. "
                "Changes made here will be overwritten.",
            )
    return envs


def write_env_specs(envs: dict[str, dict], wdir: str | None = None) -> None:
    """Write each Markdown environment's spec file, if it changed.

    The spec is derived, but it is what ``uv`` reads and what the lock is
    resolved from, so it must be byte-stable or the lock churns on every
    compile.
    """
    for env in envs.values():
        # An environment that points at a spec file already in the project
        # -- what a dev install declares -- has nothing to generate
        if env.get("_spec_content") is None:
            continue
        # uv resolves its interpreter from a .python-version in the project
        # directory. Without one the version only floats above the
        # requires-python floor, so the environment isn't really pinned.
        python = env.get("_python")
        if python is not None:
            pv_path = os.path.join(
                os.path.dirname(env["path"]), ".python-version"
            )
            if wdir is not None:
                pv_path = os.path.join(wdir, pv_path)
            pv_content = str(python) + "\n"
            if not os.path.isfile(pv_path) or (
                open(pv_path, encoding="utf-8").read() != pv_content
            ):
                os.makedirs(os.path.dirname(pv_path), exist_ok=True)
                with open(pv_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(pv_content)
        content = env["_spec_content"]
        if not content.endswith("\n"):
            content += "\n"
        fpath = env["path"]
        if wdir is not None:
            fpath = os.path.join(wdir, fpath)
        if os.path.isfile(fpath):
            with open(fpath, encoding="utf-8") as f:
                if f.read() == content:
                    continue
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)


@dataclass
class MarkdownExpansion:
    """What a project's Markdown files contributed to its pipeline."""

    ck_info: dict
    script_paths: list[str] = field(default_factory=list)
    # Environment name -> definition, and the file that declared it
    environments: dict[str, dict] = field(default_factory=dict)
    environment_sources: dict[str, str] = field(default_factory=dict)
    # Pipeline stage name -> path caching that stage's output block
    output_cache_paths: dict[str, str] = field(default_factory=dict)
    # Derived files deleted because the Markdown no longer declares them
    removed_paths: list[str] = field(default_factory=list)


def expand_ck_info(
    ck_info: dict, wdir: str | None = None
) -> MarkdownExpansion:
    """Return project info with markdown stages replaced by what they declare.

    A markdown stage stands in for however many stages and environments
    its file declares. Expanding here rather than at compile time means
    everything that reads project info---environment checking, lock file
    paths, status filtering---sees ordinary stages and environments and
    needs no knowledge of Markdown.

    The input is not modified, so callers that go on to write
    ``calkit.yaml`` can't accidentally persist derived entries.

    Environments are returned as well as merged, because they have to be
    persisted to ``calkit.yaml``: a stage's command runs ``calkit xenv``
    as a subprocess, which reads the environment back off disk.
    """
    from copy import deepcopy

    stages = ck_info.get("pipeline", {}).get("stages", {})
    if not isinstance(stages, dict):
        return MarkdownExpansion(ck_info=ck_info)
    md_stage_names = [
        name
        for name, cfg in stages.items()
        if isinstance(cfg, dict) and cfg.get("kind") == "markdown"
    ]
    if not md_stage_names:
        return MarkdownExpansion(ck_info=ck_info)
    out = deepcopy(ck_info)
    out_stages = out["pipeline"]["stages"]
    out_envs = out.setdefault("environments", {})
    if not isinstance(out_envs, dict):
        raise ValueError("Project 'environments' must be a mapping")
    result = MarkdownExpansion(ck_info=out)
    for stage_name in md_stage_names:
        md_cfg = out_stages.pop(stage_name)
        # Markdown stages are removed here, before the pipeline is
        # validated, so nothing else would catch a typo'd key in one.
        from calkit.models.pipeline import MarkdownStage

        try:
            MarkdownStage.model_validate(dict(md_cfg) | {"name": stage_name})
        except Exception as e:
            raise ValueError(
                f"Markdown stage '{stage_name}' is not defined properly: {e}"
            )
        md_path = Path(str(md_cfg.get("target_path") or stage_name)).as_posix()
        read_path = os.path.join(wdir, md_path) if wdir else md_path
        if not os.path.isfile(read_path):
            raise ValueError(
                f"Markdown stage '{stage_name}' points at '{md_path}', "
                "which does not exist"
            )
        blocks = parse_markdown_file(read_path)
        envs = extract_environments(blocks, md_path)
        specs = extract_stages(blocks, md_path)
        if not specs:
            raise ValueError(
                f"Markdown stage '{stage_name}' declares no stages; "
                "annotate a code block with 'calkit stage name=<name>' "
                "to define one"
            )
        # A file declaring exactly one environment shouldn't have to name
        # it on every block.
        default_env = md_cfg.get("environment")
        if default_env is None and len(envs) == 1:
            default_env = next(iter(envs))
        # Kinds can be inferred from the languages of the stages using
        # each environment, so this needs both halves read first.
        envs = resolve_environments(
            envs, specs, md_path, default_env=default_env, wdir=wdir
        )
        for env_name, env in envs.items():
            public = {k: v for k, v in env.items() if not k.startswith("_")}
            existing = out_envs.get(env_name)
            # An identical entry is this same definition written back on
            # an earlier compile, not a competing one.
            if existing is not None and _env_definition(
                existing
            ) != _env_definition(public):
                raise ValueError(
                    f"Environment '{env_name}' is declared in '{md_path}' "
                    "and differently in calkit.yaml; it can only be defined "
                    "in one place"
                )
            out_envs[env_name] = public
            result.environments[env_name] = public
            result.environment_sources[env_name] = md_path
        write_env_specs(envs, wdir=wdir)
        write_stage_scripts(specs, wdir=wdir)
        result.script_paths += [s.script_path for s in specs.values()]
        # An output block is cached to a file the stage depends on, so
        # editing the block by hand makes the stage stale rather than
        # leaving the file quietly claiming something untrue.
        outputs = extract_outputs(blocks, md_path)
        unknown = set(outputs) - set(specs)
        if unknown:
            raise ValueError(
                f"{md_path} has output block(s) for stage(s) that it does "
                f"not declare: {', '.join(sorted(unknown))}"
            )
        output_cache_paths = write_output_caches(outputs, md_path, wdir=wdir)
        result.output_cache_paths.update(
            {
                stage_name + STAGE_NAME_SEPARATOR + name: path
                for name, path in output_cache_paths.items()
            }
        )
        result.removed_paths += prune_derived_files(
            md_path,
            stage_names=list(specs),
            output_stage_names=list(outputs),
            wdir=wdir,
        )
        for spec in specs.values():
            sub_name = stage_name + STAGE_NAME_SEPARATOR + spec.name
            if sub_name in out_stages:
                raise ValueError(
                    f"Stage '{sub_name}' from '{md_path}' conflicts with an "
                    "existing pipeline stage"
                )
            sub: dict = {
                "kind": spec.stage_kind,
                "script_path": spec.script_path,
            }
            if md_cfg.get("wdir") is not None:
                sub["wdir"] = md_cfg["wdir"]
            sub.update(spec.attrs)
            cache_path = output_cache_paths.get(spec.name)
            if cache_path is not None:
                sub["inputs"] = list(sub.get("inputs", [])) + [cache_path]
            if "environment" not in sub:
                sub["environment"] = default_env or "_system"
            if spec.stage_kind == "shell-script" and "shell" not in sub:
                sub["shell"] = "sh" if spec.language == "sh" else spec.language
            out_stages[sub_name] = sub
    return result


# Languages whose dependencies Calkit can read out of the code itself.
# Shell and MATLAB have no import statements to go on, so stages in those
# languages keep whatever environment they were given.
# Fence languages whose content is a shell session rather than a program.
SHELL_LANGUAGES = frozenset(
    {"sh", "bash", "zsh", "shell", "console", "shell-session", "terminal"}
)

# Which environment kind each installer produces, and the language whose
# stages it therefore serves.
INSTALLER_ENV_KINDS: dict[str, str] = {
    "pip": "uv-venv",
    "uv-pip": "uv-venv",
    "uv": "uv",
    "conda": "conda",
    "julia": "julia",
    "r": "renv",
}
ENV_KIND_LANGUAGES: dict[str, str] = {
    "uv-venv": "python",
    "uv": "python",
    "conda": "python",
    "julia": "julia",
    "renv": "r",
}

# The spec file a dev install resolves to, in the order a language's
# toolchains are preferred when more than one is present.
DEV_INSTALL_SPECS: dict[str, list[tuple[str, str]]] = {
    "python": [
        ("uv", "pyproject.toml"),
        ("uv-venv", "requirements.txt"),
        ("conda", "environment.yml"),
    ],
    "julia": [("julia", "Project.toml")],
    "r": [("renv", "DESCRIPTION")],
}

# Options that consume the token after them, so their value isn't mistaken
# for a package name---``conda install -c conda-forge numpy`` asks for one
# package, not two.
_VALUE_OPTIONS = frozenset(
    {
        "-c",
        "--channel",
        "-n",
        "--name",
        "-p",
        "--prefix",
        "-f",
        "--file",
        "-r",
        "--requirement",
        "--python",
        "--index-url",
        "--extra-index-url",
        "--find-links",
        "--group",
        "--target",
        "--constraint",
    }
)
_SPEC_FILE_OPTIONS = frozenset({"-r", "--requirement", "-f", "--file"})


@dataclass
class InstallSpec:
    """What a block of install commands asks for."""

    kind: str
    packages: list[str] = field(default_factory=list)
    # Set when the command installs the project in the working directory
    # (``pip install -e .``, ``Pkg.develop(path=".")``, ``uv sync``), which
    # is an environment already described by a spec file on disk
    dev: bool = False
    # Set when the command names a spec file, as ``pip install -r`` does
    spec_path: str | None = None

    @property
    def language(self) -> str:
        return ENV_KIND_LANGUAGES[self.kind]


def _requirement_key(requirement: str) -> str:
    """Reduce a requirement to the package it names, for de-duplication.

    A README often shows the same install more than once---over SSH and
    over HTTPS, say---and those are alternatives, not two dependencies.
    """
    req = requirement.strip()
    # PEP 508 names the package before the URL it comes from
    m = re.match(r"^(?P<name>[A-Za-z0-9._-]+)\s*@\s*\S+$", req)
    if m is not None:
        return _normalize_package_name(m.group("name"))
    if "://" in req:
        name = req.rstrip("/").rsplit("/", 1)[-1]
        name = name.split("#")[0].split("?")[0]
        return _normalize_package_name(name.removesuffix(".git"))
    for sep in ["===", "==", ">=", "<=", "~=", "!=", ">", "<", "[", ";", "="]:
        req = req.split(sep)[0]
    return _normalize_package_name(req)


def _normalize_package_name(name: str) -> str:
    """Normalize a package name the way a package index would."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


# The prompts a session transcript writes before what was typed. ``pkg>``
# is missing on purpose: it marks Julia's package mode, so it is read
# rather than stripped.
_PROMPT_RE = re.compile(r"^(?:\$|%|>>>|\.\.\.|julia>|help\?>|shell>)\s+")
# What marks a block as a transcript of a session rather than a script:
# its output is interleaved with its input, so it can't be run as it
# stands, and Calkit leaves it alone rather than guessing which is which.
_TRANSCRIPT_RE = re.compile(r"^(?:>>>|\.\.\.|julia>|pkg>|help\?>|In \[\d+\]:)")


def is_repl_transcript(content: str) -> bool:
    """Determine whether a block is a session transcript, not a script."""
    return any(
        _TRANSCRIPT_RE.match(line.strip()) for line in content.splitlines()
    )


def _strip_prompt(line: str) -> str:
    """Drop the prompt a session transcript writes before what was typed."""
    stripped = line.strip()
    return _PROMPT_RE.sub("", stripped).strip()


def _parse_shell_install(line: str) -> InstallSpec | None:
    """Read one shell command as an install, or return None if it isn't."""
    import shlex

    try:
        tokens = shlex.split(line, comments=True)
    except ValueError:
        return None
    while tokens and tokens[0] in ("sudo", "!"):
        tokens = tokens[1:]
    if not tokens:
        return None
    installer: str | None = None
    dev = False
    rest: list[str] = []
    if tokens[0] in ("pip", "pip3") and tokens[1:2] == ["install"]:
        installer, rest = "pip", tokens[2:]
    elif tokens[:4] == ["python", "-m", "pip", "install"]:
        installer, rest = "pip", tokens[4:]
    elif tokens[0] == "uv" and tokens[1:2] == ["add"]:
        installer, rest = "uv", tokens[2:]
    elif tokens[:3] == ["uv", "pip", "install"]:
        installer, rest = "uv-pip", tokens[3:]
    elif tokens[0] == "uv" and tokens[1:2] in (["sync"], ["lock"]):
        # These operate on the project in the working directory, so what
        # they declare is that project's own environment
        installer, dev, rest = "uv", True, []
    elif tokens[0] in ("conda", "mamba", "micromamba"):
        if tokens[1:2] == ["install"]:
            installer, rest = "conda", tokens[2:]
        elif tokens[1:3] == ["env", "create"]:
            installer, rest = "conda", tokens[3:]
        elif tokens[1:2] == ["create"]:
            installer, rest = "conda", tokens[2:]
        else:
            return None
    if installer is None:
        return None
    packages: list[str] = []
    spec_path: str | None = None
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg.startswith("-"):
            flag, _, inline = arg.partition("=")
            if inline:
                if flag in _SPEC_FILE_OPTIONS:
                    spec_path = inline
                i += 1
                continue
            if flag in _VALUE_OPTIONS:
                if flag in _SPEC_FILE_OPTIONS and i + 1 < len(rest):
                    spec_path = rest[i + 1]
                i += 2
                continue
            i += 1
            continue
        if arg in (".", "./") or arg.startswith(("./", "../")):
            dev = True
        else:
            packages.append(arg)
        i += 1
    if not (packages or dev or spec_path):
        return None
    return InstallSpec(
        kind=INSTALLER_ENV_KINDS[installer],
        packages=packages,
        dev=dev,
        spec_path=spec_path,
    )


_JULIA_ADD_RE = re.compile(r"Pkg\.add\.?\((?P<args>.*)\)\s*$", re.DOTALL)
_JULIA_DEV_RE = re.compile(r"Pkg\.(?:develop|dev)\s*\(")
_JULIA_PKG_MODE_RE = re.compile(r"^(?:pkg>|julia>\s*\]|\])\s*(?P<rest>.*)$")
_QUOTED_RE = re.compile(r"""["']([^"']+)["']""")
# Statements that say "use the project here" rather than fetch something
_JULIA_PROJECT_CALLS = ("Pkg.instantiate(", "Pkg.activate(", "Pkg.resolve(")
_JULIA_NOOP_CALLS = ("Pkg.status(", "Pkg.precompile(", "Pkg.update(")


def _parse_julia_install(content: str) -> InstallSpec | None:
    """Read a Julia block as ``Pkg`` calls, or return None if it isn't one."""
    packages: list[str] = []
    dev = False
    saw_install = False
    for statement in _install_statements(content, separators=";"):
        mode = _JULIA_PKG_MODE_RE.match(statement)
        if mode is not None:
            rest = mode.group("rest").split()
            if rest[:1] == ["add"]:
                packages += rest[1:]
                saw_install = True
                continue
            if rest[:1] in (["dev"], ["develop"]):
                dev = True
                saw_install = True
                continue
            if rest[:1] in (["instantiate"], ["activate"], ["resolve"]):
                dev = True
                saw_install = True
                continue
            return None
        if statement in ("using Pkg", "import Pkg"):
            continue
        if statement.startswith(_JULIA_NOOP_CALLS):
            continue
        if statement.startswith(_JULIA_PROJECT_CALLS):
            dev = True
            saw_install = True
            continue
        if _JULIA_DEV_RE.match(statement):
            dev = True
            saw_install = True
            continue
        m = _JULIA_ADD_RE.match(statement)
        if m is None:
            return None
        found = _QUOTED_RE.findall(m.group("args"))
        if not found:
            return None
        packages += found
        saw_install = True
    if not saw_install:
        return None
    return InstallSpec(kind="julia", packages=packages, dev=dev)


_R_INSTALL_RE = re.compile(
    r"^(?:utils::)?install\.packages\s*\((?P<args>.*)\)\s*$", re.DOTALL
)
_R_REMOTE_RE = re.compile(
    r"^(?:remotes|devtools|pak)::(?:install_github|install_gitlab|pkg_install)"
    r"\s*\((?P<args>.*)\)\s*$",
    re.DOTALL,
)
_R_SELF_RE = re.compile(
    r"^(?:renv::(?:restore|init|snapshot|hydrate)|devtools::install|"
    r"renv::install)\s*\(\s*\)\s*$"
)


def _parse_r_install(content: str) -> InstallSpec | None:
    """Read an R block as package installs, or return None if it isn't."""
    packages: list[str] = []
    dev = False
    saw_install = False
    for statement in _install_statements(content, separators=";"):
        if _R_SELF_RE.match(statement):
            dev = True
            saw_install = True
            continue
        m = _R_INSTALL_RE.match(statement) or _R_REMOTE_RE.match(statement)
        if m is None:
            if statement.startswith("renv::install("):
                m = re.match(r"^renv::install\((?P<args>.*)\)\s*$", statement)
            if m is None:
                return None
        args = m.group("args")
        found = _QUOTED_RE.findall(args)
        if not found:
            return None
        for pkg in found:
            # A GitHub remote is written owner/repo; the package is the repo
            packages.append(pkg.rsplit("/", 1)[-1])
        saw_install = True
    if not saw_install:
        return None
    return InstallSpec(kind="renv", packages=packages, dev=dev)


def _install_statements(content: str, separators: str = "") -> list[str]:
    """Split block content into statements, dropping blanks and comments."""
    statements = []
    for line in content.splitlines():
        line = _strip_prompt(line)
        if not line or line.startswith("#"):
            continue
        parts = [line]
        for sep in separators:
            parts = [p for part in parts for p in part.split(sep)]
        for part in parts:
            part = part.strip()
            if part and not part.startswith("#"):
                statements.append(part)
    return statements


def parse_install_block(
    content: str, language: str | None
) -> InstallSpec | None:
    """Read a code block as an environment declared by installing it.

    A README says what a project needs by showing the command that
    installs it, not by listing packages, so those commands are read as
    the environment they describe. Every statement in the block has to be
    an install for it to count: a block that also does work is code.
    """
    if not content.strip():
        return None
    lang = (language or "").lower()
    if lang in ("julia", "jl"):
        return _parse_julia_install(content)
    if lang == "r":
        return _parse_r_install(content)
    if lang not in SHELL_LANGUAGES:
        return None
    specs = []
    for statement in _install_statements(content):
        spec = _parse_shell_install(statement)
        if spec is None:
            return None
        specs.append(spec)
    if not specs:
        return None
    # A block that mixes installers---pip then conda---is describing
    # alternatives rather than one environment, so the first wins
    kind = specs[0].kind
    merged = InstallSpec(kind=kind)
    for spec in specs:
        if spec.kind != kind:
            continue
        merged.dev = merged.dev or spec.dev
        merged.spec_path = merged.spec_path or spec.spec_path
        merged.packages += spec.packages
    return merged


def merge_install_specs(specs: list[InstallSpec]) -> InstallSpec:
    """Combine a language's install blocks into the environment they mean."""
    merged = InstallSpec(kind=specs[0].kind)
    seen: set[str] = set()
    for spec in specs:
        merged.dev = merged.dev or spec.dev
        merged.spec_path = merged.spec_path or spec.spec_path
        for package in spec.packages:
            key = _requirement_key(package)
            if key in seen:
                continue
            seen.add(key)
            merged.packages.append(package)
    return merged


# Where a package of each language keeps its own spec and its source, so
# a project can recognize an install of itself.
LOCAL_PACKAGE_SPECS: dict[str, tuple[str, list[str]]] = {
    # Python's source directory is named for the module, so it is worked
    # out from the package name rather than listed here
    "python": ("pyproject.toml", []),
    "julia": ("Project.toml", ["src"]),
    "r": ("DESCRIPTION", ["R"]),
}


def local_package_name(language: str, wdir: str | None = None) -> str | None:
    """Return the name of the package the project itself defines, if any."""
    entry = LOCAL_PACKAGE_SPECS.get(language)
    if entry is None:
        return None
    fname = entry[0]
    path = os.path.join(wdir, fname) if wdir else fname
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    if fname == "DESCRIPTION":
        m = re.search(r"^Package:\s*(\S+)\s*$", text, re.MULTILINE)
        return m.group(1) if m else None
    try:
        import tomllib

        data = tomllib.loads(text)
    except Exception:
        return None
    if fname == "Project.toml":
        name = data.get("name")
    else:
        name = (data.get("project") or {}).get("name")
    return str(name) if name else None


def local_package_source_paths(
    language: str, wdir: str | None = None
) -> list[str]:
    """Return the paths holding the source of the project's own package.

    A stage running in an environment that installed the project has to
    rerun when the project's code changes, and the lock file says nothing
    about that---an editable install is a pointer to the working tree.
    """
    name = local_package_name(language, wdir=wdir)
    entry = LOCAL_PACKAGE_SPECS.get(language)
    if name is None or entry is None:
        return []
    _, source_dirs = entry
    if language == "python":
        # Distributions normalize the name; directories use the module
        # spelling, which replaces separators with underscores
        module = re.sub(r"[-.]+", "_", name)
        candidates = [os.path.join("src", module), module]
    else:
        candidates = list(source_dirs)
    found = []
    for candidate in candidates:
        full = os.path.join(wdir, candidate) if wdir else candidate
        if os.path.isdir(full):
            found.append(Path(candidate).as_posix())
    return found


def installs_local_package(spec: InstallSpec, wdir: str | None = None) -> bool:
    """Determine whether an install names the project's own package.

    A README tells a reader to install the package from wherever it is
    published; read inside the package's own repo, that same line means
    the copy in the working tree.
    """
    name = local_package_name(spec.language, wdir=wdir)
    if name is None:
        return False
    key = _requirement_key(name)
    return any(_requirement_key(pkg) == key for pkg in spec.packages)


def resolve_dev_install(
    spec: InstallSpec, wdir: str | None = None
) -> tuple[str, str] | None:
    """Find the spec file a dev install refers to, as (kind, path).

    ``pip install -e .`` says the environment is this project, which is
    already described by whatever spec file sits in the project
    directory---so the environment points at that file rather than one
    Calkit generates.
    """
    candidates = DEV_INSTALL_SPECS.get(spec.language, [])
    # The installer that was named wins if its own spec file is there
    ordered = sorted(candidates, key=lambda kp: kp[0] != spec.kind)
    for kind, fname in ordered:
        path = os.path.join(wdir, fname) if wdir else fname
        if os.path.isfile(path):
            return kind, fname
    return None


LANGUAGE_DETECTORS: dict[str, str] = {
    "python": "detect_python_dependencies",
    "py": "detect_python_dependencies",
    "r": "detect_r_dependencies",
    "julia": "detect_julia_dependencies",
    "jl": "detect_julia_dependencies",
}

# Suffix distinguishing one detected environment from another when a file
# needs more than one.
LANGUAGE_SUFFIXES: dict[str, str] = {
    "python": "py",
    "py": "py",
    "r": "r",
    "julia": "jl",
    "jl": "jl",
}


# What to pin a Julia environment to when Julia isn't installed to ask.
FALLBACK_JULIA_VERSION = "1.12"


def detected_julia_version() -> str:
    """Return the installed Julia's major.minor version, or a fallback."""
    import calkit.julia

    try:
        version = calkit.julia.get_version()
    except Exception:
        return FALLBACK_JULIA_VERSION
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def _env_base_name(markdown_path: str) -> str:
    stem = Path(markdown_path).name.removesuffix(".md").lower()
    cleaned = "".join(c if c.isalnum() else "-" for c in stem).strip("-")
    return cleaned or "markdown"


def detect_environments(
    specs: dict[str, MarkdownStageSpec],
    markdown_path: str,
    existing_env_names: list[str] | None = None,
    default_env: str | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Build environments for the stages in a file that declare none.

    Stages are grouped by language and given one environment each, rather
    than one apiece: a README's examples are normally variations on the
    same setup, and a virtualenv per code block would be a lot of disk and
    lock churn for nothing.

    Returns the environments and a map of stage name -> environment name.
    """
    import calkit.environments
    from calkit import detect as _detect

    existing = list(existing_env_names or [])
    by_language: dict[str, list[MarkdownStageSpec]] = {}
    for spec in specs.values():
        if spec.attrs.get("environment") or default_env:
            continue
        if spec.language not in LANGUAGE_DETECTORS:
            continue
        by_language.setdefault(spec.language, []).append(spec)
    if not by_language:
        return {}, {}
    base = _env_base_name(markdown_path)
    envs: dict[str, dict] = {}
    assignments: dict[str, str] = {}
    for language, language_specs in sorted(by_language.items()):
        detector = getattr(_detect, LANGUAGE_DETECTORS[language])
        deps: list[str] = []
        for spec in language_specs:
            for dep in detector(code=spec.content):
                if dep not in deps:
                    deps.append(dep)
        # Suffix when this file needs more than one environment, and also
        # when it has already named one that way, so a file's environments
        # are named alike whether they were declared or detected
        suffixed = len(by_language) > 1 or any(
            n.startswith(f"{base}-") for n in existing
        )
        name = f"{base}-{LANGUAGE_SUFFIXES[language]}" if suffixed else base
        candidate = name
        n = 2
        while candidate in existing or candidate in envs:
            candidate = f"{name}-{n}"
            n += 1
        existing.append(candidate)
        kind = LANGUAGE_ENV_KINDS[language]
        env: dict[str, Any] = {
            "kind": kind,
            "path": get_env_spec_path(candidate, kind=kind),
            "_spec_content": render_env_spec(kind, "\n".join(deps), candidate),
        }
        if kind == "uv":
            # Pin the interpreter rather than letting it float above the
            # requires-python floor, so the lock means something
            env["_python"] = calkit.environments.DEFAULT_PYTHON_VERSION
        elif kind == "julia":
            # A Julia environment has no default version to fall back on,
            # so it is pinned to whatever Julia is installed here
            env["julia"] = detected_julia_version()
        envs[candidate] = env
        for spec in language_specs:
            assignments[spec.name] = candidate
    return envs, assignments


def format_attr_value(value: Any) -> str:
    """Render an attribute value the way an annotation spells it."""
    if value is True:
        return ""
    if isinstance(value, str):
        # Quote only when the value would otherwise not survive a
        # round-trip through the attribute scanner
        if value and not any(c.isspace() for c in value):
            return value
        return '"' + value.replace('"', '\\"') + '"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_attr_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{k}: {format_attr_value(v)}" for k, v in value.items()
            )
            + "}"
        )
    return str(value)


def format_attrs(attrs: dict[str, Any]) -> str:
    """Render attributes back into an annotation's key=value form."""
    parts = []
    for key, value in attrs.items():
        rendered = format_attr_value(value)
        parts.append(key if rendered == "" else f"{key}={rendered}")
    return " ".join(parts)


# Languages a plain code fence can be turned into a stage automatically.
# Deliberately narrower than what Calkit can run: a README's shell blocks
# are usually instructions for the reader---install this, clone that---and
# quietly promoting them to pipeline stages would run them.
AUTO_STAGE_LANGUAGES = tuple(LANGUAGE_DETECTORS)


@dataclass
class Annotation:
    """What annotating a plain Markdown file added to it."""

    # Stage name -> language, and environment name -> the language whose
    # stages it serves
    stages: dict[str, str] = field(default_factory=dict)
    environments: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.stages or self.environments)


@dataclass
class _Fence:
    """One code fence found while scanning a file to annotate it."""

    index: int
    indent: str
    fence: str
    info: str
    ending: str
    language: str | None
    install: InstallSpec | None = None
    transcript: bool = False


def _scan_fences(lines: list[str]) -> list[_Fence]:
    """Find the un-annotated code fences in a file, outermost first."""
    fences: list[_Fence] = []
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\r\n")
        m = _FENCE_RE.match(raw)
        if m is None:
            i += 1
            continue
        fence = m.group("fence")
        info = m.group("info").strip()
        # Find this fence's closing line first, so a longer fence's nested
        # examples aren't mistaken for blocks of their own
        j = i + 1
        while j < len(lines):
            close = _FENCE_RE.match(lines[j].rstrip("\r\n"))
            if (
                close is not None
                and close.group("fence")[0] == fence[0]
                and len(close.group("fence")) >= len(fence)
                and not close.group("info").strip()
            ):
                break
            j += 1
        try:
            language, annotation = _parse_fence_info(info)
        except ValueError:
            language, annotation = None, None
        if annotation is None and language is not None:
            content = "".join(lines[i + 1 : j])
            fences.append(
                _Fence(
                    index=i,
                    indent=m.group("indent"),
                    fence=fence,
                    info=info,
                    ending=lines[i][len(raw) :],
                    language=language,
                    install=parse_install_block(content, language),
                    transcript=is_repl_transcript(content),
                )
            )
        i = j + 1
    return fences


def annotate_code_blocks(
    text: str, markdown_path: str
) -> tuple[str, Annotation]:
    """Annotate a plain file's code fences so its blocks become a pipeline.

    This is what makes ``calkit xr README.md`` work on a README nobody has
    marked up yet. Code blocks are named for their language and so join
    into one stage per language, in document order, because consecutive
    blocks in a README read as one continuing script---what block two
    imports, block one is expected to have set up.

    Blocks that install packages are read as the environment those stages
    run in, since showing the install command is how a README says what
    its code needs.

    Only info strings are touched, never prose and never code. Fences
    that already carry a Calkit annotation are left alone.
    """
    import calkit.environments

    lines = text.splitlines(keepends=True)
    fences = _scan_fences(lines)
    stage_fences = [
        f
        for f in fences
        if f.install is None
        and not f.transcript
        and f.language is not None
        and f.language.lower() in AUTO_STAGE_LANGUAGES
    ]
    install_fences = [f for f in fences if f.install is not None]
    stage_names = {
        LANGUAGE_SUFFIXES[f.language.lower()]  # type: ignore[union-attr]
        for f in stage_fences
    }
    # An environment nothing runs in is not worth building, so only the
    # installs for a language the file actually has code in are read
    env_suffixes = {
        LANGUAGE_SUFFIXES[f.install.language]  # type: ignore[union-attr]
        for f in install_fences
    } & stage_names
    base = _env_base_name(markdown_path)
    multi = len(stage_names) > 1
    env_names = {
        suffix: (f"{base}-{suffix}" if multi else base)
        for suffix in sorted(env_suffixes)
    }
    result = Annotation()
    for f in install_fences:
        suffix = LANGUAGE_SUFFIXES[f.install.language]  # type: ignore
        if suffix not in env_names:
            continue
        name = env_names[suffix]
        annotation = f"calkit environment name={name}"
        # Pin the interpreter here rather than letting it float, so what
        # the environment resolves to doesn't depend on when it is built
        if f.install.kind == "julia":
            annotation += f" julia={detected_julia_version()}"
        elif f.install.kind in ("uv", "uv-venv") and not f.install.dev:
            annotation += (
                f" python={calkit.environments.DEFAULT_PYTHON_VERSION}"
            )
        _annotate_fence(lines, f, annotation)
        result.environments[name] = f.install.language  # type: ignore
    for f in stage_fences:
        suffix = LANGUAGE_SUFFIXES[f.language.lower()]  # type: ignore
        annotation = f"calkit stage name={suffix}"
        env_name = env_names.get(suffix)
        if env_name is not None:
            annotation += f" environment={env_name}"
        _annotate_fence(lines, f, annotation)
        result.stages[suffix] = f.language.lower()  # type: ignore
    return "".join(lines), result


def _annotate_fence(lines: list[str], fence: _Fence, annotation: str) -> None:
    """Append an annotation to a fence's info string, in place."""
    # The original info string is kept whole rather than rebuilt from the
    # language, so any other renderer's attributes on the fence survive
    lines[fence.index] = (
        fence.indent
        + fence.fence
        + fence.info
        + " "
        + annotation
        + fence.ending
    )


def set_stage_attrs(
    text: str, stage_name: str, attrs: dict[str, Any]
) -> tuple[str, bool]:
    """Add attributes to a stage's first annotated fence in Markdown text.

    Only the info string of a block that is already annotated is touched,
    never prose and never code, so this can record what was detected
    without rewriting anything the author wrote. Attributes already set
    are left alone, since the author's word beats a detected one.

    Returns the new text and whether anything changed.
    """
    if not attrs:
        return text, False
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line.rstrip("\r\n"))
        if m is None:
            continue
        try:
            language, annotation = _parse_fence_info(m.group("info"))
        except ValueError:
            continue
        if annotation is None or annotation[0] != "stage":
            continue
        if str(annotation[1].get("name")) != stage_name:
            continue
        new_attrs = {k: v for k, v in attrs.items() if k not in annotation[1]}
        if not new_attrs:
            return text, False
        ending = line[len(line.rstrip("\r\n")) :]
        info = " ".join(
            part
            for part in [
                language or "",
                "calkit stage",
                format_attrs(annotation[1]),
                format_attrs(new_attrs),
            ]
            if part
        )
        lines[i] = m.group("indent") + m.group("fence") + info + ending
        return "".join(lines), True
    return text, False


def set_output_blocks(text: str, outputs: dict[str, str]) -> tuple[str, bool]:
    """Replace the bodies of ``calkit output`` blocks with what ran.

    ``outputs`` maps a stage name to its captured standard output. Only
    the body of a block already annotated as an output for that stage is
    replaced; a stage with no output block is simply not shown, and a
    block whose stage produced nothing is emptied rather than left stale.

    Returns the new text and whether anything changed.
    """
    if not outputs:
        return text, False
    lines = text.splitlines(keepends=True)
    out_lines: list[str] = []
    changed = False
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FENCE_RE.match(line.rstrip("\r\n"))
        if m is None:
            out_lines.append(line)
            i += 1
            continue
        fence = m.group("fence")
        try:
            _, annotation = _parse_fence_info(m.group("info"))
        except ValueError:
            annotation = None
        # Find this fence's closing line either way, so a block we don't
        # touch is copied through without its contents being rescanned
        j = i + 1
        while j < len(lines):
            close = _FENCE_RE.match(lines[j].rstrip("\r\n"))
            if (
                close is not None
                and close.group("fence")[0] == fence[0]
                and len(close.group("fence")) >= len(fence)
                and not close.group("info").strip()
            ):
                break
            j += 1
        stage_name = (
            str(annotation[1].get("name") or annotation[1].get("stage"))
            if annotation is not None and annotation[0] == "output"
            else None
        )
        if stage_name is None or stage_name not in outputs:
            out_lines += lines[i : j + 1]
            i = j + 1
            continue
        body = outputs[stage_name]
        new_body = [line + "\n" for line in body.splitlines()] if body else []
        if lines[i + 1 : j] != new_body:
            changed = True
        out_lines.append(line)
        out_lines += new_body
        if j < len(lines):
            out_lines.append(lines[j])
        i = j + 1
    return "".join(out_lines), changed
