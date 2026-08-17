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
  })
})
