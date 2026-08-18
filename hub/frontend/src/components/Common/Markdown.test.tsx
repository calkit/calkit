import { ChakraProvider } from "@chakra-ui/react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import Markdown from "./Markdown"

describe("Markdown", () => {
  it("renders LaTeX math in figure titles as KaTeX", () => {
    const html = renderToStaticMarkup(
      <ChakraProvider>
        <Markdown>{"Drag coefficient $C_d$ vs. Reynolds number $Re$"}</Markdown>
      </ChakraProvider>,
    )
    expect(html).toContain("katex")
    expect(html).not.toContain("$C_d$")
  })

  it("keeps inline titles from creating links or block elements", () => {
    const html = renderToStaticMarkup(
      <ChakraProvider>
        <Markdown inline>
          {"[linked](https://example.com) **bold**\n\n# heading"}
        </Markdown>
      </ChakraProvider>,
    )
    expect(html).not.toContain('href="https://example.com"')
    expect(html).not.toContain("<h1")
    expect(html).toContain("linked")
    expect(html).toContain("bold")
    expect(html).toContain("heading")
    // Unclamped inline text keeps an inline wrapper, or a title would break
    // onto its own line
    expect(html).toMatch(/\.css-[a-z0-9]+\{display:inline;\}/)
  })

  it("clamps inline text on the element that holds it", () => {
    const html = renderToStaticMarkup(
      <ChakraProvider>
        <Markdown inline noOfLines={2}>
          {"Drag coefficient $C_d$ measured over a rather long sweep"}
        </Markdown>
      </ChakraProvider>,
    )
    // Inline rendering emits paragraphs as spans, so a clamp scoped to a
    // descendant `p` would match nothing and never truncate
    expect(html).not.toContain("<p")
    const clamp = html.match(
      /\.(css-[a-z0-9]+)\{([^}]*-webkit-line-clamp[^}]*)\}/,
    )
    expect(clamp).not.toBeNull()
    const start = html.indexOf(`<span class="${clamp?.[1]}">`)
    expect(start).toBeGreaterThan(-1)
    expect(html.slice(start)).toContain("Drag coefficient")
    expect(clamp?.[2]).toContain("--chakra-line-clamp:2")
    // The clamp needs a block-level display, so it must win over the inline
    // display the wrapper otherwise carries
    expect(clamp?.[2]).toContain("display:-webkit-box")
    expect(clamp?.[2]).not.toContain("display:inline")
  })
})
