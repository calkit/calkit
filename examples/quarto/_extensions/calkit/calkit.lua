---@diagnostic disable: undefined-global
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
    local f = io.open(input, "rb")
    local notebook = input:lower():match("%.ipynb$")
    if data and data.source_sha1 and f ~= nil and not notebook then
      outdated = pandoc.utils.sha1(f:read("a")) ~= data.source_sha1
    end
    if f ~= nil then
      f:close()
    end
  end
  return outdated
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

-- How a view looks, and drawing its graph with Quarto's own Mermaid when
-- it's opened, since Mermaid can't measure text while it's hidden
local ASSETS = [[
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
details.ck-provenance[open]{border-left:2px solid #dee2e6;
  padding-left:.75rem}
button.ck-value{all:unset;cursor:pointer;
  border-bottom:1px dotted currentColor}
button.ck-value:focus-visible{outline:2px solid #0d6efd;outline-offset:2px}
button.ck-value:not(.ck-ok),button.ck-value.ck-outdated{
  border-bottom-color:#b35900}
.ck-flag{color:#b35900;font-size:.7em;margin-left:.1em}
.ck-popover{max-width:min(48rem,92vw);max-height:80vh;overflow:auto;
  padding:1rem;border:1px solid #dee2e6;border-radius:.375rem;
  font-size:.9em}
.ck-popover table{border-collapse:collapse;margin-bottom:1rem}
.ck-popover th,.ck-popover td{padding:.2rem .6rem;text-align:left;
  border-bottom:1px solid #dee2e6}
</style>
<script>
document.addEventListener("toggle", async (event) => {
  const el = event.target;
  if (!(el.open || event.newState === "open") || !window.mermaid) return;
  for (const pre of el.querySelectorAll("pre.ck-mermaid:not([data-drawn])")) {
    pre.dataset.drawn = "true";
    const id = "ck-mermaid-" + Math.random().toString(36).slice(2);
    const { svg } = await window.mermaid.render(id, pre.textContent);
    pre.innerHTML = svg;
  }
}, true);
</script>
]]
local assets_ready = false
local function add_assets()
  if assets_ready then
    return
  end
  local share = os.getenv("QUARTO_SHARE_PATH")
  if share then
    local function asset(name)
      return pandoc.path.join({share, "formats", "html", "mermaid", name})
    end
    -- The same files, under the same name, as Quarto's own diagrams
    quarto.doc.add_html_dependency({
      name = "quarto-diagram",
      scripts = {asset("mermaid.min.js"), asset("mermaid-init.js")},
      stylesheets = {asset("mermaid.css")},
    })
  end
  quarto.doc.include_text("in-header", ASSETS)
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

local function get_classes(base, provenance, data)
  return base .. " ck-" .. (provenance.state or "ok")
    .. (is_outdated(data) and " ck-outdated" or "")
end

-- The line shown while it's collapsed, which says what's wrong
local function get_summary(provenance, data)
  local out = inlines(provenance.summary)
  if is_outdated(data) then
    out:extend(words(" · recorded before this document changed"))
  end
  return out
end

-- How it came to be, under a note if the document changed since
local function get_view(provenance, data)
  local out = pandoc.Blocks({})
  if is_outdated(data) then
    out:insert(pandoc.Para(words(
      "The document changed since this was recorded; render it with "
        .. "Calkit to update it."
    )))
  end
  out:extend(blocks(provenance.view))
  return out
end

local n_popovers = 0
local function with_provenance(text, key, kwargs)
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
  n_popovers = n_popovers + 1
  local id = "ck-value-" .. n_popovers
  local summary = get_summary(provenance, data)
  local label = "Where " .. text .. " came from: "
    .. pandoc.utils.stringify(summary)
  local warn = provenance.state ~= "ok" or is_outdated(data)
  local content = pandoc.Blocks({pandoc.Para(summary)})
  content:extend(get_view(provenance, data))
  quarto.doc.include_text(
    "after-body",
    '<div id="' .. id .. '" popover class="ck-popover">'
      .. to_html(content) .. "</div>"
  )
  return pandoc.Inlines({
    pandoc.RawInline(
      "html",
      '<button type="button" class="'
        .. get_classes("ck-value", provenance, data)
        .. '" popovertarget="' .. id .. '" aria-label="' .. escape(label)
        .. '" title="' .. escape(pandoc.utils.stringify(summary)) .. '">'
    ),
    pandoc.Str(text),
    pandoc.RawInline(
      "html",
      (warn and '<sup class="ck-flag" aria-hidden="true">⚠</sup>' or "")
        .. "</button>"
    ),
  })
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
    return with_provenance(text, path .. ":" .. key, kwargs)
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
    return with_provenance(text, "ref:" .. key .. ":" .. name, kwargs)
  end,
}
