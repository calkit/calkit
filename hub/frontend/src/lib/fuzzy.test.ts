import { describe, expect, it } from "vitest"

import { fuzzyFilter, fuzzyScore } from "./fuzzy"

const repos = [
  "pbachant/navier-wake-analysis",
  "pbachant/turbine-wake",
  "pbachant/wake-study",
  "calkit/example-basic",
  "someone/unrelated",
]

describe("fuzzyScore", () => {
  it("matches subsequences and rejects what isn't there", () => {
    // Fragments people actually remember, with the gaps left out.
    expect(
      fuzzyScore("pbachant/navier-wake-analysis", "navwake"),
    ).not.toBeNull()
    expect(fuzzyScore("data/raw/measurements.csv", "dtrawcsv")).not.toBeNull()
    // A character that isn't present at all can't match.
    expect(fuzzyScore("pbachant/turbine-wake", "zzz")).toBeNull()
    // Order matters: the letters have to appear in the order typed.
    expect(fuzzyScore("pbachant/wake-study", "ekaw")).toBeNull()
    // An empty query matches everything equally.
    expect(fuzzyScore("anything", "")).toBe(0)
    // Matching ignores case and stray spaces.
    expect(fuzzyScore("Data/Raw.csv", "data raw")).not.toBeNull()
  })

  it("scores a tighter, earlier match better", () => {
    // Lower is better. A contiguous run beats a scattered one.
    const contiguous = fuzzyScore("someone/wake", "wake")
    const scattered = fuzzyScore("someone/w-a-k-e", "wake")
    expect(contiguous).not.toBeNull()
    expect(scattered).not.toBeNull()
    expect(contiguous as number).toBeLessThan(scattered as number)
  })
})

describe("fuzzyFilter", () => {
  const identity = (s: string) => s

  it("returns everything when nothing is typed", () => {
    expect(fuzzyFilter(repos, "", identity, 20)).toHaveLength(repos.length)
  })

  it("keeps only what matches and ranks the obvious candidate first", () => {
    const matches = fuzzyFilter(repos, "wake", identity)
    expect(matches).not.toContain("someone/unrelated")
    // "wake-study" starts its match earliest of the three wake repos.
    expect(matches[0]).toBe("pbachant/wake-study")
    expect(fuzzyFilter(repos, "calkit", identity)).toContain(
      "calkit/example-basic",
    )
  })

  it("keeps the caller's order among equally good matches", () => {
    // Both match "data" identically, so the order they came in survives.
    const paths = ["b/data.csv", "a/data.csv"]
    expect(fuzzyFilter(paths, "data", identity)).toEqual(paths)
  })

  it("caps how many suggestions it offers", () => {
    const many = Array.from({ length: 50 }, (_, i) => `owner/repo-${i}`)
    expect(fuzzyFilter(many, "repo", identity)).toHaveLength(8)
    expect(fuzzyFilter(many, "repo", identity, 3)).toHaveLength(3)
  })

  it("reads the text out of whatever shape the caller has", () => {
    const options = [{ value: "data/raw.csv" }, { value: "src/plot.py" }]
    expect(fuzzyFilter(options, "csv", (o) => o.value)).toEqual([
      { value: "data/raw.csv" },
    ])
  })
})
