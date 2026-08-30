import { describe, expect, it } from "vitest"

import {
  activeTip,
  onTipPage,
  TIPS,
  TIPS_DISMISSED,
  tipDoneFlag,
  tipsProjectId,
} from "./tips"

describe("tips", () => {
  it("shows one tip at a time, in order, until done or dismissed", () => {
    expect(activeTip([])?.id).toBe(TIPS[0].id)
    expect(activeTip([tipDoneFlag(TIPS[0].id)])?.id).toBe(TIPS[1].id)
    // Order is the tips' own, not the order they were done in
    expect(activeTip([tipDoneFlag(TIPS[1].id)])?.id).toBe(TIPS[0].id)
    expect(activeTip(TIPS.map((t) => tipDoneFlag(t.id)))).toBeNull()
    expect(activeTip([TIPS_DISMISSED])).toBeNull()
    expect(activeTip(["dismissed", "editor"])?.id).toBe(TIPS[0].id)
  })
  it("belongs to the first project unless reset elsewhere", () => {
    expect(tipsProjectId([], "p1")).toBe("p1")
    expect(tipsProjectId(["cli"], null)).toBeNull()
    expect(tipsProjectId(["tips-project:p2"], "p1")).toBe("p2")
  })
  it("knows which page a tip's action is on", () => {
    const figure = TIPS.find((t) => t.id === "edit-figure")!
    expect(onTipPage(figure, "/me/proj/figures")).toBe(true)
    expect(onTipPage(figure, "/me/proj/figures/")).toBe(true)
    expect(onTipPage(figure, "/me/proj/datasets")).toBe(false)
    expect(onTipPage(figure, "/me/proj")).toBe(false)
  })
})
