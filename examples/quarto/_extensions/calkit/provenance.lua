---@diagnostic disable: undefined-global
-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows a file from the project with ::: {.ckfigure src="figures/fit.png"},
-- .cktable for a CSV or TSV file, or .ckinclude for anything else, with
-- where it came from collapsed under it. Calkit decides what that says
-- before rendering, and writes it to .calkit/local/provenance; this only
-- turns it into Pandoc's AST. It has to run at pre-ast, so Quarto numbers
-- figures and tables after.

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

local KINDS = {ckfigure = "figure", cktable = "table", ckinclude = "include"}
local MARKDOWN_EXTS = {[".md"] = true, [".qmd"] = true}

-- A file's path relative to the document, as an image's is read, when
-- nothing's recorded to say it
local function get_url(src)
  local project_dir = find_project_dir()
  return pandoc.path.make_relative(
    pandoc.path.join({project_dir, src}),
    pandoc.path.directory(quarto.doc.input_file),
    true
  )
end

local function get_image(el, url)
  local attributes = {}
  for _, key in ipairs({"width", "height", "fig-align", "fig-alt"}) do
    if el.attributes[key] then
      table.insert(attributes, {key, el.attributes[key]})
    end
  end
  local alt = el.attributes.alt and words(el.attributes.alt)
    or pandoc.Inlines({})
  return pandoc.Image(alt, url, "", pandoc.Attr("", {}, attributes))
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

local function is_off(value)
  value = (value or ""):lower()
  return value == "false" or value == "no" or value == "0" or value == "off"
end

-- Collapsed under it in HTML, saying what's wrong while it is, and only
-- that, in a line, in other formats
local function get_provenance(provenance, data)
  if quarto.doc.is_format("html:js") then
    add_assets()
    local classes = get_classes("ck-provenance", provenance, data)
    local out = pandoc.Blocks({
      pandoc.RawBlock(
        "html",
        '<details class="' .. classes .. '"><summary>'
          .. to_html({pandoc.Plain(get_summary(provenance, data))})
          .. "</summary>"
      ),
    })
    out:extend(get_view(provenance, data))
    out:insert(pandoc.RawBlock("html", "</details>"))
    return out
  end
  if provenance.line then
    return pandoc.Blocks({pandoc.Para({pandoc.Emph(inlines(provenance.line))})})
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
  local data = load_records()
  local record = data and (data.components or {})[src] or nil
  local url = record and record.url or get_url(src)
  local out = pandoc.Blocks({})
  if kind == "figure" then
    out:extend(get_figure(
      el, pandoc.Blocks({pandoc.Plain({get_image(el, url)})})
    ))
  elseif kind == "table" then
    local content = record and blocks(record.body) or pandoc.Blocks({
      -- Only its name, keeping its id and caption, so references resolve
      pandoc.utils.from_simple_table(pandoc.SimpleTable(
        {}, {pandoc.AlignDefault}, {0}, {},
        {{{pandoc.Plain({pandoc.Code(src)})}}}
      )),
    })
    for index, item in ipairs(content) do
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
    local _, ext = pandoc.path.split_extension(src)
    local text = MARKDOWN_EXTS[ext:lower()]
      and read_file(pandoc.path.join({find_project_dir(), src})) or nil
    local content = text and pandoc.read(text, "markdown").blocks
      or pandoc.Blocks({pandoc.Para({pandoc.Code(src)})})
    content:extend(el.content)
    out:insert(pandoc.Div(content, pandoc.Attr(el.identifier, {}, {})))
  end
  if is_off(el.attributes.provenance) then
    return out
  end
  if record == nil then
    out:extend(unrecorded())
  elseif record.provenance then
    out:extend(get_provenance(record.provenance, data))
  end
  return out
end

local function handle(el)
  for name, kind in pairs(KINDS) do
    if el.classes:includes(name) then
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
