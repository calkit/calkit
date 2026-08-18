// Parsing tabular files into columns and rows for display.
//
// Everything here works on text that's already been fetched: the caller
// decides whether that came from inlined base64 content or a storage URL.

export interface ParsedTable {
  columns: string[]
  rows: string[][]
}

// Split delimited text into raw fields, honoring RFC 4180 quoting: a quoted
// field can hold the delimiter, newlines, and doubled quotes. Hand-rolled
// rather than pulled in as a dependency, since this is the whole of what we
// need from one.
const parseDelimited = (text: string, delimiter: string): string[][] => {
  const rows: string[][] = []
  let row: string[] = []
  let field = ""
  let quoted = false
  let i = 0
  const pushField = () => {
    row.push(field)
    field = ""
  }
  const pushRow = () => {
    pushField()
    rows.push(row)
    row = []
  }
  while (i < text.length) {
    const char = text[i]
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i += 2
          continue
        }
        quoted = false
        i += 1
        continue
      }
      field += char
      i += 1
      continue
    }
    if (char === '"' && field === "") {
      quoted = true
      i += 1
      continue
    }
    if (char === delimiter) {
      pushField()
      i += 1
      continue
    }
    if (char === "\r" || char === "\n") {
      pushRow()
      // A CRLF ends one row, not two.
      i += char === "\r" && text[i + 1] === "\n" ? 2 : 1
      continue
    }
    field += char
    i += 1
  }
  // Trailing newlines are terminators, not an empty final row, so only keep
  // what's actually pending.
  if (field !== "" || row.length > 0) pushRow()
  return rows
}

// Trim a UTF-8 byte order mark, which otherwise becomes part of the first
// column's name and stops it matching anything.
const stripBom = (text: string) => text.replace(/^﻿/, "")

const fromDelimited = (text: string, delimiter: string): ParsedTable | null => {
  const raw = parseDelimited(stripBom(text), delimiter).filter(
    (row) => row.length > 1 || row.some((cell) => cell.trim() !== ""),
  )
  if (raw.length === 0) return null
  const columns = raw[0].map((c) => c.trim())
  const width = Math.max(...raw.map((r) => r.length))
  // A ragged row is padded rather than dropped: a missing trailing field is
  // ordinary in hand-edited CSV, and losing the row loses data.
  while (columns.length < width) columns.push("")
  const rows = raw.slice(1).map((r) => {
    const padded = r.slice(0, width)
    while (padded.length < width) padded.push("")
    return padded
  })
  return { columns, rows }
}

const fromJsonLines = (text: string): ParsedTable | null => {
  const records: unknown[] = []
  for (const line of stripBom(text).split(/\r?\n/)) {
    if (!line.trim()) continue
    try {
      records.push(JSON.parse(line))
    } catch {
      // One bad line shouldn't cost the reader the rest of the file.
    }
  }
  if (records.length === 0) return null
  const asCell = (value: unknown) => {
    if (value === null || value === undefined) return ""
    if (typeof value === "object") return JSON.stringify(value)
    return String(value)
  }
  // Objects are the common shape: columns are the union of their keys, in the
  // order they're first seen, so the file's own ordering survives.
  if (records.every((r) => r !== null && typeof r === "object")) {
    const columns: string[] = []
    for (const record of records) {
      for (const key of Object.keys(record as Record<string, unknown>)) {
        if (!columns.includes(key)) columns.push(key)
      }
    }
    const rows = records.map((record) =>
      columns.map((key) => asCell((record as Record<string, unknown>)[key])),
    )
    return { columns, rows }
  }
  return {
    columns: ["value"],
    rows: records.map((record) => [asCell(record)]),
  }
}

// Strip the TeX markup that carries no data: rules, spacing, and the
// formatting commands a generated table wraps its cells in.
const cleanTexCell = (cell: string): string => {
  let out = cell
  // \multicolumn{2}{c}{Header} and \multirow{2}{*}{Header} keep their text
  out = out.replace(
    /\\(multicolumn|multirow)\s*\{[^}]*\}\s*\{[^}]*\}\s*\{([\s\S]*?)\}/g,
    "$2",
  )
  // One level of the usual font commands, applied repeatedly so nested ones
  // (\textbf{\textit{x}}) unwrap too
  for (let i = 0; i < 3; i++) {
    out = out.replace(
      /\\(textbf|textit|texttt|textsf|emph|mathrm|text)\s*\{([\s\S]*?)\}/g,
      "$2",
    )
  }
  out = out.replace(/\\(hline|toprule|midrule|bottomrule|addlinespace)\b/g, "")
  out = out.replace(/\\cmidrule\s*(\([^)]*\))?\s*\{[^}]*\}/g, "")
  out = out.replace(/\\(?:num|si|SI)\s*\{([^}]*)\}/g, "$1")
  // Escaped characters become themselves; ~ is a space
  out = out.replace(/\\([%$&#_{}])/g, "$1")
  out = out.replace(/~/g, " ")
  out = out.replace(/\\\s/g, " ")
  return out.trim()
}

const fromTex = (text: string): ParsedTable | null => {
  const envMatch = text.match(
    /\\begin\{(tabular\*?|tabularx|longtable|tabu)\}([\s\S]*?)\\end\{\1\}/,
  )
  if (!envMatch) return null
  let body = envMatch[2]
  // Drop the column spec (and any width argument before it) that follows
  // \begin{tabular}, which is layout rather than content.
  body = body.replace(/^\s*(\{[^{}]*\}\s*)?(\[[^\]]*\]\s*)?\{[^{}]*\}/, "")
  const lines: string[][] = []
  for (const rawRow of body.split(/\\\\/)) {
    // A row's cells are separated by & -- but not by an escaped \&, which is
    // a literal ampersand inside one cell.
    const cells = rawRow
      .split(/(?<!\\)&/)
      .map(cleanTexCell)
      .map((cell) => cell.replace(/\\&/g, "&"))
    if (cells.every((cell) => cell === "")) continue
    lines.push(cells)
  }
  if (lines.length === 0) return null
  const width = Math.max(...lines.map((r) => r.length))
  const pad = (row: string[]) => {
    const out = row.slice(0, width)
    while (out.length < width) out.push("")
    return out
  }
  return { columns: pad(lines[0]), rows: lines.slice(1).map(pad) }
}

/**
 * Parse a table file's text into columns and rows, keyed off its extension.
 *
 * Returns null when the file holds nothing tabular, which callers show as
 * raw text rather than an empty grid.
 */
export const parseTable = (path: string, text: string): ParsedTable | null => {
  const ext = path.toLowerCase().split(".").pop() ?? ""
  if (ext === "csv") return fromDelimited(text, ",")
  if (ext === "tsv") return fromDelimited(text, "\t")
  if (ext === "jsonl" || ext === "ndjson") return fromJsonLines(text)
  if (ext === "tex") return fromTex(text)
  return null
}

/**
 * The cell's value as a number, or null if it isn't one.
 *
 * Used both to sort numerically and to right-align numeric columns. Commas
 * as thousands separators and a trailing % are tolerated, since a table
 * written for a reader is full of both.
 */
export const cellAsNumber = (cell: string): number | null => {
  const trimmed = cell.trim().replace(/,/g, "").replace(/%$/, "")
  if (trimmed === "") return null
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : null
}

/**
 * A row paired with its position in the file.
 *
 * Sorting and filtering reorder and drop rows, but a highlight in a shared
 * link names a row by where it sits in the file, so that number has to
 * travel with the row rather than being its position on screen.
 */
export interface TableRow {
  index: number
  cells: string[]
}

/** Pair each row with its position in the file, counting from 1. */
export const indexRows = (rows: string[][]): TableRow[] =>
  rows.map((cells, i) => ({ index: i + 1, cells }))

/** Whether most of a column's non-empty cells are numbers. */
export const isNumericColumn = (rows: TableRow[], index: number): boolean => {
  let numeric = 0
  let filled = 0
  for (const row of rows) {
    const cell = row.cells[index] ?? ""
    if (cell.trim() === "") continue
    filled += 1
    if (cellAsNumber(cell) !== null) numeric += 1
  }
  return filled > 0 && numeric / filled >= 0.8
}

/**
 * Sort rows by one column, numerically where the column holds numbers.
 *
 * Empty cells sort last in both directions, so a partially filled column
 * doesn't bury its values under blanks.
 */
export const sortRows = (
  rows: TableRow[],
  index: number,
  direction: "asc" | "desc",
): TableRow[] => {
  const numeric = isNumericColumn(rows, index)
  const sign = direction === "asc" ? 1 : -1
  return [...rows].sort((a, b) => {
    const left = (a.cells[index] ?? "").trim()
    const right = (b.cells[index] ?? "").trim()
    if (left === "" || right === "") {
      if (left === right) return 0
      return left === "" ? 1 : -1
    }
    if (numeric) {
      const ln = cellAsNumber(left)
      const rn = cellAsNumber(right)
      if (ln !== null && rn !== null) return sign * (ln - rn)
      if (ln !== null) return -sign
      if (rn !== null) return sign
    }
    return sign * left.localeCompare(right, undefined, { numeric: true })
  })
}

/** Rows holding `needle` in any cell, matched case-insensitively. */
export const filterRows = (rows: TableRow[], needle: string): TableRow[] => {
  const query = needle.trim().toLowerCase()
  if (!query) return rows
  return rows.filter((row) =>
    row.cells.some((cell) => cell.toLowerCase().includes(query)),
  )
}

/**
 * A highlighted region of a table, in 1-based file coordinates.
 *
 * An open end means "all of them": a range with no columns covers whole
 * rows, and one with no rows covers whole columns.
 */
export interface HighlightRange {
  rowStart?: number
  rowEnd?: number
  colStart?: number
  colEnd?: number
}

const parseSpan = (spec: string): [number, number] | null => {
  const match = spec.match(/^(\d+)(?:-(\d+))?$/)
  if (!match) return null
  const start = Number(match[1])
  const end = match[2] === undefined ? start : Number(match[2])
  if (start < 1 || end < 1) return null
  return start <= end ? [start, end] : [end, start]
}

/**
 * Parse a highlight spec from a URL into ranges.
 *
 * The spec is comma-separated, each part naming rows, columns, or both, in
 * 1-based numbers as shown in the table: "r3" is one row, "c2-4" three
 * columns, "r2-4c1" a block, and "r3c2,r8c5" two separate cells. Parts that
 * don't parse are dropped rather than failing the whole link.
 */
export const parseHighlight = (spec: string | undefined): HighlightRange[] => {
  if (!spec) return []
  const ranges: HighlightRange[] = []
  for (const part of spec.split(",")) {
    const match = part.trim().match(/^(?:r([\d-]+))?(?:c([\d-]+))?$/i)
    if (!match || (!match[1] && !match[2])) continue
    const rows = match[1] ? parseSpan(match[1]) : null
    const cols = match[2] ? parseSpan(match[2]) : null
    if ((match[1] && !rows) || (match[2] && !cols)) continue
    ranges.push({
      rowStart: rows?.[0],
      rowEnd: rows?.[1],
      colStart: cols?.[0],
      colEnd: cols?.[1],
    })
  }
  return ranges
}

/** Render ranges back into the spec a link carries. */
export const formatHighlight = (ranges: HighlightRange[]): string =>
  ranges
    .map((range) => {
      const span = (start?: number, end?: number) =>
        start === undefined
          ? ""
          : end === undefined || end === start
            ? String(start)
            : `${start}-${end}`
      const rows = span(range.rowStart, range.rowEnd)
      const cols = span(range.colStart, range.colEnd)
      return `${rows ? `r${rows}` : ""}${cols ? `c${cols}` : ""}`
    })
    .filter(Boolean)
    .join(",")

/** Whether a cell, in 1-based file coordinates, falls in any range. */
export const isCellHighlighted = (
  ranges: HighlightRange[],
  row: number,
  column: number,
): boolean =>
  ranges.some((range) => {
    const inRows =
      range.rowStart === undefined ||
      (row >= range.rowStart && row <= (range.rowEnd ?? range.rowStart))
    const inCols =
      range.colStart === undefined ||
      (column >= range.colStart && column <= (range.colEnd ?? range.colStart))
    return inRows && inCols
  })

/** The first row any range touches, for scrolling a shared link into view. */
export const firstHighlightedRow = (
  ranges: HighlightRange[],
): number | null => {
  const rows = ranges
    .map((range) => range.rowStart)
    .filter((row): row is number => row !== undefined)
  return rows.length > 0 ? Math.min(...rows) : null
}
