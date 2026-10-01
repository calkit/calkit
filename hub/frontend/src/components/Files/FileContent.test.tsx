import { ChakraProvider } from "@chakra-ui/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

// FileContent pulls the PDF viewer in with it, which drags in a
// react-pdf-highlighter bundle vitest can't resolve, so stub it out.
vi.mock("../Common/PdfDocumentViewer", () => ({ default: () => null }))

import type { ContentsItem } from "../../client"
import { encodeBase64Utf8 } from "../../lib/strings"

import FileContent from "./FileContent"

const readme: ContentsItem = {
  name: "README.md",
  path: "README.md",
  type: "file",
  size: 120,
  in_repo: true,
  storage: "git",
  content: encodeBase64Utf8(
    '<p align="center">\n<img src="docs/img/logo.png" alt="Logo">\n</p>',
  ),
}

describe("FileContent", () => {
  it("loads README images declared by a repo path from the project", () => {
    const client = new QueryClient()
    client.setQueryData(
      ["projects", "me", "proj", "contents", "docs/img/logo.png", undefined],
      { content: "AAAA" },
    )
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ChakraProvider>
          <FileContent item={readme} accountName="me" projectName="proj" />
        </ChakraProvider>
      </QueryClientProvider>,
    )
    // Without the project's repo, the relative src would resolve against the
    // files page URL and 404
    expect(html).toContain('src="data:image/png;base64,AAAA"')
  })
})
