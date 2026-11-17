import { describe, expect, it } from "vitest"

import { inferKindFromPath } from "./SelectedItemInfo"

describe("inferKindFromPath", () => {
  it("detects results as the Results page does", () => {
    // Data-like files under a results folder, at any depth
    expect(inferKindFromPath("results/sup.json")).toBe("result")
    expect(inferKindFromPath("analysis/results/fit.csv")).toBe("result")
    expect(inferKindFromPath("result/summary.yaml")).toBe("result")
    // Or named results anywhere
    expect(inferKindFromPath("results.json")).toBe("result")
    expect(inferKindFromPath("sim/results.toml")).toBe("result")
    // But not a figure, a config, or something hidden
    expect(inferKindFromPath("results/plot.png")).toBe("figure")
    expect(inferKindFromPath("config/settings.json")).toBeUndefined()
    expect(inferKindFromPath(".cache/results/x.json")).toBeUndefined()
    // Other kinds are unchanged
    expect(inferKindFromPath("figures/plot.json")).toBe("figure")
    expect(inferKindFromPath("paper/main.pdf")).toBe("publication")
    expect(inferKindFromPath("notebooks/a.ipynb")).toBe("notebook")
  })
})
