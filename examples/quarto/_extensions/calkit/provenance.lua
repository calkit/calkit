---@diagnostic disable: undefined-global
-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows a file from the project with ::: {.ckfigure src="figures/fit.png"},
-- .cktable for a CSV or TSV file, or .ckinclude for anything else, with
-- where it came from collapsed under it. Calkit decides what that says
-- before rendering, and writes it to .calkit/local/provenance; this only
-- turns it into Pandoc's AST. It has to run at pre-ast, so Quarto numbers
-- figures and tables after.

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
details.ck-provenance[open]{border-left:2px solid #dee2e6;
  padding-left:.75rem}
.ck-value{cursor:pointer;border-bottom:1px dotted currentColor}
button.ck-value{all:unset;cursor:pointer;
  border-bottom:1px dotted currentColor}
button.ck-value:focus-visible{outline:2px solid #0d6efd;outline-offset:2px}
.ck-value:not(.ck-ok),.ck-value.ck-outdated{border-bottom-color:#b35900}
.ck-flag{color:#b35900;font-size:.7em;margin-left:.1em;
  vertical-align:super}
.ck-popover{max-width:min(48rem,92vw);max-height:80vh;overflow:auto;
  padding:1rem;border:1px solid #dee2e6;border-radius:.375rem;
  font-size:.9em}
.ck-popover table{border-collapse:collapse;margin-bottom:1rem}
.ck-popover th,.ck-popover td{padding:.2rem .6rem;text-align:left;
  border-bottom:1px solid #dee2e6}
.ck-provenance svg,.ck-popover svg{--mermaid-label-fg-color:inherit;
  --mermaid-node-fg-color:#6c757d}
.ck-provenance svg .nodeLabel,.ck-popover svg .nodeLabel{color:inherit}
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
