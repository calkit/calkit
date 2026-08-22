// Just enough of the .ipynb format to edit sources and run cells.

export type CellType = "code" | "markdown" | "raw"

export interface NotebookCell {
  id: string
  type: CellType
  source: string
}

export interface ParsedNotebook {
  cells: NotebookCell[]
  /** The file as parsed, kept so everything we don't touch round-trips. */
  raw: any
}

const joinSource = (source: unknown): string =>
  Array.isArray(source) ? source.join("") : String(source ?? "")

/** Split a source the way Jupyter stores it: one string per line, with
 * the newline kept on each line but the last. */
export const splitSource = (text: string): string[] => {
  if (!text) return []
  const lines = text.split("\n")
  return lines
    .map((line, i) => (i < lines.length - 1 ? `${line}\n` : line))
    .filter((line, i, arr) => !(i === arr.length - 1 && line === ""))
}

/**
 * An id per raw cell, unique within the notebook.
 *
 * A cell's own id is used when it has one; a generated fallback, or a
 * duplicate of an earlier id, gets a suffix, so that what the UI keys by
 * can never point at two cells. Parsing and serializing both go through
 * this, so the ids line up.
 */
export function cellIds(raw: any): string[] {
  const seen = new Set<string>()
  return ((raw.cells ?? []) as any[]).map((cell, index) => {
    const base = String(cell.id ?? `cell-${index}`)
    let id = base
    for (let n = 2; seen.has(id); n++) id = `${base}-${n}`
    seen.add(id)
    return id
  })
}

/** The cells of a notebook, each with a stable id for the UI. */
export function parseNotebook(text: string): ParsedNotebook {
  const raw = JSON.parse(text)
  const ids = cellIds(raw)
  const cells: NotebookCell[] = (raw.cells ?? []).map(
    (cell: any, index: number) => ({
      id: ids[index],
      type: (cell.cell_type as CellType) ?? "code",
      source: joinSource(cell.source),
    }),
  )
  return { cells, raw }
}

/**
 * The notebook with edited sources written back.
 *
 * A cell whose source changed has its outputs cleared, since they no longer
 * describe that code; the pipeline run is what makes fresh ones. Anything
 * else in the file (metadata, unchanged cells' outputs) is left as it was.
 */
export function serializeNotebook(
  parsed: ParsedNotebook,
  cells: NotebookCell[],
): string {
  const byId = new Map(cells.map((c) => [c.id, c]))
  const originalById = new Map(parsed.cells.map((c) => [c.id, c]))
  const ids = cellIds(parsed.raw)
  const rawCells = (parsed.raw.cells ?? []).map((cell: any, index: number) => {
    const id = ids[index]
    const edited = byId.get(id)
    const original = originalById.get(id)
    if (!edited || !original || edited.source === original.source) return cell
    const next = { ...cell, source: splitSource(edited.source) }
    if (cell.cell_type === "code") {
      next.outputs = []
      next.execution_count = null
    }
    return next
  })
  return `${JSON.stringify({ ...parsed.raw, cells: rawCells }, null, 1)}\n`
}
