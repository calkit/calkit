import { describe, expect, it } from "vitest"

import { countNewCommits, timeAgo } from "./RecentChanges"

describe("RecentChanges helpers", () => {
  it("phrases elapsed time coarsely", () => {
    const now = new Date("2026-08-20T12:00:00Z")
    const at = (iso: string) => timeAgo(iso, now)
    expect(at("2026-08-20T11:59:50Z")).toBe("just now")
    expect(at("2026-08-20T11:58:00Z")).toBe("2 minutes ago")
    expect(at("2026-08-20T11:00:00Z")).toBe("1 hour ago")
    expect(at("2026-08-17T12:00:00Z")).toBe("3 days ago")
    expect(at("2026-06-20T12:00:00Z")).toBe("2 months ago")
    expect(at("2024-08-20T12:00:00Z")).toBe("2 years ago")
    // A clock skewed into the future reads as now, not negative.
    expect(at("2026-08-20T12:05:00Z")).toBe("just now")
  })

  it("counts commits newer than the last one seen", () => {
    const commits = [{ hash: "c" }, { hash: "b" }, { hash: "a" }]
    expect(countNewCommits(commits, "a")).toBe(2)
    expect(countNewCommits(commits, "c")).toBe(0)
    // First visit, or a hash that's gone: nothing is "new", since calling
    // everything new would just be noise.
    expect(countNewCommits(commits, null)).toBe(0)
    expect(countNewCommits(commits, "zzz")).toBe(0)
    expect(countNewCommits([], "a")).toBe(0)
  })
})
