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

const numbersJson: ContentsItem = {
  name: "numbers.json",
  path: "pubs/applied-ocean-research-model/numbers.json",
  type: "file",
  size: 20,
  in_repo: true,
  storage: "git",
  content: encodeBase64Utf8('{\n  "answer": 42\n}'),
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

  // Regression test for #1823: the git ref must be passed via a non-reserved
  // prop. When it was named `ref`, React treated the ref string as a string
  // ref on the function component and threw "Element ref was specified as a
  // string ... but no owner was set", breaking every file view at a ref.
  it("renders a file at a git ref without treating the ref as a React ref", () => {
    const client = new QueryClient()
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ChakraProvider>
          <FileContent
            item={numbersJson}
            accountName="me"
            projectName="proj"
            gitRef="1a1c5de"
          />
        </ChakraProvider>
      </QueryClientProvider>,
    )
    expect(html).toContain("answer")
  })
})
