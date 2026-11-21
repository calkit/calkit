-- Written by Calkit; changes are overwritten when the pipeline compiles.
-- Shows values from pipeline results with
-- {{< ckvalue results.json key .2f >}}, which Calkit resolves into
-- _calkit/values/<document path>.json each time the pipeline renders it.

local function read_values()
  local input = quarto.doc.input_file
  local root = quarto.project.directory or pandoc.path.directory(input)
  -- A notebook is rendered from a copy, e.g., analysis.quarto_ipynb
  local stem = pandoc.path.split_extension(
    pandoc.path.make_relative(input, root)
  )
  local fpath = pandoc.path.join({root, "_calkit", "values", stem .. ".json"})
  local f = io.open(fpath, "r")
  if f == nil then
    return {}
  end
  local content = f:read("a")
  f:close()
  return quarto.json.decode(content)
end

local values = nil

return {
  ["ckvalue"] = function(args, kwargs)
    if values == nil then
      values = read_values()
    end
    local slots = {"", "", ""}
    for i = 1, math.min(#args, 3) do
      slots[i] = pandoc.utils.stringify(args[i])
    end
    for name, slot in pairs({name = 1, path = 1, key = 2, format = 3}) do
      local value = pandoc.utils.stringify(kwargs[name] or "")
      if value ~= "" then
        slots[slot] = value
      end
    end
    local id = table.concat(slots, "\t")
    local text = values[id]
    if text == nil then
      quarto.log.warning(
        "No value for ckvalue " .. slots[1] .. " " .. slots[2]
          .. "; run the pipeline to resolve it"
      )
      return pandoc.Str("??")
    end
    return pandoc.Str(text)
  end,
}
