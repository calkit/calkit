import { describe, expect, it } from "vitest"

import { numericColumns, parseDelimited, previewCsv, toCsv } from "./csv"

describe("csv", () => {
  it("round-trips a table, quoting only what needs it", () => {
    const table = {
      columns: ["x", "note"],
      rows: [["1", "plain"], ["2", 'has "quotes", commas'], ["3"]],
    }
    const text = toCsv(table)
    expect(text).toBe('x,note\n1,plain\n2,"has ""quotes"", commas"\n3,\n')
    const [header, ...rows] = parseDelimited(text, ",")
    expect(header).toEqual(table.columns)
    expect(rows[1]).toEqual(["2", 'has "quotes", commas'])
    // The short row was padded to the header's width on the way out.
    expect(rows[2]).toEqual(["3", ""])
  })

  it("guesses tabs from a spreadsheet paste and handles CRLF", () => {
    expect(parseDelimited("a\tb\r\n1\t2\r\n")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ])
    expect(parseDelimited("")).toEqual([])
    expect(parseDelimited("single")).toEqual([["single"]])
  })

  it("previews a header plus a few rows and spots numeric columns", () => {
    const text = "x,y,label\n1,2.5,a\n2,,b\n3,4e2,c\n"
    const { columns, rows } = previewCsv(text, 2)
    expect(columns).toEqual(["x", "y", "label"])
    expect(rows).toHaveLength(2)
    const all = previewCsv(text)
    // An empty cell doesn't disqualify a column; a word does.
    expect(numericColumns(all.columns, all.rows)).toEqual(["x", "y"])
    // A column with nothing in it isn't numeric either.
    expect(numericColumns(["e"], [[""], [""]])).toEqual([])
  })
})
