import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import TexText from "./TexText"

describe("TexText", () => {
  it("renders font commands as styled text", () => {
    const html = renderToStaticMarkup(
      <TexText>{"\\textbf{Dep. Variable:} body\\_mass\\_g"}</TexText>,
    )
    expect(html).toContain('style="font-weight:bold">Dep. Variable:</span>')
    expect(html).toContain("body_mass_g")
    const two = renderToStaticMarkup(
      <TexText>{"\\textbf{x} and \\textit{y}"}</TexText>,
    )
    expect(two).toContain('style="font-weight:bold">x</span>')
    expect(two).toContain('style="font-style:italic">y</span>')
  })

  it("renders inline math with KaTeX", () => {
    const html = renderToStaticMarkup(<TexText>{"$T_{f,2}$ at 5%"}</TexText>)
    expect(html).toContain("katex")
    expect(html).toContain("at 5%")
  })
})
