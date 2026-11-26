"""Functionality for using MyST in Calkit projects."""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path

# A MyST plugin, written beside myst.yml, which lists it under
# project.plugins, in the folder Calkit writes Quarto's extension to
PLUGIN_PATH = "_extensions/calkit/myst.mjs"
# What myst.yml lists to load the plugin
PLUGIN_CONFIG = f"project:\n  plugins:\n    - {PLUGIN_PATH}\n"
# The files MyST builds a project from
DOCUMENT_EXTS = (".md", ".ipynb")
# A {ckprovenance} directive's opening line, with colons or backticks
_DIRECTIVE_RE = re.compile(
    r"^\s*(?P<fence>`{3,}|:{3,})\{ckprovenance\}\s*(?P<arg>.*?)\s*$"
)
_OPTION_RE = re.compile(r"^\s*:(?P<key>[\w-]+):\s*(?P<value>.*?)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(?!\s*\{)")

# Turns the panels Calkit wrote before building into MyST's AST, deciding
# nothing about what they say, which is decided in Python, the same as for
# Quarto, and tested there
PLUGIN_JS = r"""// Written by Calkit; changes are overwritten by 'calkit myst build'.
// Shows the file a {ckprovenance} directive names, as a figure, a table,
// or its name, with where it came from and whether it's up to date, or
// with no argument, the document's provenance. Calkit decides what each
// panel says before building, and writes it to .calkit/local/provenance;
// this only turns it into MyST's AST.
import fs from "node:fs";
import path from "node:path";

const PICTURE_EXTS = new Set([
  ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf",
]);

// The Calkit project's folder, which the panels are kept under
function findProjectDir(start) {
  let dir = start;
  while (true) {
    if (fs.existsSync(path.join(dir, "calkit.yaml"))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return start;
    }
    dir = parent;
  }
}

// What Calkit wrote for a document, read each time, since 'myst start'
// keeps this loaded across rebuilds
function loadRecords(docPath) {
  const projectDir = findProjectDir(path.dirname(docPath));
  const rel = path.relative(projectDir, docPath).split(path.sep).join("/");
  const fpath = path.join(
    projectDir, ".calkit", "local", "provenance", rel + ".json",
  );
  try {
    return JSON.parse(fs.readFileSync(fpath, "utf8"));
  } catch {
    return null;
  }
}

// Paragraphs, text, and Mermaid are MyST's own nodes already
function convert(node, hidden) {
  const { section, ...rest } = node;
  if (section && hidden.has(section)) {
    return [];
  }
  if (rest.type === "admonition") {
    const out = {
      type: "admonition",
      kind: rest.kind,
      children: [
        { type: "admonitionTitle", children: rest.title },
        ...convertAll(rest.children, hidden),
      ],
    };
    if (rest.dropdown) {
      out.class = "dropdown";
    }
    return [out];
  }
  if (rest.type === "table") {
    return [{
      type: "table",
      children: rest.children.map((row) => ({
        type: "tableRow",
        children: row.children.map((cell) => ({
          type: "tableCell",
          ...(cell.header ? { header: true } : {}),
          children: cell.children,
        })),
      })),
    }];
  }
  return [rest];
}

function convertAll(nodes, hidden) {
  return (nodes || []).flatMap((node) => convert(node, hidden));
}

const ckprovenance = {
  name: "ckprovenance",
  doc: "Show a file with where it came from and whether it's up to date, "
    + "or with no argument, the document's provenance.",
  arg: {
    type: String,
    doc: "The file, relative to the document. Omit it for the document.",
  },
  options: {
    label: { type: String, alias: ["name"], doc: "Label to refer to it." },
    kind: { type: String, doc: "figure, table, or file." },
    width: { type: String, doc: "Width, as on a figure." },
    align: { type: String, doc: "left, center, or right." },
    alt: { type: String, doc: "Alt text." },
    rows: { type: Number, doc: "Rows of a table to show (25)." },
    table: { type: Boolean, doc: "Show the document's outputs (true)." },
    graph: { type: Boolean, doc: "Show the document's graph (true)." },
  },
  body: { type: "myst", doc: "The caption, or a lead-in for the document." },
  run(data, vfile) {
    const src = (data.arg || "").trim();
    const options = data.options || {};
    const caption = data.body || [];
    const hidden = new Set(
      ["table", "graph"].filter((key) => options[key] === false),
    );
    const records = vfile.path ? loadRecords(path.resolve(vfile.path)) : null;
    let record = null;
    if (records) {
      record = src ? (records.panels || {})[src] : records.document;
    }
    // A figure or table, numbered and referred to by its label, with the
    // directive's body as its caption
    const container = (kind, children) => {
      const out = { type: "container", kind, children };
      if (options.label) {
        out.label = options.label;
        out.identifier = options.label.toLowerCase();
      }
      if (caption.length > 0) {
        const node = { type: "caption", children: caption };
        if (kind === "table") {
          children.unshift(node);
        } else {
          children.push(node);
        }
      }
      return out;
    };
    const image = () => {
      const out = { type: "image", url: src };
      for (const key of ["width", "align", "alt"]) {
        if (options[key]) {
          out[key] = options[key];
        }
      }
      return out;
    };
    if (!record) {
      const out = [];
      if (PICTURE_EXTS.has(path.extname(src).toLowerCase())) {
        out.push(container("figure", [image()]));
      }
      out.push({
        type: "admonition",
        kind: "warning",
        children: [
          {
            type: "admonitionTitle",
            children: [{ type: "text", value: "No provenance recorded" }],
          },
          {
            type: "paragraph",
            children: [
              { type: "text", value: "Build with " },
              { type: "inlineCode", value: "calkit myst build" },
              { type: "text", value: " or " },
              { type: "inlineCode", value: "calkit run" },
              { type: "text", value: "." },
            ],
          },
        ],
      });
      return out;
    }
    const out = [];
    if (record.kind === "figure") {
      out.push(container("figure", [image()]));
    } else if (record.kind === "table") {
      out.push(container("table", convertAll(record.body, hidden)));
    } else {
      out.push(...convertAll(record.body, hidden), ...caption);
    }
    out.push(...convertAll(record.panel, hidden));
    return out;
  },
};

export default { name: "Calkit", directives: [ckprovenance] };
"""


def extract_directives(text: str, document_path: str) -> list:
    """Find the ``ckprovenance`` directives in a MyST document, in order,
    as ``calkit.quarto.ProvenanceDiv``, skipping those in code blocks.

    The file a directive names is relative to the document, as MyST reads
    an image's, and ``:kind:`` overrides what its extension says to show it
    as.
    """
    from calkit.quarto import (
        _NOUNS,
        FIGURE_EXTS,
        TABLE_DELIMITERS,
        TABLE_ROW_LIMIT,
        ProvenanceDiv,
    )

    document_path = posixpath.normpath(Path(document_path).as_posix())
    lines = text.splitlines()
    divs = []
    fence = None
    for i, line in enumerate(lines):
        if fence is not None:
            if line.strip() and line.strip() == fence[0] * len(line.strip()):
                if len(line.strip()) >= len(fence):
                    fence = None
            continue
        m = _CODE_FENCE_RE.match(line)
        if m is not None:
            fence = m.group(1)
            continue
        m = _DIRECTIVE_RE.match(line)
        if m is None:
            continue
        options = {}
        for option_line in lines[i + 1 :]:
            option = _OPTION_RE.match(option_line)
            if option is None:
                break
            options[option.group("key")] = option.group("value")
        # A directive in backticks closes like a code block
        if m.group("fence").startswith("`"):
            fence = m.group("fence")
        src = m.group("arg")
        if not src:
            divs.append(ProvenanceDiv("", "", "document", line=i + 1))
            continue
        path = posixpath.normpath(
            posixpath.join(posixpath.dirname(document_path), src)
        )
        ext = posixpath.splitext(src)[1].lower()
        kind = options.get("kind", "").lower()
        if kind not in _NOUNS:
            kind = (
                "figure"
                if ext in FIGURE_EXTS
                else "table"
                if ext in TABLE_DELIMITERS
                else "file"
            )
        try:
            rows = int(options.get("rows", TABLE_ROW_LIMIT))
        except ValueError:
            rows = TABLE_ROW_LIMIT
        divs.append(ProvenanceDiv(src, path, kind, line=i + 1, rows=rows))
    return divs


def find_documents(myst_dir: str, wdir: str | None = None) -> list[str]:
    """The documents in a MyST project's folder, as POSIX paths relative to
    ``wdir``, like ``myst_dir``, leaving out folders starting with a dot or
    an underscore, e.g., ``_build``, and ``node_modules``.
    """
    root = os.path.join(wdir or "", myst_dir)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith((".", "_")) and d != "node_modules"
        )
        for name in sorted(filenames):
            if name.lower().endswith(DOCUMENT_EXTS):
                rel = os.path.relpath(os.path.join(dirpath, name), wdir or ".")
                found.append(Path(rel).as_posix())
    return found


def get_plugin_problem(myst_dir: str, wdir: str | None = None) -> str | None:
    """Why the plugin that shows ``ckprovenance`` directives won't load for
    a MyST project, or None if it will, from what its ``myst.yml`` lists
    under ``project.plugins``.
    """
    import calkit

    fpath = os.path.join(wdir or "", myst_dir, "myst.yml")
    try:
        with open(fpath, encoding="utf-8") as f:
            config = calkit.core._load_yaml_readonly(f)
    except (OSError, ValueError):
        config = None
    project = (
        (config or {}).get("project") if isinstance(config, dict) else None
    )
    plugins = (
        (project or {}).get("plugins") if isinstance(project, dict) else None
    )
    for plugin in plugins or []:
        path = plugin.get("path") if isinstance(plugin, dict) else plugin
        if (
            isinstance(path, str)
            and posixpath.normpath(path.replace("\\", "/")) == PLUGIN_PATH
        ):
            return None
    return (
        "The 'ckprovenance' directives need Calkit's MyST plugin listed in "
        f"{posixpath.join(myst_dir, 'myst.yml')}; add:\n\n{PLUGIN_CONFIG}"
    )


def get_build_stage(myst_dir: str, ck_info: dict) -> str | None:
    """The pipeline stage that builds a MyST project, i.e., one whose
    command runs ``calkit myst build`` in its folder.
    """
    stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    myst_dir = posixpath.normpath(Path(myst_dir).as_posix())
    for name, stage in stages.items():
        if not isinstance(stage, dict):
            continue
        command = stage.get("command")
        wdir = posixpath.normpath(stage.get("wdir") or ".")
        if (
            isinstance(command, str)
            and "calkit myst build" in command
            and wdir == myst_dir
        ):
            return str(name)
    return None


def write_plugin(myst_dir: str, wdir: str | None = None) -> None:
    """Write the plugin beside a MyST project's ``myst.yml``, leaving it
    alone if it's already right, so its timestamp doesn't change.
    """
    import calkit

    fpath = os.path.join(wdir or "", myst_dir, *PLUGIN_PATH.split("/"))
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    calkit.core.write_if_changed(fpath, PLUGIN_JS)
