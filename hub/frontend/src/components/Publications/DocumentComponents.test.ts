import { describe, expect, it } from "vitest"

import type { DocumentComponent } from "../../client"
import {
  componentLabel,
  pagesText,
  sortDocumentComponents,
  staleExplanation,
  valueText,
} from "./DocumentComponents"

function component(
  overrides: Partial<DocumentComponent> = {},
): DocumentComponent {
  return {
    kind: "value",
    path: "results/findings.json",
    key: "ratio",
    pages: [1, 3],
    stage: "summarize",
    stage_inputs: [],
    script: "s.py",
    provenance: "pipeline",
    build_value: 5.1014,
    current_value: 5.1014,
    build_hash: null,
    current_hash: null,
    status: "ok",
    stale_reasons: [],
    ...overrides,
  }
}

describe("sortDocumentComponents", () => {
  it("puts what needs doing first, then groups a file's values", () => {
    const sorted = sortDocumentComponents([
      component({ path: "results/b.json", key: "z", status: "ok" }),
      component({ path: "figures/plot.pdf", key: null, status: "unknown" }),
      component({ path: "results/a.json", key: "b", status: "stale" }),
      component({ path: "figures/gone.pdf", key: null, status: "missing" }),
      component({ path: "results/a.json", key: "a", status: "stale" }),
      component({ path: "results/a.json", key: "c", status: "ok" }),
    ])
    expect(sorted.map((i) => `${i.path}:${i.key ?? ""}`)).toEqual([
      "figures/gone.pdf:",
      "results/a.json:a",
      "results/a.json:b",
      "figures/plot.pdf:",
      "results/a.json:c",
      "results/b.json:z",
    ])
    // The input is left alone
    const input = [component({ status: "ok" }), component({ status: "stale" })]
    sortDocumentComponents(input)
    expect(input.map((i) => i.status)).toEqual(["ok", "stale"])
  })
})

describe("staleExplanation", () => {
  it("says why, in terms a reader can act on", () => {
    expect(
      staleExplanation(component({ stale_reasons: ["stage-out-of-date"] })),
    ).toBe("its stage needs a rerun")
    // The two are independent and both can hold at once
    expect(
      staleExplanation(
        component({
          stale_reasons: ["stage-out-of-date", "changed-since-build"],
        }),
      ),
    ).toBe(
      "its stage needs a rerun, and the project has moved on since this was built",
    )
    expect(
      staleExplanation(component({ stale_reasons: ["answer-stale"] })),
    ).toBe("the answer no longer matches its evidence")
    // A current component has nothing to explain
    expect(staleExplanation(component())).toBe("")
    // A reason from a newer backend still reads as something
    expect(
      staleExplanation(
        component({ stale_reasons: ["something-new" as "answer-stale"] }),
      ),
    ).toBe("something-new")
  })
})

describe("valueText", () => {
  it("renders whatever a results file holds", () => {
    expect(valueText(5.1014)).toBe("5.1014")
    expect(valueText("k_omega")).toBe("k_omega")
    expect(valueText(0)).toBe("0")
    expect(valueText(false)).toBe("false")
    expect(valueText({ a: 1 })).toBe('{"a":1}')
    expect(valueText([1, 2])).toBe("[1,2]")
    // Nothing to show, rather than the word "null"
    expect(valueText(null)).toBe("")
    expect(valueText(undefined)).toBe("")
  })
})

describe("componentLabel", () => {
  it("names the file, and the key within it when there is one", () => {
    expect(componentLabel(component())).toBe("results/findings.json:ratio")
    expect(
      componentLabel(component({ path: "figures/plot.pdf", key: null })),
    ).toBe("figures/plot.pdf")
  })
})

describe("pagesText", () => {
  it("counts pages the way a reader says them", () => {
    expect(pagesText([3])).toBe("Page 3")
    expect(pagesText([3, 7])).toBe("Pages 3, 7")
    // A component the document no longer shows reached no page
    expect(pagesText([])).toBe("")
  })
})
