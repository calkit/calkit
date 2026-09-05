import { describe, expect, it } from "vitest"

import type { ArtifactUsage } from "../../client"
import { pagesSuffix, usageLabel, usagesByDocument } from "./ArtifactUsagesRow"

function usage(overrides: Partial<ArtifactUsage> = {}): ArtifactUsage {
  return {
    document: "paper/main.tex",
    kind: "value",
    key: "ratio",
    pages: [1, 3],
    ...overrides,
  }
}

describe("usagesByDocument", () => {
  it("merges one document's usages into a single place to go", () => {
    // A results file cited under several keys is still one paper to look at
    const merged = usagesByDocument([
      usage({ key: "ratio", pages: [3, 1] }),
      usage({ key: "name", pages: [1] }),
      usage({ document: "poster/main.tex", key: "ratio", pages: [2] }),
    ])
    expect(merged).toEqual([
      { document: "paper/main.tex", keys: ["name", "ratio"], pages: [1, 3] },
      { document: "poster/main.tex", keys: ["ratio"], pages: [2] },
    ])
  })

  it("handles a figure, which has no key, and a record with no pages", () => {
    expect(
      usagesByDocument([
        usage({ kind: "figure", key: null, pages: [2] }),
        usage({ kind: "figure", key: null, pages: [] }),
      ]),
    ).toEqual([{ document: "paper/main.tex", keys: [], pages: [2] }])
    expect(usagesByDocument([])).toEqual([])
  })
})

describe("pagesSuffix", () => {
  it("says one page differently from several", () => {
    expect(pagesSuffix([3])).toBe("p. 3")
    expect(pagesSuffix([3, 7])).toBe("pp. 3, 7")
    expect(pagesSuffix([])).toBe("")
  })
})

describe("usageLabel", () => {
  it("names the document, the key when there is one, and the pages", () => {
    expect(usageLabel(usage())).toBe("paper/main.tex: ratio (pp. 1, 3)")
    expect(usageLabel(usage({ key: null, pages: [2] }))).toBe(
      "paper/main.tex (p. 2)",
    )
    expect(usageLabel(usage({ key: null, pages: [] }))).toBe("paper/main.tex")
  })
})
