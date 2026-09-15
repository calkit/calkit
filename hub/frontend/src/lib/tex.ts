// Reading the TeX that generated-table writers put in cells.
//
// A table written by `to_latex` and friends is full of inline math -- column
// headers like `$T_{f,2}$` and values like `$500 \cdot 10^{-3}$`. Two things
// need it in different forms: the grid renders it as math, while searching,
// sorting, and deciding whether a column is numeric all want the plain text
// underneath.

export interface TexSegment {
  type: "text" | "math"
  value: string
}

// `$...$` and `\(...\)`, the two inline forms a generated table uses. `$$`
// display math is not one of them, and a lone `$` is a literal dollar sign.
const INLINE_MATH = /\$([^$]+)\$|\\\(([\s\S]*?)\\\)/g

/**
 * Split TeX into runs of text and runs of math.
 *
 * Callers render the math runs and leave the text runs alone, so a cell that
 * is entirely `$D_s$` and a cell that mixes prose with a symbol both work.
 */
export const splitTexSegments = (text: string): TexSegment[] => {
  const segments: TexSegment[] = []
  let last = 0
  INLINE_MATH.lastIndex = 0
  let match = INLINE_MATH.exec(text)
  while (match !== null) {
    if (match.index > last) {
      segments.push({ type: "text", value: text.slice(last, match.index) })
    }
    segments.push({ type: "math", value: match[1] ?? match[2] ?? "" })
    last = match.index + match[0].length
    match = INLINE_MATH.exec(text)
  }
  if (last < text.length) {
    segments.push({ type: "text", value: text.slice(last) })
  }
  return segments
}

/**
 * The readable text inside a TeX cell, with the markup taken out.
 *
 * This is what search matches against and what the numeric check parses, so
 * `$6 $` counts as the number 6 and a column of them right-aligns like the
 * numbers it holds. Only ever applied to cells that came from a `.tex` file:
 * running it over a CSV would eat real dollar signs and backslashes.
 */
export const texToPlainText = (text: string): string => {
  let out = text
  // One level of the usual font commands, applied repeatedly so nested ones
  // (\textbf{\textit{x}}) unwrap too
  for (let i = 0; i < 3; i++) {
    out = out.replace(
      /\\(textbf|textit|texttt|textsf|emph|mathrm|mathit|text|bm|boldsymbol)\s*\{([\s\S]*?)\}/g,
      "$2",
    )
  }
  out = out.replace(/\\(?:num|si|SI)\s*\{([^}]*)\}/g, "$1")
  // Drop the math delimiters, keeping what they wrapped
  out = out.replace(INLINE_MATH, (_m, dollars, parens) => dollars ?? parens)
  // Spacing and operator commands that stand for a character
  out = out.replace(/\\cdot\b/g, "·")
  out = out.replace(/\\times\b/g, "×")
  out = out.replace(/\\pm\b/g, "±")
  out = out.replace(/\\%/g, "%")
  out = out.replace(/\\,|\\;|\\:|\\!|\\quad\b|\\qquad\b/g, " ")
  // Escaped characters become themselves
  out = out.replace(/\\([%$&#_{}])/g, "$1")
  // Whatever markup is left carries no text of its own
  out = out.replace(/\\[a-zA-Z]+\s*/g, "")
  out = out.replace(/[{}]/g, "")
  return out.replace(/\s+/g, " ").trim()
}
