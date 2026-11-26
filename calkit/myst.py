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
PLUGIN_JS = r"""// Written by Calkit; changes are overwritten by 'calkit myst build'.
// Shows a file from the project with {ckfigure}, {cktable} for a CSV or
// TSV file, or {ckinclude} for anything else, and values with {ckvalue}
// and {ckrefval}, with where each came from collapsed under it, or for a
// value, behind a marker linking to it. Calkit works out the values and
// what that says before building, and writes it to
// .calkit/local/provenance; this only turns it into MyST's AST.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const MARKDOWN_EXTS = new Set([".md"]);

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

// What Calkit recorded for a document, read each time, since 'myst start'
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

// Whether the document changed since Calkit recorded it, e.g., in
// 'myst start'
function isOutdated(records, docPath) {
  if (!records || !records.source_sha1) {
    return false;
  }
  try {
    const digest = crypto.createHash("sha1")
      .update(fs.readFileSync(docPath)).digest("hex");
    return digest !== records.source_sha1;
  } catch {
    return false;
  }
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

function getSummary(provenance, outdated) {
  const out = [...provenance.summary];
  if (outdated) {
    out.push({
      type: "text", value: " · recorded before this document changed",
    });
  }
  return out;
}

function getView(provenance, outdated) {
  const out = [];
  if (outdated) {
    out.push({
      type: "paragraph",
      children: [{
        type: "text",
        value: "The document changed since this was recorded; build it "
          + "with Calkit to update it.",
      }],
    });
  }
  return [...out, ...convertAll(provenance.view)];
}

// Collapsed, saying what's wrong while it is
function getDetails(summary, view) {
  return {
    type: "details",
    class: "ck-provenance",
    children: [{ type: "summary", children: summary }, ...view],
  };
}

function getUnrecorded() {
  return getDetails(
    [{ type: "text", value: "⚠️ No provenance recorded" }],
    [{
      type: "paragraph",
      children: [
        { type: "text", value: "Build with " },
        { type: "inlineCode", value: "calkit myst build" },
        { type: "text", value: " or " },
        { type: "inlineCode", value: "calkit run" },
        { type: "text", value: "." },
      ],
    }],
  );
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
      const opts = data.options || {};
      const caption = data.body || [];
      const docPath = vfile.path ? path.resolve(vfile.path) : null;
      const records = docPath ? loadRecords(docPath) : null;
      const record = records ? (records.components || {})[src] : null;
      const projectDir = docPath
        ? findProjectDir(path.dirname(docPath)) : process.cwd();
      const url = record ? record.url : path.relative(
        docPath ? path.dirname(docPath) : projectDir,
        path.join(projectDir, src),
      ).split(path.sep).join("/");
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
        out.push(container(record ? convertAll(record.body) : [{
          // Only its name, keeping its label, so references resolve
          type: "table",
          children: [{
            type: "tableRow",
            children: [{
              type: "tableCell",
              children: [{ type: "inlineCode", value: src }],
            }],
          }],
        }]));
      } else {
        let content = null;
        if (MARKDOWN_EXTS.has(path.extname(src).toLowerCase())
          && ctx && ctx.parseMyst) {
          try {
            const text = fs.readFileSync(path.join(projectDir, src), "utf8");
            content = ctx.parseMyst(text).children;
          } catch {
            content = null;
          }
        }
        out.push(...(content || [{
          type: "paragraph", children: [{ type: "inlineCode", value: src }],
        }]), ...caption);
      }
      if (isOff(opts.provenance)) {
        return out;
      }
      if (!record) {
        out.push(getUnrecorded());
      } else if (record.provenance) {
        const outdated = isOutdated(records, docPath);
        out.push(getDetails(
          getSummary(record.provenance, outdated),
          getView(record.provenance, outdated),
        ));
      }
      return out;
    },
  };
}

// Where a value's view is, at the end of the document
function getValueId(key) {
  return "ck-value-" + key.toLowerCase().replace(/[^a-z0-9]+/g, "-");
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
        return [{ type: "text", value: "??" }];
      }
      const out = [{ type: "text", value: role.text }];
      const value = (records.values || {})[role.key];
      if (!role.provenance || !value || !value.provenance) {
        return out;
      }
      // A quiet marker, or a warning one, linking to where it came from,
      // which MyST shows when it's hovered
      const warn = value.provenance.state !== "ok"
        || isOutdated(records, docPath);
      out.push({
        type: "crossReference",
        identifier: getValueId(role.key),
        label: getValueId(role.key),
        ckValue: role.key,
        children: [{
          type: "superscript",
          children: [{ type: "text", value: warn ? "⚠" : "ⓘ" }],
        }],
      });
      return out;
    },
  };
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children || []) {
    walk(child, visit);
  }
}

// The views of the values the document shows, collapsed at its end, where
// their markers link to
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
    const records = loadRecords(docPath) || {};
    const outdated = isOutdated(records, docPath);
    const views = keys.map((key) => {
      const provenance = records.values[key].provenance;
      return {
        type: "admonition",
        kind: provenance.state === "ok" && !outdated ? "note" : "warning",
        identifier: getValueId(key),
        label: getValueId(key),
        children: [
          {
            type: "admonitionTitle",
            children: getSummary(provenance, outdated),
          },
          ...getView(provenance, outdated),
        ],
      };
    });
    tree.children.push({
      type: "block",
      children: [getDetails(
        [{ type: "text", value: "Where the values came from" }], views,
      )],
    });
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
) -> tuple[list[Component], list[tuple[str, str, QuartoValue]]]:
    """Find the ``ckfigure``, ``cktable``, and ``ckinclude`` directives in a
    MyST document, and the values it shows with ``ckvalue`` and
    ``ckrefval`` roles, in order, skipping code blocks and directives whose
    content is literal, e.g., ``{code-cell}``.

    A directive names its file, relative to the project, as LaTeX's
    ``\\ckfigure`` and the roles do, with options as ``:key: value`` lines or
    a YAML block. A role's content reads as Quarto's shortcode's arguments
    do, e.g., ``{ckvalue}`results/fit.json slope .2f```, and each is
    returned with its role's name and content, as the plugin finds it.
    With ``read_text``, which reads a project path, or None if it can't,
    the files the document ``{include}``s are read too, with their paths
    relative to the document, as MyST reads them. ``results`` maps
    declared results' names to their paths.
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

    def scan(text: str, chain: tuple[str, ...]) -> None:
        # The files being read, so ones that include each other stop
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
                # Read as Quarto's shortcode, on its line, so a mistake
                # names it
                for role in _ROLE_RE.finditer(line):
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
                    values.append(
                        (role.group("name"), role.group("args"), found[0])
                    )
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
            if name == "include" and read_text is not None and arg:
                included = posixpath.normpath(posixpath.join(base, arg))
                included_text = (
                    read_text(included) if included not in chain else None
                )
                if included_text is not None:
                    scan(included_text, chain + (included,))
                continue
            component = get_component(
                name, arg, get_options(lines[i + 1 :]), line=i + 1
            )
            if component is not None:
                components.append(component)

    document_path = posixpath.normpath(Path(document_path).as_posix())
    base = posixpath.dirname(document_path)
    components: list[Component] = []
    values: list[tuple[str, str, QuartoValue]] = []
    scan(text, (document_path,))
    return components, values


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
            "provenance": value.provenance,
        }
    record["roles"] = by_role
    calkit.core.write_if_changed(
        record_path, json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    )


def write_plugin(myst_dir: str, wdir: str | None = None) -> None:
    """Write the plugin beside a MyST project's ``myst.yml``, leaving it
    alone if it's already right, so its timestamp doesn't change.
    """
    import calkit

    fpath = os.path.join(wdir or "", myst_dir, *PLUGIN_PATH.split("/"))
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    calkit.core.write_if_changed(fpath, PLUGIN_JS)
