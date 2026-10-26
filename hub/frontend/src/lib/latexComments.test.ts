import { describe, expect, it } from "vitest"

import {
  addComment,
  commentDate,
  editComment,
  newCommentId,
  paragraphStart,
  parseComments,
  renderComment,
} from "./latexComments"

// Rendered by `TexComment.render` in calkit/latex.py, so the two agree
const RENDERED = [
  "% COMMENT id=0a1b2c3d resolved=true issue=https://github.com/o/p/issues/7",
  '%   highlight={text: "a \\"b\\", c", occ: 2} origin={tool: "x", v: 2}',
  "%   A. Reviewer <a.reviewer@uni.edu> (2026-09-06 08:44):",
  "%     This well-known result is quite reasonable, but the comparison with the",
  "%     state-of-the-art methods needs This well-known result is quite",
  "%     reasonable, but the comparison with the state-of-the-art methods needs",
  "%   Person, Other:",
  "%     Reply: yes.",
]

describe("latex comments", () => {
  it("parses and renders the schema as calkit does", () => {
    const [t] = parseComments(["Text before.", ...RENDERED, "A paragraph."])
    expect(t.lineno).toBe(2)
    expect(t.nlines).toBe(RENDERED.length)
    expect([t.id, t.issue, t.resolved, t.highlight, t.occ]).toEqual([
      "0a1b2c3d",
      "https://github.com/o/p/issues/7",
      true,
      'a "b", c',
      2,
    ])
    expect(t.attrs).toEqual([["origin", '{tool: "x", v: 2}']])
    expect(t.entries.map((e) => e.author)).toEqual([
      "A. Reviewer",
      "Person, Other",
    ])
    expect(t.entries[0].email).toBe("a.reviewer@uni.edu")
    expect(t.entries[0].date).toBe("2026-09-06 08:44")
    expect(t.entries[1].text).toBe("Reply: yes.")
    expect(renderComment(t)).toEqual(RENDERED)
    // The plainest thread, a bare highlight, and a header on two lines
    const [plain, bare, split] = parseComments([
      "% COMMENT",
      "%   T. Author:",
      "%     Is this right?",
      "x",
      '% COMMENT highlight="something"',
      "%   A:",
      "%     Hi.",
      "y",
      "% COMMENT resolved=false",
      '%   highlight={text: "something", occ: 0}',
      "%   Someone <s@x.org>:",
      "%     A comment.",
    ])
    expect(renderComment(plain)).toEqual([
      "% COMMENT",
      "%   T. Author:",
      "%     Is this right?",
    ])
    expect([plain.id, plain.resolved, plain.highlight]).toEqual([
      null,
      false,
      null,
    ])
    expect(bare.highlight).toBe("something")
    expect([split.highlight, split.occ, split.resolved]).toEqual([
      "something",
      0,
      false,
    ])
    // A block with no messages isn't a thread
    expect(parseComments(["% COMMENT", "Text."])).toEqual([])
  })

  it("adds, edits, and removes threads above paragraphs", () => {
    const lines = [
      "\\section{Intro}",
      "",
      "% COMMENT id=11111111",
      "%   A:",
      "%     First.",
      "The first line",
      "and the second.",
      "",
      "Another paragraph.",
    ]
    // At or after a line, from where its paragraph starts
    expect(paragraphStart(lines, 7)).toBe(6)
    expect(paragraphStart(lines, 2)).toBe(6)
    expect(paragraphStart(lines, 8)).toBe(9)
    expect(paragraphStart(lines, 10)).toBeNull()
    const entry = { author: "B", email: "b@x.org", date: "2026-10-09 12:00" }
    const added = addComment(lines, 7, {
      entries: [{ ...entry, text: "Second." }],
      highlight: "second",
      occ: 0,
      resolved: false,
      id: "22222222",
      issue: null,
      attrs: [],
    })
    // Below the thread already there
    const threads = parseComments(added)
    expect(threads.map((t) => t.id)).toEqual(["11111111", "22222222"])
    expect(added[threads[1].lineno - 1 + threads[1].nlines]).toBe(
      "The first line",
    )
    // Replying and resolving rewrite the block in place
    const replied = editComment(added, threads[1], (t) => ({
      ...t,
      resolved: true,
      entries: [...t.entries, { ...entry, text: "Done." }],
    }))
    const [, second] = parseComments(replied)
    expect(second.resolved).toBe(true)
    expect(second.entries.map((e) => e.text)).toEqual(["Second.", "Done."])
    expect(replied.slice(-4)).toEqual(added.slice(-4))
    // A thread without an ID gets one when it's edited
    const [noId] = parseComments(["% COMMENT", "%   A:", "%     Hi.", "x"])
    const [given] = parseComments(
      editComment(["% COMMENT", "%   A:", "%     Hi.", "x"], noId, (t) => t),
    )
    expect(given.id).toMatch(/^[0-9a-f]{8}$/)
    // Removing takes out the block and nothing else
    expect(editComment(added, threads[1], null)).toEqual(lines)
    expect(() =>
      addComment(["% only a comment"], 1, {
        entries: [],
        highlight: null,
        occ: 0,
        resolved: false,
        id: null,
        issue: null,
        attrs: [],
      }),
    ).toThrow()
  })

  it("makes IDs and dates as the schema writes them", () => {
    expect(newCommentId()).toMatch(/^[0-9a-f]{8}$/)
    expect(commentDate(new Date("2026-10-09T17:05:59Z"))).toBe(
      "2026-10-09 17:05",
    )
  })
})
