---@diagnostic disable: undefined-global
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
    local _, ext = pandoc.path.split_extension(src)
    if PICTURE_EXTS[ext:lower()] then
      out:extend(get_figure(
        el, pandoc.Blocks({pandoc.Plain({get_image(el, src)})})
      ))
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
