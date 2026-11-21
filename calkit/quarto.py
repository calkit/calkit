"""Functionality for using Quarto in Calkit projects."""

from __future__ import annotations

import json
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Beside the document, like LaTeX's components. Quarto skips files and
# folders starting with an underscore when it renders a project.
COMPONENTS_DIR = "_calkit"
SHORTCODE_FNAME = "calkit.lua"
# One file per document, named for its stem, since a notebook is rendered
# from an intermediate copy, e.g., analysis.quarto_ipynb
VALUES_DIRNAME = "values"
# A shortcode written {{</* ckvalue */>}} is Quarto's escaped form, shown
# literally, so it doesn't match
_SHORTCODE_RE = re.compile(r"\{\{<\s*ckvalue\s+(?P<args>.*?)\s*>\}\}")

# Looks each value up by what its shortcode says, the same way the Python
# side keys them, so the two only have to agree on the raw arguments.
# Quarto gives a missing keyword argument as an empty string.
SHORTCODE_LUA = r"""-- Written by Calkit: shows values from pipeline results with
-- {{< ckvalue results.json key .2f >}}. Each document's values are resolved
-- into values/<document name>.json beside this file each time the pipeline
-- renders it.

local function read_values()
  local input = quarto.doc.input_file
  local stem = pandoc.path.split_extension(pandoc.path.filename(input))
  local dir = pandoc.path.directory(input)
  local fpath = pandoc.path.join({dir, "_calkit", "values", stem .. ".json"})
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


def get_shortcode_path(document_path: str) -> str:
    """Where the shortcode is written beside a document, as a POSIX path
    relative to whatever the document's path is."""
    folder = posixpath.dirname(Path(document_path).as_posix())
    return posixpath.join(folder, COMPONENTS_DIR, SHORTCODE_FNAME)


def get_values_path(document_path: str) -> str:
    """Where the values a document shows are written beside it, as a POSIX
    path relative to whatever the document's path is."""
    document_path = Path(document_path).as_posix()
    stem = posixpath.splitext(posixpath.basename(document_path))[0]
    return posixpath.join(
        posixpath.dirname(document_path),
        COMPONENTS_DIR,
        VALUES_DIRNAME,
        stem + ".json",
    )


def write_components(
    document_path: str, resolved: dict[str, str] | None = None
) -> None:
    """Write the shortcode beside a document, and with ``resolved``, the
    values it shows, leaving files whose content is already right alone so
    their timestamps don't change.

    The shortcode is the same for every document, so it's written whenever
    the pipeline is compiled and kept in Git; the values are a stage's
    output.
    """
    contents = {get_shortcode_path(document_path): SHORTCODE_LUA}
    if resolved is not None:
        contents[get_values_path(document_path)] = (
            json.dumps(resolved, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )
    for fpath, content in contents.items():
        try:
            with open(fpath, encoding="utf-8") as f:
                if f.read() == content:
                    continue
        except OSError:
            pass
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
