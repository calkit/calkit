import { describe, expect, it } from "vitest"

import {
  filterRows,
  firstHighlightedRow,
  formatHiddenColumns,
  formatHighlight,
  formatSort,
  indexRows,
  isCellHighlighted,
  isNumericColumn,
  parseHiddenColumns,
  parseHighlight,
  parseSort,
  parseTable,
  sortRows,
} from "./tables"

describe("parseTable", () => {
  it("parses CSV, including quoting, ragged rows, and CRLF", () => {
    const csv = 'name,count\r\n"Smith, J.",3\r\nJones,4\r\n'
    expect(parseTable("tables/t.csv", csv)).toEqual({
      columns: ["name", "count"],
      rows: [
        ["Smith, J.", "3"],
        ["Jones", "4"],
      ],
    })
    // Doubled quotes are one literal quote, and a quoted field can hold a
    // newline without ending the row
    expect(
      parseTable("t.csv", 'a,b\n"say ""hi""","two\nlines"\n')?.rows,
    ).toEqual([['say "hi"', "two\nlines"]])
    // A short row is padded rather than dropped, so its data survives
    expect(parseTable("t.csv", "a,b,c\n1,2\n")?.rows).toEqual([["1", "2", ""]])
    // Trailing newlines don't become an empty row
    expect(parseTable("t.csv", "a,b\n1,2\n\n\n")?.rows).toHaveLength(1)
    // A file with nothing in it has no table to show
    expect(parseTable("t.csv", "\n")).toBeNull()
  })

  it("parses TSV on tabs, leaving commas inside cells alone", () => {
    expect(parseTable("tables/t.tsv", "a\tb\n1,5\t2\n")).toEqual({
      columns: ["a", "b"],
      rows: [["1,5", "2"]],
    })
  })

  it("parses JSON lines, unioning keys across records", () => {
    const jsonl =
      '{"case":"base","runs":3}\n{"case":"mod","runs":4,"note":"rerun"}\n'
    expect(parseTable("results/r.jsonl", jsonl)).toEqual({
      columns: ["case", "runs", "note"],
      rows: [
        ["base", "3", ""],
        ["mod", "4", "rerun"],
      ],
    })
    // Nested values are shown as JSON rather than [object Object]
    expect(parseTable("r.ndjson", '{"a":{"b":1}}\n')?.rows).toEqual([
      ['{"b":1}'],
    ])
    // One unparseable line doesn't cost the reader the rest of the file
    expect(parseTable("r.jsonl", '{"a":1}\nnot json\n{"a":2}\n')?.rows).toEqual(
      [["1"], ["2"]],
    )
    // Bare values still make a table, under one column
    expect(parseTable("r.jsonl", "1\n2\n")).toEqual({
      columns: ["value"],
      rows: [["1"], ["2"]],
    })
  })

  it("parses a TeX tabular, dropping rules and formatting", () => {
    const tex = [
      "\\begin{table}[h]",
      "\\begin{tabular}{lrr}",
      "\\toprule",
      "\\textbf{Kernel} & \\textbf{Time} & Change \\\\",
      "\\midrule",
      "set\\_cache & 12.5 & -54\\% \\\\",
      "other & 3.1 & 0\\% \\\\",
      "\\bottomrule",
      "\\end{tabular}",
      "\\end{table}",
    ].join("\n")
    // The plain cells -- what search, sorting, and the numeric check read --
    // have the markup taken out, while the TeX is kept alongside for the grid
    // to render.
    expect(parseTable("tables/kernels.tex", tex)).toEqual({
      columns: ["Kernel", "Time", "Change"],
      rows: [
        ["set_cache", "12.5", "-54%"],
        ["other", "3.1", "0%"],
      ],
      texColumns: ["\\textbf{Kernel}", "\\textbf{Time}", "Change"],
      texRows: [
        ["set\\_cache", "12.5", "-54\\%"],
        ["other", "3.1", "0\\%"],
      ],
    })
    // Inline math is dropped from the plain cell so a column of numbers still
    // reads as numbers, and kept in the TeX so it can be typeset
    const math = parseTable(
      "v.tex",
      "\\begin{tabular}{ll}$T_{f,2}$ & $500 \\cdot 10^{-3}$ \\\\\\end{tabular}",
    )
    expect(math?.columns).toEqual(["T_f,2", "500 · 10^-3"])
    expect(math?.texColumns).toEqual(["$T_{f,2}$", "$500 \\cdot 10^{-3}$"])
    // \multicolumn keeps its text across every column it spans, and an
    // escaped ampersand stays in its cell rather than splitting it
    expect(
      parseTable(
        "t.tex",
        "\\begin{tabular}{ll}\\multicolumn{2}{c}{R \\& D} & b \\\\\\end{tabular}",
      )?.columns,
    ).toEqual(["R & D", "R & D", "b"])
    // A real generated table: the column spec nests braces, a \\cline sits
    // between rows, and one row is commented out. None of that is data.
    const real = [
      "\\begin{tabular}{lL{0.07\\linewidth}L{0.11\\linewidth}}",
      "\\toprule",
      "&& \\multicolumn{2}{c}{Location}\\\\  \\cline{3-6} ",
      "& Symbol & Humboldt, CA\\\\",
      "\\midrule ",
      "%Storm sea states & $H_s$ & - \\\\",
      "Water depth (m) & $h$ & $45 $ \\\\",
      "\\bottomrule",
      "\\end{tabular}",
    ].join("\n")
    const parsedReal = parseTable("t.tex", real)
    // The column spec is gone rather than sitting in the first cell
    expect(parsedReal?.columns[0]).toBe("")
    expect(parsedReal?.columns.join("|")).not.toContain("linewidth")
    // \cline is a rule, not a value
    expect(parsedReal?.columns.join("|")).not.toContain("cline")
    // The commented-out row isn't a row
    expect(
      parsedReal?.rows.some((r) => r.join("").includes("Storm sea states")),
    ).toBe(false)
    expect(parsedReal?.rows.at(-1)?.[0]).toBe("Water depth (m)")
    // A generator that stopped partway leaves the environment open. The rows
    // it managed to write are still worth showing, flagged as incomplete.
    const cut = [
      "\\begin{tabular}{lll}",
      "a & b & c\\\\",
      "\\hline",
      "$1 $ & $2 $ & $3 $\\\\",
      "$4 $ & $5 $ & $",
    ].join("\n")
    const parsedCut = parseTable("cut.tex", cut)
    expect(parsedCut?.isTruncated).toBe(true)
    expect(parsedCut?.columns).toEqual(["a", "b", "c"])
    expect(parsedCut?.rows[0]).toEqual(["1", "2", "3"])
    // A complete file is not flagged
    expect(
      parseTable("ok.tex", "\\begin{tabular}{ll}a & b \\\\\\end{tabular}")
        ?.isTruncated,
    ).toBeUndefined()
    // A heading spread over two rows, with a group spanning three columns
    // above the names beneath it. The full-width rule marks where the heading
    // stops, the span is repeated so the columns line up, and the merged name
    // says what each column holds. A \\cite in a heading is a pointer, not
    // part of the name.
    const spanned = [
      "\\begin{tabular}{P{0.15\\linewidth}|c|c|r}",
      "& \\multicolumn{3}{M{0.23\\linewidth}|}{DOE Report \\cite{RM3}} \\\\",
      "Variable & MDOcean & Actual & Error \\\\",
      "\\hline",
      "Mass (kg) & $213 $ & $208 $ & $2.4\\% $ \\\\",
      "\\end{tabular}",
    ].join("\n")
    const parsedSpanned = parseTable("v.tex", spanned)
    expect(parsedSpanned?.columns).toEqual([
      "Variable",
      "DOE Report MDOcean",
      "DOE Report Actual",
      "DOE Report Error",
    ])
    expect(parsedSpanned?.rows).toEqual([["Mass (kg)", "213", "208", "2.4%"]])
    // \multirow's count is rows, not columns: it takes one column like any
    // other cell, so repeating it would push the row out of line
    const multirow = parseTable(
      "m.tex",
      [
        "\\begin{tabular}{lll}",
        "\\multirow{2}{*}{Group} & a & b \\\\",
        "\\hline",
        "x & y & z \\\\",
        "\\end{tabular}",
      ].join("\n"),
    )
    expect(multirow?.columns).toEqual(["Group", "a", "b"])
    expect(multirow?.rows).toEqual([["x", "y", "z"]])
    // Nothing tabular in the file means nothing to render as a grid
    expect(parseTable("t.tex", "\\section{Results}")).toBeNull()
    // A paper is not a table: pulling its first tabular out would present a
    // fragment of a document as though it were the whole artifact
    const paper = [
      "\\documentclass{article}",
      "\\begin{document}",
      "\\section{Results}",
      "\\begin{tabular}{ll}a & b \\\\\\end{tabular}",
      "\\end{document}",
    ].join("\n")
    expect(parseTable("tables/paper.tex", paper)).toBeNull()
    // ...but the standalone class exists to put one table in one file
    const standalone = [
      "\\documentclass[border=2pt]{standalone}",
      "\\begin{document}",
      "\\begin{tabular}{ll}a & b \\\\\\end{tabular}",
      "\\end{document}",
    ].join("\n")
    expect(parseTable("tables/one.tex", standalone)?.columns).toEqual([
      "a",
      "b",
    ])
  })

  it("returns null for formats it doesn't know", () => {
    expect(parseTable("tables/t.parquet", "binary")).toBeNull()
  })
})

describe("sorting and filtering", () => {
  const rows = indexRows([
    ["b", "10", "x"],
    ["a", "9", ""],
    ["c", "-1.5", "y"],
  ])

  it("sorts numerically where the column holds numbers", () => {
    expect(isNumericColumn(rows, 1)).toBe(true)
    expect(isNumericColumn(rows, 0)).toBe(false)
    // Numeric, so 9 comes before 10 rather than after it as text would
    expect(sortRows(rows, 1, "asc").map((r) => r.cells[1])).toEqual([
      "-1.5",
      "9",
      "10",
    ])
    expect(sortRows(rows, 1, "desc").map((r) => r.cells[1])).toEqual([
      "10",
      "9",
      "-1.5",
    ])
    expect(sortRows(rows, 0, "asc").map((r) => r.cells[0])).toEqual([
      "a",
      "b",
      "c",
    ])
    // A row keeps the position it has in the file through a sort, so a
    // highlight or a shared link still names the same row
    expect(sortRows(rows, 1, "asc").map((r) => r.index)).toEqual([3, 2, 1])
    // Percentages and thousands separators are still numbers to a reader
    const formatted = indexRows([["1,200"], ["-54%"], ["3"]])
    expect(isNumericColumn(formatted, 0)).toBe(true)
    expect(sortRows(formatted, 0, "asc").map((r) => r.cells[0])).toEqual([
      "-54%",
      "3",
      "1,200",
    ])
    // Blanks sort last either way instead of burying the values
    expect(sortRows(rows, 2, "asc").map((r) => r.cells[2])).toEqual([
      "x",
      "y",
      "",
    ])
    expect(sortRows(rows, 2, "desc").map((r) => r.cells[2])).toEqual([
      "y",
      "x",
      "",
    ])
    // Sorting doesn't mutate the caller's rows
    expect(rows[0].cells[0]).toBe("b")
  })

  it("filters on any cell, case-insensitively", () => {
    expect(filterRows(rows, "X").map((r) => r.index)).toEqual([1])
    expect(filterRows(rows, "9").map((r) => r.index)).toEqual([2])
    expect(filterRows(rows, "  ")).toHaveLength(3)
    expect(filterRows(rows, "nope")).toHaveLength(0)
  })
})

describe("highlights", () => {
  it("round-trips the spec a shared link carries", () => {
    // One cell, a block, whole rows, and whole columns
    expect(parseHighlight("r3c2")).toEqual([
      { rowStart: 3, rowEnd: 3, colStart: 2, colEnd: 2 },
    ])
    expect(parseHighlight("r2-4c1-3")).toEqual([
      { rowStart: 2, rowEnd: 4, colStart: 1, colEnd: 3 },
    ])
    expect(parseHighlight("r5")).toEqual([
      { rowStart: 5, rowEnd: 5, colStart: undefined, colEnd: undefined },
    ])
    expect(parseHighlight("c2")).toEqual([
      { rowStart: undefined, rowEnd: undefined, colStart: 2, colEnd: 2 },
    ])
    // Several disjoint regions in one link
    expect(parseHighlight("r3c2,r8c5")).toHaveLength(2)
    // A backwards range still means the region between its ends
    expect(parseHighlight("r4-2")).toEqual([
      { rowStart: 2, rowEnd: 4, colStart: undefined, colEnd: undefined },
    ])
    // Junk is dropped rather than failing the whole link
    expect(parseHighlight("nonsense,r2")).toHaveLength(1)
    expect(parseHighlight("r0")).toHaveLength(0)
    expect(parseHighlight(undefined)).toHaveLength(0)
    for (const spec of ["r3c2", "r2-4c1-3", "r5", "c2", "r3c2,r8c5"]) {
      expect(formatHighlight(parseHighlight(spec))).toBe(spec)
    }
  })

  it("tests cells against every range and finds the first row", () => {
    const block = parseHighlight("r2-4c1-3")
    expect(isCellHighlighted(block, 3, 2)).toBe(true)
    expect(isCellHighlighted(block, 5, 2)).toBe(false)
    expect(isCellHighlighted(block, 3, 4)).toBe(false)
    // An open end covers everything in that direction
    const wholeRow = parseHighlight("r7")
    expect(isCellHighlighted(wholeRow, 7, 99)).toBe(true)
    expect(isCellHighlighted(wholeRow, 8, 1)).toBe(false)
    const wholeColumn = parseHighlight("c2")
    expect(isCellHighlighted(wholeColumn, 99, 2)).toBe(true)
    // Scrolling targets the topmost highlighted row
    expect(firstHighlightedRow(parseHighlight("r8c1,r3c2"))).toBe(3)
    expect(firstHighlightedRow(parseHighlight("c2"))).toBeNull()
    expect(firstHighlightedRow([])).toBeNull()
  })
})

describe("parseSort", () => {
  it("parses a column with and without a direction", () => {
    expect(parseSort("2")).toEqual({ column: 2, direction: "asc" })
    expect(parseSort("2:desc")).toEqual({ column: 2, direction: "desc" })
  })

  it("returns null for anything unusable", () => {
    expect(parseSort(undefined)).toBeNull()
    expect(parseSort("")).toBeNull()
    expect(parseSort("0")).toBeNull()
    expect(parseSort("2:sideways")).toBeNull()
    expect(parseSort("name")).toBeNull()
  })

  it("round trips through formatSort", () => {
    expect(formatSort(parseSort("3:desc"))).toBe("3:desc")
    expect(formatSort(null)).toBeUndefined()
  })
})

describe("parseHiddenColumns", () => {
  it("parses numbers and spans, deduped and sorted", () => {
    expect(parseHiddenColumns("5,2-4,2")).toEqual([2, 3, 4, 5])
  })

  it("drops parts that don't parse", () => {
    expect(parseHiddenColumns("2,nope,4")).toEqual([2, 4])
    expect(parseHiddenColumns(undefined)).toEqual([])
  })

  it("collapses back into spans", () => {
    expect(formatHiddenColumns([2, 3, 4, 7])).toBe("2-4,7")
    expect(formatHiddenColumns([])).toBeUndefined()
  })
})

describe("filterRows with hidden columns", () => {
  it("only matches columns still on screen", () => {
    const rows = indexRows([
      ["alpha", "one"],
      ["beta", "two"],
    ])
    expect(filterRows(rows, "one").length).toBe(1)
    expect(filterRows(rows, "one", [0]).length).toBe(0)
    expect(filterRows(rows, "alpha", [0]).length).toBe(1)
  })
})
