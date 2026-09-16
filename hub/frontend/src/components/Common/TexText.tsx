import katex from "katex"
import "katex/dist/katex.min.css"
import { Fragment, useMemo } from "react"

import { splitTexSegments } from "../../lib/tex"

interface TexTextProps {
  children: string
}

// The font commands worth honoring in a table cell, mapped to how they look.
const FONT_COMMANDS: Array<[RegExp, React.CSSProperties]> = [
  [/^\\(?:textbf|bm|boldsymbol)$/, { fontWeight: "bold" }],
  [/^\\(?:textit|emph)$/, { fontStyle: "italic" }],
  [/^\\texttt$/, { fontFamily: "monospace" }],
]

const FONT_CALL =
  /\\(?:textbf|textit|texttt|textsf|emph|bm|boldsymbol|text|mathrm)\s*\{([\s\S]*?)\}/g

// A text run, with the font commands turned into styled spans and the
// remaining escapes (`\%`, `\&`, ...) turned back into their characters.
const renderTextRun = (text: string, keyPrefix: string): React.ReactNode[] => {
  const nodes: React.ReactNode[] = []
  let last = 0
  FONT_CALL.lastIndex = 0
  let match = FONT_CALL.exec(text)
  const literal = (raw: string) => raw.replace(/\\([%$&#_{}])/g, "$1")
  while (match !== null) {
    if (match.index > last) {
      nodes.push(literal(text.slice(last, match.index)))
    }
    const command = match[0].slice(0, match[0].indexOf("{")).trim()
    const style = FONT_COMMANDS.find(([re]) => re.test(command))?.[1]
    nodes.push(
      <span key={`${keyPrefix}-f${match.index}`} style={style}>
        {renderTextRun(match[1], `${keyPrefix}-${match.index}`)}
      </span>,
    )
    last = match.index + match[0].length
    match = FONT_CALL.exec(text)
  }
  if (last < text.length) {
    nodes.push(literal(text.slice(last)))
  }
  return nodes
}

/**
 * A string of TeX, rendered.
 *
 * Inline math goes through KaTeX and everything else is shown as text, so a
 * generated table's `$T_{f,2}$` reads as a symbol with a subscript rather
 * than as its own source. Math that KaTeX can't parse falls back to the
 * source, which is still more useful than an error.
 */
const TexText = ({ children }: TexTextProps) => {
  const segments = useMemo(() => splitTexSegments(children), [children])
  return (
    <>
      {segments.map((segment, i) => {
        if (segment.type === "text") {
          return (
            <Fragment key={i}>{renderTextRun(segment.value, `t${i}`)}</Fragment>
          )
        }
        // `trust` stays at its default of false, so \href and \includegraphics
        // are rejected rather than rendered out of a project's table.
        const html = katex.renderToString(segment.value, {
          throwOnError: false,
          errorColor: "inherit",
          displayMode: false,
          output: "html",
        })
        return (
          // biome-ignore lint/security/noDangerouslySetInnerHtml: KaTeX output, with trust off
          <span key={i} dangerouslySetInnerHTML={{ __html: html }} />
        )
      })}
    </>
  )
}

export default TexText
