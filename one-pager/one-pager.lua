-- Lay out the one-pager's Markdown for the page, so the Markdown itself can
-- read naturally anywhere: the lead image moves up beside the numbers, and
-- the "By the numbers" section becomes the box they're shown in

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
    else
      table.insert(blocks, b)
      i = i + 1
    end
  end
  doc.blocks = blocks
  return doc
end
