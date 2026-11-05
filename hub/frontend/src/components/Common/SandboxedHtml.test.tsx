import { ChakraProvider } from "@chakra-ui/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import SandboxedHtml from "./SandboxedHtml"

const render = (props: Parameters<typeof SandboxedHtml>[0]) =>
  renderToStaticMarkup(
    <ChakraProvider>
      <QueryClientProvider client={new QueryClient()}>
        <SandboxedHtml {...props} />
      </QueryClientProvider>
    </ChakraProvider>,
  )

describe("SandboxedHtml", () => {
  it("embeds project HTML in an opaque origin, inline", () => {
    const page = "<script>parent.localStorage</script><p>Report</p>"
    const signed = "https://storage.example/report.html?sig=secret"
    for (const html of [
      render({ title: "report", html: page, url: signed }),
      render({ title: "report", content: btoa(page), url: signed }),
    ]) {
      expect(html).toContain('sandbox="allow-scripts allow-popups"')
      // Same-origin access or top-level navigation would hand the page the
      // hub's storage or the tab
      expect(html).not.toContain("allow-same-origin")
      expect(html).not.toContain("allow-top-navigation")
      expect(html).not.toContain("allow-popups-to-escape-sandbox")
      expect(html).toContain('referrerPolicy="no-referrer"')
      expect(html).toContain("srcDoc=")
      // The signed URL never reaches the frame, where scripts could read it
      expect(html).not.toContain(" src=")
      expect(html).not.toContain("sig=secret")
    }
  })

  it("renders nothing of the page until a URL-only page is fetched", () => {
    const html = render({ title: "report", url: "https://storage.example/r" })
    expect(html).not.toContain("<iframe")
    expect(html).not.toContain("storage.example")
  })
})
