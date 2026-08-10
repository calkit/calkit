import { describe, expect, it } from "vitest"

import { trimForSave } from "./strings"

describe("trimForSave", () => {
  it("strips trailing whitespace and ends with exactly one newline", () => {
    expect(trimForSave("a   \nb\t\n")).toBe("a\nb\n")
    // Missing, single, and repeated trailing newlines all normalize
    expect(trimForSave("a")).toBe("a\n")
    expect(trimForSave("a\n")).toBe("a\n")
    expect(trimForSave("a\n\n\n")).toBe("a\n")
    // Trailing whitespace on otherwise blank trailing lines goes too
    expect(trimForSave("a\n  \n \n")).toBe("a\n")
    // Interior blank lines and leading indentation are left alone
    expect(trimForSave("a\n\n    b\n")).toBe("a\n\n    b\n")
    // CRLF line endings lose the stray carriage return
    expect(trimForSave("a\r\nb\r\n")).toBe("a\nb\n")
    // An empty document stays empty rather than gaining a newline
    expect(trimForSave("")).toBe("")
    expect(trimForSave("\n\n")).toBe("")
  })
})
