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
  if kind ~= "path" and result_paths[source] ~= nil then
    return result_paths[source]
  end
  return source
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
}
