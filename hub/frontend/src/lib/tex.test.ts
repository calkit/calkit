import { describe, expect, it } from "vitest"

import { splitTexSegments, texToPlainText } from "./tex"

describe("tex", () => {
  it("splits inline math from text", () => {
    // A cell that is nothing but a symbol, which is most of a generated table
    expect(splitTexSegments("$D_s$")).toEqual([{ type: "math", value: "D_s" }])
    // Text and math interleaved, in both delimiter styles
    expect(splitTexSegments("Depth $h_s$ (m)")).toEqual([
      { type: "text", value: "Depth " },
      { type: "math", value: "h_s" },
      { type: "text", value: " (m)" },
    ])
    expect(splitTexSegments("a \\(x\\) b")).toEqual([
      { type: "text", value: "a " },
      { type: "math", value: "x" },
      { type: "text", value: " b" },
    ])
    // No math at all is one text run, and an unpaired delimiter is not math
    expect(splitTexSegments("plain")).toEqual([
      { type: "text", value: "plain" },
    ])
    expect(splitTexSegments("costs $5")).toEqual([
      { type: "text", value: "costs $5" },
    ])
  })

  it("reduces TeX to the text underneath it", () => {
    // Math delimiters go, so a column of these still reads as numbers
    expect(texToPlainText("$6 $")).toBe("6")
    expect(texToPlainText("$500 \\cdot 10^{-3}$")).toBe("500 · 10^-3")
    // Font commands unwrap, including nested ones
    expect(texToPlainText("\\textbf{Kernel}")).toBe("Kernel")
    expect(texToPlainText("\\textbf{\\textit{x}}")).toBe("x")
    // Escapes become the characters they stand for
    expect(texToPlainText("set\\_cache")).toBe("set_cache")
    expect(texToPlainText("-54\\%")).toBe("-54%")
    expect(texToPlainText("R \\& D")).toBe("R & D")
    // Markup with no text of its own leaves nothing behind
    expect(texToPlainText("$\\alpha$")).toBe("")
    // Plain text passes through untouched
    expect(texToPlainText("Float Too Heavy")).toBe("Float Too Heavy")
  })
})
