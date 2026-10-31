-- Lay out the one-pager's Markdown for the page, so the Markdown itself can
-- read naturally anywhere: the lead image moves up beside the numbers, the
-- "By the numbers" section becomes the box they're shown in, and a section
-- marked {.box} becomes a full-width box between the columns, and a
-- footer div goes in the page's footer

local function latex(inlines)
  local out = pandoc.write(pandoc.Pandoc({ pandoc.Plain(inlines) }), "latex")
  return (out:gsub("%s+$", ""))
end

local function number(item)
  -- A bold value, then what it measures
  local inlines = item[1].content
  local value = table.remove(inlines, 1)
  if inlines[1] and inlines[1].t == "Space" then
    table.remove(inlines, 1)
  end
  local shown = value.t == "Strong" and latex(value.content) or latex({ value })
  return "\\cknumber{" .. shown .. "}{" .. latex(inlines) .. "}"
end

function Span(span)
  -- A phrase to make pop, e.g., in the title
  if span.classes:includes("highlight") then
    return { pandoc.RawInline("latex", "\\textcolor{ckhighlight}{") }
      .. span.content .. { pandoc.RawInline("latex", "}") }
  end
end

function Pandoc(doc)
  local blocks = {}
  local i = 1
  while i <= #doc.blocks do
    local b = doc.blocks[i]
    local image = nil
    if b.t == "Figure" then
      image = b.content[1].content[1]
    elseif b.t == "Para" and #b.content == 1 and b.content[1].t == "Image" then
      image = b.content[1]
    end
    if image ~= nil and doc.meta.hero == nil then
      doc.meta.hero = pandoc.MetaString(image.src)
      i = i + 1
    elseif b.t == "Header" and b.identifier == "by-the-numbers" then
      local cells, notes = {}, {}
      i = i + 1
      while i <= #doc.blocks
        and not (doc.blocks[i].t == "Header" and doc.blocks[i].level <= b.level)
      do
        local c = doc.blocks[i]
        if c.t == "BulletList" then
          for _, item in ipairs(c.content) do
            table.insert(cells, number(item))
          end
        else
          table.insert(notes, pandoc.write(pandoc.Pandoc({ c }), "latex"))
        end
        i = i + 1
      end
      doc.meta.numbers = pandoc.MetaBlocks({
        pandoc.RawBlock("latex", table.concat(cells, "\n")),
      })
      if #notes > 0 then
        doc.meta["numbers-note"] = pandoc.MetaBlocks({
          pandoc.RawBlock("latex", table.concat(notes, "\n")),
        })
      end
    elseif b.t == "Div" and b.classes:includes("footer") then
      doc.meta.footer = pandoc.MetaInlines(pandoc.utils.blocks_to_inlines(b.content))
      i = i + 1
    elseif b.t == "Header" and b.classes:includes("box") then
      -- Its own columns, balanced, so a long quote can flow from one to the
      -- other rather than set the box's height
      table.insert(blocks, pandoc.RawBlock("latex",
        "\\end{multicols}\n\\begin{ckbox}{" .. latex(b.content) .. "}\n"
        .. "\\begin{multicols}{2}\\ckbody"))
      i = i + 1
      while i <= #doc.blocks
        and not (doc.blocks[i].t == "Header" and doc.blocks[i].level <= b.level)
      do
        table.insert(blocks, doc.blocks[i])
        i = i + 1
      end
      table.insert(blocks, pandoc.RawBlock("latex",
        "\\end{multicols}\n\\end{ckbox}\n\\begin{multicols}{2}\\ckbody"))
    else
      table.insert(blocks, b)
      i = i + 1
    end
  end
  doc.blocks = blocks
  return doc
end
