import { describe, expect, it } from "vitest"

import type { PublicationComponent } from "../../client"
import {
  componentLabel,
  pagesText,
  relativeComponentPath,
  sortComponents,
  staleExplanation,
} from "./PublicationComponents"

function component(
  overrides: Partial<PublicationComponent> = {},
): PublicationComponent {
  return {
    kind: "file",
    path: "paper/a.png",
    provenance: "pipeline",
    status: "unknown",
    ...overrides,
  }
}

describe("sortComponents", () => {
  it("puts what needs doing first, then groups files before page content", () => {
    const sorted = sortComponents([
      component({ path: "paper/main.tex", provenance: "authored" }),
      component({
        kind: "value",
        path: "results/f.json",
        key: "b",
        status: "ok",
      }),
      component({ path: "paper/logo.png", provenance: "undeclared" }),
      component({
        kind: "value",
        path: "results/f.json",
        key: "a",
        status: "stale",
      }),
      component({ path: "paper/fig.png", provenance: "attested" }),
    ])
    expect(sorted.map((i) => `${i.kind}:${i.path}:${i.key ?? ""}`)).toEqual([
      // Out of date and undeclared come first, worst status leading
      "value:results/f.json:a",
      "file:paper/logo.png:",
      // Then everything accounted for, files before page content
      "file:paper/fig.png:",
      "file:paper/main.tex:",
      "value:results/f.json:b",
    ])
    // The caller's array is left alone
    const input = [component({ path: "b" }), component({ path: "a" })]
    sortComponents(input)
    expect(input.map((i) => i.path)).toEqual(["b", "a"])
  })
})

describe("relativeComponentPath", () => {
  it("shows a path inside its folder, and leaves outside ones alone", () => {
    expect(relativeComponentPath("paper/figures/a.png", "paper")).toBe(
      "figures/a.png",
    )
    expect(relativeComponentPath("data/table.csv", "paper")).toBe(
      "data/table.csv",
    )
    // A publication at the repo root has no prefix to strip
    expect(relativeComponentPath("main.tex", "")).toBe("main.tex")
  })
})

describe("componentLabel", () => {
  it("names a file by its path and a value by its key within it", () => {
    expect(componentLabel(component({ path: "paper/a.png" }), "paper")).toBe(
      "a.png",
    )
    expect(
      componentLabel(
        component({ kind: "value", path: "results/f.json", key: "Cd" }),
        "paper",
      ),
    ).toBe("results/f.json:Cd")
  })
})

describe("pagesText", () => {
  it("counts pages the way a reader says them", () => {
    expect(pagesText([3])).toBe("p. 3")
    expect(pagesText([3, 7])).toBe("pp. 3, 7")
    // A file has no pages, and neither has content the document dropped
    expect(pagesText([])).toBe("")
    expect(pagesText(undefined)).toBe("")
  })
})

describe("staleExplanation", () => {
  it("says why, in terms a reader can act on", () => {
    expect(
      staleExplanation(component({ stale_reasons: ["stage-out-of-date"] })),
    ).toBe("its stage needs a rerun")
    // The reasons are independent and can hold at once
    expect(
      staleExplanation(
        component({
          stale_reasons: ["stage-out-of-date", "changed-since-build"],
        }),
      ),
    ).toBe(
      "its stage needs a rerun, and the project has moved on since this was built",
    )
    expect(staleExplanation(component())).toBe("")
  })
})
