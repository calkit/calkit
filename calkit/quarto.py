"""Functionality for using Quarto in Calkit projects."""

from __future__ import annotations

import json
import os
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

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

# Reads each value from its results file when the document renders, finding
# declared results' names in calkit.yaml, and formats it as Python would,
# which ``check_values`` makes sure of before the pipeline renders.
SHORTCODE_LUA = r"""---@diagnostic disable: undefined-global
-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows values from pipeline results with
-- {{< ckvalue results/metrics.json key .2f >}}, read from the results file
-- each time the document renders.

local function read_file(fpath)
  local f = io.open(fpath, "r")
  if f == nil then
    return nil
  end
  local content = f:read("a")
  f:close()
  return content
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
    path = ".calkit/notebooks/outputs/" .. (path:gsub("^%./", ""))
      .. "/values.json"
  end
  return path
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
    return pandoc.Str(text)
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
    local data = load_data(".calkit/reference-values/" .. file .. ".json")
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
    return pandoc.Str(text)
  end,
}
"""

# The class of a fenced div that shows a file with where it came from and
# whether it's up to date, or with no src, the document's provenance
PROVENANCE_CLASS = "ckprovenance"
# Where Calkit writes what each document's panels say, for the filter to
# read, relative to the project
PROVENANCE_DIR = ".calkit/local/provenance"
# What a document lists to run the filter, before Quarto's own filters
FILTER_CONFIG = "filters:\n  - at: pre-ast\n    path: calkit\n"

# Turns the panels Calkit wrote before rendering into Pandoc's AST, deciding
# nothing about what they say, which is decided in Python and tested there
PROVENANCE_LUA = r"""---@diagnostic disable: undefined-global
-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows the file a ::: {.ckprovenance src="figures/fit.png"} div names,
-- as a figure, a table, or its name, with where it came from and whether
-- it's up to date, or with no src, the document's provenance. Calkit
-- decides what each panel says before rendering, and writes it to
-- .calkit/local/provenance; this only turns it into Pandoc's AST.
-- It has to run at pre-ast, so Quarto numbers the figures and tables and
-- builds the callouts after.

local CALLOUT = {
  note = "callout-note",
  warning = "callout-warning",
  danger = "callout-important",
}
-- Misspellings of the class, said in the document rather than rendering
-- as a plain div with no provenance
local MISNAMED = {"calkit-provenance", "ck-provenance"}
local PICTURE_EXTS = {
  [".svg"] = true, [".png"] = true, [".jpg"] = true, [".jpeg"] = true,
  [".gif"] = true, [".webp"] = true, [".pdf"] = true,
}
local TABLE_EXTS = {[".csv"] = true, [".tsv"] = true}

local function read_file(fpath)
  local f = io.open(fpath, "r")
  if f == nil then
    return nil
  end
  local content = f:read("a")
  f:close()
  return content
end

-- The Calkit project's folder, which the panels are kept under
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

-- Whether the document changed since Calkit wrote its panels, e.g., in
-- 'quarto preview', which a notebook does by rendering with --execute
local outdated = nil
local function is_outdated(data)
  if outdated == nil then
    outdated = false
    local input = quarto.doc.input_file
    local f = io.open(input, "rb")
    local notebook = input:lower():match("%.ipynb$")
    if data.source_sha1 and f ~= nil and not notebook then
      outdated = pandoc.utils.sha1(f:read("a")) ~= data.source_sha1
    end
    if f ~= nil then
      f:close()
    end
  end
  return outdated
end

-- What Calkit wrote for this document, or false if nothing
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

-- Sections a div turns off, e.g., graph="false"
local hidden = {}

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
  return (value:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

-- Drawn by Quarto's own Mermaid, which it runs before Pandoc, so it's
-- asked for as a dependency, with the source shown where it can't draw
local diagrams_ready = false
local function mermaid(node)
  local share = os.getenv("QUARTO_SHARE_PATH")
  local source = tostring(node.value or "")
  if share and quarto.doc.is_format("html:js") then
    if not diagrams_ready then
      local function asset(name)
        return pandoc.path.join({share, "formats", "html", "mermaid", name})
      end
      quarto.doc.add_html_dependency({
        name = "quarto-diagram",
        scripts = {asset("mermaid.min.js"), asset("mermaid-init.js")},
        stylesheets = {asset("mermaid.css")},
      })
      diagrams_ready = true
    end
    return pandoc.Blocks({
      pandoc.RawBlock(
        "html",
        '<pre class="mermaid mermaid-js">' .. escape(source) .. "</pre>"
      ),
    })
  end
  return pandoc.Blocks({
    pandoc.CodeBlock(source, pandoc.Attr("", {"default"}, {})),
  })
end

local function callout(kind, title, content, collapse)
  local attributes = {{"title", title}}
  if collapse then
    attributes[#attributes + 1] = {"collapse", "true"}
  end
  return pandoc.Div(
    content, pandoc.Attr("", {CALLOUT[kind] or "callout-note"}, attributes)
  )
end

local function block(node)
  local kind = node.type
  if node.section ~= nil and hidden[node.section] then
    return pandoc.Blocks({})
  end
  if kind == "paragraph" then
    return pandoc.Blocks({pandoc.Para(inlines(node.children))})
  elseif kind == "table" then
    return pandoc.Blocks({data_table(node)})
  elseif kind == "mermaid" then
    return mermaid(node)
  elseif kind == "admonition" then
    return pandoc.Blocks({
      callout(
        node.kind,
        pandoc.utils.stringify(inlines(node.title)),
        blocks(node.children),
        node.dropdown
      ),
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

local function get_image(el, src)
  local attributes = {}
  for _, key in ipairs({"width", "height", "fig-align", "fig-alt"}) do
    if el.attributes[key] then
      table.insert(attributes, {key, el.attributes[key]})
    end
  end
  local alt = el.attributes.alt and words(el.attributes.alt)
    or pandoc.Inlines({})
  return pandoc.Image(alt, src, "", pandoc.Attr("", {}, attributes))
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

local function provenance_div(el)
  local src = el.attributes.src or ""
  local data = load_records()
  local record = nil
  if data then
    if src == "" then
      record = data.document
    else
      record = (data.panels or {})[src]
    end
  end
  local out = pandoc.Blocks({})
  if record == nil then
    -- Shown as it would be, as far as that can be without Calkit, keeping
    -- the id and caption, so cross-references still resolve
    local _, ext = pandoc.path.split_extension(src)
    ext = ext:lower()
    local kind = (el.attributes.kind or ""):lower()
    if src == "" then
      out:extend(el.content)
    elseif kind == "figure" or (kind == "" and PICTURE_EXTS[ext]) then
      out:extend(get_figure(
        el, pandoc.Blocks({pandoc.Plain({get_image(el, src)})})
      ))
    elseif kind == "table" or (kind == "" and TABLE_EXTS[ext]) then
      local item = pandoc.utils.from_simple_table(pandoc.SimpleTable(
        {}, {pandoc.AlignDefault}, {0}, {},
        {{{pandoc.Plain({pandoc.Code(src)})}}}
      ))
      item.attr = pandoc.Attr(el.identifier, {}, {})
      if #el.content > 0 then
        item.caption = {long = el.content}
      end
      out:insert(item)
    else
      out:insert(pandoc.Para({pandoc.Code(src)}))
      out:extend(el.content)
    end
    out:insert(callout("warning", "No provenance recorded", pandoc.Blocks({
      pandoc.Para({
        pandoc.Str("Render"), pandoc.Space(), pandoc.Str("with"),
        pandoc.Space(), pandoc.Code("calkit quarto render"),
        pandoc.Space(), pandoc.Str("or"), pandoc.Space(),
        pandoc.Code("calkit run"), pandoc.Str("."),
      }),
    })))
    return out
  end
  hidden = {}
  for _, section in ipairs({"table", "graph"}) do
    local value = (el.attributes[section] or ""):lower()
    hidden[section] = value == "false" or value == "no" or value == "0"
  end
  if record.kind == "figure" then
    out:extend(get_figure(
      el, pandoc.Blocks({pandoc.Plain({get_image(el, src)})})
    ))
  elseif record.kind == "table" then
    for index, item in ipairs(blocks(record.body)) do
      -- The id and caption go on the table, not a note after it
      if index == 1 and item.t == "Table" then
        item.attr = pandoc.Attr(el.identifier, {}, {})
        if #el.content > 0 then
          item.caption = {long = el.content}
        end
      end
      out:insert(item)
    end
  else
    out:extend(blocks(record.body))
    out:extend(el.content)
  end
  out:extend(blocks(record.panel))
  if is_outdated(data) then
    local title = "Document changed since panels recorded"
    out:insert(callout("warning", title, pandoc.Blocks({
      pandoc.Para({
        pandoc.Str("Render"), pandoc.Space(), pandoc.Str("with"),
        pandoc.Space(), pandoc.Code("calkit quarto render"),
        pandoc.Space(), pandoc.Str("or"), pandoc.Space(),
        pandoc.Code("calkit run"), pandoc.Str("."),
      }),
    })))
  end
  return out
end

local function handle(el)
  if el.classes:includes("ckprovenance") then
    return provenance_div(el)
  end
  for _, name in ipairs(MISNAMED) do
    if el.classes:includes(name) then
      local body = pandoc.Blocks({
        pandoc.Para({
          pandoc.Str("Use"), pandoc.Space(), pandoc.Code(".ckprovenance"),
          pandoc.Space(), pandoc.Str("rather"), pandoc.Space(),
          pandoc.Str("than"), pandoc.Space(), pandoc.Code("." .. name),
          pandoc.Str("."),
        }),
      })
      body:extend(el.content)
      return callout("danger", "No provenance shown", body)
    end
  end
  return nil
end

return {{Div = handle}}
"""


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
            got = _ckvalue_args(m.group("args"), path, i + 1)
            found.append(
                (
                    m.start(),
                    QuartoValue(
                        source=got["source"],
                        key=got["key"],
                        format=got.get("format"),
                        path=_resolve_source(
                            got["source"],
                            results,
                            path,
                            i + 1,
                            kind=got["kind"],
                        ),
                        line=i + 1,
                    ),
                )
            )
        # A citation key, a name, and a format, read the same way
        for m in _REFVAL_SHORTCODE_RE.finditer(line):
            got = _ckvalue_args(m.group("args"), path, i + 1)
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


# What a div shows a file as, by its extension, unless it says with kind=
FIGURE_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf")
TABLE_DELIMITERS = {".csv": ",", ".tsv": "\t"}
# Rows of a table shown before it's cut short, unless a div says with rows=
TABLE_ROW_LIMIT = 25
# What a panel calls what it's about
_NOUNS = {"figure": "Figure", "table": "Table", "file": "File"}
# A fenced div's opening line, e.g., ::: {.ckprovenance src="a.png"}, or
# ::: name, which Pandoc reads as a class, optionally with colons after
_DIV_OPEN_RE = re.compile(
    r"^\s*:{3,}\s*(?:\{(?P<attrs>[^}]*)\}|(?P<cls>[\w-]+))(?:\s*:+)?\s*$"
)
_DIV_ATTR_RE = re.compile(
    r"\.(?P<cls>[\w-]+)|#(?P<id>[\w:.-]+)"
    r"|(?P<key>[\w-]+)=(?:\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<bare>\S+))"
)
_CODE_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass(frozen=True)
class ProvenanceDiv:
    """One ``ckprovenance`` div in a Quarto document."""

    # The file it shows, as written, relative to the document, or "" for
    # a panel about the document
    src: str
    # That file relative to the project, or "" for the document
    path: str
    # 'figure', 'table', 'file', or 'document'
    kind: str
    # 1-indexed line of the document
    line: int = 0
    rows: int = TABLE_ROW_LIMIT


def extract_provenance_divs(
    text: str, document_path: str, wdir: str | None = None
) -> list[ProvenanceDiv]:
    """Find the ``ckprovenance`` divs in a document, in order, skipping
    those in code blocks.

    A ``src`` is relative to the document, or to its Quarto project with a
    leading ``/``, as Quarto reads an image's, and ``kind`` overrides what
    its extension says to show it as.
    """
    document_path = posixpath.normpath(Path(document_path).as_posix())
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
            elif a.group("key"):
                attrs[a.group("key")] = next(
                    v for v in a.group("dq", "sq", "bare") if v is not None
                )
        if PROVENANCE_CLASS not in classes:
            continue
        src = attrs.get("src", "").strip()
        if not src:
            divs.append(ProvenanceDiv("", "", "document", line=i + 1))
            continue
        if src.startswith("/"):
            base = get_quarto_dir(document_path, wdir)
        else:
            base = posixpath.dirname(document_path)
        path = posixpath.normpath(posixpath.join(base, src.lstrip("/")))
        ext = posixpath.splitext(src)[1].lower()
        kind = attrs.get("kind", "").strip().lower()
        if kind not in _NOUNS:
            kind = (
                "figure"
                if ext in FIGURE_EXTS
                else "table"
                if ext in TABLE_DELIMITERS
                else "file"
            )
        try:
            rows = int(attrs.get("rows", TABLE_ROW_LIMIT))
        except ValueError:
            rows = TABLE_ROW_LIMIT
        divs.append(ProvenanceDiv(src, path, kind, line=i + 1, rows=rows))
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


def get_provenance_panels(
    divs: list[ProvenanceDiv],
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
    open_text: Callable[[str], IO[str]],
    document_stage: str | None = None,
) -> dict:
    """What each ``ckprovenance`` div in a document shows, as nodes the
    Quarto filter turns into Pandoc's AST: for each file, keyed by its
    ``src``, what to show it as, e.g., a table's rows, and a panel saying
    the stage that made it, what it read, the environment, and whether
    it's up to date per ``dvc.lock``; and for the document, the pipeline
    outputs it's made from and whether each is.

    The document's own outputs are left out, since it can't say whether
    what's being rendered is up to date, as is when its stage last ran,
    since that's being recorded. Only the stages the document is made from
    are checked, with ``get_stage_status``, which gives a stage in
    ``dvc.lock``'s status, as ``get_stage_status`` does. ``open_text``
    opens a file as text to read a table from, and the other functions
    read the project, as for ``calkit.provenance.get_path_provenance``.
    ``document_stage`` names the stage that renders the document, which is
    otherwise its Quarto stage, if any.
    """
    import csv

    import calkit.dvc
    import calkit.pipeline
    from calkit.provenance import (
        find_provenance_gaps,
        get_path_provenance,
        how_to_define_origin,
        is_data_path,
    )

    # The nodes the filter reads, named as MyST's are
    def make_text(value: str) -> dict:
        return {"type": "text", "value": value}

    def make_strong(value: str) -> dict:
        return {"type": "strong", "children": [make_text(value)]}

    def make_emphasis(value: str) -> dict:
        return {"type": "emphasis", "children": [make_text(value)]}

    def make_code(value: str) -> dict:
        return {"type": "inlineCode", "value": value}

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

    def make_admonition(
        kind: str, title: str, children: list[dict], dropdown: bool = False
    ) -> dict:
        return {
            "type": "admonition",
            "kind": kind,
            "title": [make_text(title)],
            "children": children,
            "dropdown": dropdown,
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

    def get_gap_words(gap: dict) -> str:
        if gap["unchecked"]:
            return (
                f"{gap['path']} imported from somewhere that can't be checked"
            )
        return f"origin not defined for {gap['path']}"

    def get_fix_paragraph(gaps: list[dict]) -> dict:
        path = gaps[0]["path"]
        return make_paragraph(
            make_strong("To fix"),
            make_text(" "),
            make_code(path),
            make_text(": " + how_to_define_origin(path)),
        )

    def get_update_paragraph() -> dict:
        return make_paragraph(
            make_strong("To update:"), make_text(" "), make_code("calkit run")
        )

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

    def get_stage_paragraphs(
        stage: str, label: str, show_run: bool = True
    ) -> list[dict]:
        # Which stage, its environment, and where it last ran, if the
        # record of that run is for what dvc.lock says it made, which it
        # isn't for a stage that's run since the pipeline started, since
        # runs are recorded when it's done
        made = [
            make_strong(f"{label}:"),
            make_text(" "),
            make_text("stage "),
            make_code(stage),
        ]
        ck_stage = ck_stages.get(stage.split("@")[0]) or {}
        if ck_stage.get("kind"):
            made.append(make_text(f", {ck_stage['kind']}"))
        out = [make_paragraph(*made)]
        env_nodes = get_environment_nodes(stage)
        if env_nodes:
            out.append(
                make_paragraph(
                    make_strong("Environment:"), make_text(" "), *env_nodes
                )
            )
        run = stage_runs.get(stage)
        lock_stage = lock_stages.get(stage)
        if not show_run or lock_stage is None:
            return out
        if not isinstance(run, dict) or run.get(
            "dvc_lock_hash"
        ) != calkit.dvc.stage_lock_hash(lock_stage):
            out.append(
                make_paragraph(
                    make_strong("Last run:"),
                    make_text(" not recorded for its current outputs"),
                )
            )
        else:
            system = run.get("system") or {}
            parts = [str(run.get("start_time") or "")[:10]] + [
                " ".join(
                    str(system[k]) for k in ("os", "machine") if system.get(k)
                )
            ]
            nodes = [
                make_strong("Last run:"),
                make_text(" "),
                make_text(", ".join(p for p in parts if p)),
            ]
            if run.get("git_rev"):
                nodes += [
                    make_text(", commit "),
                    make_code(str(run["git_rev"])[:7]),
                ]
                if run.get("git_dirty"):
                    nodes.append(make_text(" with uncommitted changes"))
            out.append(make_paragraph(*nodes))
        return out

    def get_table_body(div: ProvenanceDiv) -> list[dict]:
        # Only as far as is shown, and one more row to tell it's cut short
        delimiter = TABLE_DELIMITERS.get(
            posixpath.splitext(div.path)[1].lower(), ","
        )
        rows = []
        try:
            with open_text(div.path) as f:
                for row in csv.reader(f, delimiter=delimiter):
                    rows.append(row)
                    if len(rows) > div.rows + 1:
                        break
        except (OSError, csv.Error):
            return [make_paragraph(make_emphasis(f"Can't read {div.src}"))]
        if not rows:
            return [make_paragraph(make_emphasis(f"{div.src} is empty"))]
        header, body = rows[0], rows[1 : div.rows + 1]
        out = [
            {
                "type": "table",
                "children": [
                    make_row(*([make_text(v)] for v in header), header=True)
                ]
                + [make_row(*([make_text(v)] for v in row)) for row in body],
            }
        ]
        if len(rows) > div.rows + 1:
            out.append(
                make_paragraph(
                    make_emphasis(f"First {div.rows} rows of {div.src}")
                )
            )
        return out

    def get_file_panel(div: ProvenanceDiv) -> dict:
        noun = _NOUNS[div.kind]
        prov = get_path_provenance(
            div.path,
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
            return make_admonition(
                "note", f"{noun} made by this document", [], dropdown=True
            )
        gaps = prov["gaps"]
        children = []
        if stage is not None:
            children += get_stage_paragraphs(stage, "Made by")
            if prov["copied_from"]:
                children.append(
                    make_paragraph(
                        make_strong("Copied from:"),
                        make_text(" "),
                        make_code(prov["copied_from"]),
                    )
                )
            # What it read, with its script or notebook first
            status = get_status(stage)
            rows = [
                make_row(
                    [make_strong("Input")],
                    [make_strong("Made by")],
                    [make_strong("State")],
                    header=True,
                )
            ]
            inputs = ([prov["source"]] if prov["source"] else []) + prov[
                "inputs"
            ]
            for path in dict.fromkeys(inputs):
                producer = get_producer(path)
                if any(under(path, p) for p in status["modified_inputs"]):
                    state = "⚠️ modified" if exists(path) else "⛔ missing"
                elif (
                    producer is not None
                    and get_output_state(path, producer)[0] != "ok"
                ):
                    state = "⚠️ out of date"
                elif any(under(g["path"], path) for g in gaps):
                    state = "❔ origin not defined"
                else:
                    state = "✅ unchanged"
                rows.append(
                    make_row(
                        [make_code(path)],
                        [make_code(producer) if producer else make_text("")],
                        [make_text(state)],
                    )
                )
            if len(rows) > 1:
                children.append({"type": "table", "children": rows})
        if prov["origin"]:
            origin: dict = make_text(prov["origin"])
            if prov["origin_url"]:
                origin = {
                    "type": "link",
                    "url": prov["origin_url"],
                    "children": [origin],
                }
            children.append(
                make_paragraph(make_strong("Origin:"), make_text(" "), origin)
            )
        if stage is None and not prov["origin"] and not gaps:
            gaps = [{"path": div.path, "unchecked": False}]
        # What's most wrong goes in the title
        state = "ok"
        if not prov["exists"]:
            state, title = "missing", f"{noun} missing"
            if stage is not None and get_status(stage)["status"] == "not-run":
                title += f": stage {stage} not run"
        elif stage is not None:
            state, words = get_output_state(div.path, stage)
            title = (
                f"{noun} up to date"
                if state == "ok"
                else (f"{noun} out of date: {words}")
            )
        if state == "ok" and gaps:
            state = "incomplete"
            title = f"{noun} has incomplete provenance: " + get_gap_words(
                gaps[0]
            )
            if len(gaps) > 1:
                title += f" and {len(gaps) - 1} more"
        elif state == "ok" and stage is None:
            title = f"{noun}: {prov['origin']}"
        if state in ("stale", "waiting", "missing", "not-run"):
            children.append(get_update_paragraph())
        elif state == "incomplete":
            children.append(get_fix_paragraph(gaps))
        kind = {"ok": "note", "incomplete": "warning"}.get(state, "danger")
        return make_admonition(kind, title, children, dropdown=kind == "note")

    def get_graph(order: list[str], states: dict[str, str]) -> dict:
        # Each stage between what it reads and makes, colored by state
        lines = ["flowchart LR"]
        ids: dict[str, str] = {}

        def get_id(path: str) -> str:
            if path not in ids:
                ids[path] = f"f{len(ids)}"
                label = path.replace('"', "#quot;")
                style = states.get(path)
                lines.append(
                    f'  {ids[path]}("{label}")'
                    + (f":::{style}" if style else "")
                )
            return ids[path]

        for i, name in enumerate(order):
            stage_id = f"s{i}"
            lines.append(f'  {stage_id}[["{name}"]]')
            for dep in stages[name][0]:
                if not is_bookkeeping(dep):
                    lines.append(f"  {get_id(dep)} --> {stage_id}")
            for out in stages[name][1]:
                lines.append(f"  {stage_id} --> {get_id(out)}")
        lines += [
            "  classDef ok fill:#e6f4ea,stroke:#1e8e3e",
            "  classDef stale fill:#fce8e6,stroke:#d93025",
            "  classDef waiting fill:#fef7e0,stroke:#f9ab00",
        ]
        return {
            "type": "mermaid",
            "value": "\n".join(lines),
            "section": "graph",
        }

    def get_document_panel() -> dict:
        roots = [d.path for d in divs if d.path]
        own = stages[doc_stage][1] if doc_stage in stages else []
        if doc_stage in stages:
            roots = stages[doc_stage][0] + roots
        # Not what it makes itself, which it can't say anything about
        roots = [
            r
            for r in dict.fromkeys(roots)
            if not is_bookkeeping(r) and not any(under(r, o) for o in own)
        ]
        order = [n for n in get_closure(roots) if n != doc_stage]
        children = []
        if doc_stage in stages:
            children += get_stage_paragraphs(
                doc_stage, "Rendered by", show_run=False
            )
        rows = [
            make_row(
                [make_strong("Output")],
                [make_strong("Made by")],
                [make_strong("State")],
                header=True,
            )
        ]
        marks = {"ok": "✅", "missing": "⛔"}
        states = {}
        n_outputs = 0
        troubled = []
        for name in order:
            for out in stages[name][1]:
                n_outputs += 1
                state, words = get_output_state(out, name)
                states[out] = (
                    "ok"
                    if state == "ok"
                    else ("waiting" if state == "waiting" else "stale")
                )
                if state != "ok":
                    troubled.append(out)
                rows.append(
                    make_row(
                        [make_code(out)],
                        [make_code(name)],
                        [make_text(f"{marks.get(state, '⚠️')} {words}")],
                    )
                )
        if n_outputs:
            children.append(
                {"type": "table", "children": rows, "section": "table"}
            )
            children.append(
                get_graph(
                    order + ([doc_stage] if doc_stage in stages else []),
                    states,
                )
            )
        if own:
            children.append(
                make_paragraph(
                    make_strong("Not checked:"),
                    make_text(" "),
                    *[
                        node
                        for i, path in enumerate(own)
                        for node in [make_text(", ")] * bool(i)
                        + [make_code(path)]
                    ],
                    make_text(", this document's own output; "),
                    make_code("calkit status"),
                    make_text(" checks it"),
                )
            )
        gaps = [
            {"path": gap.path, "unchecked": gap.unchecked}
            for gap in find_provenance_gaps(
                roots,
                ck_info=ck_info,
                dvc_yaml={"stages": yaml_stages},
                dvc_lock={"stages": lock_stages},
                is_data=lambda p: is_data_path(
                    p, is_file=is_file, is_dir=is_dir, listdir=listdir
                ),
                listdir=lambda p: listdir(p) if is_dir(p) else [],
            )
        ]
        if troubled:
            kind = "danger"
            title = (
                f"Document out of date: {len(troubled)} of {n_outputs} outputs"
            )
            children.append(get_update_paragraph())
        elif gaps:
            kind = "warning"
            title = "Document has incomplete provenance: " + get_gap_words(
                gaps[0]
            )
            if len(gaps) > 1:
                title += f" and {len(gaps) - 1} more"
            children.append(get_fix_paragraph(gaps))
        elif doc_stage not in stages:
            kind = "warning"
            title = "Document has incomplete provenance: no stage renders it"
        else:
            kind = "note"
            title = "Document up to date"
        return make_admonition(kind, title, children, dropdown=kind == "note")

    document_path = posixpath.normpath(Path(document_path).as_posix())
    ck_stages = (ck_info.get("pipeline") or {}).get("stages") or {}
    envs = ck_info.get("environments") or {}
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
    for name, stage in lock_stages.items():
        wdir = yaml_stages[name.split("@")[0]].get("wdir") or ""
        stages[name] = (
            get_paths((stage or {}).get("deps"), wdir),
            get_paths((stage or {}).get("outs"), wdir),
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
    statuses: dict[str, dict] = {}
    waiting: dict[str, list[str]] = {}
    closure = get_closure(
        [d.path for d in divs if d.path]
        + (stages[doc_stage][0] if doc_stage in stages else [])
    )
    out: dict[str, Any] = {"panels": {}, "document": None}
    for div in divs:
        if div.kind == "document":
            if out["document"] is None:
                out["document"] = {
                    "kind": "document",
                    "body": [],
                    "panel": [get_document_panel()],
                }
            continue
        if div.src in out["panels"]:
            continue
        if div.kind == "table":
            body = get_table_body(div)
        elif div.kind == "file":
            body = [make_paragraph(make_code(div.src))]
        else:
            body = []
        out["panels"][div.src] = {
            "kind": div.kind,
            "body": body,
            "panel": [get_file_panel(div)],
        }
    return out


def get_provenance_path(document_path: str) -> str:
    """Where the panels for a document are written, relative to the
    project, as the filter finds them."""
    document_path = posixpath.normpath(Path(document_path).as_posix())
    return posixpath.join(PROVENANCE_DIR, document_path + ".json")


def write_provenance(
    divs: list[ProvenanceDiv],
    document_path: str,
    ck_info: dict,
    wdir: str | None = None,
    document_stage: str | None = None,
) -> str:
    """Write what a document's ``ckprovenance`` divs show, from the project
    in ``wdir`` as it is, returning where, relative to it.

    Written before every render, so the panels say how the pipeline stood
    when the document was rendered, and kept out of Git, like the rest of
    ``.calkit/local``, with the document's SHA-1, so what shows them can
    tell it changed since.
    """
    import hashlib

    import calkit
    import calkit.dvc

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
        # From DVC, run from the project so it names paths relative to it
        if not dvc_stages:
            try:
                repo = calkit.dvc.get_dvc_repo(
                    wdir=os.path.abspath(wdir or ".")
                )
                dvc_stages.update(
                    {stage.addressing: stage for stage in repo.index.stages}
                )
            except Exception as e:
                raise ValueError(f"Can't read the pipeline to check it: {e}")
        if name not in dvc_stages:
            return {"status": "not-run"}
        prev_wdir = os.getcwd()
        try:
            os.chdir(wdir or ".")
            return get_stage_status(dvc_stages[name])
        finally:
            os.chdir(prev_wdir)

    def read_bytes(path: str) -> bytes:
        with open(get_full_path(path), "rb") as f:
            return f.read()

    def open_text(path: str) -> IO[str]:
        # Without a byte order mark, and with what isn't UTF-8 replaced
        return open(
            get_full_path(path),
            encoding="utf-8-sig",
            errors="replace",
            newline="",
        )

    dvc_stages: dict[str, Any] = {}
    panels = get_provenance_panels(
        divs,
        document_path,
        document_stage=document_stage,
        ck_info=ck_info,
        dvc_yaml=read_yaml("dvc.yaml"),
        dvc_lock=read_yaml("dvc.lock"),
        stage_runs=calkit.core.read_stage_runs(wdir=wdir),
        get_stage_status=get_status,
        is_file=lambda p: os.path.isfile(get_full_path(p)),
        is_dir=lambda p: os.path.isdir(get_full_path(p)),
        listdir=lambda p: (
            os.listdir(get_full_path(p))
            if os.path.isdir(get_full_path(p))
            else []
        ),
        read_bytes=read_bytes,
        open_text=open_text,
    )
    # So what shows them can tell the document changed since
    with open(get_full_path(document_path), "rb") as f:
        panels["source_sha1"] = hashlib.sha1(f.read()).hexdigest()
    calkit.core.ensure_local_dir(wdir)
    rel_path = get_provenance_path(document_path)
    fpath = get_full_path(rel_path)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    calkit.core.write_if_changed(
        fpath, json.dumps(panels, indent=2, ensure_ascii=False) + "\n"
    )
    return rel_path


def get_filter_problem(
    text: str,
    document_path: str,
    wdir: str | None = None,
    to: str | None = None,
) -> str | None:
    """Why the filter that shows ``ckprovenance`` divs won't run for a
    document, or None if it will, from the ``filters`` its front matter,
    its folders' ``_metadata.yml``, and its Quarto project's
    ``_quarto.yml`` list, since Quarto only runs a filter that's listed,
    and this one has to run before Quarto numbers figures.

    Filters listed for a format count for that format, i.e., ``to``, e.g.,
    ``html``, or for any without one.
    """
    import io

    import calkit

    def load(content: str) -> dict:
        try:
            data = calkit.core._load_yaml_readonly(io.StringIO(content))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def get_filters(meta: dict) -> list:
        found = list(meta.get("filters") or [])
        formats = meta.get("format")
        for name, fmt in (
            formats if isinstance(formats, dict) else {}
        ).items():
            # E.g., html for an html+raw or an html with extensions
            base = re.split(r"[+-]", str(name))[0]
            if isinstance(fmt, dict) and (to is None or base == to_base):
                found += list(fmt.get("filters") or [])
        return found

    to_base = re.split(r"[+-]", to)[0] if to else None

    document_path = posixpath.normpath(Path(document_path).as_posix())
    filters = []
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*(\n|$)", text, flags=re.DOTALL)
    if m is not None:
        filters += get_filters(load(m.group(1)))
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
                    filters += get_filters(load(f.read()))
        if folder in ("", ".", quarto_dir):
            break
        folder = posixpath.dirname(folder)
    entries = [
        f
        for f in filters
        if f == "calkit" or (isinstance(f, dict) and f.get("path") == "calkit")
    ]
    if any(isinstance(f, dict) and f.get("at") == "pre-ast" for f in entries):
        return None
    where = "listed" if not entries else "listed to run at pre-ast"
    return (
        f"The '{PROVENANCE_CLASS}' divs in {document_path} need Calkit's "
        f"filter {where}, before Quarto numbers figures; add this to its "
        f"front matter or _quarto.yml:\n\n{FILTER_CONFIG}"
    )
