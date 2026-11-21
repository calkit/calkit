"""Functionality for using Quarto in Calkit projects."""

from __future__ import annotations

import json
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# A Quarto extension, so documents use the shortcode without listing it,
# written where Quarto looks for one: the Quarto project's folder, or the
# document's without one
EXTENSION_DIR = "_extensions/calkit"
EXTENSION_YML = """# Written by Calkit; changes are overwritten when the pipeline compiles
title: Calkit
author: Calkit
version: 1.0.0
quarto-required: ">=1.4.0"
contributes:
  shortcodes:
    - calkit.lua
"""
# The values each document shows, beside the extension, at the document's
# path like Quarto's _freeze, which Quarto skips when rendering a project
VALUES_DIR = "_calkit/values"
# A shortcode written {{</* ckvalue */>}} is Quarto's escaped form, shown
# literally, so it doesn't match
_SHORTCODE_RE = re.compile(r"\{\{<\s*ckvalue\s+(?P<args>.*?)\s*>\}\}")

# Looks each value up by what its shortcode says, the same way the Python
# side keys them, so the two only have to agree on the raw arguments.
# Quarto gives a missing keyword argument as an empty string.
SHORTCODE_LUA = r"""-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows values from pipeline results with
-- {{< ckvalue results.json key .2f >}}, which Calkit resolves into
-- _calkit/values/<document path>.json each time the pipeline renders it.

local function read_values()
  local input = quarto.doc.input_file
  local root = quarto.project.directory or pandoc.path.directory(input)
  -- A notebook is rendered from a copy, e.g., analysis.quarto_ipynb
  local stem = pandoc.path.split_extension(
    pandoc.path.make_relative(input, root)
  )
  local fpath = pandoc.path.join({root, "_calkit", "values", stem .. ".json"})
  local f = io.open(fpath, "r")
  if f == nil then
    return {}
  end
  local content = f:read("a")
  f:close()
  return quarto.json.decode(content)
end

local values = nil

return {
  ["ckvalue"] = function(args, kwargs)
    if values == nil then
      values = read_values()
    end
    local slots = {"", "", ""}
    for i = 1, math.min(#args, 3) do
      slots[i] = pandoc.utils.stringify(args[i])
    end
    for name, slot in pairs({name = 1, path = 1, key = 2, format = 3}) do
      local value = pandoc.utils.stringify(kwargs[name] or "")
      if value ~= "" then
        slots[slot] = value
      end
    end
    local id = table.concat(slots, "\t")
    local text = values[id]
    if text == nil then
      quarto.log.warning(
        "No value for ckvalue " .. slots[1] .. " " .. slots[2]
          .. "; run the pipeline to resolve it"
      )
      return pandoc.Str("??")
    end
    return pandoc.Str(text)
  end,
}
"""


@dataclass(frozen=True)
class QuartoValue:
    """One value a Quarto document shows with the ``ckvalue`` shortcode."""

    # Its arguments as written, which is how the shortcode looks it up
    source: str
    key: str
    format: str | None
    # The results file it reads, relative to the project
    path: str
    # 1-indexed line of the document, or of the cell in a notebook
    line: int = 0

    @property
    def id(self) -> str:
        """What the shortcode looks the value up by."""
        return "\t".join([self.source, self.key, self.format or ""])


def read_document_text(path: str) -> str | None:
    """A document's text that shortcodes can be in, or None if it's missing.

    For a notebook, that's its Markdown and raw cells, since a code cell's
    source isn't rendered as text.
    """
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if not path.endswith(".ipynb"):
        return content
    try:
        nb = json.loads(content)
    except json.JSONDecodeError:
        return None
    texts = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") in ("markdown", "raw"):
            source = cell.get("source", "")
            texts.append(
                "".join(source) if isinstance(source, list) else str(source)
            )
    return "\n".join(texts)


def extract_values(
    text: str, document_path: str, results: dict[str, str] | None = None
) -> list[QuartoValue]:
    """Find the ``ckvalue`` shortcodes in a document, in order.

    Their arguments read the way the Markdown marker's do: a results file
    or a declared result's name, a key, and optionally a format, each
    positionally or by name. A malformed one raises
    ``calkit.markdown.MarkdownParseError`` naming its line.
    """
    from calkit.markdown import _ckvalue_args, _resolve_source

    path = Path(document_path).as_posix()
    values = []
    for i, line in enumerate(text.splitlines()):
        for m in _SHORTCODE_RE.finditer(line):
            got = _ckvalue_args(m.group("args"), path, i + 1)
            values.append(
                QuartoValue(
                    source=got["source"],
                    key=got["key"],
                    format=got.get("format"),
                    path=_resolve_source(
                        got["source"], results, path, i + 1, kind=got["kind"]
                    ),
                    line=i + 1,
                )
            )
    return values


def resolve_values(
    values: list[QuartoValue], document_path: str, wdir: str | None = None
) -> dict[str, str]:
    """Each value's text, keyed by what its shortcode looks it up by.

    A missing results file or key raises
    ``calkit.markdown.MarkdownParseError`` naming the shortcode's line.
    """
    from calkit.markdown import (
        MarkdownParseError,
        _ck_format,
        format_value,
        lookup_value,
    )
    from calkit.results import load_result

    data_by_path: dict[str, Any] = {}
    resolved = {}
    for value in values:
        fpath = os.path.join(wdir, value.path) if wdir else value.path
        if value.path not in data_by_path:
            if not os.path.isfile(fpath):
                raise MarkdownParseError(
                    f"Results file '{value.path}' for value '{value.key}' "
                    "doesn't exist; is it an output of a stage that has run?",
                    path=document_path,
                    line=value.line,
                )
            try:
                data_by_path[value.path] = load_result(fpath)
            except ValueError as e:
                raise MarkdownParseError(
                    str(e), path=document_path, line=value.line
                )
        try:
            raw = lookup_value(data_by_path[value.path], value.key)
        except KeyError:
            raise MarkdownParseError(
                f"'{value.path}' has no key '{value.key}'",
                path=document_path,
                line=value.line,
            )
        resolved[value.id] = format_value(raw, _ck_format(value.format))
    return resolved


def get_quarto_dir(document_path: str, wdir: str | None = None) -> str:
    """Where Quarto looks for the extension and values for a document: the
    nearest folder at or above it with a ``_quarto.yml``, i.e., its Quarto
    project, or else its own.

    ``document_path`` is relative to ``wdir``, which bounds the search, and
    so is the returned POSIX path, which is ``""`` for ``wdir`` itself.
    """
    folder = posixpath.dirname(
        posixpath.normpath(Path(document_path).as_posix())
    )
    candidate = folder
    while True:
        for fname in ("_quarto.yml", "_quarto.yaml"):
            if os.path.isfile(os.path.join(wdir or "", candidate, fname)):
                return candidate
        parent = posixpath.dirname(candidate)
        if candidate in ("", ".") or parent == candidate:
            return folder
        candidate = parent


def get_extension_dir(document_path: str, wdir: str | None = None) -> str:
    """Where the extension is written for a document, as a POSIX path
    relative to ``wdir``."""
    return posixpath.join(get_quarto_dir(document_path, wdir), EXTENSION_DIR)


def get_values_path(document_path: str, wdir: str | None = None) -> str:
    """Where the values a document shows are written, as a POSIX path
    relative to ``wdir``, mirroring the document's path in its Quarto
    project."""
    document_path = posixpath.normpath(Path(document_path).as_posix())
    quarto_dir = get_quarto_dir(document_path, wdir)
    rel = posixpath.relpath(document_path, quarto_dir or ".")
    return posixpath.join(
        quarto_dir, VALUES_DIR, posixpath.splitext(rel)[0] + ".json"
    )


def write_components(
    document_path: str,
    resolved: dict[str, str] | None = None,
    wdir: str | None = None,
) -> None:
    """Write the extension for a document, and with ``resolved``, the values
    it shows, leaving files whose content is already right alone so their
    timestamps don't change.

    The extension is the same for every document, so it's written whenever
    the pipeline is compiled and kept in Git; the values are a stage's
    output.
    """
    ext_dir = get_extension_dir(document_path, wdir)
    contents = {
        posixpath.join(ext_dir, "_extension.yml"): EXTENSION_YML,
        posixpath.join(ext_dir, "calkit.lua"): SHORTCODE_LUA,
    }
    if resolved is not None:
        contents[get_values_path(document_path, wdir)] = (
            json.dumps(resolved, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )
    for rel_path, content in contents.items():
        fpath = os.path.join(wdir or "", rel_path)
        try:
            with open(fpath, encoding="utf-8") as f:
                if f.read() == content:
                    continue
        except OSError:
            pass
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
