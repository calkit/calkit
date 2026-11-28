"""Core functionality."""

from __future__ import annotations

import base64
import contextlib
import copy
import csv
import functools
import glob
import hashlib
import json
import logging
import os
import pickle
import platform
import posixpath
import re
import socket
import subprocess
import sys
import threading
import uuid
import warnings
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from os import PathLike

import calkit

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _timezone

    UTC = _timezone.utc

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Iterator, Literal

if TYPE_CHECKING:
    from calkit.models import ProjectInfo, ProjectStatus

import ruamel.yaml

logger = logging.getLogger(__package__)
logger.setLevel(logging.INFO)
# Folders in the home folder that macOS asks before a process reads, which
# projects aren't kept in, e.g., Pictures, which has the Photos library
MACOS_MEDIA_FOLDERS = (
    "Applications",
    "Library",
    "Movies",
    "Music",
    "Pictures",
    "Public",
)
# Those macOS asks about where projects may be kept
MACOS_PROTECTED_FOLDERS = ("Desktop", "Documents", "Downloads")


class _FoldedPlainStr(str):
    """A scalar read from a file, remembering where its lines broke.

    ``fold_pos`` holds the index of each space that was a line break, none
    if it was on one line, so the value can be written back the way it was
    wrapped rather than re-folded at whatever width ruamel is set to, which
    rewrote every paragraph of a file wrapped any other way, and broke
    every line longer than the width.

    Plain scalars are loaded as one, and double-quoted ones are written out
    as one.
    """

    fold_pos: list[int]
    #: Whether it started a line, e.g., below its key, which is kept too
    own_line: bool
    #: Where it started, so an item of a wrapped flow list starts there again
    column: int


class _SourceDoubleQuotedStr(
    ruamel.yaml.scalarstring.DoubleQuotedScalarString
):
    """A double-quoted scalar read from a file, remembering where its lines
    broke, as ``_FoldedPlainStr`` does."""

    __slots__ = ("fold_pos", "own_line", "column")


class _SourceFoldedStr(str):
    """A folded block scalar's text, as read from a file, on its way out.

    Its line breaks are the ones it was read with, which ruamel marks, so
    the emitter adds none of its own at the width.
    """


class _FoldPreservingConstructor(ruamel.yaml.constructor.RoundTripConstructor):
    def construct_scalar(self, node: Any) -> Any:
        from ruamel.yaml.scalarstring import (
            DoubleQuotedScalarString,
            FoldedScalarString,
        )

        value = super().construct_scalar(node)
        # ruamel records a folded block's breaks only if it has some, and
        # one without is otherwise taken for one made in code
        if isinstance(value, FoldedScalarString):
            if not hasattr(value, "fold_pos"):
                value.fold_pos = []  # type: ignore[attr-defined]
            return value
        quoted = type(value) is DoubleQuotedScalarString
        if not quoted and (type(value) is not str or node.style is not None):
            return value
        # Only text loaded from a string has its source in the marks
        buffer = getattr(node.start_mark, "buffer", None)
        if buffer is None:
            return value
        source = buffer[node.start_mark.index : node.end_mark.index]
        lines = source.split("\n")
        if quoted:
            # A break in quotes can be escaped, or follow spaces that are
            # kept, and these are left to ruamel
            if len(lines) > 1 and "\\" in source:
                return value
            lines[0] = lines[0].removeprefix('"')
            lines[-1] = lines[-1].removesuffix('"')
            lines = (
                [lines[0]]
                if len(lines) == 1
                else [
                    lines[0].rstrip(),
                    *(line.strip() for line in lines[1:-1]),
                    lines[-1].lstrip(),
                ]
            )
        else:
            lines = [line.strip() for line in lines]
        # Blank lines are newlines in the value, which the emitter handles.
        # Quotes on one line can hold escapes, but have no breaks to find.
        if len(lines) > 1 and ("" in lines or " ".join(lines) != value):
            return value
        if len(lines) == 1 and not quoted and lines[0] != value:
            return value
        out: Any = (
            _SourceDoubleQuotedStr(value, anchor=node.anchor)
            if quoted
            else _FoldedPlainStr(value)
        )
        out.fold_pos = []
        pos = -1
        for line in lines[:-1]:
            pos += len(line) + 1
            out.fold_pos.append(pos)
        i = node.start_mark.index - 1
        while i >= 0 and buffer[i] in " \t":
            i -= 1
        out.own_line = i < 0 or buffer[i] == "\n"
        out.column = node.start_mark.column
        return out


class _FoldPreservingRepresenter(ruamel.yaml.representer.RoundTripRepresenter):
    def represent_folded_scalarstring(self, data: Any) -> Any:
        node = super().represent_folded_scalarstring(data)
        if hasattr(data, "fold_pos"):
            node.value = _SourceFoldedStr(node.value)
        return node

    def represent_source_double_quoted(self, data: Any) -> Any:
        node = self.represent_double_quoted_scalarstring(data)
        # One given a new value in code has nothing to keep, since ruamel
        # keeps the type of the value it replaced
        if not hasattr(data, "fold_pos"):
            return node
        node.value = _FoldedPlainStr(node.value)
        node.value.fold_pos = data.fold_pos
        node.value.own_line = data.own_line
        node.value.column = data.column
        return node


# Values read from calkit.yaml end up in files other dumpers write, e.g.,
# DVC writing dvc.yaml, which would otherwise refuse them
for _representer in (
    ruamel.yaml.representer.SafeRepresenter,
    ruamel.yaml.representer.RoundTripRepresenter,
    _FoldPreservingRepresenter,
):
    _representer.add_representer(
        _FoldedPlainStr, ruamel.yaml.representer.SafeRepresenter.represent_str
    )
ruamel.yaml.representer.RoundTripRepresenter.add_representer(
    _SourceDoubleQuotedStr,
    ruamel.yaml.representer.RoundTripRepresenter.represent_double_quoted_scalarstring,
)
_FoldPreservingRepresenter.add_representer(
    _SourceDoubleQuotedStr,
    _FoldPreservingRepresenter.represent_source_double_quoted,
)
_FoldPreservingRepresenter.add_representer(
    ruamel.yaml.scalarstring.FoldedScalarString,
    _FoldPreservingRepresenter.represent_folded_scalarstring,
)


class _FoldPreservingEmitter(ruamel.yaml.emitter.Emitter):
    def _write(self, data: str) -> None:
        self.column += len(data)
        self.stream.write(
            data.encode(self.encoding) if self.encoding else data
        )

    def _flow_item_from_source(self) -> bool:
        """Whether the next item of a flow sequence was read from a file,
        and if so, start it on a new line if it was on one."""
        if not hasattr(getattr(self.event, "value", None), "fold_pos"):
            return False
        if self.event.value.own_line:
            self.write_indent()
            self._write(" " * (self.event.value.column - self.column))
        self.states.append(self.expect_flow_sequence_item)
        self.expect_node(sequence=True)
        return True

    def expect_first_flow_sequence_item(self) -> None:
        if not self._flow_item_from_source():
            super().expect_first_flow_sequence_item()

    def expect_flow_sequence_item(self) -> None:
        from ruamel.yaml.events import SequenceEndEvent

        if isinstance(self.event, SequenceEndEvent) or not hasattr(
            getattr(self.event, "value", None), "fold_pos"
        ):
            return super().expect_flow_sequence_item()
        self.write_indicator(self.flow_seq_separator, False)
        self._flow_item_from_source()

    def write_folded(self, text: Any, comment: Any) -> None:
        if not isinstance(text, _SourceFoldedStr):
            return super().write_folded(text, comment)
        best_width = self.best_width
        self.best_width = sys.maxsize
        try:
            super().write_folded(text, comment)
        finally:
            self.best_width = best_width

    def write_double_quoted(self, text: Any, split: Any = True) -> None:
        fold_pos = getattr(text, "fold_pos", None)
        if self.root_context or fold_pos is None:
            return super().write_double_quoted(text, split)

        def escaped(s: str) -> str:
            # The same escapes as the parent's
            out = []
            for ch in s:
                if ch in '"\\\x85  ﻿' or not (
                    "\x20" <= ch <= "\x7e"
                    or (
                        self.allow_unicode
                        and (
                            "\xa0" <= ch <= "퟿"
                            or "" <= ch <= "�"
                            or "\U00010000" <= ch <= "\U0010ffff"
                        )
                    )
                ):
                    if ch in self.ESCAPE_REPLACEMENTS:
                        ch = "\\" + self.ESCAPE_REPLACEMENTS[ch]
                    elif ch <= "\xff":
                        ch = "\\x%02X" % ord(ch)
                    elif ch <= "￿":
                        ch = "\\u%04X" % ord(ch)
                    else:
                        ch = "\\U%08X" % ord(ch)
                out.append(ch)
            return "".join(out)

        # Breaking where the source did, each break reading as the space
        # it replaced
        self.write_indicator('"', True)
        start = 0
        for pos in fold_pos if split else []:
            self._write(escaped(text[start:pos]))
            self.write_indent()
            start = pos + 1
        self._write(escaped(text[start:]))
        self.write_indicator('"', False)

    def write_plain(self, text: Any, split: Any = True) -> None:
        fold_pos = getattr(text, "fold_pos", None)
        if self.root_context or not text or (split and fold_pos is None):
            return super().write_plain(text, split)
        # The same bookkeeping as the parent's, breaking where the source
        # did instead of where the width says to. A value on one line stays
        # on one line, however long.
        if not self.whitespace:
            if (
                split
                and not self.flow_level
                and getattr(text, "own_line", False)
                and self.indent is not None
                and self.column > self.indent
            ):
                self.write_indent()
            else:
                self._write(" ")
        self.whitespace = False
        self.indention = False
        # A simple key gets no breaks: ruamel still wraps one past the width,
        # but a key can't span lines
        start = 0
        for pos in fold_pos if split and fold_pos is not None else []:
            self._write(text[start:pos])
            self.write_indent()
            self.whitespace = False
            self.indention = False
            start = pos + 1
        self._write(text[start:])


class _ThreadLocalYAML(threading.local):
    """Holds one configured ruamel ``YAML`` per thread.

    A ``YAML`` instance carries scanner, parser and composer state for the
    duration of a load, so two threads sharing one interleave their parses
    and corrupt each other. The symptom is not a clean failure: a perfectly
    valid file comes back as a ``ParserError`` or ``ComposerError`` pointing
    at a random line, an ``IndexError`` from the scanner, or an internal
    ``AttributeError`` that escapes the usual YAML error handling entirely.

    The CLI is single-threaded and never hit this, but the hub calls into
    ``calkit`` from a request threadpool, where concurrent reads of the same
    calkit.yaml made project pages intermittently 500 or report a project as
    having no metadata at all.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Replace this thread's ``YAML`` with a freshly configured one."""
        self.yaml = ruamel.yaml.YAML()
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self.yaml.preserve_quotes = True
        # 80 rather than ruamel's default so prose wrapped at the usual
        # 79-80 columns is written back as it was; at 70, lines of 71-80
        # characters were re-folded with a stray word on the next line
        self.yaml.width = 80
        # Prose wrapped some other way is still written back as it was
        self.yaml.Constructor = _FoldPreservingConstructor
        self.yaml.Representer = _FoldPreservingRepresenter
        self.yaml.Emitter = _FoldPreservingEmitter


_yaml_local = _ThreadLocalYAML()


class _ThreadLocalYAMLProxy:
    """Forwards to the calling thread's ``YAML``.

    Keeps ``ryaml`` usable as the module-level object it has always been,
    so no call site has to know about any of this.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(_yaml_local.yaml, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_yaml_local.yaml, name, value)

    def load(self, stream: Any) -> Any:
        """Load YAML, reading it to a string first.

        Only a string load leaves the source in the marks, which is how
        multi-line values remember where they were wrapped.
        """
        from pathlib import Path

        if isinstance(stream, Path):
            stream = stream.read_text(encoding="utf-8")
        elif hasattr(stream, "read"):
            stream = stream.read()
        return _yaml_local.yaml.load(stream)

    def dump(self, data: Any, stream: Any = None, **kwargs: Any) -> Any:
        """Dump YAML, dropping the space ruamel leaves before a fold.

        When wrapping a long value, ruamel writes the space that separates
        two words and then breaks the line, leaving it at the end. The
        space is redundant---a line break in a plain scalar already reads
        as one---but every whitespace-trimming tool strips it and Calkit
        writes it back, so the two take turns rewriting the same file.

        It is not redundant in a block scalar, where trailing spaces are
        content. Rather than trying to tell the cases apart while
        emitting, the cleaned text is parsed back and only used if it
        still means the same thing.

        A ``Path`` is only written once the dump has succeeded, so a
        failure can't leave the file empty, as opening it with ``"w"``
        first would.
        """
        import io
        from pathlib import Path

        yaml = _yaml_local.yaml
        buf = io.StringIO()
        try:
            if stream is None:
                return yaml.dump(data, stream, **kwargs)
            yaml.dump(data, buf, **kwargs)
        except BaseException:
            # ruamel only clears the output it's dumping to on success, so
            # after a failure every later dump on this thread would go to
            # the old stream, e.g., leaving calkit.yaml empty
            _yaml_local.reset()
            raise
        text = buf.getvalue()
        if " \n" in text:
            cleaned = "".join(
                line.rstrip() + "\n" for line in text.splitlines()
            )
            try:
                if yaml.load(cleaned) == yaml.load(text):
                    text = cleaned
            except Exception:
                pass
        if isinstance(stream, Path):
            stream.write_text(text, encoding="utf-8")
        else:
            stream.write(text)
        return None


ryaml = _ThreadLocalYAMLProxy()


def set_yaml_item(mapping: dict, key: Any, value: Any) -> None:
    """Set an item in a mapping loaded with ``ryaml``, keeping its layout.

    ruamel.yaml attaches the blank lines and comments that follow a mapping
    to its last item, however deeply nested, so a key appended after it
    would land below them, e.g., below the blank line separating the mapping
    from the next top-level key. The new last item takes them over instead.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    def get_last_items(node: Any) -> list[tuple[Any, Any]]:
        # The collection and key of each last item, outermost first
        if isinstance(node, CommentedMap) and node:
            last = next(reversed(node))
        elif isinstance(node, CommentedSeq) and node:
            last = len(node) - 1
        else:
            return []
        return [(node, last)] + get_last_items(node[last])

    def to_commented(node: Any) -> Any:
        if isinstance(node, dict):
            return CommentedMap((k, to_commented(v)) for k, v in node.items())
        if isinstance(node, list):
            return CommentedSeq(to_commented(v) for v in node)
        return node

    is_last = bool(mapping) and key == next(reversed(mapping))
    # A scalar replacing a scalar keeps the item's comments as they are
    if not isinstance(mapping, CommentedMap) or (
        key in mapping
        and (
            not is_last
            or (
                not isinstance(mapping[key], (dict, list))
                and not isinstance(value, (dict, list))
            )
        )
    ):
        mapping[key] = value
        return
    # Maps keep a trailing comment in slot 2 of an item, and sequences in 0
    token = None
    for node, k in reversed(get_last_items(mapping)):
        slots = node.ca.items.get(k)
        slot = 2 if isinstance(node, CommentedMap) else 0
        if slots and slots[slot] is not None:
            token = slots[slot]
            slots[slot] = None
            # A comment at the end of the item's own line stays with it
            if token.value.startswith("#"):
                eol, _, rest = token.value.partition("\n")
                slots[slot] = copy.copy(token)
                slots[slot].value = eol + "\n"
                token = copy.copy(token)
                token.value = "\n" + rest
                if not rest:
                    token = None
            break
    if token is None:
        mapping[key] = value
        return
    mapping[key] = to_commented(value)
    node, k = get_last_items(mapping)[-1]
    if isinstance(node, CommentedMap):
        node.ca.items[k] = [None, None, token, None]
    else:
        node.ca.items[k] = [token, None]


try:
    # libyaml-backed loader, many times faster than the pure-Python one.
    # PyYAML ships prebuilt wheels with libyaml on every platform we target,
    # so this is the normal path; the fallback keeps a source install or an
    # exotic build working, just slower.
    from yaml import CSafeLoader as _BaseYamlLoader
except ImportError:  # pragma: no cover - depends on the libyaml build
    from yaml import SafeLoader as _BaseYamlLoader


class _YamlLoader(_BaseYamlLoader):  # type: ignore[no-any-unimported]
    """The C loader, reading scalars as YAML 1.2 like ``ryaml`` does.

    PyYAML follows YAML 1.1, where ``no`` and ``on`` are booleans, ``1:30``
    is 90, and ``010`` is octal, so the same file would load differently
    depending on which parser read it.
    """


def _construct_yaml12_int(loader: Any, node: Any) -> int:
    value = str(loader.construct_scalar(node)).replace("_", "")
    sign = -1 if value.startswith("-") else 1
    value = value.lstrip("+-")
    for prefix, base in (("0b", 2), ("0o", 8), ("0x", 16)):
        if value.startswith(prefix):
            return sign * int(value[2:], base)
    return sign * int(value)


# ruamel.yaml's YAML 1.2 resolvers for the scalars that differ from 1.1
_YAML12_RESOLVERS = {
    "tag:yaml.org,2002:bool": (
        r"^(?:true|True|TRUE|false|False|FALSE)$",
        "tTfF",
    ),
    "tag:yaml.org,2002:float": (
        r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+]?[0-9]+)?
        |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
        |[-+]?\.[0-9_]+(?:[eE][-+][0-9]+)?
        |[-+]?\.(?:inf|Inf|INF)
        |\.(?:nan|NaN|NAN))$""",
        "-+0123456789.",
    ),
    "tag:yaml.org,2002:int": (
        r"""^(?:[-+]?0b[0-1_]+
        |[-+]?0o?[0-7_]+
        |[-+]?[0-9_]+
        |[-+]?0x[0-9a-fA-F_]+)$""",
        "-+0123456789",
    ),
}
_YamlLoader.yaml_implicit_resolvers = {
    first: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag not in _YAML12_RESOLVERS
    ]
    for first, resolvers in _BaseYamlLoader.yaml_implicit_resolvers.items()
}
for _tag, (_pattern, _first) in _YAML12_RESOLVERS.items():
    _YamlLoader.add_implicit_resolver(
        _tag, re.compile(_pattern, re.X), list(_first)
    )
_YamlLoader.add_constructor("tag:yaml.org,2002:int", _construct_yaml12_int)


def _load_yaml_readonly(stream: Any) -> Any:
    """Parse YAML with the C loader, for data we never write back."""
    import yaml

    return yaml.load(stream, Loader=_YamlLoader)


# Constants for version control auto-ignore
AUTO_IGNORE_SUFFIXES = [
    ".DS_Store",
    ".env",
    ".pyc",
    ".synctex.gz",
    ".auxlock",
]
AUTO_IGNORE_PATHS = [os.path.join(".dvc", "config.local")]
AUTO_IGNORE_PREFIXES = [
    ".venv",
    ".calkit/overleaf/",
]
# Directories ignored wherever they are in the project, e.g., the
# checkpoints Jupyter writes next to each notebook
AUTO_IGNORE_DIR_NAMES = [".ipynb_checkpoints", "__pycache__"]


def get_auto_ignore_path(path: str) -> str | None:
    """The path to ignore so ``path`` isn't committed, if it's one Calkit
    ignores automatically.

    A file in a directory that's always ignored gives that directory, so it
    takes one line of ``.gitignore`` however many files it holds.
    """
    from pathlib import Path

    path = Path(path).as_posix()
    parts = path.split("/")
    for n, part in enumerate(parts[:-1]):
        if part in AUTO_IGNORE_DIR_NAMES:
            return "/".join(parts[: n + 1]) + "/"
    if (
        any(path.endswith(s) for s in AUTO_IGNORE_SUFFIXES)
        or any(path.startswith(p) for p in AUTO_IGNORE_PREFIXES)
        or path in {Path(p).as_posix() for p in AUTO_IGNORE_PATHS}
    ):
        return path
    return None


# Constants for version control auto-add to DVC
DVC_EXTENSIONS = [
    ".gif",
    ".h5",
    ".parquet",
    ".pickle",
    ".mp4",
    ".avi",
    ".webm",
    ".xlsx",
    ".docx",
    ".pptx",
    ".xls",
    ".doc",
    ".ppt",
    ".nc",
    ".nc4",
    ".zarr",
]
DVC_SIZE_THRESH_BYTES = 5_000_000
# Figures go in Git so a clone has them, unless they're big, since each
# version stays in its history at about full size
FIGURE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".pdf", ".svg"]
FIGURE_DVC_SIZE_THRESH_BYTES = 1_000_000
# What pipeline runs of Python tell tools to date their files, so the same
# data gives the same bytes. Tools that write ZIPs can't go before 1980.
OUTPUT_SOURCE_DATE_EPOCH = "315532800"
# How each stage's current outputs were made, kept with the project
STAGE_RUNS_FPATH = os.path.join(".calkit", "stage-runs.json")


def read_stage_runs(wdir: str | None = None) -> dict:
    """The recorded runs of the stages a project's ``dvc.lock`` records, by
    their names there.

    Kept beside that ``dvc.lock``, so a subproject's are in its own
    directory whether its stages ran from it or from its parent.
    """
    try:
        with open(os.path.join(wdir or "", STAGE_RUNS_FPATH)) as f:
            stage_runs = json.load(f)
    except OSError:
        return {}
    return stage_runs if isinstance(stage_runs, dict) else {}


def check_or_x(val: bool | int) -> str:
    """A check mark for something that holds, an X for something that does
    not.

    The mark every report prints, so a project's checks read the same way
    wherever they are shown.
    """
    return "✅" if val else "❌"


def encode_safe(message: str, err: bool = False) -> str:
    """A message with whatever the console cannot encode replaced.

    A Windows console is typically cp1252, which has no check mark: left
    alone, printing one raises UnicodeEncodeError and the command dies
    with no output at all. Anything that can carry a mark or an emoji has
    to go through here rather than straight to ``typer.echo``.
    """
    stream = sys.stderr if err else sys.stdout
    enc = stream.encoding or "utf-8"
    return message.encode(enc, errors="replace").decode(enc)


def echo(message: str) -> None:
    """Print a message safely, replacing unencodable characters
    (e.g., emoji).
    """
    import typer

    typer.echo(encode_safe(message))


def get_project_paths_path() -> str:
    """Where the folders projects were created or cloned into on this
    machine are recorded.
    """
    return os.path.join(
        get_user_home(), ".calkit", f"project-paths{get_env_suffix()}.json"
    )


def get_recorded_project_paths() -> list[str]:
    """The folders projects were created or cloned into on this machine."""
    try:
        with open(get_project_paths_path()) as f:
            paths = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(paths, list):
        return []
    return [p for p in paths if isinstance(p, str)]


def write_json(path: str, data: Any, **kwargs: Any) -> None:
    """Write JSON to a file all at once, so it's never read half written,
    through a temporary file of its own, so writers don't share one.
    """
    import tempfile
    import time

    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=folder, prefix=os.path.basename(path) + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, **kwargs)
        # Windows refuses to replace a file while another process reads it
        n_retries = 40 if sys.platform == "win32" else 0
        for n_retries_left in range(n_retries, -1, -1):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if n_retries_left == 0:
                    raise
                time.sleep(0.05)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


def record_project_path(wdir: str = ".") -> None:
    """Remember where a project is on this machine, so it's found wherever
    it is, e.g., by 'calkit open project' or the browser extension.
    """
    from filelock import FileLock

    path = os.path.realpath(wdir)
    if path in get_recorded_project_paths():
        return
    fpath = get_project_paths_path()
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    # Read again once it's ours, so another process's addition isn't lost
    with FileLock(fpath + ".lock", timeout=60):
        paths = get_recorded_project_paths()
        if path in paths:
            return
        # Ones since moved or deleted are dropped while it's being written
        paths = [
            p for p in paths if os.path.isfile(os.path.join(p, "calkit.yaml"))
        ]
        write_json(fpath, paths + [path], indent=2)


def find_project_dirs(
    relative: bool = False, max_depth: int = 3, search_protected: bool = True
) -> list[str]:
    """Find all Calkit project directories, i.e., those up to
    ``max_depth`` folders into the home folder, and, unless ``relative``,
    those recorded when created, cloned, or found before.

    On macOS, the home folder's media and system folders are never
    searched, and, without ``search_protected``, nor are its Desktop,
    Documents, and Downloads folders, since macOS asks before a process
    reads any of them, e.g., one the browser starts; recorded projects in
    them are still found.
    """
    if relative:
        start = ""
    else:
        start = os.path.expanduser("~")
    skipped = set()
    if platform.system() == "Darwin" and not relative:
        skipped |= set(MACOS_MEDIA_FOLDERS)
        if not search_protected:
            skipped |= set(MACOS_PROTECTED_FOLDERS)
    try:
        top_names = sorted(
            entry.name
            for entry in os.scandir(start or ".")
            if not entry.name.startswith(".")
            and entry.name not in skipped
            and entry.is_dir()
        )
    except OSError:
        top_names = []
    res = []
    for i in range(max_depth):
        for top_name in top_names:
            top = os.path.join(glob.escape(start), glob.escape(top_name))
            pattern = os.path.join(top, *["*"] * i, "calkit.yaml")
            res += glob.glob(pattern)
            # Check GitHub documents for users who use GitHub Desktop
            pattern = os.path.join(
                top, "GitHub", *["*"] * (i + 1), "calkit.yaml"
            )
            res += glob.glob(pattern)
    if not relative:
        res += [
            os.path.join(p, "calkit.yaml")
            for p in get_recorded_project_paths()
        ]
    final_res = []
    for ck_fpath in res:
        path = os.path.dirname(ck_fpath)
        if path in final_res or not os.path.isfile(ck_fpath):
            continue
        # Make sure this path is a Git repo
        try:
            calkit.git.get_repo(path)
        except calkit.git.InvalidGitRepositoryError:
            continue
        final_res.append(path)
    return final_res


def get_project_checkouts(
    name: str,
    owner: str = "",
    warn: Any = None,
    search_protected: bool = True,
) -> dict[str, str]:
    """Find the checkouts of a project on this machine, by the owner and
    name each says it has, returning each one's owner by its real path.

    ``warn`` is called with why a project that can't be read was skipped.
    ``search_protected`` is as for :func:`find_project_dirs`. Each found is
    recorded, so it's found again without searching where it is.
    """
    found: dict[str, str] = {}
    for path in find_project_dirs(search_protected=search_protected):
        path = os.path.realpath(path)
        if path in found:
            continue
        try:
            # Most projects say their name, which rules them out without
            # asking Git for a remote, or, for one written plainly on its
            # own line, even parsing the file
            with open(os.path.join(path, "calkit.yaml"), "rb") as f:
                text = f.read()
            match = re.search(
                rb"^name:[ \t]*([\"']?)([\w.-]+)\1[ \t]*(?:#[^\r\n]*)?\r?$",
                text,
                flags=re.MULTILINE,
            )
            if match and match.group(2).decode() not in (
                name,
                "null",
                "Null",
                "NULL",
                "~",
            ):
                continue
            # One that says none takes it from its Git remote, so it's in
            # the repo's config, unless that's elsewhere, as a worktree's is
            git_config_path = os.path.join(path, ".git", "config")
            if not re.search(
                rb"^name[ \t]*:", text, flags=re.MULTILINE
            ) and os.path.isfile(git_config_path):
                with open(git_config_path, "rb") as f:
                    if name.encode() not in f.read():
                        continue
            info = load_calkit_info(wdir=path, read_only=True)
            declared = info.get("name") if isinstance(info, dict) else None
            if declared is not None and declared != name:
                continue
            # A subproject without its own repo would look like its parent
            repo = calkit.git.get_repo(path)
            if os.path.realpath(str(repo.working_tree_dir)) != path:
                continue
            p_owner, p_name = detect_project_name(wdir=path).split("/", 1)
        except ValueError:
            # It names no owner, so it can't be the one asked for
            continue
        except Exception as e:
            # E.g., a calkit.yaml left with merge conflict markers
            if warn is not None:
                warn(f"Skipping {path}, which can't be read: {e}")
            continue
        if p_name == name and owner in ("", p_owner):
            found[path] = p_owner
    for path in found:
        with contextlib.suppress(Exception):
            record_project_path(path)
    return found


def load_calkit_info(
    wdir: str | PathLike | None = None,
    read_only: bool = False,
) -> dict:
    """Load Calkit project information as a dictionary.

    Parameters
    ----------
    wdir : str
        Working directory. Defaults to current working directory.
    read_only: bool
        Parse with the C-backed loader instead of ruamel's round-trip
        parser, which is roughly 15x faster (~5 ms versus ~78 ms on a 42 KB
        calkit.yaml). Key order is preserved either way, since the loader
        builds plain dicts and those keep insertion order. What is lost is
        everything a faithful rewrite needs: comments, quoting style and
        anchors. Only pass True when the result will not be written back.
    """
    from ruamel.yaml.comments import CommentedMap

    info: dict = {}
    txt = ""
    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        # Always read as UTF-8; on Windows the default open() encoding is
        # cp1252, which mangles non-ASCII content (e.g., Greek letters).
        with open(fpath, encoding="utf-8") as f:
            txt = f.read()
        info = _load_yaml_readonly(txt) if read_only else ryaml.load(txt)
    if info is None:
        # A file holding nothing but comments parses as None, and returning a
        # plain dict here would drop them the next time it's written back.
        # That's the file ``calkit init`` creates: only the schema modeline,
        # which would then vanish on the project's first ``calkit new``.
        info = CommentedMap()
        comment = "\n".join(
            line.lstrip().removeprefix("#").strip()
            for line in txt.splitlines()
            if line.lstrip().startswith("#")
        )
        if comment and not read_only:
            info.yaml_set_start_comment(comment)
    return info


def iter_projects(
    wdir: str | None = None,
    ck_info: dict | None = None,
    read_only: bool = True,
    _seen: set[str] | None = None,
) -> Iterator[tuple[str, dict]]:
    """Yield ``(wdir, ck_info)`` for a project and each of its subprojects.

    Parent first, depth first, with paths relative to ``wdir``. A check
    that loops over this covers everything ``calkit run`` would run, which
    is what makes a subproject's requirements and environments part of the
    parent's rather than something only found by going in there.
    """
    base = os.path.normpath(wdir) if wdir else "."
    if ck_info is None:
        ck_info = load_calkit_info(wdir=base, read_only=read_only)
    yield base, ck_info
    # A subproject declaring its parent, or itself, would otherwise recurse
    # until the stack runs out
    seen = _seen if _seen is not None else {os.path.realpath(base)}
    for subproject in ck_info.get("subprojects") or []:
        path = subproject.get("path") if isinstance(subproject, dict) else None
        if not isinstance(path, str):
            continue
        sp_wdir = os.path.normpath(os.path.join(base, path))
        real = os.path.realpath(sp_wdir)
        if real in seen or not os.path.isfile(
            os.path.join(sp_wdir, "calkit.yaml")
        ):
            continue
        seen.add(real)
        yield from iter_projects(wdir=sp_wdir, read_only=read_only, _seen=seen)


def get_subprojects(ck_info: dict | None = None) -> dict[str, dict]:
    """Map each subproject's path, relative to the project, to the project
    declaring it (``parent``), its entry there, and its own ``ck_info``.

    Nested subprojects are included, in the order ``iter_projects`` visits
    them.
    """
    from pathlib import Path

    projects = {
        Path(wdir).as_posix(): info
        for wdir, info in iter_projects(ck_info=ck_info)
    }
    found: dict[str, dict] = {}
    for wdir, info in projects.items():
        for entry in info.get("subprojects") or []:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("path"), str
            ):
                continue
            sp = Path(os.path.normpath(os.path.join(wdir, entry["path"])))
            sp_posix = sp.as_posix()
            if sp_posix in projects and sp_posix != ".":
                found.setdefault(
                    sp_posix,
                    {
                        "parent": wdir,
                        "entry": entry,
                        "ck_info": projects[sp_posix],
                    },
                )
    return {p: found[p] for p in projects if p in found}


def describe_project(wdir: str) -> str:
    """How to name a subproject in a message, and nothing for the project
    itself."""
    return "" if wdir in (".", "") else f"subproject '{wdir}': "


def qualify_with_project(wdir: str, name: str) -> str:
    """Name something in a subproject the way its stages are named."""
    if wdir in (".", ""):
        return name
    from pathlib import Path

    return f"{Path(os.path.normpath(wdir)).as_posix()}:{name}"


@contextlib.contextmanager
def in_project(wdir: str) -> Iterator[None]:
    """Work from a project's directory, with its ``.env`` loaded, as if
    running from there."""
    import dotenv

    prev_wdir = os.getcwd()
    os.chdir(wdir)
    try:
        dotenv.load_dotenv(dotenv_path=".env")
        yield
    finally:
        os.chdir(prev_wdir)


def save_calkit_info(
    info: dict,
    wdir: str | PathLike | None = None,
) -> None:
    """Save Calkit project information to ``calkit.yaml``."""
    from pathlib import Path

    fpath = "calkit.yaml"
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    # Written as UTF-8, since on Windows the default open() encoding is
    # cp1252, which mangles non-ASCII content (e.g., Greek letters) into
    # mojibake, and only once the dump has succeeded, so a failure can't
    # leave the file empty
    ryaml.dump(info, Path(fpath))


def load_calkit_info_object(wdir: str | None = None) -> ProjectInfo:
    """Load Calkit project information as a ``ProjectInfo`` object."""
    from calkit.models import ProjectInfo

    return ProjectInfo.model_validate(load_calkit_info(wdir=wdir))


def utcnow(remove_tz=True) -> datetime:
    """Return now in UTC, optionally stripping timezone information."""
    dt = datetime.now(UTC)
    if remove_tz:
        dt = dt.replace(tzinfo=None)
    return dt


# Where set_env_vars keeps the user's own home directory when a project's
# env_vars change it, e.g., to /tmp for a tool a stage runs, so Calkit still
# finds its config, credentials, and caches
USER_HOME_ENV_VAR = "CALKIT_USER_HOME"


# These are here rather than in calkit.config, which every command's update
# check would otherwise import, with keyring and pydantic-settings, only to
# find where its state is kept
def get_calkit_cmd(module: str = "calkit") -> list[str]:
    """The command that runs one of Calkit's modules with this Python,
    without importing anything from the folder it runs in first, e.g., a
    project's own ``queue.py``.
    """
    if sys.version_info >= (3, 11):
        return [sys.executable, "-P", "-m", module]
    return [
        sys.executable,
        "-c",
        "import runpy, sys; sys.path.pop(0); "
        f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)",
    ]


def get_user_home() -> str:
    """The home directory Calkit keeps its own files in."""
    return os.environ.get(USER_HOME_ENV_VAR) or os.path.expanduser("~")


def get_env_suffix(sep: str = "-") -> str:
    """Suffix for the config file name, keyring service, and env var
    prefix.

    All real hubs share a single config file and keyring service, with
    hub credentials scoped inside them (see ``calkit.config``); only the
    test environment gets its own isolated config, so tests never touch
    real credentials.
    """
    if os.getenv("CALKIT_ENV") == "test":
        return sep + "test"
    return ""


LOCAL_DIR = ".calkit/local"


def ensure_local_dir(wdir: str | None = None) -> str:
    """Ensure the gitignored ``.calkit/local`` directory exists; return it.

    Everything under ``.calkit/local`` is private to the machine and kept out
    of version control via a ``*`` .gitignore.
    """
    base = os.path.join(wdir, LOCAL_DIR) if wdir else LOCAL_DIR
    os.makedirs(base, exist_ok=True)
    gitignore = os.path.join(base, ".gitignore")
    if not os.path.isfile(gitignore):
        with open(gitignore, "w") as f:
            f.write("*\n")
    return base


def write_if_changed(path: str, content: str | bytes) -> bool:
    """Write a file only if its content differs, returning whether it did,
    so whatever goes by its content or timestamp, e.g., DVC or latexmk,
    doesn't rerun for nothing.

    Text is written as UTF-8 bytes, so it's byte-identical on every
    platform, where text mode would write CRLF on Windows.
    """
    data = content.encode("utf-8") if isinstance(content, str) else content
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return True


def write_text(path: str | os.PathLike, text: str) -> None:
    """Write ``text``, with ``\\n`` line endings, to ``path`` as UTF-8 with
    the line endings the file has already, or else those Git checks it out
    with, so editing a file doesn't change the rest of its bytes.
    """
    import calkit.git

    try:
        with open(path, "rb") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = b""
    first_break = existing.find(b"\n")
    if first_break == -1:
        newline = calkit.git.get_checkout_newline(path)
    else:
        is_crlf = existing[first_break - 1 : first_break] == b"\r"
        newline = "\r\n" if is_crlf else "\n"
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


NOTEBOOK_STAGE_OUT_FORMATS = ["pickle", "parquet", "json", "yaml", "csv"]


def get_notebook_stage_dir(stage_name: str) -> str:
    return os.path.join(".calkit", "notebook-stages", stage_name)


def get_notebook_stage_script_path(stage_name: str) -> str:
    return os.path.join(get_notebook_stage_dir(stage_name), "script.py")


def get_notebook_stage_out_dir(stage_name: str) -> str:
    return os.path.join(get_notebook_stage_dir(stage_name), "outs")


def get_notebook_stage_out_path(
    stage_name: str,
    out_name: str,
    fmt: Literal["pickle", "parquet", "json", "yaml", "csv"] = "pickle",
) -> str:
    if fmt not in NOTEBOOK_STAGE_OUT_FORMATS:
        raise ValueError(f"Invalid output format '{fmt}'")
    return os.path.join(
        get_notebook_stage_out_dir(stage_name), f"{out_name}.{fmt}"
    )


def load_notebook_stage_out(
    stage_name: str,
    out_name: str,
    fmt: Literal["pickle", "parquet", "json", "yaml", "csv"] = "pickle",
    engine: Literal["pandas", "polars"] | None = None,
):
    fpath = get_notebook_stage_out_path(stage_name, out_name, fmt=fmt)
    if fmt in ["pickle", "json", "yaml"] and engine is not None:
        raise ValueError(
            f"Engine '{engine}' not compatible with format '{fmt}'"
        )
    if fmt == "pickle":
        with open(fpath, "rb") as f:
            return pickle.load(f)
    elif fmt == "yaml":
        with open(fpath) as f:
            return ryaml.load(f)
    elif fmt == "json":
        with open(fpath) as f:
            return json.load(f)
    elif fmt == "csv" and engine == "pandas":
        import pandas as pd

        return pd.read_csv(fpath)
    elif fmt == "csv" and engine == "polars":
        import polars as pl

        return pl.read_csv(fpath)
    elif fmt == "parquet" and engine == "pandas":
        import pandas as pd

        return pd.read_parquet(fpath)
    elif fmt == "parquet" and engine == "polars":
        import polars as pl

        return pl.read_parquet(fpath)
    raise ValueError(f"Unsupported format '{fmt}' for engine '{engine}'")


def save_notebook_stage_out(
    obj,
    stage_name: str,
    out_name: str,
    fmt: Literal["pickle", "parquet", "json", "yaml", "csv"] = "pickle",
    engine: Literal["pandas", "polars"] | None = None,
):
    fpath = get_notebook_stage_out_path(stage_name, out_name, fmt=fmt)
    dirname = os.path.dirname(fpath)
    os.makedirs(dirname, exist_ok=True)
    if fmt in ["pickle", "json", "yaml"] and engine is not None:
        raise ValueError(
            f"Engine '{engine}' not compatible with format '{fmt}'"
        )
    if fmt == "pickle":
        with open(fpath, "wb") as f:
            pickle.dump(obj, f)
    elif fmt == "json":
        with open(fpath, "w") as f:
            json.dump(obj, f)
    elif fmt == "yaml":
        with open(fpath, "w") as f:
            ryaml.dump(obj, f)
    elif fmt == "csv" and engine == "pandas":
        obj.to_csv(fpath)
    elif fmt == "parquet" and engine == "pandas":
        obj.to_parquet(fpath)
    elif fmt == "csv" and engine == "polars":
        obj.write_csv(fpath)
    elif fmt == "parquet" and engine == "polars":
        obj.write_parquet(fpath)
    else:
        raise ValueError(f"Unsupported format '{fmt}' for engine '{engine}'")


def make_readme_content(
    project_name: str, project_title: str, project_description: str | None
) -> str:
    """Create Markdown content for a Calkit project README."""
    txt = f"# {project_title}\n\n"
    if project_description is not None:
        txt += f"\n{project_description}\n"
    return txt


def update_readme_content(
    text: str, project_title: str, project_description: str | None
) -> str:
    """Retitle an existing README and add a description, keeping the rest.

    A template's README is often the project: its instructions, and in a
    runnable README the pipeline itself. So the first heading is replaced
    with the new title and the description goes just below it, and
    everything else is left as it was. A README with no heading gets one
    put in front of it.
    """
    lines = text.splitlines(keepends=True)
    heading = f"# {project_title}\n"
    intro = f"\n{project_description}\n" if project_description else ""
    for i, line in enumerate(lines):
        if re.match(r"^#(?!#)\s*\S", line):
            lines[i] = heading
            rest = "".join(lines[i + 1 :])
            if intro and not rest.startswith("\n"):
                intro += "\n"
            return "".join(lines[: i + 1]) + intro + rest
    body = text.lstrip("\n")
    return heading + intro + ("\n" + body if body else "")


def is_terminal(stream: Any) -> bool:
    """True when a stream is a terminal.

    On Windows, ``isatty`` is also true of the NUL device, e.g., for
    ``2>NUL`` or ``subprocess.DEVNULL``, so only a stream with a console
    mode counts there. Python writes to NUL with the ANSI code page, so
    taking it for a terminal, e.g., to draw a spinner, fails on the first
    character it can't encode. mintty isn't a console either; see
    :func:`is_mintty`.
    """
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if sys.platform != "win32":
        return True
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
    except (AttributeError, OSError, ValueError):
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetConsoleMode.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    mode = wintypes.DWORD()
    return bool(kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def is_tty() -> bool:
    """True only when both stdin and stdout are TTYs.

    Stdout matters because the prompt needs to render; stdin matters because
    we need to read the user's answer. CI environments fail at least one
    and fall through to the abort-with-fix-command path.

    Neither counts on Windows when it's the NUL device; see
    :func:`is_terminal`.
    """
    return is_terminal(sys.stdin) and is_terminal(sys.stdout)


def is_wsl() -> bool:
    """Whether this is Linux running under the Windows Subsystem for Linux."""
    if not sys.platform.startswith("linux"):
        return False
    # A container on a Windows host shares the WSL kernel, but it isn't WSL
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return False
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def is_mintty(stream: Any) -> bool:
    """True when a stream is a Git Bash or Cygwin (mintty) terminal.

    mintty gives native programs a named pipe rather than a console, so
    Python sees no terminal and picks the ANSI code page, even though
    mintty shows UTF-8 and ANSI escapes. It's told apart by the pipe's
    name, as Git for Windows does.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileNameInfo(ctypes.Structure):
        _fields_ = [
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 260),
        ]

    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
    except (AttributeError, OSError, ValueError):
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    # FILE_TYPE_PIPE
    if kernel32.GetFileType(handle) != 3:
        return False
    info = FileNameInfo()
    # FileNameInfo
    if not kernel32.GetFileInformationByHandleEx(
        handle, 2, ctypes.byref(info), ctypes.sizeof(info)
    ):
        return False
    name = info.FileName[: info.FileNameLength // 2]
    return (
        re.match(r"\\(cygwin|msys)-[0-9a-f]+-pty\d+-(from|to)-master", name)
        is not None
    )


def check_dep_exists(
    name: str,
    kind: Literal["app", "env-var", "calkit-config"] = "app",
    system_info: dict | None = None,
) -> bool:
    """Check that a dependency exists.

    TODO: Add version checking.
    """
    import shutil

    if kind == "env-var":
        return name in os.environ
    if kind == "calkit-config":
        import calkit.config

        cfg = calkit.config.read()
        return getattr(cfg, name, None) is not None
    if name == "calkit":
        return True
    if system_info is not None and system_info.get(f"{name.lower()}_version"):
        return True
    if find_app_path(name) is not None:
        return True
    # One on the PATH that wasn't found where Calkit looks for it is
    # another program, e.g., a 'word' that isn't Microsoft Word
    if shutil.which(name) is not None:
        return False
    cmd = [name]
    # Executables with non-conventional CLIs
    if name == "matlab":
        cmd.append("-help")
    else:
        # Fall back to simply calling ``--version``
        cmd.append("--version")
    try:
        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return True
    except FileNotFoundError:
        return False


def find_app_path(name: str) -> str | None:
    """Find where an app is installed, which can be off the PATH."""
    import shutil

    import calkit.office

    # Conda and mamba are frequently installed but not on the PATH (most
    # commonly on Windows), so search their typical install locations
    # rather than relying on the bare name being directly executable.
    if name in ("conda", "mamba"):
        from calkit.conda import find_conda_exe, find_mamba_exe

        return find_conda_exe() if name == "conda" else find_mamba_exe()
    # Julia runs through juliaup's launcher when its 'julia' isn't on the
    # PATH, which is found by its path rather than its bare name
    if name == "julia":
        from calkit.julia import get_julia_exe

        exe = get_julia_exe()
        return exe if os.path.isabs(exe) else None
    # Apps that aren't run by their name, or not on every OS
    if name in calkit.office.OFFICE_APPS:
        return calkit.office.find_app_path(name)
    if name == "libreoffice":
        from calkit.docx import find_soffice

        return find_soffice()
    # Apps Calkit exports with can be installed off the PATH, e.g., as a
    # macOS app bundle
    from calkit.export import exporters

    known = {e.name: e for e in exporters()}
    if name.lower() in known:
        return known[name.lower()].find_executable()
    return shutil.which(name)


def system_property_requirement_kinds() -> dict[str, str]:
    """Requirement kinds that name a machine property, and their info keys.

    These constrain something about the machine rather than requiring a
    thing to be present, so they carry no name: ``cpu-count`` is the whole
    identity of the entry. The values are the keys
    :func:`get_system_info` reports them under, which for the GPU
    properties is the list of GPUs they're read from.
    """
    from typing import get_args

    from calkit.environments import SYSTEM_LOCK_PROPERTIES
    from calkit.models.core import SystemNumberProperty, SystemValueProperty
    from calkit.models.requirements import GPU_PROPERTY_FIELDS

    props = list(get_args(SystemNumberProperty)) + list(
        get_args(SystemValueProperty)
    )
    return {
        prop: "gpus"
        if prop in GPU_PROPERTY_FIELDS
        else SYSTEM_LOCK_PROPERTIES[prop]
        for prop in props
    }


def _numeric_property_kinds() -> tuple[str, ...]:
    from typing import get_args

    from calkit.models.core import SystemNumberProperty

    return get_args(SystemNumberProperty)


# Whether the old key's deprecation has already been mentioned. Reading
# the requirements happens several times in one command -- the preflight
# check, the env-var resolution, the environment build -- and a project is
# only asked to rename the key once, not once per reader.
_warned_deprecated_dependencies_key = False


def get_requirements(ck_info: dict) -> list:
    """Read a project's requirements, honoring the old key name.

    ``dependencies`` was renamed to ``requirements`` once the list grew to
    hold things that can't be depended on so much as demanded -- a CPU
    count, an amount of memory. The old key still works, and says so once,
    since a rename nobody is told about is one nobody makes. A project that
    sets both has said the same thing twice in two places that can drift
    apart, so that is reported rather than merged.
    """
    global _warned_deprecated_dependencies_key
    reqs = ck_info.get("requirements")
    deps = ck_info.get("dependencies")
    if reqs and deps:
        raise ValueError(
            "Both 'requirements' and 'dependencies' are set in calkit.yaml; "
            "'dependencies' is the old name for the same key, so merge them "
            "into 'requirements'"
        )
    if deps and not _warned_deprecated_dependencies_key:
        from calkit.cli import warn

        _warned_deprecated_dependencies_key = True
        # Written for whoever has to act on it rather than raised as a
        # UserWarning, whose file-and-line formatting reads as a defect in
        # Calkit instead of a line to change in their own project
        warn(
            "The 'dependencies' key in calkit.yaml is deprecated; rename it "
            "to 'requirements', which is what it's called now that it also "
            "holds constraints on the machine itself.",
            err=True,
        )
    return list(reqs or deps or [])


def _normalize_requirement(req) -> dict:
    """Normalize a calkit.yaml requirement entry into a ``{kind, ...}`` dict.

    Accepts every form supported by ``check_requirements`` so callers that
    need access to extra fields (``check_command``, ``min``, etc.) don't
    have to re-parse:

    - plain string (treated as an app name, version specifiers split off)
    - ``{name: {kind: ..., ...attrs}}`` single-key form
    - ``{name, kind, ...attrs}`` flat form

    ``name`` is the identity of an ``app`` or ``env-var``, so it is
    required there. A ``setup`` requirement may omit it, since a single
    anonymous setup step is common and forcing users to invent a name adds
    friction; a stable one is synthesized from a short hash of
    ``check_command``. An ``aws-credentials`` requirement may omit it too,
    and is named after its profile and account. A machine-property
    requirement has no name at all --
    ``kind: cpu-count`` already says everything there is to say about which
    property it constrains -- so the kind is used as the name in messages.
    """

    def malformed() -> ValueError:
        return ValueError(
            f"Malformed requirement {req!r}; list an app by name, e.g., "
            "'- sbatch' or '- python>=3.11', or give the requirement's "
            "'kind', e.g., '- kind: env-var' with 'name: TOKEN'"
        )

    def check_search_paths(out: dict) -> None:
        if (
            out.get("search_paths") is not None
            and out["kind"] != "env-var-path"
        ):
            raise ValueError(
                f"Malformed requirement {req!r}; only an 'env-var-path' can "
                "have 'search_paths', since it's what names a path to look for"
            )

    if isinstance(req, str):
        # Split on the first version operator so a string like
        # ``calkit>=0.38`` produces both a clean name and a version spec
        # the caller can validate.
        m = re.match(r"^([A-Za-z0-9_.\-]+)(.*)$", req.strip())
        if m is None:
            raise malformed()
        out: dict = {"name": m.group(1), "kind": "app"}
        spec = m.group(2).strip()
        if spec:
            out["version_spec"] = spec
        return out
    if not isinstance(req, dict):
        raise malformed()
    keys = list(req.keys())
    # Flat form, an app unless it gives a kind: only requires ``name`` for
    # kinds where name is the identity (app, env-var). Setup requirements
    # may omit it, and property requirements have none to give.
    if "kind" in keys or "name" in keys:
        out = dict(req)
        out.setdefault("kind", "app")
        if "name" not in out:
            kind = out["kind"]
            if kind in system_property_requirement_kinds():
                out["name"] = kind
            elif kind == "setup":
                check_command = out.get("check_command", "")
                short = hashlib.sha1(
                    check_command.encode("utf-8")
                ).hexdigest()[:8]
                out["name"] = f"setup-{short}"
            elif kind == "aws-credentials":
                out["name"] = "-".join(
                    ["aws-credentials"]
                    + [
                        str(out[key])
                        for key in ("profile", "account_id")
                        if out.get(key)
                    ]
                )
            else:
                raise ValueError(f"Requirement missing required 'name': {req}")
        # YAML reads an unquoted name in braces, e.g., {var}, as a mapping
        if not isinstance(out["name"], str):
            raise ValueError(
                f"Malformed requirement {req!r}; its 'name' must be text, "
                'so quote it if it\'s in braces, e.g., name: "{var}"'
            )
        check_search_paths(out)
        return out
    if len(keys) != 1:
        raise malformed()
    # Single-key form: {name: {kind: ..., ...}}
    name = keys[0]
    attrs = req[name] or {}
    if not isinstance(attrs, dict):
        raise malformed()
    out = dict(attrs)
    out["name"] = name
    out.setdefault("kind", "app")
    check_search_paths(out)
    return out


def check_property_requirement(
    req: dict, system_info: dict, described_as: str = "this machine"
) -> Any:
    """Check one machine-property requirement against a machine, and return
    the value that meets it, e.g., the name of the GPU that does.

    ``system_info`` is what :func:`get_system_info` reports, either from
    here or from the far end of an SSH connection, so the same constraints
    can be checked wherever the stage will actually run. ``described_as``
    names that machine in any error, since "2 CPUs are required, this has
    1" is a different problem depending on which machine "this" is.

    Raises ``ValueError`` describing what was asked for and what was found.
    A property the machine can't report is an error too, rather than a
    silent pass: an unanswerable question isn't a satisfied one.
    """
    from calkit.models.requirements import GPU_PROPERTY_FIELDS

    def check_value(value: Any) -> None:
        """Check one value of the property against the requirement."""
        from packaging.specifiers import SpecifierSet
        from packaging.version import InvalidVersion, Version

        # Numeric properties are bounded; everything else is matched or
        # compared as a version.
        if prop in _numeric_property_kinds():
            minimum = req.get("min")
            maximum = req.get("max")
            if minimum is None and maximum is None:
                raise ValueError(
                    f"Requirement on '{prop}' needs a 'min' or a 'max'; to "
                    "depend on its value rather than constrain it, add it to "
                    "the environment's 'lock'"
                )
            if minimum is not None and value < minimum:
                raise ValueError(
                    f"{described_as} has {prop} {_fmt_prop(value)}, but at "
                    f"least {_fmt_prop(minimum)} is required"
                )
            if maximum is not None and value > maximum:
                raise ValueError(
                    f"{described_as} has {prop} {_fmt_prop(value)}, but at "
                    f"most {_fmt_prop(maximum)} is required"
                )
            return
        equals = req.get("equals")
        spec = req.get("version_spec")
        patterns = req.get("matches")
        if equals is None and spec is None and patterns is None:
            raise ValueError(
                f"Requirement on '{prop}' needs an 'equals', 'matches' or a "
                "'version_spec'; to depend on its value rather than constrain "
                "it, add it to the environment's 'lock'"
            )
        if patterns is not None:
            import fnmatch

            globs = [patterns] if isinstance(patterns, str) else list(patterns)
            if not any(
                fnmatch.fnmatchcase(str(value).lower(), str(g).lower())
                for g in globs
            ):
                wanted = " or ".join(f"'{g}'" for g in globs)
                raise ValueError(
                    f"{described_as} has {prop} '{value}', which doesn't "
                    f"match {wanted}"
                )
        if equals is not None:
            allowed = [equals] if isinstance(equals, str) else list(equals)
            # Matched case-insensitively because the same machine is 'Darwin'
            # or 'darwin' depending on who is writing it down, and nobody means
            # those to be different answers.
            if str(value).lower() not in [str(a).lower() for a in allowed]:
                wanted = " or ".join(f"'{a}'" for a in allowed)
                raise ValueError(
                    f"{described_as} has {prop} '{value}', but {wanted} is "
                    "required"
                )
        if spec is not None:
            try:
                spec_set = SpecifierSet(
                    spec if spec[0] in "<>=!~" else f"=={spec}"
                )
            except Exception as e:
                raise ValueError(
                    f"Invalid version_spec '{spec}' for {prop}: {e}"
                )
            try:
                parsed = Version(str(value))
            except InvalidVersion:
                raise ValueError(
                    f"{described_as} reports {prop} '{value}', which can't be "
                    f"read as a version to compare against '{spec}'"
                )
            if parsed not in spec_set:
                raise ValueError(
                    f"{described_as} has {prop} '{value}', but '{spec}' is "
                    "required"
                )

    prop = req["kind"]
    key = system_property_requirement_kinds()[prop]
    value = system_info.get(key)
    if value is None:
        raise ValueError(
            f"Requirement on '{prop}' can't be checked because "
            f"{described_as} doesn't report it"
        )
    if prop in GPU_PROPERTY_FIELDS:
        field = GPU_PROPERTY_FIELDS[prop]
        values = [gpu[field] for gpu in value if gpu.get(field)]
        if not values:
            raise ValueError(
                f"Requirement on '{prop}' isn't met because {described_as} "
                "has no GPU that reports it"
            )
        problems = []
        for gpu_value in values:
            try:
                check_value(gpu_value)
                return gpu_value
            except ValueError as e:
                problems.append(str(e))
        if len(problems) == 1:
            raise ValueError(problems[0])
        raise ValueError(
            f"No GPU on {described_as} meets the requirement on '{prop}': "
            + "; ".join(problems)
        )
    check_value(value)
    return value


def _fmt_prop(value: float) -> str:
    """Format a numeric property so whole numbers don't read as floats."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def extract_version(text: str, full: bool = False) -> str | None:
    """Pull a comparable version out of what a tool prints for ``--version``.

    Tools answer that question in their own way -- 'git version 2.39.5',
    'uv 0.4.18 (a1b2c3d)' -- so the number has to be found rather than
    read off. It's the first dotted number not inside another number,
    which may follow letters, e.g., 'go1.22.0' or 'OpenSSH_9.6p1'. Failing
    that, it's a bare number that doesn't follow a word, so a name like
    'x86_64' isn't mistaken for it, though letters may follow, as in
    Windows Server's release, '2025Server'. A year like nvcc's
    'Copyright (c) 2005' is only taken if there's no dotted number. A build
    hash that follows is not part of what a specifier compares.

    With ``full``, a suffix attached to the number is kept, e.g.,
    '3.12.10rc1' or '11.4.0-1ubuntu1~22.04'.
    """
    m = re.search(
        r"(?<![\d.])v?(\d+(?:\.\d+)+)((?:[-+~.]?[0-9A-Za-z]+)*)", text or ""
    ) or re.search(
        r"(?<![\w.])v?(\d+)((?:[-+~]?[A-Za-z][0-9A-Za-z]*)*)(?![\d.])",
        text or "",
    )
    if m is None:
        return None
    return m.group(1) + m.group(2) if full else m.group(1)


def check_app_version(
    name: str,
    spec: str,
    system_info: dict | None = None,
    described_as: str = "this machine",
    probe_locally: bool = True,
) -> str | None:
    """Check an installed app against a version specifier, and return the
    version found, if it could be read.

    ``system_info`` supplies versions for the tools a system description
    already collects; anything else is asked directly, unless the machine
    in question isn't this one, which is what ``probe_locally=False``
    says. Reading a local version to check a remote requirement would
    answer a different question than the one asked.

    A version that can't be read is reported rather than treated as a
    failure: plenty of tools don't answer ``--version`` in any parseable
    way, and refusing to run because we couldn't read one would make the
    field unusable for them. Saying so keeps it from looking checked.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    raw = (system_info or {}).get(f"{name.lower()}_version")
    if raw is None and probe_locally:
        raw = get_dep_version(name)
    found = extract_version(raw) if raw else None
    if found is None:
        print(
            f"Warning: could not read {name}'s version on {described_as}, so "
            f"'{spec}' was not checked"
        )
        return None
    spec_str = spec if spec[0] in "<>=!~" else f"=={spec}"
    try:
        spec_set = SpecifierSet(spec_str)
    except Exception as e:
        raise ValueError(f"Invalid version_spec '{spec}' for app {name}: {e}")
    try:
        parsed = Version(found)
    except InvalidVersion:
        print(
            f"Warning: {name} reports version '{found}' on {described_as}, "
            f"which can't be compared against '{spec}'"
        )
        return None
    if parsed not in spec_set:
        raise ValueError(
            f"app '{name}' is version {found} on {described_as}, but "
            f"'{spec_str}' is required"
        )
    return found


def get_version_checked_app_names(
    ck_info: dict, stage_names: list[str] | set[str] | None = None
) -> list[str]:
    """The apps a requirement checked here gives a version spec for.

    Only these are worth asking for a version up front, since some apps,
    e.g., MATLAB, take seconds to say. That's the project's requirements
    and those of the stages in ``stage_names``, or all stages, and their
    environments, except for stages run on another machine, whose
    requirements are checked there.
    """
    from calkit.environments import (
        COMPOSITE_ENV_SEP,
        SWITCH_KIND,
        runs_elsewhere,
    )
    from calkit.install import NAME_ALIASES
    from calkit.pipeline import get_stage_items

    envs = ck_info.get("environments") or {}
    reqs = list(get_requirements(ck_info))
    stages = (ck_info.get("pipeline") or {}).get("stages", {})
    # With each item's values, when its environment or requirements use them
    items: dict[str, dict] = {}
    for name, stage in stages.items():
        if stage_names is None or name in stage_names:
            items |= get_stage_items(
                name, stage, params=ck_info.get("parameters")
            )
    for stage in items.values():
        env_names = str(stage.get("environment") or "_system").split(
            COMPOSITE_ENV_SEP
        )
        stage_envs = [envs.get(n) or {} for n in env_names]
        if any(runs_elsewhere(env) for env in stage_envs):
            continue
        # A switch may pick any of its options here that are local
        for env in list(stage_envs):
            if env.get("kind") == SWITCH_KIND:
                # An option is named or, when only the switch uses it,
                # defined in place
                options = [
                    o["use"]
                    if isinstance(o.get("use"), dict)
                    else envs.get(o.get("use")) or {}
                    for o in env.get("switch") or []
                    if isinstance(o, dict)
                ]
                stage_envs += [o for o in options if not runs_elsewhere(o)]
        reqs += stage.get("requirements") or []
        for env in stage_envs:
            reqs += env.get("requirements") or []
    names = []
    for raw in reqs:
        req = _normalize_requirement(raw)
        if (
            req["kind"] == "app"
            and req["name"] != "calkit"
            and req.get("version_spec")
        ):
            # As checked, e.g., code for vscode
            names.append(NAME_ALIASES.get(req["name"], req["name"]))
    return list(dict.fromkeys(names))


def get_requirement_key(req: Any, wdir: str | None = None) -> str:
    """Identify a requirement however it's written, e.g., to cache its check.

    One checked by running something in the project, e.g., a setup step's
    ``check_command``, or by reading its ``.env``, is identified by that
    project's directory too.
    """
    normalized = _normalize_requirement(req)
    if normalized["kind"] in ("setup", "aws-credentials", "env-var-path"):
        normalized = normalized | {"_wdir": os.path.abspath(wdir or ".")}
    return json.dumps(normalized, sort_keys=True, default=str)


def check_requirements(
    ck_info: dict | None = None,
    wdir: str | None = None,
    system_info: dict | None = None,
    interactive: bool | None = None,
    use_cache: bool = True,
    requirements: list | None = None,
    described_as: str = "this machine",
    checked: dict[str, str | None] | None = None,
    report: Callable[[str], None] | None = None,
) -> None:
    """Check that a project's declared requirements are satisfied.

    With no ``requirements`` given, the project's own list is checked,
    which describes the host -- the built-in ``_system`` environment. A
    ``system`` environment passes its own list here instead, for the
    machine it names.

    With ``checked``, each requirement is checked once across calls: its
    outcome, None or what's wrong, is kept there under
    :func:`get_requirement_key` and reused, so one many stages share is only
    asked about once. Every requirement of a kind is then checked, and what
    isn't met reported together, but not those of later kinds, which may
    depend on them.

    ``setup`` requirements are verified via
    :func:`calkit.requirements.check_setup_dep`, which runs the
    ``check_command`` and -- on an interactive TTY -- optionally runs the
    declared ``setup_command`` after asking the user. Non-interactive
    failures abort with the fix-it command printed for the user to run.
    ``aws-credentials`` requirements are checked the same way, by
    :func:`calkit.requirements.check_aws_credentials_req`.

    ``report`` is given a line for each requirement met, saying how, e.g.,
    where an app was found. An env var's value is never in it, since
    secrets are kept in them.
    """
    import calkit.office
    from calkit import install as _install

    def abbreviate_home(path: str) -> str:
        """Write a path in the home directory from ``~``."""
        home = os.path.expanduser("~")
        if path == home or path.startswith(home + os.sep):
            return "~" + path[len(home) :]
        return path

    def report_app(declared_name: str, name: str, version: str | None) -> None:
        """Report where an app was found, and its version if checked."""
        if report is None:
            return
        path = find_app_path(name)
        details = [version] if version else []
        # Office apps and app bundles, which are folders, aren't run from
        # the PATH anyway
        if (
            path is not None
            and os.path.isfile(path)
            and name not in calkit.office.OFFICE_APPS
        ):
            path_dirs = [
                os.path.normcase(os.path.abspath(d))
                for d in os.environ.get("PATH", "").split(os.pathsep)
                if d
            ]
            found_dir = os.path.dirname(os.path.abspath(path))
            if os.path.normcase(found_dir) not in path_dirs:
                details.append("not on PATH")
        report(
            f"{declared_name}: "
            + ("found" if path is None else abbreviate_home(path))
            + (f" ({', '.join(details)})" if details else "")
        )

    def describe_property_requirement(req: dict) -> str:
        """Describe what a machine-property requirement asks for."""
        parts = [
            f"{key} {_fmt_prop(req[key])}"
            for key in ("min", "max")
            if req.get(key) is not None
        ]
        for key in ("equals", "matches"):
            value = req.get(key)
            if value is not None:
                values = [value] if isinstance(value, str) else value
                parts.append(key + " " + " or ".join(f"'{v}'" for v in values))
        if req.get("version_spec"):
            parts.append(str(req["version_spec"]))
        return ", ".join(parts)

    if requirements is not None:
        # An environment's own list is checked exactly as declared: it
        # describes a machine that runs stages, which is a smaller claim
        # than being where the project lives.
        reqs = list(requirements)
    else:
        if ck_info is None:
            ck_info = load_calkit_info(wdir=wdir)
        reqs = get_requirements(ck_info)
        # Git is how a project exists at all, so the host needs it whether
        # or not anyone wrote it down, e.g., as git>=2.30
        if not any(
            r["kind"] == "app" and r["name"] == "git"
            for r in map(_normalize_requirement, reqs)
        ):
            reqs.append("git")
    # Resolve TTY interactivity once so a single per-call answer drives
    # every prompt (env-var, app installer, setup step).
    if interactive is None:
        interactive = is_tty()
    # Process in dependency order: machine properties first, since a
    # machine that is too small to run the project at all should say so
    # before we start installing things on it, then env-vars (some
    # installers and setup commands read from them), then apps (env
    # managers like pixi / uv need to exist before setup steps that run
    # inside an env), then setup steps, then AWS credentials, which need
    # the AWS CLI and may be set up by a step. The setup-step
    # ``check_command`` typically wraps ``calkit xenv``, which validates
    # its own environment, so we don't need a separate env-check phase.
    property_kinds = system_property_requirement_kinds()
    buckets: dict[str, list[dict]] = {
        "_property": [],
        "env-var": [],
        "env-var-path": [],
        "app": [],
        "setup": [],
        "aws-credentials": [],
    }
    for raw in reqs:
        req = _normalize_requirement(raw)
        kind = req["kind"]
        if kind in property_kinds:
            buckets["_property"].append(req)
        elif kind not in buckets:
            # Unknown / legacy kinds (e.g., ``calkit-config``) fall through
            # to ``check_dep_exists`` in original order so we don't change
            # behavior for them silently.
            buckets.setdefault("_other", []).append(req)
        else:
            buckets[kind].append(req)
    if checked is not None:
        # One at a time, in the order below, so each outcome is known
        if buckets["_property"] and system_info is None:
            system_info = get_machine_properties()
        for bucket in (
            "_property",
            "env-var",
            "env-var-path",
            "app",
            "_other",
            "setup",
            "aws-credentials",
        ):
            problems = []
            for req in buckets.get(bucket, []):
                key = get_requirement_key(req, wdir=wdir)
                if key not in checked:
                    try:
                        check_requirements(
                            wdir=wdir,
                            system_info=system_info,
                            interactive=interactive,
                            use_cache=use_cache,
                            requirements=[req],
                            described_as=described_as,
                            report=report,
                        )
                        checked[key] = None
                    except ValueError as e:
                        checked[key] = str(e)
                elif report is not None and checked[key] is None:
                    report(f"{req['name']}: checked above")
                problem = checked[key]
                if problem is not None:
                    problems.append(problem)
            if problems:
                raise ValueError("; ".join(problems))
        return
    if buckets["_property"]:
        # Read the machine only when something asks about it; describing a
        # system shells out for a version from every package manager it can
        # find, which is not a cost to pay for a project that has no
        # property requirements at all.
        info = (
            system_info
            if system_info is not None
            else get_machine_properties()
        )
        # GPUs likewise, since finding them can start a GPU runtime
        gpu_kinds = [k for k, v in property_kinds.items() if v == "gpus"]
        if "gpus" not in info and any(
            req["kind"] in gpu_kinds for req in buckets["_property"]
        ):
            info = {**info, "gpus": [dict(g) for g in get_gpus()]}
        for req in buckets["_property"]:
            value = check_property_requirement(
                req, info, described_as=described_as
            )
            if report is None:
                continue
            # A machine's raw ID should be kept confidential
            if req["kind"] == "machine-id":
                report("machine-id: matches")
                continue
            if isinstance(value, float):
                value = _fmt_prop(value)
            report(
                f"{req['kind']}: {value} "
                f"({describe_property_requirement(req)})"
            )
    for req in buckets["env-var"]:
        req_name = req["name"]
        if req_name in os.environ:
            if report is not None:
                report(f"{req_name}: set")
            continue
        # On a TTY, prompt the user and persist to .env so the very next
        # ``calkit run`` works without a separate setup step. Non-TTY
        # (CI) falls through to the legacy "not found" abort.
        if interactive:
            from calkit.requirements import prompt_for_env_var_req

            if prompt_for_env_var_req(req) is not None:
                if report is not None:
                    report(f"{req_name}: set")
                continue
        msg = f"env-var '{req_name}' not found"
        if req.get("setup_command"):
            msg += (
                f"; get a value with '{req['setup_command']}' and set it "
                f"with 'calkit set-env-var {req_name} <value>'"
            )
        raise ValueError(msg)
    for req in buckets["env-var-path"]:
        from calkit.requirements import check_env_var_path_req

        path = check_env_var_path_req(req, interactive=interactive)
        if report is not None:
            report(f"{req['name']}: {abbreviate_home(path)}")
    for req in buckets["app"]:
        declared_name = req["name"]
        # Checked and installed as the binary it provides, e.g., code for
        # vscode
        req_name = _install.NAME_ALIASES.get(declared_name, declared_name)
        # The ``calkit`` app is always satisfied by the running process,
        # but a declared ``version_spec`` (e.g. ``calkit>=0.38``) is
        # checked against the installed version so projects can pin a
        # minimum CLI without writing a custom setup step.
        if req_name == "calkit":
            spec = req.get("version_spec")
            if spec:
                from calkit.requirements import check_calkit_version

                check_calkit_version(spec)
            if report is not None:
                from calkit import __version__

                report(f"{declared_name}: {__version__}")
            continue
        spec = req.get("version_spec")
        if check_dep_exists(req_name, "app", system_info=system_info):
            version = None
            if spec:
                version = check_app_version(
                    req_name,
                    spec,
                    system_info=system_info,
                    described_as=described_as,
                )
            report_app(declared_name, req_name, version)
            continue
        # Offer the project's own way to install it, or else the registered
        # native installer when we have one
        setup_command = req.get("setup_command")
        description = (req.get("description") or "").strip()
        registered = _install.get_installer(req_name)
        # Only the project's own command is an override; the registered
        # installer goes through by name, so declining it points at
        # 'calkit install' rather than its raw script
        override: _install.Installer | None = None
        if setup_command:
            override = {"script": setup_command, "path_add": []}
            if registered is not None:
                # The app tends to land in the same place however it's
                # installed, e.g., ~/.local/bin, so keep where to look for
                # it, but not the registry's prerequisites, which the
                # project's command may not need
                override["path_add"] = registered["path_add"]
                if "binary" in registered:
                    override["binary"] = registered["binary"]
        if override is not None or registered is not None:
            print(f"App '{declared_name}' is not installed.")
            if description and interactive:
                print(f"  {description}")
            if _install.prompt_and_install(
                req_name, interactive=interactive, entry=override
            ) and check_dep_exists(req_name, "app", system_info=system_info):
                version = None
                if spec:
                    version = check_app_version(
                        req_name,
                        spec,
                        system_info=system_info,
                        described_as=described_as,
                    )
                report_app(declared_name, req_name, version)
                continue
        # Some apps have no installer here but a known way in, e.g., a
        # system package manager on Linux
        hint = (
            None
            if setup_command
            else _install.get_unsupported_message(req_name)
        )
        raise ValueError(
            f"app '{declared_name}' not found on {described_as}"
            + (f"; {hint}" if hint else "")
            + (f"\n  {description}" if description else "")
        )
    for req in buckets.get("_other", []):
        req_name = req["name"]
        req_kind = req["kind"]
        if not check_dep_exists(req_name, req_kind, system_info=system_info):
            raise ValueError(f"{req_kind} '{req_name}' not found")
        if report is not None:
            report(f"{req_name}: found")
    for req in buckets["setup"]:
        from calkit.requirements import check_setup_dep

        ok = check_setup_dep(
            req,
            interactive=interactive,
            use_cache=use_cache,
            wdir=wdir,
            report=report,
        )
        if not ok:
            raise ValueError(
                f"setup requirement '{req['name']}' is not satisfied"
            )
    for req in buckets["aws-credentials"]:
        from calkit.requirements import check_aws_credentials_req

        ok = check_aws_credentials_req(
            req,
            interactive=interactive,
            use_cache=use_cache,
            wdir=wdir,
            report=report,
        )
        if not ok:
            raise ValueError(
                f"aws-credentials requirement '{req['name']}' is not satisfied"
            )


# Pre-rename names, kept so existing callers keep working.
check_system_deps = check_requirements
_normalize_dep = _normalize_requirement


def get_env_var_dep_names(ck_info: dict | None = None) -> list[str]:
    """Get the names of the project's ``env-var`` requirements.

    ``env-var-path`` requirements are left out, since what these are for,
    passing them into Docker containers, would hand a container a path on
    the host.
    """
    if ck_info is None:
        ck_info = load_calkit_info()
    env_vars = []
    for req in get_requirements(ck_info):
        # Delegate shape-parsing to ``_normalize_requirement`` so this stays
        # in lockstep with ``check_requirements`` -- string entries,
        # single-key dicts, flat dicts, and nameless setup steps all flow
        # through one path.
        normalized = _normalize_requirement(req)
        if normalized["kind"] == "env-var":
            env_vars.append(normalized["name"])
    return env_vars


def project_and_path_from_path(path: str) -> tuple:
    """Split a path into project and path, respecting the ``CALKIT_PROJECT``
    environmental variable if set.

    For example, a path like

        someone/some-project:some/path/to/file.png

    will return

        (someone/some-project, some/path/to/file.png)
    """
    path_split = path.split(":")
    if len(path_split) == 2:
        project = path_split[0]
        path = path_split[1]
    elif len(path_split) == 1:
        project = None
    else:
        raise ValueError("Path has too many colons in it")
    if project is None:
        project = os.getenv("CALKIT_PROJECT")
    return project, path


def read_file(path: str, as_bytes: bool | None = None) -> str | bytes:
    """Read file content from path, which can optionally include a project
    identifier, which if specified will indicate we should read from the API.
    """
    project, path = project_and_path_from_path(path)
    if as_bytes is None:
        _, ext = os.path.splitext(path)
        as_bytes = ext in [
            ".png",
            ".jpg",
            ".gif",
            ".jpeg",
            ".pdf",
            ".xlsx",
            ".docx",
        ]
    if project is not None:
        import calkit.hub

        if len(project.split("/")) != 2:
            raise ValueError("Invalid project identifier (too many slashes)")
        resp = calkit.hub.get(f"/projects/{project}/contents/{path}")
        # If the response has a content key, that is a base64 encoded string
        if (content := resp.get("content")) is not None:
            # Load the content appropriately
            content_bytes = base64.b64decode(content)
            if as_bytes:
                return content_bytes
            else:
                return content_bytes.decode()
        # If the response has a URL, we can fetch from that directly
        elif (url := resp.get("url")) is not None:
            import requests

            resp2 = requests.get(url)
            resp2.raise_for_status()
            if as_bytes:
                return resp2.content
            else:
                return resp2.text
        else:
            raise ValueError("No content or URL returned from API")
    # Project is None, so let's just read a local file
    with open(path, mode="rb" if as_bytes else "r") as f:
        return f.read()


def get_dvc_size_thresh_bytes(path: str) -> int:
    """The size above which a new file at ``path`` goes to DVC."""
    if os.path.splitext(path)[-1].lower() in FIGURE_EXTENSIONS:
        return FIGURE_DVC_SIZE_THRESH_BYTES
    return DVC_SIZE_THRESH_BYTES


def get_output_date_env_vars() -> dict[str, str]:
    """Environmental variables that keep the time out of files a pipeline
    run of Python writes, e.g., Matplotlib's PDFs, unless already set.
    """
    if not os.environ.get("CALKIT_PIPELINE_RUNNING") or os.environ.get(
        "SOURCE_DATE_EPOCH"
    ):
        return {}
    return {"SOURCE_DATE_EPOCH": OUTPUT_SOURCE_DATE_EPOCH}


def get_size(path: str):
    """Get the size of a path in bytes.

    This differs from ``os.path.getsize`` in that it is recursive.
    """
    if os.path.isfile(path):
        return os.path.getsize(path)
    # From https://stackoverflow.com/a/1392549/2284865
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size


def to_kebab_case(str) -> str:
    """Convert a string to kebab-case."""
    return re.sub(r"[-_/,\.\ ]", "-", str.lower())


def get_project_status_history(wdir: str | None = None, as_pydantic=True):
    from calkit.models import ProjectStatus

    statuses = []
    fpath = os.path.join(".calkit", "status.csv")
    if wdir is not None:
        fpath = os.path.join(wdir, fpath)
    if os.path.isfile(fpath):
        with open(fpath) as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header row
            for line in reader:
                ts, status, message = line
                ts = datetime.fromisoformat(ts)
                obj = ProjectStatus(
                    timestamp=ts,
                    status=status,  # type: ignore
                    message=message,
                )
                if not as_pydantic:
                    obj = obj.model_dump()
                statuses.append(obj)
    return statuses


def get_latest_project_status(wdir: str | None = None) -> ProjectStatus | None:
    statuses = get_project_status_history(wdir=wdir)
    if statuses:
        return statuses[-1]  # type: ignore


def get_owner_and_name_from_git_url(url: str) -> tuple[str, str] | None:
    """Read an owner and project name out of a Git remote URL.

    Handles the SSH and HTTPS forms of any host, since the last two path
    segments name the owner and repo on GitHub, GitLab, and everything
    modeled on them. A GitLab project inside subgroups takes the innermost
    group as its owner, which is what its container registry namespace uses
    as well. Returns None for a URL with nothing that looks like a path,
    which is where a local or unusual remote ends up.
    """
    url = url.strip().removesuffix(".git").removesuffix("/")
    # An SSH remote is 'git@host:owner/repo', whose path is what follows the
    # colon rather than a slash
    if "://" not in url and ":" in url:
        url = url.split(":", 1)[-1]
    else:
        url = url.split("://", 1)[-1]
        # Drop 'user@host' or 'host', leaving the path
        url = url.split("/", 1)[-1] if "/" in url else ""
    parts = [p for p in url.split("/") if p]
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def detect_project_name(
    wdir: str | None = None, prepend_owner: bool = True
) -> str:
    """Detect a Calkit project owner and name.

    ``owner`` and ``name`` in ``calkit.yaml`` are what a project is, so
    they're read first and the Git remote is only consulted for what they
    don't say. A remote is a weaker answer: a fork's remote names whoever
    forked it rather than the project it's a copy of.

    If ``prepend_owner`` is False, fall back to the working directory name
    if there is no Git remote or name specified in ``calkit.yaml``.
    """
    ck_info = load_calkit_info(wdir=wdir, read_only=True)
    name = ck_info.get("name")
    if name is not None and not prepend_owner:
        return name
    owner = ck_info.get("owner")
    from_url = None
    if name is None or owner is None:
        try:
            url = calkit.git.get_repo(wdir).remote().url
            from_url = get_owner_and_name_from_git_url(url)
        except (ValueError, calkit.git.InvalidGitRepositoryError):
            from_url = None
    if from_url is not None:
        owner_from_url, name_from_url = from_url
        if name is None:
            name = name_from_url
        if owner is None:
            owner = owner_from_url
    if not prepend_owner:
        if name is not None:
            return name
        if wdir is None:
            wdir = os.getcwd()
        return os.path.basename(os.path.abspath(wdir))
    if name is None or owner is None:
        raise ValueError(
            "Project owner and name are not set in calkit.yaml, and no Git "
            "remote names them"
        )
    return f"{owner}/{name}"


def normalize_git_url(url: str) -> str:
    """An SSH GitHub URL as its HTTPS form; anything else unchanged.

    ``git@github.com:owner/repo.git`` and ``https://github.com/owner/repo``
    name the same repo, and only the latter is a link, so that's the one
    worth recording.
    """
    url = url.strip()
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:") :]
    if url.startswith("https://github.com/") and url.endswith(".git"):
        url = url[: -len(".git")]
    return url


def detect_project_github_url(wdir: str | None = None) -> str | None:
    """Detect the GitHub URL for the current project."""
    try:
        url = calkit.git.get_repo(wdir).remote().url
    except ValueError:
        warnings.warn("No Git remote set with name 'origin'")
        return None
    if "github.com" not in url:
        warnings.warn("Git remote is not a GitHub URL")
        return None
    url = url.removesuffix(".git")
    url = normalize_git_url(url)
    return url


def get_dep_version(dep_name: str) -> str | None:
    """Get the version of a system-level dependency."""
    from calkit.export import exporters

    known = {e.name: e for e in exporters()}
    if dep_name.lower() in known:
        return known[dep_name.lower()].version()
    # MATLAB has no '--version', and starts in full if passed one
    if dep_name == "matlab":
        cmd = [dep_name, "-batch", "disp(version)"]
    else:
        cmd = [dep_name, "--version"]
    try:
        # Without stdin, a tool that ignores the flag can't wait on a prompt
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
        # Some tools, e.g., older Java, print their version to stderr
        return result.stdout.strip() or result.stderr.strip()
    except Exception:
        return None


# Where each platform records an identifier for the machine itself, as
# opposed to a name for it. Documentation for the error paths and the docs
# below; the readers are selected by ``platform.system()``, not by this.
MACHINE_ID_SOURCES = {
    "Darwin": "IOPlatformUUID (ioreg)",
    "Linux": "/etc/machine-id",
    "Windows": r"HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid",
}


def _read_darwin_machine_id() -> str | None:
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    return match.group(1).strip() if match else None


def _read_linux_machine_id() -> str | None:
    # The dbus copy predates systemd's and is still the only one on systems
    # without it. Both hold the same value where both exist.
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path) as f:
                value = f.read().strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _read_windows_machine_id() -> str | None:
    # Guarded on sys.platform rather than caught as an ImportError so type
    # checkers on other platforms know the body doesn't apply to them;
    # winreg is always there on the one platform that reaches it
    if sys.platform != "win32":
        return None
    import winreg

    try:
        # Explicitly the 64-bit view, so a 32-bit Python doesn't get
        # redirected to a different key and report a different machine
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
    except OSError:
        return None
    return str(value).strip() or None


@functools.cache
def _read_platform_machine_id() -> str | None:
    # Cached, since it can take a subprocess and is read for every stage
    readers = {
        "Darwin": _read_darwin_machine_id,
        "Linux": _read_linux_machine_id,
        "Windows": _read_windows_machine_id,
    }
    reader = readers.get(platform.system())
    return reader() if reader is not None else None


def normalize_machine_id(machine_id: str | None) -> str | None:
    """Reduce a machine ID to what is worth comparing.

    Platforms write the same kind of identifier differently -- macOS in
    uppercase with dashes, systemd in lowercase without -- and users paste
    back whichever form they were shown. Case and dashes carry no
    information here, so they don't get to decide whether two IDs match.
    """
    if not machine_id:
        return None
    return machine_id.strip().lower().replace("-", "") or None


def machine_ids_match(a: str | None, b: str | None) -> bool:
    """Whether two machine IDs name the same machine.

    An unknown ID matches nothing, including another unknown one: not
    knowing which machine this is is never evidence that it's the one
    being asked about.
    """
    norm_a = normalize_machine_id(a)
    return norm_a is not None and norm_a == normalize_machine_id(b)


def get_machine_id() -> str | None:
    """A stable identifier for the machine we're running on, if there is one.

    Hostnames are the obvious way to say "this machine" and the worst way
    to mean it: they get renamed, they differ between what the machine
    calls itself and what DNS calls it, and two machines on different
    networks can share one. Pinning results to a particular machine, or
    recognizing that we're already on it, needs something that outlives all
    of that.

    Read from the platform (see ``MACHINE_ID_SOURCES``) rather than
    generated by Calkit, so there's nothing to bootstrap on a new machine,
    nothing lost by clearing Calkit's own config, and no way for two
    machines to end up sharing an ID by restoring one's dotfiles onto the
    other. ``machine_id`` in the Calkit config overrides it, for a machine
    that was rebuilt but should still count as the same one, and for
    platforms that supply nothing.

    Returns None where no identifier can be read. Callers must treat that
    as "unknown", never as "different from the one I was given".
    """
    from calkit.config import read as read_config

    try:
        configured = read_config().machine_id
    except Exception:
        # An unreadable config shouldn't make the machine unidentifiable
        configured = None
    if configured and configured.strip():
        return configured.strip()
    return _read_platform_machine_id()


def get_machine_properties() -> dict:
    """The properties of this machine that are cheap to read.

    Everything in ``get_system_info`` except what it has to run a program
    for, e.g., tool versions.
    """
    import psutil

    return {
        "os": platform.system(),
        "os_version": platform.release(),
        "calkit_python_version": platform.python_version(),
        "calkit_version": calkit.__version__,
        "calkit_git_rev": None,
        "hostname": socket.gethostname(),
        "machine_id": get_machine_id(),
        "processor": platform.processor(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_compiler": platform.python_compiler(),
        "memory_gb": psutil.virtual_memory().total / (1024**3),
        "cpu_count": os.cpu_count(),
    }


@functools.cache
def get_gpus() -> tuple[dict, ...]:
    """Get this machine's GPUs, each with a ``name``, ``vendor`` and ``arch``.

    They're read from what the drivers install rather than from a framework
    like PyTorch, so this works before any environment is built: the HIP
    runtime for AMD, ``nvidia-smi`` for NVIDIA, and the chip itself on Apple
    silicon. ``arch`` is what a build targets, e.g., 'gfx1201' or 'sm_89',
    or None where there's no such thing. Cached, since this can start a GPU
    runtime, and a machine's GPUs don't change while a command runs.
    """

    def get_apple_gpus() -> list[dict]:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            return []
        res = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return []
        return [{"name": res.stdout.strip(), "vendor": "apple", "arch": None}]

    gpus = []
    for get in (_get_amd_gpus, _get_nvidia_gpus, get_apple_gpus):
        # A broken driver is a machine with no usable GPU, not a crash
        try:
            gpus += get()
        except (
            OSError,
            AttributeError,
            ValueError,
            subprocess.SubprocessError,
        ):
            pass
    return tuple(gpus)


def _get_amd_gpus() -> list[dict]:
    """Get AMD GPUs from the HIP runtime, falling back to Linux's KFD.

    Windows drivers install the runtime, while on Linux it comes with a
    ROCm install that a machine using ROCm wheels needn't have, so there
    the kernel's description of each GPU is read instead.
    """
    import ctypes

    if sys.platform == "win32":
        candidates = ["amdhip64_7.dll", "amdhip64_6.dll"]
    else:
        candidates = ["libamdhip64.so", "/opt/rocm/lib/libamdhip64.so"]
    for candidate in candidates:
        try:
            if sys.platform == "win32":
                hip = ctypes.WinDLL(candidate)
            else:
                hip = ctypes.CDLL(candidate)
        except OSError:
            continue
        count = ctypes.c_int()
        if hip.hipGetDeviceCount(ctypes.byref(count)) != 0:
            return []
        get_props = getattr(hip, "hipGetDevicePropertiesR0600", None)
        if get_props is None:
            get_props = hip.hipGetDeviceProperties
        gpus = []
        for i in range(count.value):
            # The properties struct starts with the name, but where the
            # architecture sits has moved between releases, so it's found
            # by its shape in a buffer bigger than any release's struct
            props = ctypes.create_string_buffer(8192)
            if get_props(props, i) != 0:
                continue
            raw = props.raw
            name = raw[:256].split(b"\0")[0].decode(errors="replace")
            arch = re.search(rb"gfx[0-9a-f]{3,5}(?=[\0:])", raw[256:])
            gpus.append(
                {
                    "name": name or None,
                    "vendor": "amd",
                    "arch": arch.group().decode() if arch else None,
                }
            )
        return gpus
    gpus = []
    nodes = glob.glob("/sys/class/kfd/kfd/topology/nodes/*/properties")
    for path in sorted(nodes):
        with open(path) as f:
            node_props = dict(
                line.split(maxsplit=1) for line in f if len(line.split()) == 2
            )
        # Zero for a CPU node, else major, minor and stepping as decimal
        # pairs, e.g., 120001 for gfx1201 or 90010 for gfx90a
        version = int(node_props.get("gfx_target_version", "0"))
        if version:
            major, minor, step = (
                version // 10000,
                version // 100 % 100,
                version % 100,
            )
            gpus.append(
                {
                    "name": None,
                    "vendor": "amd",
                    "arch": f"gfx{major}{minor:x}{step:x}",
                }
            )
    return gpus


def _get_nvidia_gpus() -> list[dict]:
    """Get NVIDIA GPUs from ``nvidia-smi``, which the driver installs."""
    import shutil

    if shutil.which("nvidia-smi") is None:
        return []
    # Drivers older than 510 can't report compute_cap, so they're asked for
    # names alone
    for fields in ("name,compute_cap", "name"):
        res = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={fields}",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0:
            break
    else:
        return []
    gpus = []
    for line in res.stdout.splitlines():
        if fields == "name":
            name, cap = line, ""
        else:
            name, _, cap = line.rpartition(",")
        if name.strip():
            gpus.append(
                {
                    "name": name.strip(),
                    "vendor": "nvidia",
                    "arch": f"sm_{cap.strip().replace('.', '')}"
                    if cap.strip()
                    else None,
                }
            )
    return gpus


# Apps whose versions 'calkit describe system' reports on every OS
ALWAYS_REPORTED_APPS = (
    "python",
    "git",
    "docker",
    "conda",
    "mamba",
    "uv",
    "pixi",
    "Rscript",
    "juliaup",
    "julia",
)


def get_system_info(
    apps: list[str] | None = None,
    all_apps: bool = True,
    gpus: bool | None = None,
) -> dict:
    """Get information about the system on which we're currently running.

    ``apps`` are reported with a version each, beyond the ones always
    reported, e.g., the apps a project's requirements name. Without
    ``all_apps``, only ``apps`` are, since each costs a subprocess.
    ``gpus`` reports the machine's GPUs too, which can mean starting a GPU
    runtime, so it defaults to ``all_apps``.
    """
    system_info = get_machine_properties()
    if gpus is None:
        gpus = all_apps
    if gpus:
        system_info["gpus"] = [dict(g) for g in get_gpus()]
    os_name = system_info["os"]
    node_id = uuid.getnode()
    # The multicast bit is the 40th bit from the right (0-indexed)
    # This corresponds to the least significant bit of the first octet
    # A standard unicast MAC address has this bit as 0
    # A randomly generated node ID by uuid.getnode() will have this bit as 1
    is_random_fallback = bool(node_id & 0x010000000000)
    if is_random_fallback:
        node_id = None
    system_info["node_id"] = node_id
    # See if we can detect Calkit Git rev
    try:
        repo = calkit.git.get_repo(os.path.dirname(calkit.__file__))
        system_info["calkit_git_rev"] = repo.head.commit.hexsha
    except Exception:
        pass
    # Get versions of important foundational dependencies, and OS-specific
    # package managers
    os_apps = {
        "Darwin": ["brew", "port"],
        "Linux": ["apt", "yum"],
        "Windows": ["choco", "winget"],
    }.get(os_name, [])
    for dep in [*ALWAYS_REPORTED_APPS, *os_apps]:
        if all_apps or dep.lower() in [a.lower() for a in apps or []]:
            system_info[f"{dep.lower()}_version"] = get_dep_version(dep)
    for app in apps or []:
        if f"{app.lower()}_version" not in system_info:
            system_info[f"{app.lower()}_version"] = get_dep_version(app)
    system_info_str = json.dumps(system_info, sort_keys=True).encode()
    system_info["id"] = hashlib.sha1(system_info_str).hexdigest()
    return system_info


def get_md5(path: str, exclude_files: list[str] | None = None) -> str:
    if os.path.isdir(path):
        # See https://github.com/calkit/calkit/issues/346
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            import checksumdir
        return checksumdir.dirhash(path, excluded_files=exclude_files)
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        # Read the file in chunks to avoid memory issues with large files
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def set_env_vars(ck_info: dict, cli: bool = True) -> None:
    """Set environmental variables according to the values read from
    ``calkit.yaml``.

    TODO: This should also handle ``dotenv``.
    """
    env_vars = ck_info.get("env_vars", {})
    if not isinstance(env_vars, dict):
        msg = (
            "Environmental variables in Calkit project info must be a "
            "map/dictionary"
        )
        if cli:
            from calkit.cli import raise_error

            raise_error(msg)
        else:
            raise ValueError(msg)
    # A project that points the home directory elsewhere, e.g., at /tmp for
    # a tool a stage runs, would otherwise hide the user's Calkit config,
    # and with it their credentials, from every Calkit command it runs
    home = os.path.expanduser("~")
    for k, v in env_vars.items():
        os.environ[str(k)] = str(v)
    if os.path.expanduser("~") != home:
        os.environ.setdefault(USER_HOME_ENV_VAR, home)


def normalize_orcid(orcid: str) -> str:
    """Check an ORCID, bare or as a URL, and return it as its URL.

    Raises ``ValueError`` if it isn't shaped like one or its check digit
    doesn't match the rest.
    """
    match = re.fullmatch(
        r"(?:(?:https?://)?(?:www\.)?orcid\.org/)?"
        r"(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])",
        orcid.strip(),
    )
    if match is None:
        raise ValueError(
            f"orcid must look like 0000-0002-1825-0097 (got {orcid!r})"
        )
    bare = match.group(1).upper()
    # The last character is an ISO 7064 MOD 11-2 check digit over the
    # other 15, so a typo is caught here rather than by whoever later
    # finds the identifier resolves to a stranger, or to nobody.
    total = 0
    for digit in bare[:-1].replace("-", ""):
        total = (total + int(digit)) * 2
    result = (12 - total % 11) % 11
    expected = "X" if result == 10 else str(result)
    if bare[-1] != expected:
        raise ValueError(
            f"orcid {orcid!r} has check digit {bare[-1]} but its other "
            f"digits call for {expected}, so one of them is mistyped"
        )
    return f"https://orcid.org/{bare}"


# Git for Windows checks text files out with CRLF by default, and DVC
# hashes the working tree, so a stage using a file committed with LF
# reads as out of date there unless an ``eol`` attribute pins it

# What to do about files whose line endings aren't pinned
EOL_FIX = "run `calkit fix line-endings` and commit .gitattributes"

# Marks the block of rules ``pin_eol()`` writes
EOL_MARKER = "calkit line endings"

# The rules ``pin_eol()`` writes, first in ``.gitattributes`` so a project's
# own rules after them win. ``text=auto`` leaves binary files alone, and
# files committed with CRLF, which are checked out the same everywhere
# already, so pinning makes no committed file read as changed.
EOL_RULES = [
    "# Check out text files with LF everywhere, including Windows, so the",
    "# files the pipeline hashes are the same on every machine",
    "* text=auto eol=lf",
    "# cmd.exe can misread batch files with LF",
    "*.bat text=auto eol=crlf",
    "*.cmd text=auto eol=crlf",
]

# Most characters of paths to give one Git command, well within the 32,767
# of a whole command line on Windows
GIT_MAX_PATH_CHARS = 16_000


@dataclass
class TrackedEol:
    """How Git stores a tracked file's line endings, and how it checks it
    out, as ``git ls-files --eol`` reports them."""

    path: str
    # In the index: ``lf``, ``crlf``, ``mixed``, ``none`` (no line
    # breaks), or ``-text`` (binary)
    index: str
    # In the working tree, likewise, or empty if the file isn't there
    worktree: str
    # The ``text`` and ``eol`` attributes that apply, e.g., ``text eol=lf``
    attr: str

    @property
    def pinned(self) -> bool:
        """Whether Git checks it out the same way on every platform."""
        tokens = self.attr.split()
        return any(t.startswith("eol=") for t in tokens) or "-text" in tokens

    @property
    def at_risk(self) -> bool:
        """Whether a checkout on Windows would have other bytes than one on
        macOS or Linux."""
        return self.index in ("lf", "mixed") and not self.pinned

    @property
    def rewritten(self) -> bool:
        """Whether this checkout has CRLF where Git has LF, so it hashes
        differently from a checkout on macOS or Linux."""
        return self.index == "lf" and self.worktree == "crlf"


def _run_git_on_paths(
    args: list[str], paths: list[str], wdir: str = "."
) -> bytes:
    """Run ``git`` with ``args``, then ``--`` and ``paths``, and return its
    output.

    Paths are split across as many calls as it takes to keep each command
    line short enough for Windows, which refuses one over 32,767 characters,
    e.g., for every file in a large repo.

    Raises
    ------
    OSError
        If Git can't be run.
    subprocess.CalledProcessError
        If Git fails.
    """
    chunks: list[list[str]] = [[]]
    size = 0
    for path in paths:
        # Each path may also be quoted and spaced from the next
        if chunks[-1] and size + len(path) + 3 > GIT_MAX_PATH_CHARS:
            chunks.append([])
            size = 0
        chunks[-1].append(path)
        size += len(path) + 3
    return b"".join(
        subprocess.run(
            ["git", *args, "--", *chunk],
            cwd=wdir,
            capture_output=True,
            check=True,
        ).stdout
        for chunk in chunks
        if chunk
    )


def list_tracked_eol(paths: list[str], wdir: str = ".") -> list[TrackedEol]:
    """Report the line endings of the Git-tracked files at or under
    ``paths``, relative to ``wdir``, in one call to Git.

    Paths Git doesn't track, e.g., outputs kept in DVC, are left out, as is
    everything when ``wdir`` isn't in a Git repo.
    """
    if not paths:
        return []
    subs = get_submodule_paths(wdir)
    paths = [posixpath.normpath(p).rstrip("/") or "." for p in paths]
    # Git refuses a path inside a submodule
    top_paths = [
        p for p in paths if not any(p.startswith(sm + "/") for sm in subs)
    ]
    out = ""
    try:
        if top_paths:
            out = _run_git_on_paths(
                ["ls-files", "--eol", "-z"], top_paths, wdir=wdir
            ).decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    res = []
    # A file under paths in different calls to Git is listed by each
    seen = set()
    for entry in out.split("\0"):
        # <index> <worktree> attr/<attrs>, padded with spaces, then a tab
        info, sep, path = entry.partition("\t")
        if not sep or path in seen:
            continue
        seen.add(path)
        fields = info.split()
        if len(fields) < 3:
            continue
        res.append(
            TrackedEol(
                path=path,
                index=fields[0].removeprefix("i/"),
                worktree=fields[1].removeprefix("w/"),
                attr=" ".join(fields[2:]).removeprefix("attr/"),
            )
        )
    # Git lists a submodule as one entry, so what's in it is asked of its
    # own repo, whose attributes are its own
    for sm in subs:
        sub_paths = []
        for path in paths:
            if path in (".", sm) or sm.startswith(path + "/"):
                sub_paths = ["."]
                break
            if path.startswith(sm + "/"):
                sub_paths.append(path[len(sm) + 1 :])
        for f in list_tracked_eol(sub_paths, wdir=os.path.join(wdir, sm)):
            f.path = f"{sm}/{f.path}"
            res.append(f)
    return res


def get_submodule_paths(wdir: str = ".") -> list[str]:
    """The paths, relative to ``wdir``, of the checked-out submodules
    under it."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-s", "-z"],
            cwd=wdir,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    res = []
    for entry in out.split("\0"):
        info, sep, path = entry.partition("\t")
        if sep and info.startswith("160000 "):
            if os.path.exists(os.path.join(wdir, path, ".git")):
                res.append(path)
    return res


def get_pipeline_paths(wdir: str = ".") -> list[str]:
    """The paths the compiled pipeline in ``wdir`` hashes, its stages'
    dependencies and outputs, relative to ``wdir``."""
    import calkit.dvc

    paths = []
    for stage in (
        calkit.dvc.read_pipeline(wdir=wdir).get("stages") or {}
    ).values():
        if not isinstance(stage, dict):
            continue
        base = stage.get("wdir") or ""
        for field in ("deps", "outs"):
            for item in stage.get(field) or []:
                path = (
                    item if isinstance(item, str) else next(iter(item), None)
                )
                # A templated path names no file until DVC expands it
                if not isinstance(path, str) or "${" in path:
                    continue
                path = posixpath.normpath(posixpath.join(base, path))
                if path.startswith("../") or os.path.isabs(path):
                    continue
                paths.append(path)
    return list(dict.fromkeys(paths))


def check_pipeline_eol(wdir: str = ".") -> list[TrackedEol]:
    """The Git-tracked text files the pipeline hashes whose line endings
    Git doesn't pin, or that this checkout has rewritten."""
    files = list_tracked_eol(get_pipeline_paths(wdir=wdir), wdir=wdir)
    return [f for f in files if f.at_risk or f.rewritten]


def summarize_paths(paths: list[str], n: int = 3) -> str:
    """A few paths, and how many more there are."""
    shown = ", ".join(paths[:n])
    if len(paths) > n:
        shown += f", and {len(paths) - n} more"
    return shown


@dataclass
class EolPinResult:
    """What ``pin_eol()`` changed."""

    # Whether ``.gitattributes`` was written
    wrote_gitattributes: bool = False
    # Working-tree files rewritten to the line endings Git checks out
    converted: list[str] = dataclass_field(default_factory=list)
    # Submodules set to check files out as committed, in this clone only
    submodules: list[str] = dataclass_field(default_factory=list)


def all_eol_pinned(wdir: str = ".") -> bool:
    """Whether ``wdir``'s ``.gitattributes`` already sets ``eol`` for every
    file, with Calkit's block or a ``*`` rule of its own."""
    path = os.path.join(wdir, ".gitattributes")
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if (
                len(parts) > 1
                and parts[0] == "*"
                and any(p.startswith("eol=") for p in parts[1:])
            ):
                return True
    return False


def write_eol_rules(wdir: str = ".") -> bool:
    """Put ``EOL_RULES`` first in ``wdir``'s ``.gitattributes``, unless it
    pins every file already. Returns whether the file was written."""
    path = os.path.join(wdir, ".gitattributes")
    begin = f"# >>> {EOL_MARKER} (managed by calkit) >>>"
    end = f"# <<< {EOL_MARKER} <<<"
    block = "\n".join([begin, *EOL_RULES, end])
    existing = ""
    if os.path.isfile(path):
        # Read with universal newlines and written with LF, as the rules
        # it gets say it should be
        with open(path, encoding="utf-8") as f:
            existing = f.read()
    block_re = re.compile(
        re.escape(begin) + r".*?" + re.escape(end), flags=re.DOTALL
    )
    if block_re.search(existing):
        updated = block_re.sub(lambda _: block, existing)
    elif all_eol_pinned(wdir):
        return False
    else:
        # First, since the last rule that matches a file wins
        updated = block + "\n" + ("\n" + existing if existing else "")
    if updated == existing:
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(updated)
    return True


def convert_worktree_eol(
    wdir: str = ".", as_committed: bool = False
) -> list[str]:
    """Rewrite the Git-tracked files under ``wdir`` whose line endings on
    disk aren't what Git would check out now, e.g., CRLF from a checkout
    made before an ``eol=lf`` rule, and return their paths.

    With ``as_committed``, a text file without an ``eol`` attribute is
    expected as Git has it, as when ``core.autocrlf`` is off.

    Git itself only rewrites a file it checks out again, and skips one whose
    size and time haven't changed. Until then the file reads as modified,
    with nothing in its diff, and hashes differently from other machines.
    Converting in place keeps any uncommitted changes. Only files Git has
    with LF are touched, since one committed with CRLF is checked out as it
    is.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--eol", "-z"],
            cwd=wdir,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return []
    converted = []
    for entry in out.split("\0"):
        info, sep, path = entry.partition("\t")
        fields = info.split()
        if not sep or len(fields) < 3:
            continue
        tracked = TrackedEol(
            path=path,
            index=fields[0].removeprefix("i/"),
            worktree=fields[1].removeprefix("w/"),
            attr=" ".join(fields[2:]).removeprefix("attr/"),
        )
        eols = [
            t.removeprefix("eol=")
            for t in tracked.attr.split()
            if t.startswith("eol=")
        ]
        want = eols[-1] if eols else None
        if want is None and as_committed:
            want = None if "-text" in tracked.attr.split() else "lf"
        if tracked.index != "lf" or want not in ("lf", "crlf"):
            continue
        if tracked.worktree not in ("lf", "crlf", "mixed"):
            continue
        if tracked.worktree == want:
            continue
        fpath = os.path.join(wdir, path)
        if os.path.islink(fpath) or not os.path.isfile(fpath):
            continue
        with open(fpath, "rb") as f:
            data = f.read()
        new = data.replace(b"\r\n", b"\n")
        if want == "crlf":
            new = new.replace(b"\n", b"\r\n")
        if new == data:
            continue
        with open(fpath, "wb") as f:
            f.write(new)
        converted.append(path)
    _refresh_git_index(converted, wdir=wdir)
    return converted


def _refresh_git_index(paths: list[str], wdir: str = ".") -> None:
    """Record the new size and time of rewritten files that match what's
    staged, which Git otherwise shows as modified, since it doesn't compare
    content when a file's size has changed. Files with uncommitted changes
    are left as they are, so nothing new is staged."""
    if not paths:
        return
    try:
        staged = {}
        out = _run_git_on_paths(
            ["ls-files", "-s", "-z"], paths, wdir=wdir
        ).decode("utf-8", errors="replace")
        for entry in out.split("\0"):
            info, sep, path = entry.partition("\t")
            if sep:
                staged[path] = info.split()[1]
        hashes = (
            _run_git_on_paths(["hash-object"], paths, wdir=wdir)
            .decode()
            .split()
        )
        same = [p for p, h in zip(paths, hashes) if staged.get(p) == h]
        if same:
            _run_git_on_paths(["update-index", "-q"], same, wdir=wdir)
    except (OSError, subprocess.CalledProcessError, IndexError):
        pass


def pin_eol(wdir: str = ".") -> EolPinResult:
    """Pin line endings for everything under ``wdir`` and bring this
    checkout in line with the rules.

    This changes no file's committed content, and on a checkout that
    already matches, e.g., most on macOS and Linux, nothing on disk but
    ``.gitattributes``.
    """
    res = EolPinResult(wrote_gitattributes=write_eol_rules(wdir))
    res.converted = convert_worktree_eol(wdir)
    sub = pin_submodules_eol(wdir)
    res.converted += sub.converted
    res.submodules = sub.submodules
    return res


def pin_submodules_eol(wdir: str = ".") -> EolPinResult:
    """Check the files of the submodules under ``wdir`` out as committed,
    and bring this checkout in line, for those that don't pin their line
    endings themselves.

    A submodule is its own repo, so the project's ``.gitattributes`` doesn't
    reach it, and a rule committed to it would be a change to someone else's
    project. Instead, ``core.autocrlf`` is turned off in this clone of it,
    which leaves its own attributes in charge, unlike a rule in
    ``info/attributes``, which would outrank them. Its files then have the
    bytes it committed, on every platform.
    """
    res = EolPinResult()
    for sm in get_submodule_paths(wdir):
        subdir = os.path.join(wdir, sm)
        if not all_eol_pinned(subdir):
            try:
                current = subprocess.run(
                    ["git", "config", "--local", "core.autocrlf"],
                    cwd=subdir,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if current != "false":
                    subprocess.run(
                        ["git", "config", "--local", "core.autocrlf", "false"],
                        cwd=subdir,
                        capture_output=True,
                        check=True,
                    )
                    res.submodules.append(sm)
            except (OSError, subprocess.CalledProcessError):
                continue
        res.converted += [
            f"{sm}/{p}"
            for p in convert_worktree_eol(
                subdir, as_committed=not all_eol_pinned(subdir)
            )
        ]
        nested = pin_submodules_eol(subdir)
        res.converted += [f"{sm}/{p}" for p in nested.converted]
        res.submodules += [f"{sm}/{p}" for p in nested.submodules]
    return res
