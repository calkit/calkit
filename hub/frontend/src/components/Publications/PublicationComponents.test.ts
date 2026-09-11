import { describe, expect, it } from "vitest"

import { relativeComponentPath, sortComponents } from "./PublicationComponents"

describe("sortComponents", () => {
  it("puts unknowns first, then kinds in reader order, then by path", () => {
    const sorted = sortComponents([
      { path: "paper/fig2.png", kind: "unknown" },
      { path: "paper/main.tex", kind: "authored", source: "overleaf" },
      { path: "paper/fig1.png", kind: "produced", stage: "plot" },
      { path: "paper/fig3.png", kind: "unknown", matching_figure: "f.png" },
      { path: "paper/logo.png", kind: "imported" },
      { path: "paper/refs.bib", kind: "authored", source: "git" },
      { path: "paper/photo.jpg", kind: "attested" },
      { path: "paper/a.png", kind: "unknown" },
    ])
    expect(sorted.map((i) => i.path)).toEqual([
      "paper/a.png",
      "paper/fig2.png",
      "paper/fig3.png",
      "paper/fig1.png",
      "paper/main.tex",
      "paper/refs.bib",
      "paper/photo.jpg",
      "paper/logo.png",
    ])
    // An unrecognized kind sorts with the unknowns, and input is untouched
    const input = [
      { path: "b", kind: "produced" as const },
      { path: "a", kind: "weird" as "unknown" },
    ]
    expect(sortComponents(input).map((i) => i.path)).toEqual(["a", "b"])
    expect(input.map((i) => i.path)).toEqual(["b", "a"])
    expect(sortComponents([])).toEqual([])
  })
})

describe("paths", () => {
  it("strips the folder from a component path", () => {
    expect(relativeComponentPath("paper/figures/a.png", "paper")).toBe(
      "figures/a.png",
    )
    expect(relativeComponentPath("paper/figures/a.png", "paper/")).toBe(
      "figures/a.png",
    )
    expect(relativeComponentPath("papers/a.png", "paper")).toBe("papers/a.png")
    expect(relativeComponentPath("a.png", "")).toBe("a.png")
  })
})
