// Written by Calkit; changes are overwritten by 'calkit doc myst build'.
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
      const id = getValueId(projectDir, docPath, key);
      // Its mark links to its first paragraph, which every export labels,
      // e.g., Typst, which doesn't label an admonition, or else to it
      const first = view.findIndex((n) => n.type === "paragraph");
      const target = { identifier: id, label: id };
      if (first !== -1) {
        view[first] = { ...view[first], ...target };
      }
      return {
        type: "admonition",
        kind: ok ? "note" : "warning",
        class: "dropdown ck-provenance" + (ok ? " ck-ok" : ""),
        ...(first === -1 ? target : {}),
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
