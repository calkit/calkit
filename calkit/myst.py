"""Functionality for using MyST in Calkit projects."""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from calkit.quarto import Component, QuartoValue

# A MyST plugin, written beside myst.yml, which lists it under
# project.plugins, in the folder Calkit writes Quarto's extension to
PLUGIN_PATH = "_extensions/calkit/myst.mjs"
# What myst.yml lists to load the plugin
PLUGIN_CONFIG = f"project:\n  plugins:\n    - {PLUGIN_PATH}\n"
# A role showing a value, e.g., {ckvalue}`results/fit.json slope .2f`
_ROLE_RE = re.compile(r"\{(?P<name>ckvalue|ckrefval)\}`(?P<args>[^`]*)`")
# Inline code, found with roles blanked out
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# The files MyST builds a project from
DOCUMENT_EXTS = (".md", ".ipynb")
# A fence: backticks or tildes opening a code block, or with a {name}, a
# directive, as colons always do, or closing one when it's bare
_FENCE_RE = re.compile(
    r"^\s*(?P<fence>`{3,}|~{3,}|:{3,})\s*"
    r"(?:\{(?P<name>[^}\s]+)\}\s*(?P<arg>.*?)|(?P<info>.*?))\s*$"
)
_OPTION_RE = re.compile(r"^\s*:(?P<key>[\w-]+):\s*(?P<value>.*?)\s*$")
# Directives whose content is read as it's written, like a code block's
LITERAL_DIRECTIVES = {
    "code",
    "code-block",
    "code-cell",
    "sourcecode",
    "math",
    "mermaid",
    "raw",
    "csv-table",
}
# Turns what Calkit recorded before building into MyST's AST, deciding
# nothing about what it says, which is decided in Python, the same as for
# Quarto, and tested there
PLUGIN_JS = r"""// Written by Calkit; changes are overwritten by 'calkit doc myst build'.
// Shows a file from the project with {ckfigure}, {cktable} for a CSV or
// TSV file, or {ckinclude} for anything else, and values with {ckvalue}
// and {ckrefval}, with where each came from collapsed under it, or for a
// value, behind a mark linking to it. Calkit works out the values and
// what that says before building, and writes it to
// .calkit/local/provenance; this only turns it into MyST's AST.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const MARKDOWN_EXTS = new Set([".md"]);
const TABLE_DELIMITERS = { ".csv": ",", ".tsv": "\t" };
// Marks every format can show, e.g., LaTeX, which has neither ⓘ nor ⚠
const MARK = "†";
const WARNING_MARK = "!";

// The Calkit project's folder, which paths are relative to
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

function getRel(projectDir, fpath) {
  return path.relative(projectDir, fpath).split(path.sep).join("/");
}

// What Calkit recorded for a document, read each time, since 'myst start'
// keeps this loaded across rebuilds
function loadRecords(docPath) {
  const projectDir = findProjectDir(path.dirname(docPath));
  const fpath = path.join(
    projectDir, ".calkit", "local", "provenance",
    getRel(projectDir, docPath) + ".json",
  );
  try {
    return JSON.parse(fs.readFileSync(fpath, "utf8"));
  } catch {
    return null;
  }
}

function getSha1(fpath) {
  try {
    return crypto.createHash("sha1").update(fs.readFileSync(fpath))
      .digest("hex");
  } catch {
    return null;
  }
}

// What changed since Calkit recorded it, e.g., a figure made again by
// hand, or the document, e.g., in 'myst start', or null if nothing did
function getChanged(records, docPath, relPath, sha1) {
  const projectDir = findProjectDir(path.dirname(docPath));
  if (sha1 && getSha1(path.join(projectDir, relPath)) !== sha1) {
    return relPath;
  }
  if (records && records.source_sha1
    && getSha1(docPath) !== records.source_sha1) {
    return "this document";
  }
  return null;
}

function isOff(value) {
  return value === false
    || ["false", "no", "0", "off"].includes(String(value).toLowerCase());
}

// Paragraphs, text, links, and Mermaid are MyST's own nodes already
function convert(node) {
  if (node.type === "table") {
    return [{
      type: "table",
      children: node.children.map((row) => ({
        type: "tableRow",
        children: row.children.map((cell) => ({
          type: "tableCell",
          ...(cell.header ? { header: true } : {}),
          children: cell.children,
        })),
      })),
    }];
  }
  return [node];
}

function convertAll(nodes) {
  return (nodes || []).flatMap((node) => convert(node));
}

function text(value) {
  return { type: "text", value };
}

function getSummary(provenance, changed) {
  if (changed && provenance.state === "ok") {
    return [text(`⚠️ Recorded before ${changed} changed`)];
  }
  const out = [...provenance.summary];
  if (changed) {
    out.push(text(` · recorded before ${changed} changed`));
  }
  return out;
}

function getView(provenance, changed) {
  const out = [];
  if (changed) {
    out.push({
      type: "paragraph",
      children: [text(
        `Recorded before ${changed} changed; build the project with Calkit `
          + "to update this.",
      )],
    });
  }
  return [...out, ...convertAll(provenance.view)];
}

// Collapsed, saying what's wrong while it is
function getDetails(summary, view, ok = false) {
  return {
    type: "details",
    class: "ck-provenance" + (ok ? " ck-ok" : ""),
    children: [{ type: "summary", children: summary }, ...view],
  };
}

function getUnrecorded() {
  return getDetails(
    [text("⚠️ No provenance recorded")],
    [{
      type: "paragraph",
      children: [
        text("Build with "),
        { type: "inlineCode", value: "calkit doc myst build" },
        text(" or "),
        { type: "inlineCode", value: "calkit run" },
        text("."),
      ],
    }],
  );
}

// A CSV or TSV file's rows, quoted fields included
function parseDelimited(content, delimiter) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < content.length; i++) {
    const c = content[i];
    if (quoted) {
      if (c === '"' && content[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') {
        quoted = false;
      } else {
        field += c;
      }
    } else if (c === '"' && field === "") {
      quoted = true;
    } else if (c === delimiter) {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && content[i + 1] === "\n") {
        i++;
      }
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

// A table's rows, read from its file as the document builds, so they're
// what it has now, up to as many as it says
function getTable(projectDir, src, limit) {
  const delimiter = TABLE_DELIMITERS[path.extname(src).toLowerCase()] || ",";
  let rows;
  try {
    const content = fs.readFileSync(path.join(projectDir, src), "utf8")
      .replace(/^﻿/, "");
    rows = parseDelimited(content, delimiter);
  } catch {
    rows = null;
  }
  if (!rows || rows.length === 0) {
    return [{
      type: "paragraph",
      children: [{ type: "emphasis", children: [text(`Can't read ${src}`)] }],
    }];
  }
  const cell = (value, header) => ({
    type: "tableCell",
    ...(header ? { header: true } : {}),
    children: [text(value)],
  });
  const [head, ...body] = rows;
  const out = [{
    type: "table",
    children: [
      { type: "tableRow", children: head.map((v) => cell(v, true)) },
      ...body.slice(0, limit).map((r) => ({
        type: "tableRow", children: r.map((v) => cell(v, false)),
      })),
    ],
  }];
  if (body.length > limit) {
    out.push({
      type: "paragraph",
      children: [{
        type: "emphasis",
        children: [text(
          (limit === 1 ? "First row of " : `First ${limit} rows of `) + src,
        )],
      }],
    });
  }
  return out;
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children || []) {
    walk(child, visit);
  }
}

const OPTIONS = {
  label: { type: String, alias: ["name"], doc: "Label to refer to it." },
  provenance: { type: Boolean, doc: "Show where it came from (true)." },
};

function makeComponent(name, kind, options) {
  return {
    name,
    doc: `Show a ${kind} from the project, with where it came from.`,
    arg: { type: String, required: true, doc: "Its path in the project." },
    options: { ...OPTIONS, ...options },
    body: { type: "myst", doc: "The caption." },
    run(data, vfile, ctx) {
      const src = (data.arg || "").trim();
      const relPath = path.posix.normalize(src.replace(/^\/+/, ""));
      const opts = data.options || {};
      const caption = data.body || [];
      const docPath = vfile.path ? path.resolve(vfile.path) : null;
      const records = docPath ? loadRecords(docPath) : null;
      const record = records ? (records.components || {})[src] : null;
      const projectDir = docPath
        ? findProjectDir(path.dirname(docPath)) : process.cwd();
      const docDir = docPath ? path.dirname(docPath) : projectDir;
      const url = record ? record.url
        : getRel(docDir, path.join(projectDir, relPath));
      // Numbered and referred to by its label, with the body as caption
      const container = (children) => {
        const out = { type: "container", kind, children };
        if (opts.label) {
          out.label = opts.label;
          out.identifier = opts.label.toLowerCase();
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
      const out = [];
      if (kind === "figure") {
        const image = { type: "image", url };
        for (const key of ["width", "align", "alt"]) {
          if (opts[key]) {
            image[key] = opts[key];
          }
        }
        out.push(container([image]));
      } else if (kind === "table") {
        const content = getTable(projectDir, relPath, opts.rows || 25);
        out.push(container([content[0]]), ...content.slice(1));
      } else {
        let content = null;
        if (MARKDOWN_EXTS.has(path.extname(src).toLowerCase())
          && ctx && ctx.parseMyst) {
          try {
            const included = path.join(projectDir, relPath);
            content = ctx.parseMyst(fs.readFileSync(included, "utf8"))
              .children;
            // Its images, relative to it, as the document finds them
            for (const node of content) {
              walk(node, (child) => {
                if (child.type === "image" && child.url
                  && !/^([a-z]+:|\/)/i.test(child.url)) {
                  child.url = getRel(
                    docDir, path.join(path.dirname(included), child.url),
                  );
                }
              });
            }
          } catch {
            content = null;
          }
        }
        out.push(...(content || [{
          type: "paragraph",
          children: [{ type: "inlineCode", value: src }],
        }]), ...caption);
      }
      if (isOff(opts.provenance)) {
        return out;
      }
      if (!record) {
        out.push(getUnrecorded());
      } else if (record.provenance) {
        const changed = getChanged(records, docPath, relPath, record.sha1);
        out.push(getDetails(
          getSummary(record.provenance, changed),
          getView(record.provenance, changed),
          record.provenance.state === "ok" && !changed,
        ));
      }
      return out;
    },
  };
}

// Where a value's view is, at the end of its document, unique to it
function getValueId(projectDir, docPath, key) {
  const digest = crypto.createHash("sha1")
    .update(getRel(projectDir, docPath) + "\0" + key).digest("hex");
  return "ck-value-" + digest.slice(0, 12);
}

function makeValueRole(name) {
  return {
    name,
    doc: "Show a value from the pipeline, or quoted from a reference, as "
      + "its Quarto shortcode does, with where it came from.",
    body: { type: String, doc: "As the shortcode's arguments." },
    run(data, vfile) {
      const body = (data.body || "").trim();
      const docPath = vfile.path ? path.resolve(vfile.path) : null;
      const records = docPath ? loadRecords(docPath) : null;
      const role = records ? ((records.roles || {})[name] || {})[body] : null;
      if (!role) {
        return [text("??")];
      }
      // As Calkit read and formatted it, since MyST doesn't read results
      // files, so a mark says when the file changed since
      const out = [text(role.text)];
      const value = (records.values || {})[role.key];
      if (!role.provenance || !value || !value.provenance) {
        return out;
      }
      const projectDir = findProjectDir(path.dirname(docPath));
      const changed = getChanged(records, docPath, role.path, value.sha1);
      const warn = value.provenance.state !== "ok" || changed !== null;
      const summary = getSummary(value.provenance, changed)
        .map((n) => n.value || "").join("");
      // A mark linking to where it came from, which MyST previews when
      // it's hovered, named for what it is
      out.push({
        type: "crossReference",
        identifier: getValueId(projectDir, docPath, role.key),
        label: getValueId(projectDir, docPath, role.key),
        ckValue: role.key,
        children: [{
          type: "abbreviation",
          // And what's wrong, if anything
          title: `Where ${role.text} came from` + (warn ? `: ${summary}` : ""),
          children: [{
            type: "superscript",
            children: [text(warn ? WARNING_MARK : MARK)],
          }],
        }],
      });
      return out;
    },
  };
}

// The views of the values the document shows, each collapsed, at its end,
// where their marks link to
const valueViews = {
  name: "calkit-value-views",
  stage: "document",
  plugin: () => (tree, vfile) => {
    const keys = [];
    walk(tree, (node) => {
      if (node.type === "crossReference" && node.ckValue
        && !keys.includes(node.ckValue)) {
        keys.push(node.ckValue);
      }
    });
    if (keys.length === 0 || !vfile.path) {
      return;
    }
    const docPath = path.resolve(vfile.path);
    const projectDir = findProjectDir(path.dirname(docPath));
    const records = loadRecords(docPath) || {};
    // Each value's file, by what it's recorded under
    const paths = {};
    for (const roles of Object.values(records.roles || {})) {
      for (const role of Object.values(roles)) {
        paths[role.key] = role.path;
      }
    }
    // A value with no record, e.g., one deleted since, gets no view
    const recorded = records.values || {};
    const views = keys.filter((key) => recorded[key]).map((key) => {
      const value = recorded[key];
      const changed = getChanged(records, docPath, paths[key], value.sha1);
      const provenance = value.provenance;
      // Titled by what it is, e.g., its key in a file, which the recorded
      // view starts with
      const intro = provenance.view.find((n) => n.type === "paragraph");
      const view = getView(
        { ...provenance, view: provenance.view.filter((n) => n !== intro) },
        changed,
      );
      const ok = provenance.state === "ok" && !changed;
      return {
        type: "admonition",
        kind: ok ? "note" : "warning",
        class: "dropdown ck-provenance" + (ok ? " ck-ok" : ""),
        identifier: getValueId(projectDir, docPath, key),
        label: getValueId(projectDir, docPath, key),
        children: [
          {
            type: "admonitionTitle",
            // What it is, and only what's wrong, if anything
            children: [
              ...(intro ? intro.children : []),
              ...(ok ? [] : [text(": "), ...getSummary(provenance, changed)]),
            ],
          },
          ...view,
        ],
      };
    });
    tree.children.push({ type: "block", children: views });
  },
};

export default {
  name: "Calkit",
  directives: [
    makeComponent("ckfigure", "figure", {
      width: { type: String, doc: "Width, as on a figure." },
      align: { type: String, doc: "left, center, or right." },
      alt: { type: String, doc: "Alt text." },
    }),
    makeComponent("cktable", "table", {
      rows: { type: Number, doc: "Rows to show (25)." },
    }),
    makeComponent("ckinclude", "include", {}),
  ],
  roles: [makeValueRole("ckvalue"), makeValueRole("ckrefval")],
  transforms: [valueViews],
};
"""


def extract_document(
    text: str,
    document_path: str,
    read_text: Callable[[str], str | None] | None = None,
    results: dict[str, str] | None = None,
) -> tuple[list[Component], list[tuple[str, str, QuartoValue]], list[str]]:
    """Find the ``ckfigure``, ``cktable``, and ``ckinclude`` directives in a
    MyST document, and the values it shows with ``ckvalue`` and
    ``ckrefval`` roles, in order, skipping code blocks and directives whose
    content is literal, e.g., ``{code-cell}``.

    A directive names its file, relative to the project, as LaTeX's
    ``\\ckfigure`` and the roles do, with options as ``:key: value`` lines or
    a YAML block. A role's content reads as Quarto's shortcode's arguments
    do, e.g., ``{ckvalue}`results/fit.json slope .2f```, and each is
    returned with its role's name and content, as the plugin finds it,
    leaving out comments and inline code, and including a directive's
    argument, e.g., an admonition's title. With ``read_text``, which reads
    a project path, or None if it can't, the files the document
    ``{include}``s, unless it's literally, are read too, relative to the
    file including them, as MyST reads them, as is Markdown it shows with
    ``ckinclude``, and returned, too. ``results`` maps declared results'
    names to their paths.
    """
    import calkit
    from calkit.quarto import extract_values, get_component

    def get_options(lines: list[str]) -> dict:
        options: dict = {}
        if lines and lines[0].strip() == "---":
            block = []
            for line in lines[1:]:
                if line.strip() == "---":
                    break
                block.append(line)
            try:
                loaded = calkit.core._load_yaml_readonly("\n".join(block))
            except Exception:
                loaded = None
            if isinstance(loaded, dict):
                options = {str(k): str(v) for k, v in loaded.items()}
            return options
        for line in lines:
            option = _OPTION_RE.match(line)
            if option is None:
                break
            options[option.group("key")] = option.group("value")
        return options

    def add_roles(text: str, i: int, chain: tuple[str, ...]) -> None:
        # Read as Quarto's shortcode, on its line, so a mistake names it,
        # except in inline code, e.g., ``{ckvalue}`x` ``
        # With roles blanked, so their backticks aren't taken for code's
        masked = _ROLE_RE.sub(lambda m: " " * len(m.group()), text)
        code = [m.span() for m in _INLINE_CODE_RE.finditer(masked)]
        for role in _ROLE_RE.finditer(text):
            if any(start <= role.start() < end for start, end in code):
                continue
            found = extract_values(
                "\n" * i
                + "{{< "
                + role.group("name")
                + " "
                + role.group("args")
                + " >}}",
                chain[-1],
                results=results,
            )
            values.append((role.group("name"), role.group("args"), found[0]))

    def include(path: str, chain: tuple[str, ...]) -> None:
        path = posixpath.normpath(path)
        if read_text is None or path in chain:
            return
        included_text = read_text(path)
        if included_text is not None:
            if path not in included:
                included.append(path)
            scan(included_text, chain + (path,))

    def scan(text: str, chain: tuple[str, ...]) -> None:
        # The files being read, so ones that include each other stop, and
        # without HTML comments, which MyST doesn't show
        text = _HTML_COMMENT_RE.sub(
            lambda m: "\n" * m.group().count("\n"), text
        )
        lines = text.splitlines()
        # Each open fence's character and length, and whether its content
        # is literal
        stack: list[tuple[str, int, bool]] = []
        for i, line in enumerate(lines):
            m = _FENCE_RE.match(line)
            fence = m.group("fence") if m is not None else ""
            closes = (
                m is not None
                and not m.group("name")
                and not m.group("info")
                and bool(stack)
                and stack[-1][0] == fence[0]
                and len(fence) >= stack[-1][1]
            )
            if stack and stack[-1][2]:
                if closes:
                    stack.pop()
                continue
            if m is None:
                # A comment, which MyST doesn't show
                if not line.lstrip().startswith("%"):
                    add_roles(line, i, chain)
                continue
            if closes:
                stack.pop()
                continue
            name = m.group("name")
            if name is None:
                # A code block, since colons only make directives
                if not fence.startswith(":"):
                    stack.append((fence[0], len(fence), True))
                continue
            stack.append((fence[0], len(fence), name in LITERAL_DIRECTIVES))
            arg = m.group("arg") or ""
            options = get_options(lines[i + 1 :])
            # A file included as it's written, e.g., as code, shows nothing,
            # with a bare ':literal:' flag meaning it is
            literal = "literal" in options and options[
                "literal"
            ].strip().lower() not in ("false", "no", "off", "0")
            if name == "include" and arg and not literal:
                # Relative to the file including it, as MyST reads it
                include(
                    posixpath.join(
                        posixpath.dirname(chain[-1]), arg.replace("\\", "/")
                    ),
                    chain,
                )
                continue
            component = get_component(name, arg, options, line=i + 1)
            if component is not None:
                components.append(component)
                # Markdown it includes is read as part of the document
                if (
                    component.kind == "include"
                    and component.path.lower().endswith(".md")
                ):
                    include(component.path, chain)
                continue
            # E.g., an admonition's title
            add_roles(arg, i, chain)

    document_path = posixpath.normpath(Path(document_path).as_posix())
    components: list[Component] = []
    values: list[tuple[str, str, QuartoValue]] = []
    included: list[str] = []
    scan(text, (document_path,))
    return components, values, included


def find_documents(myst_dir: str, wdir: str | None = None) -> list[str]:
    """The documents a MyST project builds, as POSIX paths relative to
    ``wdir``, like ``myst_dir``: those its ``myst.yml``'s ``toc`` lists,
    files or patterns, or else, as MyST does without one, every Markdown
    file and notebook in its folder, except in ``_build``, folders starting
    with a dot, and ``node_modules``, either way leaving out what its
    ``exclude`` patterns match.
    """
    import fnmatch
    import glob

    import calkit

    def get_rel(fpath: str) -> str:
        return Path(os.path.relpath(fpath, root)).as_posix()

    def is_excluded(rel: str) -> bool:
        return any(
            fnmatch.fnmatch(rel, pattern)
            or fnmatch.fnmatch(rel, pattern.rstrip("/") + "/*")
            for pattern in exclude
        )

    def add_entries(entries: list) -> None:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("file"), str):
                rel = posixpath.normpath(entry["file"].replace("\\", "/"))
                # Without an extension, the file MyST finds for it
                if not rel.lower().endswith(DOCUMENT_EXTS):
                    rel = next(
                        (
                            rel + ext
                            for ext in DOCUMENT_EXTS
                            if os.path.isfile(os.path.join(root, rel + ext))
                        ),
                        rel,
                    )
                found.append(rel)
            if isinstance(entry.get("pattern"), str):
                found.extend(
                    sorted(
                        get_rel(f)
                        for f in glob.glob(
                            os.path.join(root, entry["pattern"]),
                            recursive=True,
                        )
                        if os.path.isfile(f)
                    )
                )
            add_entries(entry.get("children") or [])

    root = os.path.join(wdir or "", myst_dir)
    try:
        with open(os.path.join(root, "myst.yml"), encoding="utf-8") as f:
            config = calkit.core._load_yaml_readonly(f) or {}
    except (OSError, ValueError):
        config = {}
    project = config.get("project") if isinstance(config, dict) else None
    project = project if isinstance(project, dict) else {}
    exclude = project.get("exclude") or []
    exclude = [exclude] if isinstance(exclude, str) else list(exclude)
    found: list[str] = []
    if isinstance(project.get("toc"), list):
        add_entries(project["toc"])
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if not d.startswith(".")
                and d not in ("_build", "node_modules")
            )
            for name in sorted(filenames):
                if name.lower().endswith(DOCUMENT_EXTS):
                    found.append(get_rel(os.path.join(dirpath, name)))
    return [
        posixpath.normpath(posixpath.join(myst_dir, rel))
        for rel in dict.fromkeys(found)
        if not is_excluded(rel)
        and rel.lower().endswith(DOCUMENT_EXTS)
        and os.path.isfile(os.path.join(root, rel))
    ]


def get_plugin_problem(myst_dir: str, wdir: str | None = None) -> str | None:
    """Why the plugin that shows ``ckfigure``, ``cktable``, ``ckinclude``,
    ``ckvalue``, and ``ckrefval`` won't load for
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
        "The ckfigure, cktable, and ckinclude directives and ckvalue and "
        "ckrefval roles need Calkit's MyST plugin listed in "
        f"{posixpath.join(myst_dir, 'myst.yml')}; add:\n\n{PLUGIN_CONFIG}"
    )


def get_target_paths(
    target_path: str, wdir: str | None = None
) -> tuple[str | None, str | None]:
    """The folder of the MyST project a target is in, i.e., where its
    ``myst.yml`` is, and the document it names, if any, both as POSIX
    paths relative to ``wdir``, like ``target_path``.

    The target is the project's folder, its ``myst.yml``, or a document in
    it, whose project is the nearest folder above it with a ``myst.yml``,
    without leaving ``wdir``. The folder is None if there's no
    ``myst.yml`` there.
    """

    def has_config(folder: str) -> bool:
        return os.path.isfile(os.path.join(wdir or "", folder, "myst.yml"))

    target = posixpath.normpath(target_path.replace("\\", "/"))
    if os.path.isdir(os.path.join(wdir or "", target)):
        return (target if has_config(target) else None), None
    if posixpath.basename(target) == "myst.yml":
        folder = posixpath.dirname(target) or "."
        return (folder if has_config(folder) else None), None
    folder = posixpath.dirname(target) or "."
    while not has_config(folder):
        if folder in (".", "") or folder.startswith(".."):
            return None, target
        folder = posixpath.dirname(folder) or "."
    return folder, target


# The export formats 'myst build' options build, as exports name them
EXPORT_FLAGS = {
    "--pdf": "pdf",
    "--tex": "tex",
    "--typst": "typst",
    "--word": "docx",
    "--docx": "docx",
    "--md": "md",
    "--jats": "jats",
    "--xml": "jats",
    "--meca": "meca",
    "--cff": "cff",
}


def get_build_outputs(
    myst_dir: str,
    document: str | None,
    args: list[str],
    wdir: str | None = None,
) -> list[str]:
    """What ``myst build`` writes, built from a MyST project's folder with
    these arguments, given a document or not, as POSIX paths relative to
    ``wdir``, like ``myst_dir`` and ``document``.

    The site goes to ``_build/site`` with ``--site`` or ``--all``, or with
    no format given when ``myst.yml`` defines one, and ``--html`` to
    ``_build/html``. Exports go where ``myst.yml``'s or a document's front
    matter says, or else to ``_build/exports``: those of the formats
    given, or all, with ``--all`` or for a document given without one.
    """
    import calkit

    def load_yaml(text: str) -> dict:
        try:
            loaded = calkit.core._load_yaml_readonly(text)
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def get_front_matter(path: str) -> dict:
        try:
            with open(os.path.join(wdir or "", path), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return {}
        if not text.startswith("---"):
            return {}
        end = text.find("\n---", 3)
        return load_yaml(text[3:end]) if end != -1 else {}

    def get_exports(info: dict) -> list:
        exports = info.get("exports") or []
        return [e for e in exports if isinstance(e, dict)]

    build_dir = posixpath.normpath(posixpath.join(myst_dir, "_build"))
    try:
        with open(
            os.path.join(wdir or "", myst_dir, "myst.yml"), encoding="utf-8"
        ) as f:
            config = load_yaml(f.read())
    except OSError:
        config = {}
    project = config.get("project")
    project = project if isinstance(project, dict) else {}
    options = args[: args.index("--")] if "--" in args else args
    flags = {a for a in options if a.startswith("-")}
    files = [a for a in options if not a.startswith("-")]
    if document is not None:
        files.append(posixpath.relpath(document, myst_dir))
    formats = {EXPORT_FLAGS[f] for f in flags if f in EXPORT_FLAGS}
    build_all = bool(flags & {"-a", "--all"})
    outputs = []
    if "--html" in flags:
        outputs.append(f"{build_dir}/html")
    if (
        "--site" in flags
        or build_all
        or (not formats and not files and "--html" not in flags)
    ) and ("site" in config or "--site" in flags):
        outputs.append(f"{build_dir}/site")
    # Exports, each from the file declaring it, and the project's only
    # when no document is given
    if formats or build_all or files:

        def is_wanted(export: dict) -> bool:
            fmt = str(export.get("format") or "").split("+")[0]
            return build_all or not formats or fmt in formats

        given = [
            posixpath.normpath(posixpath.join(myst_dir, f)) for f in files
        ]
        declared = (
            []
            if given
            else [(e, myst_dir) for e in get_exports(project) if is_wanted(e)]
        )
        to_default = "--force" in flags
        for path in given or find_documents(myst_dir, wdir=wdir):
            exports = [
                e for e in get_exports(get_front_matter(path)) if is_wanted(e)
            ]
            declared += [(e, posixpath.dirname(path)) for e in exports]
            # A document given is exported in each format given, declared
            # or not
            fmts = {str(e.get("format") or "").split("+")[0] for e in exports}
            if path in given and formats - fmts:
                to_default = True
        for export, base in declared:
            output = export.get("output")
            if isinstance(output, str) and output:
                outputs.append(
                    posixpath.normpath(posixpath.join(base, output))
                )
            else:
                to_default = True
        if to_default:
            outputs.append(f"{build_dir}/exports")
    return list(dict.fromkeys(outputs))


def get_build_stage(
    target_path: str, ck_info: dict, wdir: str | None = None
) -> str | None:
    """The pipeline stage that builds a MyST target, a folder, its
    ``myst.yml``, or a document, relative to ``wdir``: a ``myst`` stage
    building the same, or else its whole project, or else a stage whose
    command runs ``calkit doc myst build`` from the project's folder.
    """
    myst_dir, document = get_target_paths(target_path, wdir=wdir)
    if myst_dir is None:
        return None
    stages = {
        str(name): stage
        for name, stage in (
            (ck_info.get("pipeline") or {}).get("stages") or {}
        ).items()
        if isinstance(stage, dict)
    }
    builds = {}
    for name, stage in stages.items():
        if stage.get("kind") == "myst" and isinstance(
            stage.get("target_path"), str
        ):
            builds[name] = get_target_paths(
                posixpath.join(stage.get("wdir") or "", stage["target_path"]),
                wdir=wdir,
            )
    for wanted in [(myst_dir, document), (myst_dir, None)]:
        for name, paths in builds.items():
            if paths == wanted:
                return name
    for name, stage in stages.items():
        command = stage.get("command")
        if (
            isinstance(command, str)
            and re.search(r"\bcalkit (doc|document) myst build\b", command)
            and posixpath.normpath(stage.get("wdir") or ".") == myst_dir
        ):
            return name
    return None


def get_unlisted_paths(
    paths: list[str], stage: str, wdir: str | None = None
) -> list[str]:
    """The project paths a stage's documents show that aren't among the
    inputs ``dvc.yaml`` lists for it, or in one, nor its outputs, in order.

    Nothing is, if ``dvc.yaml`` doesn't have the stage yet, and a path that
    doesn't exist, which no stage makes, can't be an input, so it's left
    for its panel to say it's missing.
    """
    import calkit

    def under(path: str, parent: str) -> bool:
        return path == parent or path.startswith(parent.rstrip("/") + "/")

    def get_paths(dvc_stage: dict, key: str) -> list[str]:
        base = dvc_stage.get("wdir") or ""
        found = []
        for item in dvc_stage.get(key) or []:
            if isinstance(item, dict):
                item = item.get("path") or next(iter(item), None)
            if isinstance(item, str):
                found.append(posixpath.normpath(posixpath.join(base, item)))
        return found

    try:
        with open(os.path.join(wdir or "", "dvc.yaml"), encoding="utf-8") as f:
            dvc_yaml = calkit.core._load_yaml_readonly(f) or {}
    except OSError:
        return []
    dvc_stages = {
        name: s
        for name, s in (dvc_yaml.get("stages") or {}).items()
        if isinstance(s, dict)
    }
    if stage not in dvc_stages:
        return []
    listed = get_paths(dvc_stages[stage], "deps") + get_paths(
        dvc_stages[stage], "outs"
    )
    made = [p for s in dvc_stages.values() for p in get_paths(s, "outs")]
    return [
        path
        for path in dict.fromkeys(paths)
        if not any(under(path, p) for p in listed)
        and (
            os.path.exists(os.path.join(wdir or "", path))
            or any(under(path, p) for p in made)
        )
    ]


def add_role_values(
    record_path: str,
    roles: list[tuple[str, str, QuartoValue]],
    texts: list[str],
) -> None:
    """Add what each role shows to a document's record, by its name and
    content, as the plugin finds it: the value's text, formatted as Quarto
    and LaTeX format it, what its provenance is recorded under, and
    whether to show it.
    """
    import json

    import calkit
    from calkit.quarto import get_value_key

    with open(record_path, encoding="utf-8") as f:
        record = json.load(f)
    by_role: dict[str, dict] = {}
    for (name, args, value), text in zip(roles, texts):
        by_role.setdefault(name, {})[args.strip()] = {
            "text": text,
            "key": get_value_key(value),
            "path": value.path,
            "provenance": value.provenance,
        }
    record["roles"] = by_role
    calkit.core.write_if_changed(
        record_path, json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    )


# Quiets what the plugin shows, for book-theme, which loads it if
# myst.yml lists it under site.options.style
PLUGIN_CSS = """/* Written by Calkit; changes are overwritten by 'calkit doc myst build'. */
/* Where something came from, collapsed under it as a small, muted line,
   as in Quarto, saying what's wrong in a warning color while collapsed */
details.ck-provenance {
  border: none !important;
  box-shadow: none !important;
  background: none !important;
  margin: -0.25rem 0 1rem !important;
  border-radius: 0 !important;
}
details.ck-provenance > summary {
  display: inline-block !important;
  min-height: 0 !important;
  padding: 0 !important;
  background: none !important;
  box-shadow: none !important;
  list-style: none;
  font-size: 0.85rem !important;
  font-weight: normal !important;
  color: inherit;
  opacity: 0.7;
}
details.ck-provenance > summary::-webkit-details-marker {
  display: none;
}
details.ck-provenance > summary::before {
  content: "\\25B8\\00a0";
}
details.ck-provenance[open] > summary::before {
  content: "\\25BE\\00a0";
}
details.ck-provenance > summary > *,
details.ck-provenance > summary > * > * {
  display: inline !important;
  color: inherit !important;
}
details.ck-provenance > summary svg {
  display: none !important;
}
details.ck-provenance:not(.ck-ok) > summary {
  opacity: 1;
  color: #b35900;
  font-weight: 600 !important;
}
.dark details.ck-provenance:not(.ck-ok) > summary {
  color: #f0a04b;
}
details.ck-provenance[open] > .details-body {
  border-left: 2px solid rgba(128, 128, 128, 0.35);
  margin: 0.25rem 0 0 0.2rem;
  padding: 0 0 0 0.75rem !important;
  font-size: 0.9rem;
}
"""
PLUGIN_CSS_PATH = "_extensions/calkit/myst.css"


def write_plugin(myst_dir: str, wdir: str | None = None) -> None:
    """Write the plugin and its stylesheet beside a MyST project's
    ``myst.yml``, leaving them alone if they're already right, so their
    timestamps don't change.
    """
    import calkit

    for path, content in [
        (PLUGIN_PATH, PLUGIN_JS),
        (PLUGIN_CSS_PATH, PLUGIN_CSS),
    ]:
        fpath = os.path.join(wdir or "", myst_dir, *path.split("/"))
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        calkit.core.write_if_changed(fpath, content)
