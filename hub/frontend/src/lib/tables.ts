import { texToPlainText } from "./tex"

// Parsing tabular files into columns and rows for display.
//
// Everything here works on text that's already been fetched: the caller
// decides whether that came from inlined base64 content or a storage URL.

export interface ParsedTable {
  columns: string[]
  rows: string[][]
  // The TeX each cell was written as, present only for `.tex` tables. The
  // plain `columns`/`rows` above are what search, sorting, and the numeric
  // check read; these are what the grid renders, so `$T_{f,2}$` shows up
  // typeset rather than as its own source.
  texColumns?: string[]
  texRows?: string[][]
  // Set when the file stops before the table does, so the view can say the
  // rows are only what survived rather than presenting a partial table as
  // the whole thing.
  isTruncated?: boolean
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

// Strip the TeX that describes the table's *structure* rather than its
// contents: the rules between rows, and the wrappers a spanning cell sits
// in. What's left is the cell as written, math and font commands included,
// which the grid renders and `texToPlainText` reduces for search and sorting.
const cleanTexCell = (cell: string): string => {
  let out = cell
  // \multicolumn{2}{c}{Header} and \multirow{2}{*}{Header} keep their text
  out = out.replace(
    /\\(multicolumn|multirow)\s*\{[^}]*\}\s*\{[^}]*\}\s*\{([\s\S]*?)\}/g,
    "$2",
  )
  out = out.replace(/\\(hline|toprule|midrule|bottomrule|addlinespace)\b/g, "")
  out = out.replace(/\\(cmidrule|cline)\s*(\([^)]*\))?\s*\{[^}]*\}/g, "")
  // ~ is a non-breaking space, and a backslash before one is an explicit space
  out = out.replace(/~/g, " ")
  out = out.replace(/\\\s/g, " ")
  return out.trim()
}

/**
 * Whether a .tex file is a table in its own file, rather than a document
 * that happens to contain one.
 *
 * A paper is not a table: pulling the first tabular out of one would show a
 * fragment of a document as though it were the whole artifact. What counts
 * is a bare fragment -- what `to_latex` and friends write, with no preamble
 * -- or a document whose class is `standalone`, which exists for this. The
 * backend applies the same rule when auto-detecting tables.
 */
const isStandaloneTexTable = (text: string): boolean => {
  const documentClass = text.match(
    /\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}/,
  )
  if (!documentClass) return !text.includes("\\begin{document}")
  return documentClass[1].trim() === "standalone"
}

// Consume `count` brace groups (and an optional `[pos]` before them) from the
// start of `text`, returning what's left.
//
// Counting braces rather than matching them with a regex, because a real
// column spec nests: `{lL{0.07\linewidth}p{3cm}}` is one group, and a regex
// that stops at the first `}` leaves most of the layout sitting in the
// table's first cell.
const dropLeadingGroups = (text: string, count: number): string => {
  let i = 0
  const skipSpace = () => {
    while (i < text.length && /\s/.test(text[i])) i++
  }
  skipSpace()
  if (text[i] === "[") {
    while (i < text.length && text[i] !== "]") i++
    i++
  }
  for (let g = 0; g < count; g++) {
    skipSpace()
    if (text[i] !== "{") return text.slice(i)
    let depth = 0
    while (i < text.length) {
      if (text[i] === "{") depth++
      else if (text[i] === "}") {
        depth--
        if (depth === 0) {
          i++
          break
        }
      }
      i++
    }
  }
  return text.slice(i)
}

// A `%` runs to the end of its line and isn't data. A row commented out this
// way would otherwise be shown as though it were part of the table.
const stripTexComments = (text: string): string =>
  text.replace(/(^|[^\\])%.*$/gm, "$1")

const fromTex = (text: string): ParsedTable | null => {
  if (!isStandaloneTexTable(text)) return null
  const envMatch = text.match(
    /\\begin\{(tabular\*?|tabularx|longtable|tabu)\}([\s\S]*?)\\end\{\1\}/,
  )
  // A generator that died partway leaves the environment open. The rows it
  // did write are still a table, and showing them beats dropping the reader
  // back to raw TeX, so parse to the end of what's there and flag it.
  const openMatch =
    envMatch ??
    text.match(/\\begin\{(tabular\*?|tabularx|longtable|tabu)\}([\s\S]*)$/)
  if (!openMatch) return null
  const isTruncated = envMatch === null
  // `tabular*` and `tabularx` take a width before the column spec; the rest
  // take the spec alone. Either way it's layout, not content.
  const takesWidth = openMatch[1] === "tabular*" || openMatch[1] === "tabularx"
  let body = dropLeadingGroups(
    stripTexComments(openMatch[2]),
    takesWidth ? 2 : 1,
  )
  const lines: string[][] = []
  for (const rawRow of body.split(/\\\\/)) {
    // A row's cells are separated by & -- but not by an escaped \&, which is
    // a literal ampersand inside one cell.
    const cells = rawRow.split(/(?<!\\)&/).map(cleanTexCell)
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
  const texRows = lines.map(pad)
  const plainRows = texRows.map((row) => row.map(texToPlainText))
  return {
    columns: plainRows[0],
    rows: plainRows.slice(1),
    texColumns: texRows[0],
    texRows: texRows.slice(1),
    ...(isTruncated ? { isTruncated: true } : {}),
  }
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

/**
 * Rows holding `needle` in any cell, matched case-insensitively.
 *
 * `columns` limits the search to those 0-based column indexes, so a hidden
 * column doesn't leave rows on screen with no visible reason for matching.
 */
export const filterRows = (
  rows: TableRow[],
  needle: string,
  columns?: number[],
): TableRow[] => {
  const query = needle.trim().toLowerCase()
  if (!query) return rows
  // Searching every column is the common case and runs over every cell in the
  // table, so it stays a plain scan rather than building an index list per row.
  if (columns === undefined) {
    return rows.filter((row) =>
      row.cells.some((cell) => cell.toLowerCase().includes(query)),
    )
  }
  return rows.filter((row) =>
    columns.some((i) => (row.cells[i] ?? "").toLowerCase().includes(query)),
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

/** A column sort, in the 1-based column numbers a URL carries. */
export interface TableSort {
  column: number
  direction: "asc" | "desc"
}

/**
 * Parse a sort spec from a URL, e.g. "2" or "2:desc".
 *
 * The column is 1-based, matching the numbers highlight specs use, and an
 * omitted direction means ascending. Anything that doesn't parse means no
 * sort rather than a broken page.
 */
export const parseSort = (spec: string | undefined): TableSort | null => {
  if (!spec) return null
  const match = spec.trim().match(/^(\d+)(?::(asc|desc))?$/i)
  if (!match) return null
  const column = Number(match[1])
  if (column < 1) return null
  return {
    column,
    direction: match[2]?.toLowerCase() === "desc" ? "desc" : "asc",
  }
}

/** Render a sort back into the spec a link carries. */
export const formatSort = (sort: TableSort | null): string | undefined =>
  sort ? `${sort.column}:${sort.direction}` : undefined

/**
 * Parse a hidden-column spec from a URL, e.g. "2,5-7".
 *
 * Columns are 1-based and may be given as spans, so hiding a long run of
 * them doesn't blow the URL up. Parts that don't parse are dropped.
 */
export const parseHiddenColumns = (spec: string | undefined): number[] => {
  if (!spec) return []
  const hidden = new Set<number>()
  for (const part of spec.split(",")) {
    const span = parseSpan(part.trim())
    if (!span) continue
    for (let column = span[0]; column <= span[1]; column++) hidden.add(column)
  }
  return [...hidden].sort((a, b) => a - b)
}

/** Render hidden columns back into the spec a link carries, spans collapsed. */
export const formatHiddenColumns = (columns: number[]): string | undefined => {
  const sorted = [...new Set(columns)].sort((a, b) => a - b)
  if (sorted.length === 0) return undefined
  const parts: string[] = []
  let start = sorted[0]
  let end = sorted[0]
  const flush = () => parts.push(start === end ? `${start}` : `${start}-${end}`)
  for (const column of sorted.slice(1)) {
    if (column === end + 1) {
      end = column
      continue
    }
    flush()
    start = column
    end = column
  }
  flush()
  return parts.join(",")
}
