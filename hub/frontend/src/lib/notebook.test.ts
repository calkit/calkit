import { describe, expect, it } from "vitest"

import {
  browserRunnable,
  parseNotebook,
  serializeNotebook,
  splitSource,
} from "./notebook"

const nb = JSON.stringify({
  cells: [
    { id: "a", cell_type: "markdown", source: ["# Title\n", "text"] },
    {
      id: "b",
      cell_type: "code",
      source: ["x = 1\n", "x"],
      outputs: [
        { output_type: "execute_result", data: { "text/plain": ["1"] } },
      ],
      execution_count: 3,
      metadata: {},
    },
    { cell_type: "code", source: "print('no id')", outputs: [], metadata: {} },
  ],
  metadata: { kernelspec: { name: "python3" } },
  nbformat: 4,
  nbformat_minor: 5,
})

describe("notebook", () => {
  it("parses cells with stable ids and joined sources", () => {
    const parsed = parseNotebook(nb)
    expect(parsed.cells.map((c) => [c.id, c.type])).toEqual([
      ["a", "markdown"],
      ["b", "code"],
      ["cell-2", "code"],
    ])
    expect(parsed.cells[0].source).toBe("# Title\ntext")
    expect(parsed.cells[1].source).toBe("x = 1\nx")
  })

  it("splits sources the way Jupyter stores them", () => {
    expect(splitSource("a\nb")).toEqual(["a\n", "b"])
    expect(splitSource("a\nb\n")).toEqual(["a\n", "b\n"])
    expect(splitSource("")).toEqual([])
  })

  it("writes back edited sources, clearing only their outputs", () => {
    const parsed = parseNotebook(nb)
    const cells = parsed.cells.map((c) =>
      c.id === "b" ? { ...c, source: "x = 2\nx" } : c,
    )
    const out = JSON.parse(serializeNotebook(parsed, cells))
    expect(out.metadata.kernelspec.name).toBe("python3")
    expect(out.cells[0].source).toEqual(["# Title\n", "text"])
    expect(out.cells[1].source).toEqual(["x = 2\n", "x"])
    expect(out.cells[1].outputs).toEqual([])
    expect(out.cells[1].execution_count).toBeNull()
    // Untouched cells keep everything, outputs included
    const unchanged = JSON.parse(serializeNotebook(parsed, parsed.cells))
    expect(unchanged.cells[1].execution_count).toBe(3)
    expect(unchanged.cells[1].outputs).toHaveLength(1)
  })
})

it("keeps cell ids unique even when a fallback would collide", () => {
  const text = JSON.stringify({
    cells: [
      { cell_type: "code", source: "a" },
      { cell_type: "code", source: "b", id: "cell-0" },
      { cell_type: "code", source: "c", id: "cell-0" },
    ],
  })
  const parsed = parseNotebook(text)
  expect(parsed.cells.map((c) => c.id)).toEqual([
    "cell-0",
    "cell-0-2",
    "cell-0-3",
  ])
  // An edit lands on the cell it was made in, not a namesake
  const edited = parsed.cells.map((c) =>
    c.id === "cell-0-3" ? { ...c, source: "changed" } : c,
  )
  const out = JSON.parse(serializeNotebook(parsed, edited))
  expect(out.cells.map((c: any) => c.source)).toEqual(["a", "b", ["changed"]])
})

it("only offers a browser run for Python notebooks", () => {
  expect(browserRunnable(undefined, "uv-venv").ok).toBe(true)
  expect(browserRunnable("kind: jupyter-notebook\n", "docker").ok).toBe(true)
  expect(browserRunnable(undefined, undefined).ok).toBe(true)
  expect(browserRunnable(undefined, "julia")).toEqual({
    ok: false,
    reason:
      "This notebook's environment is Julia, and the browser only runs Python.",
  })
  expect(browserRunnable(undefined, "renv").reason).toContain("is R")
  expect(
    browserRunnable("kind: jupyter-notebook\nlanguage: julia\n", "uv").ok,
  ).toBe(false)
  expect(browserRunnable("kind: [", "uv").ok).toBe(true)
})
