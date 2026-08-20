import { describe, expect, it } from "vitest"

import { filterRepos, scoreRepo } from "./RepoPicker"

const repos = [
  { full_name: "pbachant/navier-wake-analysis" },
  { full_name: "pbachant/turbine-wake" },
  { full_name: "pbachant/wake-study" },
  { full_name: "calkit/example-basic" },
  { full_name: "someone/unrelated" },
]

describe("scoreRepo", () => {
  it("matches subsequences and rejects what isn't there", () => {
    // Fragments people actually remember, with the gaps left out.
    expect(scoreRepo("pbachant/navier-wake-analysis", "navwake")).not.toBeNull()
    expect(scoreRepo("pbachant/turbine-wake", "turbwake")).not.toBeNull()
    // A character that isn't present at all can't match.
    expect(scoreRepo("pbachant/turbine-wake", "zzz")).toBeNull()
    // Order matters: the letters have to appear in the order typed.
    expect(scoreRepo("pbachant/wake-study", "ekaw")).toBeNull()
    // An empty query matches everything equally.
    expect(scoreRepo("anything", "")).toBe(0)
  })

  it("scores a tighter, earlier match better", () => {
    // Lower is better. An exact contiguous run beats a scattered one.
    const contiguous = scoreRepo("someone/wake", "wake")
    const scattered = scoreRepo("someone/w-a-k-e", "wake")
    expect(contiguous).not.toBeNull()
    expect(scattered).not.toBeNull()
    expect(contiguous as number).toBeLessThan(scattered as number)
  })
})

describe("filterRepos", () => {
  it("returns every repo, best first, when nothing is typed", () => {
    expect(filterRepos(repos, "")).toHaveLength(repos.length)
  })

  it("keeps only what matches and ranks the obvious candidate first", () => {
    const matches = filterRepos(repos, "wake")
    expect(matches.map((r) => r.full_name)).not.toContain("someone/unrelated")
    // "wake-study" starts its match earliest of the three wake repos.
    expect(matches[0].full_name).toBe("pbachant/wake-study")
    // Typing the owner narrows to that owner's repos.
    const byOwner = filterRepos(repos, "calkit")
    expect(byOwner.map((r) => r.full_name)).toContain("calkit/example-basic")
  })

  it("caps how many suggestions it offers", () => {
    const many = Array.from({ length: 50 }, (_, i) => ({
      full_name: `owner/repo-${i}`,
    }))
    expect(filterRepos(many, "repo")).toHaveLength(8)
    expect(filterRepos(many, "repo", 3)).toHaveLength(3)
  })
})
