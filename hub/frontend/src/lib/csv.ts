// Just enough CSV to move a table between a grid and a file.

export interface Table {
  columns: string[]
  rows: string[][]
}

const needsQuoting = (value: string) => /[",\r\n]/.test(value)

const quote = (value: string) =>
  needsQuoting(value) ? `"${value.replace(/"/g, '""')}"` : value

/** RFC 4180 output: quoted only where a value would otherwise break. */
export function toCsv({ columns, rows }: Table): string {
  const lines = [columns.map(quote).join(",")]
  for (const row of rows) {
    // Ragged rows are padded so every line has the header's width.
    const cells = columns.map((_, i) => quote(row[i] ?? ""))
    lines.push(cells.join(","))
  }
  return `${lines.join("\n")}\n`
}

/**
 * Parse delimited text into rows, handling quoted fields.
 *
 * The delimiter is guessed from the first line: a tab if there is one
 * (what a spreadsheet puts on the clipboard), else a comma.
 */
export function parseDelimited(text: string, delimiter?: string): string[][] {
  const trimmed = text.replace(/\r\n?/g, "\n").replace(/\n+$/, "")
  if (!trimmed) return []
  const firstLine = trimmed.split("\n")[0]
  const sep = delimiter ?? (firstLine.includes("\t") ? "\t" : ",")
  const rows: string[][] = []
  let row: string[] = []
  let cell = ""
  let quoted = false
  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i]
    if (quoted) {
      if (ch === '"') {
        if (trimmed[i + 1] === '"') {
          cell += '"'
          i++
        } else {
          quoted = false
        }
      } else {
        cell += ch
      }
    } else if (ch === '"' && cell === "") {
      quoted = true
    } else if (ch === sep) {
      row.push(cell)
      cell = ""
    } else if (ch === "\n") {
      row.push(cell)
      rows.push(row)
      row = []
      cell = ""
    } else {
      cell += ch
    }
  }
  row.push(cell)
  rows.push(row)
  return rows
}

/** Header and first rows of a CSV, for picking columns to plot. */
export function previewCsv(
  text: string,
  maxRows = 5,
): { columns: string[]; rows: string[][] } {
  const rows = parseDelimited(text, ",")
  if (!rows.length) return { columns: [], rows: [] }
  const [columns, ...rest] = rows
  return { columns, rows: rest.slice(0, maxRows) }
}

/** Columns whose sampled values all parse as numbers. */
export function numericColumns(columns: string[], rows: string[][]): string[] {
  return columns.filter((_, i) => {
    const values = rows
      .map((r) => r[i])
      .filter((v) => v !== undefined && v !== "")
    return values.length > 0 && values.every((v) => !Number.isNaN(Number(v)))
  })
}
