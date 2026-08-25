import { describe, expect, it } from "vitest"

import { countNewItems, splitActivityLink, timeAgo } from "./RecentChanges"

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

  it("counts items newer than the last one seen", () => {
    const items = [{ id: "c" }, { id: "b" }, { id: "a" }]
    expect(countNewItems(items, "a")).toBe(2)
    expect(countNewItems(items, "c")).toBe(0)
    // First visit, or an id that's gone: nothing is "new", since calling
    // everything new would just be noise.
    expect(countNewItems(items, null)).toBe(0)
    expect(countNewItems(items, "zzz")).toBe(0)
    expect(countNewItems([], "a")).toBe(0)
  })

  it("splits an activity link into path and search", () => {
    expect(splitActivityLink("history?commit=abc123")).toEqual({
      path: "history",
      search: { commit: "abc123" },
    })
    expect(splitActivityLink("collaborators")).toEqual({
      path: "collaborators",
      search: {},
    })
    expect(splitActivityLink("comments?path=a%20b&view=1")).toEqual({
      path: "comments",
      search: { path: "a b", view: "1" },
    })
  })
})
