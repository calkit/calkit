import { describe, expect, it } from "vitest"

import { isSubmitChord } from "./useSubmitOnCmdEnter"

const key = (overrides: Partial<Parameters<typeof isSubmitChord>[0]>) => ({
  key: "Enter",
  metaKey: false,
  ctrlKey: false,
  altKey: false,
  shiftKey: false,
  ...overrides,
})

describe("isSubmitChord", () => {
  it("fires on Cmd+Enter or Ctrl+Enter and nothing else", () => {
    expect(isSubmitChord(key({ metaKey: true }))).toBe(true)
    expect(isSubmitChord(key({ ctrlKey: true }))).toBe(true)
    // Plain Enter is the textarea's newline, not a submit.
    expect(isSubmitChord(key({}))).toBe(false)
    // Shift+Enter and Alt+Enter mean other things in editors.
    expect(isSubmitChord(key({ metaKey: true, shiftKey: true }))).toBe(false)
    expect(isSubmitChord(key({ metaKey: true, altKey: true }))).toBe(false)
    expect(isSubmitChord(key({ metaKey: true, key: "a" }))).toBe(false)
  })
})
