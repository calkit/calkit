"""Functionality for using Quarto in Calkit projects."""

from __future__ import annotations

import json
import os
import posixpath
import re
from collections.abc import Callable
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
  # Listed by a document as {at: pre-ast, path: calkit}, before Quarto's own
  # filters number figures and build callouts
  filters:
    - provenance.lua
"""
# The part of Python's format spec the shortcode formats the way Python
# does, e.g., "+,.2f", without a space for a sign, which Quarto trims
FORMAT_SPEC_RE = re.compile(r"^[+\-]?[,_]?(\.\d+[fFeEgG%]|[fFeEgGd%s]?)$")
# Text the shortcode would show changed, since Pandoc reads YAML strings as
# Markdown, e.g., *emphasis*, a backslash escape, HTML, or math
_YAML_MARKDOWN_RE = re.compile(r"[*\\<>`$^]|~~|\]\(|  |^\s|\s$")
# A field of a format written as a template, e.g., "{value:.1f} m/s"
_FORMAT_FIELD_RE = re.compile(r"\{([^{}]*)\}")
# A shortcode written {{</* ckvalue */>}} is Quarto's escaped form, shown
# literally, so it doesn't match
_SHORTCODE_RE = re.compile(r"\{\{<\s*ckvalue\s+(?P<args>.*?)\s*>\}\}")
# {{< ckrefval key name format >}}, a value quoted from a reference
_REFVAL_SHORTCODE_RE = re.compile(r"\{\{<\s*ckrefval\s+(?P<args>.*?)\s*>\}\}")
# Quarto's own shortcode for a cell's output from another document, e.g.,
# {{< embed analysis.ipynb#fig-decay >}}
_EMBED_RE = re.compile(r"\{\{<\s*embed\s+[\"']?(?P<path>[^\s#\"'>]+)")

# What the filter and the shortcodes share: reading what Calkit recorded
# for the document, and turning a provenance view into Pandoc's AST or
# HTML, deciding nothing about what it says, which is decided in Python
PROVENANCE_LUA_COMMON = r"""
local function read_file(fpath, mode)
  local f = io.open(fpath, mode or "r")
  if f == nil then
    return nil
  end
  local content = f:read("a")
  f:close()
  return content
end

-- A path as Python's posixpath.normpath writes it, so it's looked up as
-- Calkit recorded it, e.g., results/fit.json for ./results/fit.json
local function normpath(path)
  local parts = {}
  for part in (path:gsub("\\", "/")):gmatch("[^/]+") do
    if part == ".." and #parts > 0 and parts[#parts] ~= ".." then
      table.remove(parts)
    elseif part ~= "." then
      table.insert(parts, part)
    end
  end
  return #parts > 0 and table.concat(parts, "/") or "."
end

-- The Calkit project's folder, which paths are relative to
local function find_project_dir()
  local dir = pandoc.path.directory(quarto.doc.input_file)
  while true do
    if read_file(pandoc.path.join({dir, "calkit.yaml"})) ~= nil then
      return dir
    end
    local parent = pandoc.path.directory(dir)
    if parent == dir then
      return quarto.project.directory
        or pandoc.path.directory(quarto.doc.input_file)
    end
    dir = parent
  end
end

-- What Calkit recorded for this document, or false if nothing
local records = nil
local function load_records()
  if records ~= nil then
    return records
  end
  records = false
  local project_dir = find_project_dir()
  local rel = pandoc.path.make_relative(quarto.doc.input_file, project_dir)
  local content = read_file(pandoc.path.join({
    project_dir, ".calkit", "local", "provenance",
    (rel:gsub("\\", "/")) .. ".json",
  }))
  if content ~= nil then
    local ok, data = pcall(quarto.json.decode, content)
    if ok and type(data) == "table" then
      records = data
    end
  end
  return records
end

-- Whether the document changed since Calkit recorded it, e.g., in
-- 'quarto preview', which a notebook does by rendering with --execute
local outdated = nil
local function is_outdated(data)
  if outdated == nil then
    outdated = false
    local input = quarto.doc.input_file
    local notebook = input:lower():match("%.ipynb$")
    local content = read_file(input, "rb")
    if data and data.source_sha1 and content ~= nil and not notebook then
      outdated = pandoc.utils.sha1(content) ~= data.source_sha1
    end
  end
  return outdated
end

-- What changed since Calkit recorded it, e.g., a figure made again by
-- hand, or the document, which the view then says it's from before, or
-- nil if nothing did
local function get_changed(data, path, sha1)
  if sha1 then
    local content = read_file(
      pandoc.path.join({find_project_dir(), path}), "rb"
    )
    if content == nil or pandoc.utils.sha1(content) ~= sha1 then
      return path
    end
  end
  if is_outdated(data) then
    return "this document"
  end
  return nil
end

local inlines, blocks

-- Text as Str and Space inlines rather than one long Str
local function words(value)
  local out = pandoc.Inlines({})
  local first = true
  for piece in string.gmatch(tostring(value) .. " ", "([^ ]*) ") do
    if not first then
      out:insert(pandoc.Space())
    end
    if piece ~= "" then
      out:insert(pandoc.Str(piece))
    end
    first = false
  end
  return out
end

local function inline(node)
  local kind = node.type
  if kind == "text" then
    return words(node.value or "")
  elseif kind == "strong" then
    return pandoc.Inlines({pandoc.Strong(inlines(node.children))})
  elseif kind == "emphasis" then
    return pandoc.Inlines({pandoc.Emph(inlines(node.children))})
  elseif kind == "inlineCode" then
    return pandoc.Inlines({pandoc.Code(node.value or "")})
  elseif kind == "link" then
    return pandoc.Inlines({
      pandoc.Link(inlines(node.children), node.url or ""),
    })
  end
  quarto.log.warning("Calkit provenance: unknown inline " .. tostring(kind))
  return pandoc.Inlines({})
end

inlines = function(nodes)
  local out = pandoc.Inlines({})
  for _, node in ipairs(nodes or {}) do
    out:extend(inline(node))
  end
  return out
end

local function data_table(node)
  local head, body, columns = {}, {}, 0
  for index, row in ipairs(node.children or {}) do
    local cells, header = {}, false
    for _, item in ipairs(row.children or {}) do
      if item.header then
        header = true
      end
      table.insert(cells, {pandoc.Plain(inlines(item.children))})
    end
    if #cells > columns then
      columns = #cells
    end
    if index == 1 and header then
      head = cells
    else
      table.insert(body, cells)
    end
  end
  local aligns, widths = {}, {}
  for index = 1, columns do
    aligns[index] = pandoc.AlignDefault
    widths[index] = 0
  end
  return pandoc.utils.from_simple_table(
    pandoc.SimpleTable({}, aligns, widths, head, body)
  )
end

local function escape(value)
  return (value:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")
    :gsub('"', "&quot;"))
end

-- How a view looks; its graph is drawn by provenance.js when it's opened,
-- loading Mermaid then, since it can't measure text while it's hidden
local STYLE = [[
<style>
details.ck-provenance{margin:-.25rem 0 1rem;font-size:.85em;
  color:var(--bs-secondary-color,#6c757d)}
details.ck-provenance>summary{cursor:pointer;display:inline-block;
  list-style:none}
details.ck-provenance>summary::-webkit-details-marker{display:none}
details.ck-provenance>summary::before{content:"\25B8  "}
details.ck-provenance[open]>summary::before{content:"\25BE  "}
details.ck-provenance:not(.ck-ok)>summary,
details.ck-provenance.ck-outdated>summary{color:#b35900;font-weight:600}
details.ck-provenance[open]{
  border-left:2px solid var(--bs-border-color,#dee2e6);padding-left:.75rem}
.ck-value{cursor:pointer;border-bottom:1px dotted currentColor}
button.ck-value{all:unset;cursor:pointer;
  border-bottom:1px dotted currentColor}
button.ck-value:focus-visible{outline:2px solid #0d6efd;outline-offset:2px}
.ck-value:not(.ck-ok),.ck-value.ck-outdated{border-bottom-color:#b35900}
.ck-flagged::after{content:"⚠";color:#b35900;font-size:.7em;
  margin-left:.1em;vertical-align:super}
.ck-popover{max-width:min(48rem,92vw);max-height:80vh;overflow:auto;
  padding:1rem;border:1px solid var(--bs-border-color,#dee2e6);
  border-radius:.375rem;font-size:.9em;
  background:var(--bs-body-bg,Canvas);color:var(--bs-body-color,CanvasText)}
.ck-popover table{border-collapse:collapse;margin-bottom:1rem}
.ck-popover th,.ck-popover td{padding:.2rem .6rem;text-align:left;
  border-bottom:1px solid var(--bs-border-color,#dee2e6)}
.ck-provenance svg .nodeLabel,.ck-popover svg .nodeLabel{color:#1f1f1f}
.ck-provenance svg .flowchart-link,.ck-popover svg .flowchart-link{
  stroke:var(--bs-secondary-color,#6c757d)!important}
.ck-provenance svg marker path,.ck-popover svg marker path{
  fill:var(--bs-secondary-color,#6c757d)!important;
  stroke:var(--bs-secondary-color,#6c757d)!important}
</style>
]]
local assets_ready = false
local function add_assets()
  if assets_ready then
    return
  end
  local share = os.getenv("QUARTO_SHARE_PATH")
  local scripts, resources = {}, {}
  if share then
    local mermaid_path = pandoc.path.join({
      share, "formats", "html", "mermaid", "mermaid.min.js",
    })
    local data = load_records()
    if data and data.embeds_resources then
      -- Loaded with the page, which can't load anything later
      table.insert(scripts, mermaid_path)
    else
      -- Copied beside provenance.js, but only loaded when a view opens
      table.insert(resources, {name = "mermaid.min.js", path = mermaid_path})
    end
  end
  table.insert(scripts, quarto.utils.resolve_path("provenance.js"))
  quarto.doc.add_html_dependency({
    name = "calkit-provenance",
    scripts = scripts,
    resources = resources,
  })
  quarto.doc.include_text("in-header", STYLE)
  assets_ready = true
end

local function block(node)
  local kind = node.type
  if kind == "paragraph" then
    return pandoc.Blocks({pandoc.Para(inlines(node.children))})
  elseif kind == "table" then
    return pandoc.Blocks({data_table(node)})
  elseif kind == "mermaid" then
    if quarto.doc.is_format("html:js") then
      return pandoc.Blocks({
        pandoc.RawBlock(
          "html",
          '<pre class="ck-mermaid">' .. escape(node.value or "") .. "</pre>"
        ),
      })
    end
    return pandoc.Blocks({
      pandoc.CodeBlock(node.value or "", pandoc.Attr("", {"default"}, {})),
    })
  end
  quarto.log.warning("Calkit provenance: unknown block " .. tostring(kind))
  return pandoc.Blocks({})
end

blocks = function(nodes)
  local out = pandoc.Blocks({})
  for _, node in ipairs(nodes or {}) do
    out:extend(block(node))
  end
  return out
end

local function to_html(content)
  return (pandoc.write(pandoc.Pandoc(content), "html"):gsub("%s+$", ""))
end

local function get_classes(base, provenance, changed)
  return base .. " ck-" .. (provenance.state or "ok")
    .. (changed and " ck-outdated" or "")
end

-- The line shown while it's collapsed, which says what's wrong
local function get_summary(provenance, changed)
  if changed and (provenance.state or "ok") == "ok" then
    return words("⚠️ Recorded before " .. changed .. " changed")
  end
  local out = inlines(provenance.summary)
  if changed then
    out:extend(words(" · recorded before " .. changed .. " changed"))
  end
  return out
end

-- How it came to be, under a note if what it's about changed since
local function get_view(provenance, changed)
  local out = pandoc.Blocks({})
  if changed then
    out:insert(pandoc.Para(words(
      "Recorded before " .. changed .. " changed; render the document "
        .. "with Calkit to update this."
    )))
  end
  out:extend(blocks(provenance.view))
  return out
end
"""

# Shows where each file a page loads from came from, and makes values into
# buttons opening where they came from, except where a button can't go,
# e.g., in a heading or link
PROVENANCE_JS = r"""// Written by Calkit; changes are overwritten when the pipeline compiles.
(() => {
  const base = document.currentScript
    ? document.currentScript.src.replace(/[^/]*$/, "")
    : "";
  let loading = null;
  // Mermaid, loaded the first time a view with a graph opens, unless the
  // page already has it
  function loadMermaid() {
    if (window.mermaid) {
      return Promise.resolve(window.mermaid);
    }
    if (!loading) {
      loading = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = base + "mermaid.min.js";
        script.onload = () => {
          window.mermaid.initialize({ startOnLoad: false });
          resolve(window.mermaid);
        };
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }
    return loading;
  }
  async function draw(root) {
    const pres = root.querySelectorAll("pre.ck-mermaid:not([data-drawn])");
    if (pres.length === 0) {
      return;
    }
    let mermaid;
    try {
      mermaid = await loadMermaid();
    } catch {
      // Left as its source, e.g., in a page with everything embedded
      return;
    }
    for (const pre of pres) {
      pre.dataset.drawn = "true";
      const id = "ck-mermaid-" + Math.random().toString(36).slice(2);
      // One Mermaid can't draw stays as its source, not the rest
      try {
        const { svg } = await mermaid.render(id, pre.textContent);
        pre.innerHTML = svg;
      } catch {
        continue;
      }
    }
  }
  document.addEventListener("toggle", (event) => {
    const el = event.target;
    if (el.open || event.newState === "open") {
      draw(el);
    }
  }, true);
  function addButtons() {
    const spans = document.querySelectorAll("span.ck-value[data-ck-popover]");
    for (const span of spans) {
      if (span.closest("a, h1, h2, h3, h4, h5, h6, nav, .title, summary")) {
        continue;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = span.className;
      button.title = span.title;
      button.setAttribute("popovertarget", span.dataset.ckPopover);
      button.setAttribute("aria-label", span.dataset.ckLabel);
      button.append(...span.childNodes);
      span.replaceWith(button);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", addButtons);
  } else {
    addButtons();
  }
})();
"""

# Turns what Calkit recorded for each of a document's components into
# Pandoc's AST, deciding nothing about what it says
PROVENANCE_LUA = (
    r"""---@diagnostic disable: undefined-global
-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows a file from the project with ::: {.ckfigure src="figures/fit.png"},
-- .cktable for a CSV or TSV file, or .ckinclude for anything else, with
-- where it came from collapsed under it. Calkit decides what that says
-- before rendering, and writes it to .calkit/local/provenance; this only
-- turns it into Pandoc's AST. It has to run at pre-ast, so Quarto numbers
-- figures and tables after.
"""
    + PROVENANCE_LUA_COMMON
    + r"""
local KINDS = {ckfigure = "figure", cktable = "table", ckinclude = "include"}
local MARKDOWN_EXTS = {[".md"] = true, [".qmd"] = true}
local TABLE_READERS = {[".csv"] = "csv", [".tsv"] = "tsv"}
-- What a component takes for itself rather than passing to its figure
local OWN_ATTRIBUTES = {src = true, rows = true, provenance = true}

local function is_off(value)
  value = (value or ""):lower()
  return value == "false" or value == "no" or value == "0" or value == "off"
end

-- The file's path relative to the document, as an image's is read, when
-- nothing's recorded to say it
local function get_url(path)
  return pandoc.path.make_relative(
    pandoc.path.join({find_project_dir(), path}),
    pandoc.path.directory(quarto.doc.input_file),
    true
  )
end

-- An image with the div's figure options and classes, e.g., fig-pos or
-- .lightbox, as Quarto reads them on one
local function get_image(el, url)
  local attributes = {}
  for key, value in pairs(el.attributes) do
    if not OWN_ATTRIBUTES[key] and key ~= "alt" then
      table.insert(attributes, {key, value})
    end
  end
  table.sort(attributes, function(a, b) return a[1] < b[1] end)
  local alt = el.attributes.alt and words(el.attributes.alt)
    or pandoc.Inlines({})
  return pandoc.Image(alt, url, "", pandoc.Attr("", el.classes, attributes))
end

-- A Quarto figure, numbered and cross-referenced by the div's id, with its
-- content as the caption, so citations and cross-references in it work
local function get_figure(el, content)
  if el.identifier == "" and #el.content == 0 then
    return content
  end
  return pandoc.Blocks({
    pandoc.Figure(
      content, {long = el.content}, pandoc.Attr(el.identifier, {}, {})
    ),
  })
end

-- Text with any byte that isn't part of UTF-8 replaced, which Pandoc
-- reads only
local function to_utf8(text)
  if utf8.len(text) then
    return text
  end
  local out, i = {}, 1
  while i <= #text do
    local byte = text:byte(i)
    local n = byte >= 0xF0 and 4 or byte >= 0xE0 and 3
      or byte >= 0xC0 and 2 or 1
    local piece = text:sub(i, i + n - 1)
    if utf8.len(piece) == 1 then
      table.insert(out, piece)
      i = i + n
    else
      table.insert(out, "\239\191\189")
      i = i + 1
    end
  end
  return table.concat(out)
end

-- A CSV or TSV file's rows, read when the document renders, so they're
-- what the file has now, up to as many as it says
local function get_table(path, rows)
  local _, ext = pandoc.path.split_extension(path)
  local reader = TABLE_READERS[ext:lower()] or "csv"
  local text = read_file(pandoc.path.join({find_project_dir(), path}), "rb")
  if text == nil then
    return pandoc.Blocks({pandoc.Para({
      pandoc.Emph(words("Can't read " .. path)),
    })})
  end
  -- Without a byte order mark, and with what isn't UTF-8 replaced
  text = to_utf8((text:gsub("^\239\187\191", "")))
  local ok, doc = pcall(pandoc.read, text, reader)
  if not ok or #doc.blocks == 0 or doc.blocks[1].t ~= "Table" then
    return pandoc.Blocks({pandoc.Para({
      pandoc.Emph(words("Can't read " .. path)),
    })})
  end
  local tbl = doc.blocks[1]
  local limit = tonumber(rows) or 25
  local bodies = tbl.bodies
  local body = bodies[1] and bodies[1].body or {}
  local n_rows = #body
  if n_rows > limit then
    -- Set back whole, since what's read from the table is a copy
    while #body > limit do
      table.remove(body)
    end
    bodies[1].body = body
    tbl.bodies = bodies
  end
  local out = pandoc.Blocks({tbl})
  if n_rows > limit then
    out:insert(pandoc.Para({pandoc.Emph(words(
      (limit == 1 and "First row of " or "First " .. limit .. " rows of ")
        .. path
    ))}))
  end
  return out
end

-- Collapsed under it in HTML, saying what's wrong while it is, and only
-- that, in a line, in other formats
local function get_provenance(provenance, changed, path)
  if quarto.doc.is_format("html:js") then
    add_assets()
    local summary = get_summary(provenance, changed)
    local classes = get_classes("ck-provenance", provenance, changed)
    local out = pandoc.Blocks({
      pandoc.RawBlock(
        "html",
        '<details class="' .. classes .. '"><summary aria-label="'
          .. escape("Where " .. path .. " came from: "
            .. pandoc.utils.stringify(summary))
          .. '">' .. to_html({pandoc.Plain(summary)}) .. "</summary>"
      ),
    })
    out:extend(get_view(provenance, changed))
    out:insert(pandoc.RawBlock("html", "</details>"))
    return out
  end
  local line = provenance.line and inlines(provenance.line) or nil
  if changed then
    line = line or pandoc.Inlines({})
    if #line > 0 then
      line:insert(pandoc.Str(";"))
      line:insert(pandoc.Space())
    end
    line:extend(words("provenance recorded before " .. changed .. " changed"))
  end
  if line then
    return pandoc.Blocks({pandoc.Para({pandoc.Emph(line)})})
  end
  return pandoc.Blocks({})
end

local function unrecorded()
  if not quarto.doc.is_format("html:js") then
    return pandoc.Blocks({})
  end
  add_assets()
  return pandoc.Blocks({
    pandoc.RawBlock(
      "html",
      '<details class="ck-provenance ck-missing"><summary>'
        .. "⚠️ No provenance recorded</summary>"
    ),
    pandoc.Para({
      pandoc.Str("Render"), pandoc.Space(), pandoc.Str("with"),
      pandoc.Space(), pandoc.Code("calkit quarto render"),
      pandoc.Space(), pandoc.Str("or"), pandoc.Space(),
      pandoc.Code("calkit run"), pandoc.Str("."),
    }),
    pandoc.RawBlock("html", "</details>"),
  })
end

local function component_div(el, kind)
  local src = el.attributes.src or ""
  local path = normpath(src:gsub("^/+", ""))
  local data = load_records()
  local record = data and (data.components or {})[src] or nil
  local url = record and record.url or get_url(path)
  local out = pandoc.Blocks({})
  if kind == "figure" then
    out:extend(get_figure(
      el, pandoc.Blocks({pandoc.Plain({get_image(el, url)})})
    ))
  elseif kind == "table" then
    local content = get_table(path, el.attributes.rows)
    if el.identifier ~= "" or #el.content > 0 then
      -- Quarto's own form of a table with a caption, which it numbers
      local caption = pandoc.utils.blocks_to_inlines(el.content)
      local float = pandoc.Blocks({content[1]})
      if #caption > 0 then
        float:insert(pandoc.Para(caption))
      end
      out:insert(pandoc.Div(float, pandoc.Attr(el.identifier, {}, {})))
      for index = 2, #content do
        out:insert(content[index])
      end
    else
      out:extend(content)
    end
  else
    local _, ext = pandoc.path.split_extension(path)
    local text = MARKDOWN_EXTS[ext:lower()]
      and read_file(pandoc.path.join({find_project_dir(), path})) or nil
    local content = text and pandoc.read(text, "markdown").blocks
      or pandoc.Blocks({pandoc.Para({pandoc.Code(src)})})
    content:extend(el.content)
    out:insert(pandoc.Div(content, pandoc.Attr(el.identifier, {}, {})))
  end
  if is_off(el.attributes.provenance) then
    return out
  end
  if record == nil then
    if data then
      quarto.log.warning(
        "Calkit recorded no provenance for " .. src .. "; is it in a "
          .. "place 'calkit quarto render' doesn't look, e.g., an include?"
      )
    end
    out:extend(unrecorded())
  elseif record.provenance then
    local changed = get_changed(data, path, record.sha1)
    out:extend(get_provenance(record.provenance, changed, path))
  end
  return out
end

local function handle(el)
  for name, kind in pairs(KINDS) do
    if el.classes:includes(name) then
      el.classes = el.classes:filter(function(c) return c ~= name end)
      return component_div(el, kind)
    end
  end
  -- What these were called before, said rather than shown as a plain div
  if el.classes:includes("ckprovenance") then
    local body = pandoc.Blocks({
      pandoc.Para(words(
        "Use .ckfigure, .cktable, or .ckinclude rather than .ckprovenance."
      )),
    })
    body:extend(el.content)
    return pandoc.Div(
      body,
      pandoc.Attr("", {"callout-important"}, {{"title", "Not shown"}})
    )
  end
  return nil
end

return {{Div = handle}}
"""
)

# Shows a value with where it came from, marked as text a script makes a
# button opening a popover, except where a button can't go, saying what's
# wrong while it's closed, and shows only the value in other formats
VALUE_PROVENANCE_LUA = r"""
local n_popovers = 0
local function with_provenance(text, key, path, kwargs)
  local out = pandoc.Inlines({pandoc.Str(text)})
  local flag = pandoc.utils.stringify(kwargs.provenance or ""):lower()
  if flag == "false" or flag == "no" or flag == "0" or flag == "off"
    or not quarto.doc.is_format("html:js") then
    return out
  end
  local data = load_records()
  local record = data and (data.values or {})[key] or nil
  if record == nil or not record.provenance then
    return out
  end
  add_assets()
  local provenance = record.provenance
  local changed = get_changed(data, path, record.sha1)
  n_popovers = n_popovers + 1
  local id = "ck-value-" .. n_popovers
  local summary = get_summary(provenance, changed)
  local warn = provenance.state ~= "ok" or changed ~= nil
  local label = "Where " .. text .. " came from"
  if warn then
    label = label .. ": " .. pandoc.utils.stringify(summary)
  end
  -- Headed by what it is, e.g., its key in a file, which names it
  local view = get_view(provenance, changed)
  local content = pandoc.Blocks({})
  if #view > 0 then
    content:insert(pandoc.Div({view[1]}, pandoc.Attr(id .. "-title", {}, {})))
  end
  content:insert(pandoc.Para(summary))
  for index = 2, #view do
    content:insert(view[index])
  end
  quarto.doc.include_text(
    "after-body",
    '<div id="' .. id .. '" popover class="ck-popover" role="dialog" '
      .. 'aria-labelledby="' .. id .. '-title">' .. to_html(content)
      .. "</div>"
  )
  -- Flagged with CSS, so a title, which Quarto makes text, gets only the
  -- value
  local inner = pandoc.Inlines({pandoc.Str(text)})
  local classes = {"ck-value", "ck-" .. (provenance.state or "ok")}
  if changed then
    table.insert(classes, "ck-outdated")
  end
  if warn then
    table.insert(classes, "ck-flagged")
  end
  return pandoc.Inlines({pandoc.Span(inner, pandoc.Attr(
    "",
    classes,
    {
      {"data-ck-popover", id},
      {"data-ck-label", label},
      {"title", pandoc.utils.stringify(summary)},
    }
  ))})
end
"""

# Reads each value from its results file when the document renders, finding
# declared results' names in calkit.yaml, and formats it as Python would,
# which ``check_values`` makes sure of before the pipeline renders.
SHORTCODE_LUA = (
    r"""---@diagnostic disable: undefined-global
-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows values from pipeline results with
-- {{< ckvalue results/metrics.json key .2f >}}, read from the results file
-- each time the document renders.
"""
    + PROVENANCE_LUA_COMMON
    + VALUE_PROVENANCE_LUA
    + r"""
-- A number as YAML writes it, which Pandoc's metadata gives as text
local yaml_specials = {
  [".inf"] = math.huge, ["+.inf"] = math.huge, ["-.inf"] = -math.huge,
  [".nan"] = 0 / 0,
}
local function get_yaml_number(text)
  local special = yaml_specials[text:lower()]
  if special ~= nil then
    return special
  end
  if text:match("^[-+]?[%d_]+$") then
    return math.tointeger(tonumber((text:gsub("_", ""))))
  end
  if text:match("^[-+]?[%d_]*%.?[%d_]*[eE]?[-+]?%d*$") and text:match("%d") then
    return tonumber((text:gsub("_", "")))
  end
  return nil
end

-- Plain Lua values from Pandoc's metadata, which reads YAML
local function from_meta(value)
  local kind = pandoc.utils.type(value)
  if kind == "boolean" or kind == "string" or kind == "number" then
    return value
  end
  if kind == "List" then
    local out = {}
    for i, item in ipairs(value) do
      out[i] = from_meta(item)
    end
    return out
  end
  if kind == "table" or kind == "Meta" then
    local out = {}
    for k, item in pairs(value) do
      out[k] = from_meta(item)
    end
    return out
  end
  local text = pandoc.utils.stringify(value)
  local n = get_yaml_number(text)
  if n ~= nil then
    return n
  end
  return text
end

local function load_yaml(content)
  -- Pandoc only reads metadata starting on the first line
  content = content:gsub("^%s*\n", ""):gsub("^%-%-%-[^\n]*\n", "")
  local ok, doc = pcall(
    pandoc.read, "---\n" .. content .. "\n---\n", "markdown-smart"
  )
  if not ok then
    return nil
  end
  return from_meta(doc.meta)
end

-- TOML, which Quarto's Lua has no reader for, with dates kept as text
local function load_toml(text)
  local pos, len = 1, #text
  local root = {}
  local current = root
  -- Written this way so Calkit's Python source can hold it
  local triple_double = string.rep('"', 3)
  local escapes = {
    b = "\b", t = "\t", n = "\n", f = "\f", r = "\r",
    ['"'] = '"', ["\\"] = "\\",
  }
  local function fail(msg)
    error("TOML: " .. msg .. " at character " .. pos)
  end
  local function skip_space()
    pos = text:find("[^ \t]", pos) or len + 1
  end
  local function skip_blank()
    while pos <= len do
      local c = text:sub(pos, pos)
      if c == "#" then
        pos = (text:find("\n", pos, true) or len) + 1
      elseif c:match("[ \t\r\n]") then
        pos = pos + 1
      else
        return
      end
    end
  end
  -- Up to two quotes before a closing triple are the string's
  local function close_multiline(quote, out)
    local run = text:match("^" .. quote .. "+", pos)
    out[#out + 1] = string.rep(quote, math.min(#run - 3, 2))
    pos = pos + math.min(#run, 5)
  end
  local function skip_first_newline()
    if text:sub(pos, pos) == "\n" then
      pos = pos + 1
    elseif text:sub(pos, pos + 1) == "\r\n" then
      pos = pos + 2
    end
  end
  local function parse_basic(multiline)
    local out = {}
    if multiline then
      skip_first_newline()
    end
    while true do
      if pos > len then
        fail("unterminated string")
      end
      local c = text:sub(pos, pos)
      if multiline and text:sub(pos, pos + 2) == triple_double then
        close_multiline('"', out)
        return table.concat(out)
      elseif c == '"' and not multiline then
        pos = pos + 1
        return table.concat(out)
      elseif c == "\\" then
        local e = text:sub(pos + 1, pos + 1)
        if multiline and e:match("[ \t\r\n]") then
          pos = text:find("[^ \t\r\n]", pos + 1) or len + 1
        elseif escapes[e] then
          out[#out + 1] = escapes[e]
          pos = pos + 2
        elseif e == "u" or e == "U" then
          local n = e == "u" and 4 or 8
          local code = tonumber(text:sub(pos + 2, pos + 1 + n), 16)
          out[#out + 1] = utf8.char(code)
          pos = pos + 2 + n
        else
          fail("bad escape")
        end
      else
        out[#out + 1] = c
        pos = pos + 1
      end
    end
  end
  local function parse_literal(multiline)
    local quote = multiline and "'''" or "'"
    if multiline then
      skip_first_newline()
    end
    local stop = assert(
      text:find(quote, pos, true),
      "TOML: unterminated string at character " .. pos
    )
    local out = {text:sub(pos, stop - 1)}
    pos = stop
    if multiline then
      close_multiline("'", out)
    else
      pos = pos + 1
    end
    return table.concat(out)
  end
  local function parse_key()
    local parts = {}
    while true do
      skip_space()
      local c = text:sub(pos, pos)
      if c == '"' then
        pos = pos + 1
        parts[#parts + 1] = parse_basic(false)
      elseif c == "'" then
        pos = pos + 1
        parts[#parts + 1] = parse_literal(false)
      else
        local s, e = text:find("^[%w_%-]+", pos)
        if s == nil then
          fail("expected a key")
        end
        parts[#parts + 1] = text:sub(s, e)
        pos = e + 1
      end
      skip_space()
      if text:sub(pos, pos) ~= "." then
        return parts
      end
      pos = pos + 1
    end
  end
  -- The table at the first n parts of a dotted key, made if it isn't there,
  -- going into the last of an array of tables
  local function get_table(tbl, keys, n)
    for i = 1, n do
      if tbl[keys[i]] == nil then
        tbl[keys[i]] = {}
      end
      tbl = tbl[keys[i]]
      if #tbl > 0 and type(tbl[#tbl]) == "table" then
        tbl = tbl[#tbl]
      end
    end
    return tbl
  end
  local function expect(token)
    skip_space()
    if text:sub(pos, pos + #token - 1) ~= token then
      fail("expected " .. token)
    end
    pos = pos + #token
  end
  local parse_value
  local function parse_array()
    local items = {}
    while true do
      skip_blank()
      if text:sub(pos, pos) == "]" then
        pos = pos + 1
        return items
      end
      items[#items + 1] = parse_value()
      skip_blank()
      local c = text:sub(pos, pos)
      pos = pos + 1
      if c == "]" then
        return items
      elseif c ~= "," then
        fail("expected , or ]")
      end
    end
  end
  local function parse_inline_table()
    local tbl = {}
    while true do
      skip_blank()
      if text:sub(pos, pos) == "}" then
        pos = pos + 1
        return tbl
      end
      local keys = parse_key()
      expect("=")
      get_table(tbl, keys, #keys - 1)[keys[#keys]] = parse_value()
      skip_blank()
      local c = text:sub(pos, pos)
      pos = pos + 1
      if c == "}" then
        return tbl
      elseif c ~= "," then
        fail("expected , or }")
      end
    end
  end
  local specials = {
    ["true"] = true, ["false"] = false,
    inf = math.huge, ["+inf"] = math.huge, ["-inf"] = -math.huge,
    nan = 0 / 0, ["+nan"] = 0 / 0, ["-nan"] = 0 / 0,
  }
  local bases = {x = 16, o = 8, b = 2}
  parse_value = function()
    skip_space()
    local c = text:sub(pos, pos)
    if text:sub(pos, pos + 2) == triple_double then
      pos = pos + 3
      return parse_basic(true)
    elseif c == '"' then
      pos = pos + 1
      return parse_basic(false)
    elseif text:sub(pos, pos + 2) == "'''" then
      pos = pos + 3
      return parse_literal(true)
    elseif c == "'" then
      pos = pos + 1
      return parse_literal(false)
    elseif c == "[" then
      pos = pos + 1
      return parse_array()
    elseif c == "{" then
      pos = pos + 1
      return parse_inline_table()
    end
    local s, e = text:find("^[^%s,%]}#]+", pos)
    if s == nil then
      fail("expected a value")
    end
    -- A date and time can be separated by a space
    if text:sub(s, e):match("^%d%d%d%d%-%d%d%-%d%d$")
      and text:sub(e + 1, e + 4):match("^ %d%d:") then
      e = select(2, text:find("^[^%s,%]}#]+", e + 2))
    end
    local token = text:sub(s, e)
    pos = e + 1
    if specials[token] ~= nil then
      return specials[token]
    end
    local plain = token:gsub("_", "")
    local base = bases[plain:match("^0([xob])") or ""]
    if base ~= nil then
      return math.tointeger(tonumber(plain:sub(3), base))
    end
    return tonumber(plain) or token
  end
  while true do
    skip_blank()
    if pos > len then
      return root
    end
    if text:sub(pos, pos + 1) == "[[" then
      pos = pos + 2
      local keys = parse_key()
      expect("]]")
      local parent = get_table(root, keys, #keys - 1)
      local items = parent[keys[#keys]] or {}
      parent[keys[#keys]] = items
      current = {}
      items[#items + 1] = current
    elseif text:sub(pos, pos) == "[" then
      pos = pos + 1
      local keys = parse_key()
      expect("]")
      current = get_table(root, keys, #keys)
    else
      local keys = parse_key()
      expect("=")
      get_table(current, keys, #keys - 1)[keys[#keys]] = parse_value()
    end
  end
end

local project_dir = nil
local result_paths = nil
local data_by_path = {}

local function load_data(path)
  if data_by_path[path] == nil then
    local content = read_file(pandoc.path.join({project_dir, path}))
    if content == nil then
      return nil
    end
    local _, ext = pandoc.path.split_extension(path)
    ext = ext:lower()
    if ext == ".json" then
      data_by_path[path] = quarto.json.decode(content)
    elseif ext == ".toml" then
      local ok, data = pcall(load_toml, content)
      if not ok then
        quarto.log.warning("Can't read " .. path .. ": " .. data)
      end
      data_by_path[path] = ok and data or {}
    else
      data_by_path[path] = load_yaml(content) or {}
    end
  end
  return data_by_path[path]
end

-- A results file by declared name in calkit.yaml, or else as a path
local function get_results_path(source, kind)
  if result_paths == nil then
    result_paths = {}
    local content = read_file(pandoc.path.join({project_dir, "calkit.yaml"}))
    local info = content and load_yaml(content) or {}
    for _, result in ipairs(info.results or {}) do
      if type(result) == "table" and result.name and result.path then
        result_paths[result.name] = result.path
      end
    end
  end
  local path = source
  if kind ~= "path" and result_paths[source] ~= nil then
    path = result_paths[source]
  end
  -- A notebook stands for the values the pipeline saves from its cells
  if path:lower():match("%.ipynb$") then
    path = ".calkit/notebooks/outputs/" .. normpath(path) .. "/values.json"
  end
  -- As Calkit records it, e.g., without a leading ./, and an absolute
  -- path still absolute
  local absolute = path:match("^[/\\]") ~= nil
  path = normpath(path)
  return absolute and "/" .. path or path
end

-- A dotted key, e.g., fit.coeffs.0, with numbers indexing lists from 0
local function lookup(data, key)
  local value = data
  for part in string.gmatch(key, "[^.]+") do
    if type(value) ~= "table" then
      return nil
    end
    local index = tonumber(part)
    if value[part] ~= nil then
      value = value[part]
    elseif index ~= nil and math.type(index) == "integer" and #value > 0 then
      value = value[index < 0 and #value + index + 1 or index + 1]
    else
      return nil
    end
  end
  return value
end

-- A float as Python's repr writes it, which is how JSON does
local function repr_float(v)
  if v ~= v then
    return "NaN"
  elseif v == math.huge then
    return "Infinity"
  elseif v == -math.huge then
    return "-Infinity"
  end
  local s
  for p = 0, 16 do
    s = string.format("%." .. p .. "e", v)
    if tonumber(s) == v then
      break
    end
  end
  local sign, int, frac, exp_text = s:match("^(-?)(%d)%.?(%d*)e([-+]%d+)$")
  local exp = tonumber(exp_text) or 0
  local digits = (int .. frac):gsub("0+$", "")
  if digits == "" then
    digits = "0"
  end
  if exp < -4 or exp >= 16 then
    local mantissa = digits:sub(1, 1)
    if #digits > 1 then
      mantissa = mantissa .. "." .. digits:sub(2)
    end
    return sign .. mantissa .. string.format(
      "e%s%02d", exp < 0 and "-" or "+", math.abs(exp)
    )
  elseif exp < 0 then
    return sign .. "0." .. string.rep("0", -exp - 1) .. digits
  elseif #digits <= exp + 1 then
    return sign .. digits .. string.rep("0", exp + 1 - #digits) .. ".0"
  end
  return sign .. digits:sub(1, exp + 1) .. "." .. digits:sub(exp + 2)
end

-- A value as JSON writes it
local function to_text(value)
  if type(value) == "string" then
    return value
  elseif type(value) == "boolean" then
    return tostring(value)
  elseif math.type(value) == "integer" then
    return tostring(value)
  elseif type(value) == "number" then
    return repr_float(value)
  end
  return quarto.json.encode(value)
end

local function group_digits(text, sep)
  local pre, int, post = text:match("^(%D*)(%d+)(.*)$")
  if int == nil then
    return text
  end
  int = int:reverse():gsub("(%d%d%d)", "%1" .. sep):reverse()
  return pre .. int:gsub("^%" .. sep, "") .. post
end

-- A value with one spec of Python's format mini-language
local function format_spec(value, spec)
  local sign, sep, prec, kind = spec:match(
    "^([+%-]?)([,_]?)%.?(%d*)([fFeEgGd%%s]?)$"
  )
  if sign == nil then
    return nil
  end
  if sign == "-" then
    sign = ""
  end
  local text
  if kind == "s" or (kind == "" and type(value) ~= "number") then
    text = to_text(value)
  else
    local n = tonumber(value)
    if n == nil then
      return nil
    end
    if prec == "" then
      prec = "6"
    end
    if kind == "" then
      text = (sign ~= "" and n >= 0 and sign or "") .. to_text(n)
    elseif kind == "d" then
      text = string.format("%" .. sign .. "d", n)
    elseif kind == "%" then
      text = string.format("%" .. sign .. "." .. prec .. "f", n * 100) .. "%"
    else
      text = string.format("%" .. sign .. "." .. prec .. kind, n)
    end
  end
  if sep ~= "" then
    text = group_digits(text, sep)
  end
  return text
end

-- A value with a format as Calkit takes one: a bare spec, e.g., .2f, or a
-- template with fields, e.g., {value:.1f} m/s
local function format_value(value, fmt)
  if fmt == "" then
    return to_text(value)
  end
  if not fmt:find("{", 1, true) then
    return format_spec(value, fmt)
  end
  local ok = true
  local text = fmt:gsub("{([^{}]*)}", function(field)
    local spec = field:match("^[%w_]*:?(.*)$")
    local formatted = format_spec(value, spec or "")
    if formatted == nil then
      ok = false
      return ""
    end
    return formatted
  end)
  return ok and text or nil
end

return {
  ["ckvalue"] = function(args, kwargs)
    if project_dir == nil then
      project_dir = find_project_dir()
    end
    local slots = {"", "", ""}
    for i = 1, math.min(#args, 3) do
      slots[i] = pandoc.utils.stringify(args[i])
    end
    local kind = ""
    for name, slot in pairs({name = 1, path = 1, key = 2, format = 3}) do
      local value = pandoc.utils.stringify(kwargs[name] or "")
      if value ~= "" then
        slots[slot] = value
        if slot == 1 then
          kind = name
        end
      end
    end
    local source, key, fmt = slots[1], slots[2], slots[3]
    local path = get_results_path(source, kind)
    local data = load_data(path)
    if data == nil then
      quarto.log.warning(
        "Results file " .. path .. " for ckvalue " .. key
          .. " doesn't exist; run the pipeline to make it"
      )
      return pandoc.Str("??")
    end
    local value = lookup(data, key)
    local text = value ~= nil and format_value(value, fmt) or nil
    if text == nil then
      quarto.log.warning(
        "Can't show ckvalue " .. source .. " " .. key .. " " .. fmt
      )
      return pandoc.Str("??")
    end
    return with_provenance(text, path .. ":" .. key, path, kwargs)
  end,
  -- A value quoted from a reference: its citation key, its name, and
  -- optionally a format, from the file Calkit writes them all to
  ["ckrefval"] = function(args, kwargs)
    if project_dir == nil then
      project_dir = find_project_dir()
    end
    local slots = {"", "", ""}
    for i = 1, math.min(#args, 3) do
      slots[i] = pandoc.utils.stringify(args[i])
    end
    -- The name and format can be given by name, as for ckvalue
    for name, slot in pairs({key = 2, format = 3}) do
      local value = pandoc.utils.stringify(kwargs[name] or "")
      if value ~= "" then
        slots[slot] = value
      end
    end
    local key, name, fmt = slots[1], slots[2], slots[3]
    -- One file per reference, named for its key percent-encoded, as
    -- Python's urllib.parse.quote(key, safe="") writes it
    local file = key:gsub("[^A-Za-z0-9_%.~%-]", function(c)
      return string.format("%%%02X", string.byte(c))
    end)
    local values_path = ".calkit/reference-values/" .. file .. ".json"
    local data = load_data(values_path)
    local value = nil
    if type(data) == "table" then
      value = data[name]
    end
    if value == nil then
      quarto.log.warning(
        "calkit.yaml records no value " .. name .. " quoted from " .. key
      )
      return pandoc.Str("??")
    end
    local text = format_value(value, fmt)
    if text == nil then
      quarto.log.warning(
        "Can't show ckrefval " .. key .. " " .. name .. " " .. fmt
      )
      return pandoc.Str("??")
    end
    return with_provenance(
      text, "ref:" .. key .. ":" .. name, values_path, kwargs
    )
  end,
}
"""
)


# Where Calkit writes where each document's components and values came
# from, for what renders it to read, relative to the project
PROVENANCE_DIR = ".calkit/local/provenance"
# What a document lists to run the filter, before Quarto's own filters
FILTER_CONFIG = "filters:\n  - at: pre-ast\n    path: calkit\n"


@dataclass(frozen=True)
class QuartoValue:
    """One value a Quarto document shows with the ``ckvalue`` shortcode."""

    # A results file or a declared result's name, as written
    source: str
    key: str
    format: str | None
    # The results file it reads, relative to the project
    path: str
    # 1-indexed line of the document, or of the cell in a notebook
    line: int = 0
    # For a value quoted from a reference, its citation key and name
    ref: tuple[str, str] | None = None
    # Whether to show where it came from
    provenance: bool = True


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


def _split_provenance_arg(args: str) -> tuple[str, bool]:
    """A shortcode's arguments without ``provenance=false``, which turns
    off showing where its value came from, and whether it's shown."""
    m = re.search(r"(^|\s)provenance=(['\"]?)(\w+)\2(?=\s|$)", args)
    if m is None:
        return args, True
    rest = (args[: m.start()] + args[m.end() :]).strip()
    return rest, m.group(3).lower() not in ("false", "no", "0", "off")


def extract_values(
    text: str, document_path: str, results: dict[str, str] | None = None
) -> list[QuartoValue]:
    """Find the ``ckvalue`` shortcodes in a document, in order.

    Their arguments read the way the Markdown marker's do: a results file
    or a declared result's name, a key, and optionally a format, each
    positionally or by name. A malformed one raises
    ``calkit.markdown.MarkdownParseError`` naming its line.
    """
    from calkit.markdown import (
        MarkdownParseError,
        _ckvalue_args,
        _resolve_source,
    )
    from calkit.references.values import get_values_path

    path = Path(document_path).as_posix()
    values = []
    for i, line in enumerate(text.splitlines()):
        found = []
        for m in _SHORTCODE_RE.finditer(line):
            args, provenance = _split_provenance_arg(m.group("args"))
            got = _ckvalue_args(args, path, i + 1)
            found.append(
                (
                    m.start(),
                    QuartoValue(
                        source=got["source"],
                        key=got["key"],
                        format=got.get("format"),
                        # Normalized as the extension finds it
                        path=posixpath.normpath(
                            _resolve_source(
                                got["source"],
                                results,
                                path,
                                i + 1,
                                kind=got["kind"],
                            ).replace("\\", "/")
                        ),
                        line=i + 1,
                        provenance=provenance,
                    ),
                )
            )
        # A citation key, a name, and a format, read the same way
        for m in _REFVAL_SHORTCODE_RE.finditer(line):
            args, provenance = _split_provenance_arg(m.group("args"))
            got = _ckvalue_args(args, path, i + 1)
            if got["kind"]:
                raise MarkdownParseError(
                    f"'ckrefval' takes a citation key and a name, not "
                    f"{got['kind']}=",
                    path=path,
                    line=i + 1,
                )
            found.append(
                (
                    m.start(),
                    QuartoValue(
                        source=got["source"],
                        key=got["key"],
                        format=got.get("format"),
                        path=get_values_path(got["source"]),
                        line=i + 1,
                        ref=(got["source"], got["key"]),
                        provenance=provenance,
                    ),
                )
            )
        values += [value for _, value in sorted(found, key=lambda f: f[0])]
    return values


def extract_embedded_paths(
    text: str, document_path: str, wdir: str | None = None
) -> list[str]:
    """The documents a document embeds cells' outputs from, in order, as
    POSIX paths relative to ``wdir``, like ``document_path``.

    Quarto reads an embedded path relative to the document, or to the
    Quarto project if it starts with a ``/``.
    """
    document_path = posixpath.normpath(Path(document_path).as_posix())
    paths = []
    for m in _EMBED_RE.finditer(text):
        path = m.group("path")
        if path.startswith("/"):
            base = get_quarto_dir(document_path, wdir)
            path = path.lstrip("/")
        else:
            base = posixpath.dirname(document_path)
        path = posixpath.normpath(posixpath.join(base, path))
        if path not in paths:
            paths.append(path)
    return paths


def check_values(
    values: list[QuartoValue], document_path: str, wdir: str | None = None
) -> list[str]:
    """Each value's text, as the shortcode shows it when the document
    renders, checking it can.

    A missing or unreadable results file, a missing key, or a format the
    shortcode can't apply the way Python does raises
    ``calkit.markdown.MarkdownParseError`` naming the shortcode's line.
    """
    from calkit.markdown import (
        MarkdownParseError,
        _ck_format,
        format_value,
    )
    from calkit.notebooks import get_notebook_of_values_path
    from calkit.questions import resolve_key
    from calkit.results import load_result

    def check_format(value: QuartoValue) -> None:
        fmt = value.format or ""
        fields = _FORMAT_FIELD_RE.findall(fmt) if "{" in fmt else [":" + fmt]
        rest = _FORMAT_FIELD_RE.sub("", fmt)
        for field in fields:
            name, _, spec = field.partition(":")
            if (
                name not in ("", "0", "value")
                or not FORMAT_SPEC_RE.match(spec)
                or "{" in rest
                or "}" in rest
            ):
                raise MarkdownParseError(
                    f"'ckvalue' can't format with '{fmt}' in a Quarto "
                    "document; it takes a sign, a ',' or '_' separator, "
                    "and a precision and type, e.g., '.2f', ',d', '.1%', "
                    "or '{value:.1f} m/s'",
                    path=document_path,
                    line=value.line,
                )

    data_by_path: dict[str, Any] = {}
    texts = []
    for value in values:
        check_format(value)
        fpath = os.path.join(wdir, value.path) if wdir else value.path
        if value.ref is not None and not os.path.isfile(fpath):
            raise MarkdownParseError(
                f"calkit.yaml records no value '{value.ref[1]}' quoted "
                f"from '{value.ref[0]}'",
                path=document_path,
                line=value.line,
            )
        if value.path not in data_by_path:
            if not os.path.isfile(fpath):
                notebook_path = get_notebook_of_values_path(value.path)
                raise MarkdownParseError(
                    f"No values saved from {notebook_path} yet; add "
                    f"'{value.key}' as a cell output and run the pipeline"
                    if notebook_path
                    else f"Results file '{value.path}' for value "
                    f"'{value.key}' doesn't exist; is it an output of a "
                    "stage that has run?",
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
            raw = resolve_key(data_by_path[value.path], value.key)
        except KeyError:
            raise MarkdownParseError(
                f"calkit.yaml records no value '{value.ref[1]}' quoted "
                f"from '{value.ref[0]}'"
                if value.ref is not None
                else f"'{value.path}' has no key '{value.key}'",
                path=document_path,
                line=value.line,
            )
        problem = None
        if isinstance(raw, (dict, list)):
            problem = "is a list or table, not one value; name a key in it"
        elif isinstance(raw, str) and value.path.lower().endswith(
            (".yaml", ".yml")
        ):
            if re.fullmatch(
                r"(?=\D*\d)[-+]?[\d_]*\.?[\d_]*([eE][-+]?\d+)?"
                r"|[-+]?\.(inf|nan)",
                raw,
                flags=re.IGNORECASE,
            ):
                problem = (
                    "is text that looks like a number, which reads as one "
                    "from YAML in a Quarto document"
                )
            elif _YAML_MARKDOWN_RE.search(raw):
                problem = (
                    "is text that reads as Markdown from YAML in a Quarto "
                    "document, so it wouldn't show as written"
                )
            if problem is not None:
                problem += "; keep it in a JSON or TOML results file"
        if problem is not None:
            raise MarkdownParseError(
                f"'{value.key}' in '{value.path}' {problem}",
                path=document_path,
                line=value.line,
            )
        try:
            texts.append(format_value(raw, _ck_format(value.format)))
        except (ValueError, TypeError) as e:
            raise MarkdownParseError(
                f"Can't format '{value.key}' in '{value.path}' with "
                f"'{value.format}': {e}",
                path=document_path,
                line=value.line,
            )
    return texts


def get_quarto_dir(document_path: str, wdir: str | None = None) -> str:
    """Where Quarto looks for the extension for a document: the nearest
    folder at or above it with a ``_quarto.yml``, i.e., its Quarto
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


def write_components(document_path: str, wdir: str | None = None) -> None:
    """Write the extension for a document, leaving files whose content is
    already right alone so their timestamps don't change.

    It's the same for every document, so it's written whenever the pipeline
    is compiled and kept in Git.
    """
    ext_dir = get_extension_dir(document_path, wdir)
    contents = {
        posixpath.join(ext_dir, "_extension.yml"): EXTENSION_YML,
        posixpath.join(ext_dir, "calkit.lua"): SHORTCODE_LUA,
        posixpath.join(ext_dir, "provenance.lua"): PROVENANCE_LUA,
        posixpath.join(ext_dir, "provenance.js"): PROVENANCE_JS,
    }
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


# What each component's class, or directive in MyST, shows its file as, as
# LaTeX's \ckfigure, \cktable, and \ckinclude do
COMPONENT_KINDS = {
    "ckfigure": "figure",
    "cktable": "table",
    "ckinclude": "include",
}
TABLE_DELIMITERS = {".csv": ",", ".tsv": "\t"}
# Rows of a table shown before it's cut short, unless it says with rows=
TABLE_ROW_LIMIT = 25
# What a component is called where its provenance is described
_NOUNS = {"figure": "Figure", "table": "Table", "include": "File"}
# Files an included one is read as Markdown from
MARKDOWN_EXTS = (".md", ".qmd")
# A fenced div's opening line, e.g., ::: {.ckfigure src="a.png"}, or
# ::: name, which Pandoc reads as a class, optionally with colons after
_DIV_OPEN_RE = re.compile(
    r"^\s*(?:>\s*)*:{3,}\s*(?:\{(?P<attrs>[^}]*)\}|(?P<cls>[\w-]+))"
    r"(?:\s*:+)?\s*$"
)
_DIV_ATTR_RE = re.compile(
    r"\.(?P<cls>[\w-]+)|#(?P<id>[\w:.-]+)"
    r"|(?P<key>[\w-]+)=(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<bare>\S+))"
)
_CODE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass(frozen=True)
class Component:
    """A figure, table, or other file from the project a document shows,
    with a ``ckfigure``, ``cktable``, or ``ckinclude`` div or directive.
    """

    # 'figure', 'table', or 'include'
    kind: str
    # The file as written, relative to the project
    src: str
    # That file, normalized
    path: str
    # What it's referred to by, e.g., fig-fit, if anything
    label: str = ""
    # 1-indexed line of the document
    line: int = 0
    rows: int = TABLE_ROW_LIMIT
    # Whether to show where it came from
    provenance: bool = True


def has_components(text: str) -> bool:
    """Whether a document's text might show any components, to skip the
    rest cheaply."""
    return any(name in text for name in COMPONENT_KINDS)


def get_component(
    name: str, src: str, options: dict[str, str], line: int = 0
) -> Component | None:
    """A component from its class or directive name, the file it names,
    relative to the project, and its options, or None for another name or
    no file.
    """
    kind = COMPONENT_KINDS.get(name)
    src = src.strip()
    if kind is None or not src:
        return None
    try:
        rows = int(options.get("rows", TABLE_ROW_LIMIT))
    except ValueError:
        rows = TABLE_ROW_LIMIT
    return Component(
        kind=kind,
        src=src,
        path=posixpath.normpath(src.replace("\\", "/").lstrip("/")),
        label=options.get("label") or options.get("name") or "",
        line=line,
        rows=rows,
        provenance=str(options.get("provenance", "true")).strip().lower()
        not in ("false", "no", "0", "off"),
    )


def get_value_key(value: QuartoValue) -> str:
    """What a value's provenance is recorded under, as what shows it looks
    it up: its results file and key, or its reference's key and name."""
    if value.ref is not None:
        return f"ref:{value.ref[0]}:{value.ref[1]}"
    return f"{value.path}:{value.key}"


def extract_components(text: str) -> list[Component]:
    """Find the ``ckfigure``, ``cktable``, and ``ckinclude`` divs in a
    Quarto document, in order, skipping those in code blocks.

    Each names its file with ``src``, relative to the project, as
    ``ckvalue`` does, and its id is what it's referred to by.
    """
    divs = []
    fence = None
    for i, line in enumerate(text.splitlines()):
        m = _CODE_FENCE_RE.match(line)
        if m is not None:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif line.strip() == marker[0] * len(line.strip()) and len(
                line.strip()
            ) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        m = _DIV_OPEN_RE.match(line)
        if m is None:
            continue
        classes = [m.group("cls")] if m.group("cls") else []
        attrs: dict[str, str] = {}
        for a in _DIV_ATTR_RE.finditer(m.group("attrs") or ""):
            if a.group("cls"):
                classes.append(a.group("cls"))
            elif a.group("id"):
                attrs["label"] = a.group("id")
            elif a.group("key"):
                attrs[a.group("key")] = next(
                    v for v in a.group("dq", "sq", "bare") if v is not None
                )
        for name in classes:
            component = get_component(
                name, attrs.get("src", ""), attrs, line=i + 1
            )
            if component is not None:
                divs.append(component)
                break
    return divs


def get_stage_status(stage: Any) -> dict:
    """How a DVC stage stands against what ``dvc.lock`` recorded, as the
    hub gives a stage's status, from DVC's own checks, so what it reads or
    makes being added or removed, ``.dvcignore``, and an iterated stage's
    command count, and hashes DVC has already computed are reused.

    ``Stage.status`` asserts the repo lock is held, which ``dvc repro``
    holds while a stage runs, so the checks it makes are called directly;
    they only read. Paths are as DVC names them, i.e., relative to the
    working directory.
    """
    found: list = []
    if not stage.frozen:
        stage._status_deps(found)
    stage._status_outs(found, filter_info=None)
    stage._status_always_changed(found)
    stage._status_stage(found)
    modified_inputs = []
    modified_outputs = []
    missing_outputs = []
    for item in found:
        if not isinstance(item, dict):
            continue
        for path, change in (item.get("changed deps") or {}).items():
            modified_inputs.append(Path(path).as_posix())
        for path, change in (item.get("changed outs") or {}).items():
            path = Path(path).as_posix()
            if change == "deleted":
                missing_outputs.append(path)
            elif change != "not in cache":
                modified_outputs.append(path)
    modified_command = any(
        item in ("changed command", "changed checksum") for item in found
    )
    stale = (
        modified_inputs
        or modified_outputs
        or missing_outputs
        or modified_command
    )
    return {
        "status": (
            "stale"
            if stale
            else "always-run"
            if "always changed" in found
            else "up-to-date"
        ),
        "modified_command": modified_command,
        "modified_inputs": modified_inputs,
        "modified_outputs": modified_outputs,
        "missing_outputs": missing_outputs,
    }


def get_provenance_records(
    components: list[Component],
    document_path: str,
    ck_info: dict,
    dvc_yaml: dict,
    dvc_lock: dict,
    stage_runs: dict,
    get_stage_status: Callable[[str], dict],
    is_file: Callable[[str], bool],
    is_dir: Callable[[str], bool],
    listdir: Callable[[str], list[str]],
    read_bytes: Callable[[str], bytes],
    values: list[QuartoValue] | None = None,
    get_file_url: Callable[[str, str | None], str | None] = (
        lambda path, commit_sha: None
    ),
    check_reference_value: Callable[[str, str], tuple[bool, str | None]] = (
        lambda key, name: (False, None)
    ),
    document_stage: str | None = None,
) -> dict:
    """What a document shows for each of its components, keyed by the
    file as written, as nodes that what renders the document turns into
    its own, e.g., Pandoc's AST: what to show it as, e.g., a table's rows,
    and, unless it's turned off for it or the project, its provenance.

    Its provenance is a line saying whether it's up to date per
    ``dvc.lock``, or what's wrong if not, shown even while what's behind it
    is collapsed, a short line for formats that can't expand, and how it
    came to be: a graph of the stages it's made from, however far back,
    and each one's kind, environment, script or command, last run, every
    input, and the outputs on the way to it.

    The document's own outputs aren't checked, since it can't say whether
    what's being rendered is up to date, and neither is when its stage last
    ran. Stages are checked with ``get_stage_status``, which gives a stage
    in ``dvc.lock``'s status, as ``get_stage_status`` does, or a file's
    ``.dvc`` file's, named for it.
    Values, from ``ckvalue`` and ``ckrefval``, are keyed as
    ``get_value_key`` says, and a value quoted from a reference describes
    the reference rather than a pipeline, with whether it matched the
    reference's PDF, per ``check_reference_value``, which says whether it
    was checked and what's wrong if anything.
    ``get_file_url`` gives a link to a file in Git, at a commit, or the
    current one if None, if there's a host to link to, which is also taken
    to mean it's in Git. The other functions read the project, as for
    ``calkit.provenance.get_path_provenance``. Each file shown is recorded
    with its SHA-1, so what shows it can tell it changed since.
    ``document_stage`` names the stage that renders the document, which is
    otherwise its Quarto stage, if any.
    """
    import hashlib

    import calkit.dvc
    import calkit.pipeline
    from calkit.notebooks import get_notebook_of_values_path
    from calkit.provenance import (
        SOURCE_FIELDS,
        get_path_provenance,
        how_to_define_origin,
    )
    from calkit.references.values import iter_declared_values

    # The nodes what renders it reads, named as MyST's are
    def make_text(value: str) -> dict:
        return {"type": "text", "value": value}

    def make_strong(value: str) -> dict:
        return {"type": "strong", "children": [make_text(value)]}

    def make_emphasis(value: str) -> dict:
        return {"type": "emphasis", "children": [make_text(value)]}

    def make_code(value: str) -> dict:
        return {"type": "inlineCode", "value": value}

    def make_link(url: str, *children: dict) -> dict:
        return {"type": "link", "url": url, "children": list(children)}

    def make_paragraph(*children: dict) -> dict:
        return {"type": "paragraph", "children": list(children)}

    def make_row(*cells: list[dict], header: bool = False) -> dict:
        return {
            "type": "tableRow",
            "children": [
                {"type": "tableCell", "header": header, "children": cell}
                for cell in cells
            ],
        }

    def under(path: str, parent: str) -> bool:
        return path == parent or path.startswith(parent.rstrip("/") + "/")

    def get_paths(items: list | None, wdir: str) -> list[str]:
        out = []
        for item in items or []:
            if isinstance(item, dict):
                item = item.get("path") or next(iter(item), None)
            if isinstance(item, str) and "${" not in item:
                out.append(posixpath.normpath(posixpath.join(wdir, item)))
        return out

    def exists(path: str) -> bool:
        return is_file(path) or is_dir(path)

    def is_bookkeeping(path: str) -> bool:
        # E.g., environment locks, which a stage's environment names
        return path.startswith(".calkit/") or path == "calkit.yaml"

    def get_producer(path: str) -> str | None:
        exact = [n for n, (_, outs) in stages.items() if path in outs]
        inside = [
            n
            for n, (_, outs) in stages.items()
            if any(under(path, out) for out in outs)
        ]
        return (exact + inside)[0] if exact or inside else None

    def get_status(name: str) -> dict:
        if name not in statuses:
            if name in lock_stages:
                statuses[name] = get_stage_status(name)
            else:
                statuses[name] = {
                    "status": "not-run",
                    "modified_command": False,
                    "modified_inputs": [],
                    "modified_outputs": [],
                    "missing_outputs": [],
                }
        return statuses[name]

    def get_waiting(name: str) -> list[str]:
        # Inputs made by stages that aren't up to date, however far back
        if name not in waiting:
            # Guarding against a cycle
            waiting[name] = []
            found = []
            for dep in stages[name][0]:
                producer = get_producer(dep)
                if (
                    producer is not None
                    and producer != name
                    and not is_bookkeeping(dep)
                    and (
                        get_status(producer)["status"] in ("stale", "not-run")
                        or get_waiting(producer)
                    )
                ):
                    found.append(dep)
            waiting[name] = found
        return waiting[name]

    def get_output_state(path: str, stage: str) -> tuple[str, str]:
        # A state, i.e., 'ok', 'stale', 'waiting', 'missing', or 'not-run',
        # and how it reads
        status = get_status(stage)
        if status["status"] == "not-run":
            return "not-run", f"stage {stage} not run"
        if not exists(path):
            return "missing", "missing"
        if status["status"] == "stale":
            if any(under(path, p) for p in status["modified_outputs"]):
                return "stale", "modified outside pipeline"
            if status["modified_inputs"]:
                return "stale", ", ".join(
                    p + (" modified" if exists(p) else " missing")
                    for p in status["modified_inputs"]
                )
            if status["modified_command"]:
                return "stale", f"stage {stage} command modified"
            return "stale", f"stage {stage} out of date"
        if get_waiting(stage):
            return "waiting", "waiting on " + ", ".join(get_waiting(stage))
        return "ok", "up to date"

    def get_closure(roots: list[str]) -> list[str]:
        # The stages that make the roots, however far back, upstream first
        order: list[str] = []

        def visit(name: str) -> None:
            if name in order or name in visiting:
                return
            visiting.add(name)
            for dep in stages[name][0]:
                producer = get_producer(dep)
                if producer is not None and not is_bookkeeping(dep):
                    visit(producer)
            order.append(name)

        visiting: set[str] = set()
        for root in roots:
            producer = get_producer(root)
            if producer is not None:
                visit(producer)
        return order

    def get_run(stage: str) -> dict | None:
        # The record of the run that made what dvc.lock says it made
        run = stage_runs.get(stage)
        lock_stage = lock_stages.get(stage)
        if (
            isinstance(run, dict)
            and lock_stage is not None
            and run.get("dvc_lock_hash")
            == calkit.dvc.stage_lock_hash(lock_stage)
        ):
            return run
        return None

    def get_path_nodes(path: str, commit_sha: str | None) -> list[dict]:
        # A file, linked to where it's shown in the document, or on the
        # repo's host if it's in Git, or with its hash if DVC stores it
        if path in labels:
            return [make_link("#" + labels[path], make_code(path))]
        url = get_file_url(path, commit_sha)
        if url:
            return [make_link(url, make_code(path))]
        if lock_md5s.get(path) and (
            path in dvc_cached or is_file(path + ".dvc")
        ):
            return [
                make_code(path),
                make_text(f" (DVC md5 {lock_md5s[path][:7]})"),
            ]
        return [make_code(path)]

    def get_environment_nodes(stage: str) -> list[dict]:
        ck_stage = ck_stages.get(stage.split("@")[0]) or {}
        env_name = ck_stage.get("environment")
        if not isinstance(env_name, str) or not env_name:
            return []
        if env_name == "_system":
            return [make_code(env_name), make_text(", i.e., none")]
        kinds = [
            str((envs.get(name) or {}).get("kind") or "")
            for name in env_name.split(":")
        ]
        nodes = [make_code(env_name)]
        if any(kinds):
            nodes.append(make_text(f" ({', '.join(k for k in kinds if k)})"))
        return nodes

    def get_origin_nodes(path: str, gaps: list[dict]) -> list[dict]:
        # Where a file no stage makes came from, or that nothing says
        if any(under(path, g["path"]) or under(g["path"], path) for g in gaps):
            return [make_text("❔ origin not defined")]
        prov = get_path_provenance(
            path,
            ck_info=ck_info,
            dvc_yaml={"stages": yaml_stages},
            dvc_lock={"stages": lock_stages},
            stage_statuses={},
            is_file=is_file,
            is_dir=is_dir,
            listdir=listdir,
            read_bytes=read_bytes,
        )
        if not prov["origin"]:
            return []
        if prov["origin_url"]:
            return [make_link(prov["origin_url"], make_text(prov["origin"]))]
        return [make_text(prov["origin"])]

    def get_graph(order: list[str], target: str, on_path: set[str]) -> dict:
        # The stages it's made from, between what each reads and makes on
        # the way to it, colored by state
        lines = ["flowchart LR"]
        ids: dict[str, str] = {}

        def get_id(path: str) -> str:
            if path not in ids:
                ids[path] = f"f{len(ids)}"
                label = path.replace('"', "#quot;")
                producer = get_producer(path)
                style = ""
                if producer is not None:
                    state = get_output_state(path, producer)[0]
                    style = {"ok": "ok", "waiting": "waiting"}.get(
                        state, "stale"
                    )
                lines.append(
                    f'  {ids[path]}("{label}")'
                    + (f":::{style}" if style else "")
                )
                if path == target:
                    lines.append(f"  class {ids[path]} target")
            return ids[path]

        for i, name in enumerate(order):
            stage_id = f"s{i}"
            lines.append(f'  {stage_id}[["{name}"]]')
            for dep in stages[name][0]:
                if not is_bookkeeping(dep):
                    lines.append(f"  {get_id(dep)} --> {stage_id}")
            for out in stages[name][1]:
                if out in on_path or any(under(p, out) for p in on_path):
                    lines.append(f"  {stage_id} --> {get_id(out)}")
        lines += [
            "  classDef ok fill:#e6f4ea,stroke:#1e8e3e,color:#1f1f1f",
            "  classDef stale fill:#fce8e6,stroke:#d93025,color:#1f1f1f",
            "  classDef waiting fill:#fef7e0,stroke:#f9ab00,color:#1f1f1f",
            "  classDef target stroke-width:3px",
        ]
        return {"type": "mermaid", "value": "\n".join(lines)}

    def get_stage_blocks(
        name: str, on_path: set[str], gaps: list[dict]
    ) -> list[dict]:
        # One stage on the way to it: what it is, what it runs, where, when
        # it last ran, everything it reads, and what it makes on the way
        ck_stage = ck_stages.get(name.split("@")[0]) or {}
        run = get_run(name)
        commit_sha = (
            str(run["git_rev"]) if run and run.get("git_rev") else None
        )
        head = [make_strong("Stage"), make_text(" "), make_code(name)]
        if ck_stage.get("kind"):
            head.append(make_text(f" ({ck_stage['kind']})"))
        env_nodes = get_environment_nodes(name)
        if env_nodes:
            head += [make_text(", environment "), *env_nodes]
        blocks = [make_paragraph(*head)]
        wdir = ck_stage.get("wdir") or ""
        field = next((f for f in SOURCE_FIELDS if ck_stage.get(f)), None)
        if field is not None:
            source = posixpath.normpath(posixpath.join(wdir, ck_stage[field]))
            blocks.append(
                make_paragraph(
                    make_text("Runs "), *get_path_nodes(source, commit_sha)
                )
            )
        elif isinstance(ck_stage.get("command"), str):
            blocks.append(
                make_paragraph(
                    make_text("Runs "), make_code(ck_stage["command"])
                )
            )
        if run is not None:
            system = run.get("system") or {}
            parts = [str(run.get("start_time") or "")[:10]] + [
                " ".join(
                    str(system[k]) for k in ("os", "machine") if system.get(k)
                )
            ]
            nodes = [make_text("Last run " + ", ".join(p for p in parts if p))]
            # Runs come before the commit that records them, so the commit
            # they ran after is said, whether or not the tree was clean
            if commit_sha:
                nodes += [
                    make_text(", after commit "),
                    make_code(commit_sha[:7]),
                ]
            blocks.append(make_paragraph(*nodes))
        elif name in lock_stages:
            blocks.append(
                make_paragraph(
                    make_text("Last run not recorded for its current outputs")
                )
            )
        status = get_status(name)
        rows = [
            make_row(
                [make_strong("Input")],
                [make_strong("From")],
                [make_strong("State")],
                header=True,
            )
        ]
        for dep in stages[name][0]:
            if is_bookkeeping(dep):
                continue
            producer = get_producer(dep)
            if any(under(dep, p) for p in status["modified_inputs"]):
                state = "⚠️ modified" if exists(dep) else "⛔ missing"
            elif (
                producer is not None
                and get_output_state(dep, producer)[0] != "ok"
            ):
                state = "⚠️ out of date"
            elif not exists(dep):
                state = "⛔ missing"
            else:
                state = "✅ unchanged"
            source_nodes = (
                [make_text("stage "), make_code(producer)]
                if producer is not None
                else get_origin_nodes(dep, gaps)
                or [
                    make_text(
                        "in Git" if get_file_url(dep, commit_sha) else "—"
                    )
                ]
            )
            if get_dvc_file_status(dep) == "stale":
                state = "⚠️ modified since added to DVC"
            rows.append(
                make_row(
                    get_path_nodes(dep, commit_sha),
                    source_nodes,
                    [make_text(state)],
                )
            )
        if len(rows) > 1:
            blocks.append({"type": "table", "children": rows})
        made = [
            out
            for out in stages[name][1]
            if out in on_path or any(under(p, out) for p in on_path)
        ]
        if made:
            nodes = [make_text("Makes ")]
            for i, out in enumerate(made):
                if i:
                    nodes.append(make_text(", "))
                nodes += get_path_nodes(out, commit_sha)
            blocks.append(make_paragraph(*nodes))
        return blocks

    def get_sha1(path: str) -> str | None:
        if not is_file(path):
            return None
        try:
            return hashlib.sha1(read_bytes(path)).hexdigest()
        except Exception:
            return None

    def get_dvc_file_status(path: str) -> str | None:
        # Whether a file DVC tracks with a .dvc file changed since it was
        # added, from that file's own stage
        if not is_file(path + ".dvc"):
            return None
        try:
            return str(get_stage_status(path + ".dvc")["status"])
        except Exception:
            return None

    def get_provenance(path: str, noun: str, intro: list[dict]) -> dict:
        # Whether it's up to date, and how it came to be, after what
        # ``intro`` says it is, e.g., for a value, its key in a file
        prov = get_path_provenance(
            path,
            ck_info=ck_info,
            dvc_yaml={"stages": yaml_stages},
            dvc_lock={"stages": lock_stages},
            stage_statuses={name: get_status(name) for name in closure},
            is_file=is_file,
            is_dir=is_dir,
            listdir=listdir,
            read_bytes=read_bytes,
        )
        stage = prov["stage"] if prov["stage"] in stages else None
        if stage is not None and stage == doc_stage:
            return {
                "state": "ok",
                "summary": [make_text("Provenance: made by this document")],
                "line": None,
                "view": intro
                + [
                    make_paragraph(
                        make_text("Made by this document's own stage, "),
                        make_code(stage),
                        make_text(", which is being run."),
                    )
                ],
            }
        gaps = prov["gaps"]
        if stage is None and not prov["origin"] and not gaps:
            gaps = [{"path": path, "unchecked": False}]
        # What's most wrong is said while it's collapsed
        state, words = "ok", "up to date"
        if not prov["exists"]:
            state, words = "missing", "missing"
            if stage is not None and get_status(stage)["status"] == "not-run":
                words += f": stage {stage} not run"
        elif stage is not None:
            state, words = get_output_state(path, stage)
        elif get_dvc_file_status(path) == "stale":
            state, words = "stale", "modified since added to DVC"
        if state == "ok" and gaps:
            state = "incomplete"
            gap = gaps[0]
            words = (
                f"{gap['path']} imported from somewhere that can't be checked"
                if gap["unchecked"]
                else f"origin not defined for {gap['path']}"
            )
            if len(gaps) > 1:
                words += f" and {len(gaps) - 1} more"
        if state == "ok":
            summary = "Provenance"
            line = None
        elif state == "missing":
            summary = "⛔ Missing" + words.removeprefix("missing")
            line = f"{noun} {words}"
        elif state == "incomplete":
            summary = "⚠️ Incomplete provenance: " + words
            line = f"{noun} has incomplete provenance: {words}"
        else:
            state = "stale"
            summary = "⚠️ Out of date: " + words
            line = f"{noun} out of date: {words}"
        # How it came to be, stage by stage, upstream first
        order = [n for n in get_closure([path]) if n != doc_stage]
        on_path = {path}
        for name in order:
            on_path.update(d for d in stages[name][0] if not is_bookkeeping(d))
        view: list[dict] = list(intro)
        if order:
            view.append(get_graph(order, path, on_path))
            for name in order:
                view += get_stage_blocks(name, on_path, gaps)
        else:
            nodes = get_origin_nodes(path, gaps)
            view.append(
                make_paragraph(
                    make_text("Not made by a stage. "),
                    *(
                        nodes
                        if nodes
                        and nodes[0].get("value") != "❔ origin not defined"
                        else [make_text("Nothing records where it came from.")]
                    ),
                )
            )
        if prov["copied_from"]:
            view.append(
                make_paragraph(
                    make_text("Copied from "),
                    *get_path_nodes(prov["copied_from"], None),
                )
            )
        if gaps:
            view.append(
                make_paragraph(
                    make_strong("To fix"),
                    make_text(" "),
                    make_code(gaps[0]["path"]),
                    make_text(": " + how_to_define_origin(gaps[0]["path"])),
                )
            )
        if state in ("stale", "missing"):
            view.append(
                make_paragraph(
                    make_strong("To update:"),
                    make_text(" "),
                    make_code("calkit run"),
                )
            )
        return {
            "state": state,
            "summary": [make_text(summary)],
            "line": [make_text(line)] if line else None,
            "view": view,
        }

    def get_reference_provenance(key: str, name: str) -> dict:
        # A value quoted from a reference comes from it, not a pipeline
        found = [
            (path, info)
            for path, k, n, info in iter_declared_values(ck_info)
            if k == key and n == name
        ]
        intro = [
            make_paragraph(
                make_code(name),
                make_text(", quoted from reference "),
                make_code(key),
                *(
                    [make_text(" in "), *get_path_nodes(found[0][0], None)]
                    if found
                    else []
                ),
            )
        ]
        if not found:
            return {
                "state": "missing",
                "summary": [make_text("⛔ Not recorded for its reference")],
                "line": [make_text(f"Value {name} not recorded for {key}")],
                "view": intro
                + [
                    make_paragraph(
                        make_text("calkit.yaml records no value "),
                        make_code(name),
                        make_text(" for "),
                        make_code(key),
                        make_text("; add it with "),
                        make_code("calkit new ref-value"),
                    )
                ],
            }
        info = found[0][1]
        view = list(intro)
        details = [make_text(f"Recorded as {info.get('value')}")]
        if info.get("page") is not None:
            details.append(make_text(f", on page {info['page']}"))
        view.append(make_paragraph(*details))
        if info.get("context"):
            view.append(
                make_paragraph(
                    make_text("Where it says: "),
                    make_emphasis(str(info["context"])),
                )
            )
        checked, problem = check_reference_value(key, name)
        if not checked:
            view.append(
                make_paragraph(
                    make_text(
                        "Not checked against its PDF, which isn't on the "
                        "machine that rendered this; "
                    ),
                    make_code("calkit check repro"),
                    make_text(" checks it"),
                )
            )
            state, summary, line = "ok", "Provenance", None
        elif problem:
            view.append(
                make_paragraph(make_text(f"Doesn't match its PDF: {problem}"))
            )
            state = "stale"
            summary = f"⚠️ Doesn't match its reference: {problem}"
            line = f"Value doesn't match its reference: {problem}"
        else:
            view.append(make_paragraph(make_text("Matches its PDF")))
            state, summary, line = "ok", "Provenance", None
        return {
            "state": state,
            "summary": [make_text(summary)],
            "line": [make_text(line)] if line else None,
            "view": view,
        }

    def get_value_provenance(value: QuartoValue) -> dict:
        if value.ref is not None:
            return get_reference_provenance(*value.ref)
        notebook_path = get_notebook_of_values_path(value.path)
        where = (
            [
                make_text(", saved from a cell of "),
                *get_path_nodes(notebook_path, None),
            ]
            if notebook_path
            else [make_text(" in "), *get_path_nodes(value.path, None)]
        )
        intro = [make_paragraph(make_code(value.key), *where)]
        return get_provenance(value.path, "Value", intro)

    document_path = posixpath.normpath(Path(document_path).as_posix())
    ck_stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    envs = ck_info.get("environments") or {}
    show = ck_info.get("show_provenance") is not False
    values = values or []
    yaml_stages = {
        name: stage
        for name, stage in (dvc_yaml.get("stages") or {}).items()
        if isinstance(stage, dict)
    }
    lock_stages = calkit.pipeline.get_live_lock_stages(
        dvc_lock.get("stages") or {}, yaml_stages
    )
    # Each stage's inputs and outputs relative to the project, as run if
    # it has, since an iterated stage's are only concrete in dvc.lock
    stages: dict[str, tuple[list[str], list[str]]] = {}
    lock_md5s: dict[str, str] = {}
    for name, stage in lock_stages.items():
        wdir = yaml_stages[name.split("@")[0]].get("wdir") or ""
        stages[name] = (
            get_paths((stage or {}).get("deps"), wdir),
            get_paths((stage or {}).get("outs"), wdir),
        )
        for entry in ((stage or {}).get("outs") or []) + (
            (stage or {}).get("deps") or []
        ):
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                lock_md5s[
                    posixpath.normpath(posixpath.join(wdir, entry["path"]))
                ] = str(entry.get("md5") or "")
    # What DVC keeps in its cache rather than Git, to show by its hash
    dvc_cached = set()
    for name, stage in yaml_stages.items():
        for out in stage.get("outs") or []:
            if isinstance(out, str):
                dvc_cached.add(
                    posixpath.normpath(
                        posixpath.join(stage.get("wdir") or "", out)
                    )
                )
            elif isinstance(out, dict):
                out_path, opts = next(iter(out.items()))
                if (
                    not isinstance(opts, dict)
                    or opts.get("cache") is not False
                ):
                    dvc_cached.add(
                        posixpath.normpath(
                            posixpath.join(stage.get("wdir") or "", out_path)
                        )
                    )
    locked_bases = {name.split("@")[0] for name in lock_stages}
    for name, stage in yaml_stages.items():
        if (
            name.startswith("_")
            or name in locked_bases
            or "matrix" in stage
            or "foreach" in stage
        ):
            continue
        wdir = stage.get("wdir") or ""
        stages[name] = (
            get_paths(stage.get("deps"), wdir),
            get_paths(stage.get("outs"), wdir),
        )
    # The stage that renders it, named, or else its Quarto stage
    doc_stage = document_stage or next(
        (
            name
            for name, stage in ck_stages.items()
            if isinstance(stage, dict)
            and stage.get("kind") == "quarto"
            and posixpath.normpath(
                posixpath.join(
                    stage.get("wdir") or "", stage.get("target_path") or ""
                )
            )
            == document_path
        ),
        None,
    )
    # What's shown in the document under a label, to link to there
    labels = {c.path: c.label for c in reversed(components) if c.label}
    statuses: dict[str, dict] = {}
    waiting: dict[str, list[str]] = {}
    closure = get_closure(
        [c.path for c in components] + [v.path for v in values if not v.ref]
    )
    records: dict[str, dict] = {}
    for component in components:
        # Its provenance is worked out if any showing of it shows it
        wanted = [
            c
            for c in components
            if c.src == component.src and c.provenance and show
        ]
        if component.src in records:
            continue
        records[component.src] = {
            "kind": component.kind,
            # As the document refers to it, for an image
            "url": posixpath.relpath(
                component.path, posixpath.dirname(document_path) or "."
            ),
            # So what shows it can tell it changed since
            "sha1": get_sha1(component.path),
            "provenance": (
                get_provenance(component.path, _NOUNS[component.kind], [])
                if wanted
                else None
            ),
        }
    value_records: dict[str, dict] = {}
    for value in values:
        key = get_value_key(value)
        wanted_values = [
            v
            for v in values
            if get_value_key(v) == key and v.provenance and show
        ]
        if key not in value_records:
            value_records[key] = {
                "sha1": get_sha1(value.path),
                "provenance": (
                    get_value_provenance(value) if wanted_values else None
                ),
            }
    return {"components": records, "values": value_records}


def get_provenance_path(document_path: str) -> str:
    """Where what a document's components and values came from is written,
    relative to the project, as what renders it finds it."""
    document_path = posixpath.normpath(Path(document_path).as_posix())
    return posixpath.join(PROVENANCE_DIR, document_path + ".json")


def write_provenance(
    components: list[Component],
    document_path: str,
    ck_info: dict,
    wdir: str | None = None,
    document_stage: str | None = None,
    values: list[QuartoValue] | None = None,
) -> str:
    """Write where a document's components and values came from, from the
    project in ``wdir`` as it is, returning where, relative to it.

    Written before every render, so it says how the pipeline stood when the
    document was rendered, and kept out of Git, like the rest of
    ``.calkit/local``, with the document's SHA-1, so what shows it can
    tell the document changed since. Files in Git link to the repo's host,
    from ``git_repo_url`` in ``calkit.yaml``, or else the ``origin`` remote,
    and values quoted from references are checked against PDFs of them on
    this machine, without downloading any.
    """
    import hashlib

    import calkit
    import calkit.dvc
    import calkit.git

    def get_full_path(path: str) -> str:
        return os.path.join(wdir or "", *path.split("/"))

    def read_yaml(name: str) -> dict:
        try:
            with open(get_full_path(name), encoding="utf-8") as f:
                data = calkit.core._load_yaml_readonly(f)
        except OSError:
            return {}
        return data if isinstance(data, dict) else {}

    def get_status(name: str) -> dict:
        # From DVC, run from the project, so it names stages and paths as
        # dvc.lock does, e.g., 'clean' rather than '../dvc.yaml:clean'
        prev_wdir = os.getcwd()
        try:
            os.chdir(wdir or ".")
            if not dvc_stages:
                try:
                    repo = calkit.dvc.get_dvc_repo(wdir=".")
                    dvc_stages.update(
                        {s.addressing: s for s in repo.index.stages}
                    )
                except Exception as e:
                    raise ValueError(
                        f"Can't read the pipeline to check it: {e}"
                    )
            if name not in dvc_stages:
                return {
                    "status": "not-run",
                    "modified_command": False,
                    "modified_inputs": [],
                    "modified_outputs": [],
                    "missing_outputs": [],
                }
            return get_stage_status(dvc_stages[name])
        finally:
            os.chdir(prev_wdir)

    def get_file_url(path: str, commit_sha: str | None) -> str | None:
        # A file in Git on the repo's host, at a commit, or the current one
        if not git_info:
            git_info["remote"] = None
            try:
                repo = calkit.git.get_repo(os.path.abspath(wdir or "."))
                remotes = {r.name: r for r in repo.remotes}
                git_info["remote"] = ck_info.get("git_repo_url") or (
                    remotes["origin"].url if "origin" in remotes else None
                )
                prefix = os.path.relpath(
                    os.path.abspath(wdir or "."), repo.working_dir
                )
                git_info["prefix"] = Path(prefix).as_posix()
                # Unquoted, e.g., a path that isn't ASCII
                git_info["tracked"] = set(repo.git.ls_files("-z").split("\0"))
                git_info["repo"] = repo
                git_info["pushed"] = {}
            except Exception:
                git_info["remote"] = None
        if not git_info["remote"]:
            return None
        repo_path = posixpath.normpath(
            posixpath.join(git_info["prefix"], path)
        )
        if repo_path not in git_info["tracked"]:
            return None
        # At a commit the host has, as far as this clone knows, i.e., one
        # a remote-tracking branch has, or else none
        for sha in (commit_sha, "HEAD"):
            if sha is None:
                continue
            if sha not in git_info["pushed"]:
                try:
                    repo = git_info["repo"]
                    full_sha = repo.commit(sha).hexsha
                    on_remote = bool(
                        repo.git.branch("-r", "--contains", full_sha).strip()
                    )
                except Exception:
                    full_sha, on_remote = None, False
                git_info["pushed"][sha] = full_sha if on_remote else None
            if git_info["pushed"][sha]:
                return calkit.git.get_web_file_url(
                    git_info["remote"], git_info["pushed"][sha], repo_path
                )
        return None

    def check_reference_value(key: str, name: str) -> tuple[bool, str | None]:
        # Against a PDF of the reference already on this machine
        from calkit.references.check import load_collections
        from calkit.references.values import (
            check_value,
            get_entry_file,
            get_pdf,
            iter_declared_values,
            read_pdf_pages,
        )

        for collection_path, k, n, info in iter_declared_values(ck_info):
            if (k, n) != (key, name):
                continue
            try:
                collection = next(
                    c
                    for c in ck_info.get("references") or []
                    if isinstance(c, dict) and c.get("path") == collection_path
                )
                entries = load_collections(
                    wdir=wdir, paths=[collection_path]
                ).get(collection_path, {})
                pdf = get_pdf(
                    collection_path,
                    key,
                    entry=entries.get(key),
                    file=get_entry_file(collection, key),
                    wdir=wdir,
                    download=False,
                    zotero_desktop=False,
                )
                if pdf is None:
                    return False, None
                return True, check_value(
                    read_pdf_pages(pdf.path),
                    info.get("value"),
                    page=info.get("page"),
                    context=info.get("context"),
                )
            except Exception:
                return False, None
        return False, None

    def read_bytes(path: str) -> bytes:
        with open(get_full_path(path), "rb") as f:
            return f.read()

    def get_stage_runs() -> dict:
        # As recorded, and for stages run by a pipeline that's still going,
        # e.g., this document's, from its log, since runs are recorded when
        # it's done
        from calkit.cli.main.core import (
            RUN_INFO_ENV_VAR,
            _stage_run_info_from_log_content,
        )

        stage_runs = calkit.core.read_stage_runs(wdir=wdir)
        try:
            run_info = json.loads(os.environ.get(RUN_INFO_ENV_VAR) or "{}")
            with open(run_info["log_path"], encoding="utf-8") as f:
                log_content = f.read()
        except (OSError, KeyError, TypeError, ValueError):
            return stage_runs
        lock_stages = (read_yaml("dvc.lock").get("stages")) or {}
        system = calkit.core.get_machine_properties()
        for name, info in _stage_run_info_from_log_content(
            log_content
        ).items():
            # Only those that ran, not ones skipped or gated off here
            if (
                name not in lock_stages
                or not info.get("start_time")
                or info.get("status") != "completed"
            ):
                continue
            stage_runs[name] = {
                "start_time": info["start_time"],
                "git_rev": run_info.get("git_rev"),
                "git_dirty": run_info.get("git_dirty"),
                "system": {k: system.get(k) for k in ("os", "machine")},
                "dvc_lock_hash": calkit.dvc.stage_lock_hash(lock_stages[name]),
            }
        return stage_runs

    dvc_stages: dict[str, Any] = {}
    git_info: dict[str, Any] = {}
    records = get_provenance_records(
        components,
        document_path,
        values=values,
        get_file_url=get_file_url,
        check_reference_value=check_reference_value,
        document_stage=document_stage,
        ck_info=ck_info,
        dvc_yaml=read_yaml("dvc.yaml"),
        dvc_lock=read_yaml("dvc.lock"),
        stage_runs=get_stage_runs(),
        get_stage_status=get_status,
        is_file=lambda p: os.path.isfile(get_full_path(p)),
        is_dir=lambda p: os.path.isdir(get_full_path(p)),
        listdir=lambda p: (
            os.listdir(get_full_path(p))
            if os.path.isdir(get_full_path(p))
            else []
        ),
        read_bytes=read_bytes,
    )
    # So what shows it can tell the document changed since
    with open(get_full_path(document_path), "rb") as f:
        records["source_sha1"] = hashlib.sha1(f.read()).hexdigest()
    # So a graph can be drawn in a page that can't load anything later
    text = read_document_text(get_full_path(document_path)) or ""
    records["embeds_resources"] = embeds_resources(text, document_path, wdir)
    calkit.core.ensure_local_dir(wdir)
    rel_path = get_provenance_path(document_path)
    fpath = get_full_path(rel_path)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    calkit.core.write_if_changed(
        fpath, json.dumps(records, indent=2, ensure_ascii=False) + "\n"
    )
    return rel_path


def get_metadata(
    text: str, document_path: str, wdir: str | None = None
) -> list[dict]:
    """The metadata Quarto reads for a document, as written, nearest last:
    its Quarto project's ``_quarto.yml``, its folders' ``_metadata.yml``,
    and its front matter.
    """
    import io

    import calkit

    def load(content: str) -> dict:
        try:
            data = calkit.core._load_yaml_readonly(io.StringIO(content))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    document_path = posixpath.normpath(Path(document_path).as_posix())
    found: list[dict] = []
    quarto_dir = get_quarto_dir(document_path, wdir)
    folder = posixpath.dirname(document_path)
    names = ["_metadata.yml", "_metadata.yaml"]
    while True:
        if folder == quarto_dir:
            names += ["_quarto.yml", "_quarto.yaml"]
        for name in names:
            fpath = os.path.join(wdir or "", folder, name)
            if os.path.isfile(fpath):
                with open(fpath, encoding="utf-8") as f:
                    found.insert(0, load(f.read()))
        if folder in ("", ".", quarto_dir):
            break
        folder = posixpath.dirname(folder)
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*(\n|$)", text, flags=re.DOTALL)
    if m is not None:
        found.append(load(m.group(1)))
    return found


def get_format_options(meta: dict, to: str | None = None) -> list[dict]:
    """A document's metadata, and its options for the format ``to``, e.g.,
    ``html``, or for every format without one."""
    found = [meta]
    formats = meta.get("format")
    to_base = re.split(r"[+-]", to)[0] if to else None
    for name, fmt in (formats if isinstance(formats, dict) else {}).items():
        # E.g., html for an html+raw or an html with extensions
        base = re.split(r"[+-]", str(name))[0]
        if isinstance(fmt, dict) and (to_base is None or base == to_base):
            found.append(fmt)
    return found


def embeds_resources(
    text: str, document_path: str, wdir: str | None = None
) -> bool:
    """Whether a document's HTML has everything it loads embedded, e.g.,
    with ``embed-resources``, so nothing can be loaded later."""
    embeds = False
    for meta in get_metadata(text, document_path, wdir):
        for options in get_format_options(meta, "html"):
            for key in ("embed-resources", "self-contained"):
                if key in options:
                    embeds = options[key] is True
    return embeds


def get_filter_problem(
    text: str,
    document_path: str,
    wdir: str | None = None,
    to: str | None = None,
) -> str | None:
    """Why the filter that shows ``ckfigure``, ``cktable``, and
    ``ckinclude`` divs won't run for a
    document, or None if it will, from the ``filters`` its front matter,
    its folders' ``_metadata.yml``, and its Quarto project's
    ``_quarto.yml`` list, since Quarto only runs a filter that's listed,
    and this one has to run before Quarto numbers figures.

    Filters listed for a format count for that format, i.e., ``to``, e.g.,
    ``html``, or for any without one.
    """
    document_path = posixpath.normpath(Path(document_path).as_posix())
    filters = []
    for meta in get_metadata(text, document_path, wdir):
        for options in get_format_options(meta, to):
            filters += list(options.get("filters") or [])
    entries = [
        f
        for f in filters
        if f == "calkit" or (isinstance(f, dict) and f.get("path") == "calkit")
    ]
    if any(isinstance(f, dict) and f.get("at") == "pre-ast" for f in entries):
        return None
    where = "listed" if not entries else "listed to run at pre-ast"
    return (
        f"The ckfigure, cktable, and ckinclude divs in {document_path} "
        f"need Calkit's filter {where}, before Quarto numbers figures; add "
        "this to its "
        f"front matter or _quarto.yml:\n\n{FILTER_CONFIG}"
    )
