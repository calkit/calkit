import { ChakraProvider } from "@chakra-ui/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"

import { ProjectsService } from "../../client"

import Markdown, { repoImagePath } from "./Markdown"

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

  it("restores paragraphs YAML folding collapsed, except in code", () => {
    const folded =
      "First paragraph.\nSecond paragraph.\n\n```py\nx = 1\n\ny = 2\n```"
    const html = renderToStaticMarkup(
      <ChakraProvider>
        <Markdown foldedProse>{folded}</Markdown>
      </ChakraProvider>,
    )
    // Two paragraphs plus the fence, rather than one wall of text.
    expect(html.match(/Second paragraph\./)).not.toBeNull()
    expect(html.match(/<p[ >]/g)?.length).toBe(2)
    // A blank line inside a fence is content, so the code is left alone.
    expect(html).toContain("x = 1\n\ny = 2")
    // Without the flag, the single newline stays a soft break.
    const plain = renderToStaticMarkup(
      <ChakraProvider>
        <Markdown>{folded}</Markdown>
      </ChakraProvider>,
    )
    expect(plain.match(/<p[ >]/g)?.length).toBe(1)
  })

  it("keeps long code blocks within the markdown container", () => {
    const html = renderToStaticMarkup(
      <ChakraProvider>
        <Markdown>{"```sh\ncommand --with-a-very-long-argument\n```"}</Markdown>
      </ChakraProvider>,
    )
    const preClass = html.match(/<pre[^>]*class="(css-[a-z0-9]+)"/i)?.[1]
    expect(preClass).toBeDefined()
    const preStyles = html.match(new RegExp(`\\.${preClass}\\{([^}]*)\\}`))?.[1]
    expect(preStyles).toContain("max-width:100%")
    expect(preStyles).toContain("overflow-x:auto")
  })
})

describe("repoImagePath", () => {
  it("resolves repo images against the file's directory", () => {
    expect(repoImagePath("docs/img/logo.png")).toBe("docs/img/logo.png")
    expect(repoImagePath("./logo.png", "docs")).toBe("docs/logo.png")
    expect(repoImagePath("../img/logo.png", "docs/guide")).toBe(
      "docs/img/logo.png",
    )
    // A leading slash is the repo root, as on GitHub
    expect(repoImagePath("/img/logo.png", "docs")).toBe("img/logo.png")
    expect(repoImagePath("logo.png?raw=true")).toBe("logo.png")
    // Markdown URL-encodes what the repo names plainly
    expect(repoImagePath("docs/my%20logo.png")).toBe("docs/my logo.png")
    expect(repoImagePath("%2e%2e/logo.png", "docs")).toBe("logo.png")
  })

  it("leaves images that aren't in the repo alone", () => {
    expect(repoImagePath("https://example.com/logo.png")).toBeNull()
    expect(repoImagePath("//example.com/logo.png")).toBeNull()
    expect(repoImagePath("data:image/png;base64,AAAA")).toBeNull()
    expect(repoImagePath("")).toBeNull()
    // Above the repo root
    expect(repoImagePath("../logo.png")).toBeNull()
    expect(repoImagePath("%2e%2e/logo.png")).toBeNull()
    // Separators or bad escapes smuggled in by encoding
    expect(repoImagePath("..%2f..%2fsecret.png", "docs")).toBeNull()
    expect(repoImagePath("a%5c..%5csecret.png")).toBeNull()
    expect(repoImagePath("bad%zzname.png")).toBeNull()
  })
})

describe("Markdown with a repo", () => {
  const repo = { accountName: "me", projectName: "proj", ref: "main" }
  const render = (text: string, client: QueryClient) =>
    renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <ChakraProvider>
          <Markdown repo={repo}>{text}</Markdown>
        </ChakraProvider>
      </QueryClientProvider>,
    )
  const key = (path: string) => [
    "projects",
    "me",
    "proj",
    "contents",
    path,
    "main",
  ]

  it("shows repo images from their content or storage URL", () => {
    const client = new QueryClient()
    client.setQueryData(key("docs/logo.png"), { content: "AAAA" })
    client.setQueryData(key("figs/plot.png"), {
      url: "https://storage.test/plot.png",
    })
    const html = render(
      '<img src="docs/logo.png" alt="Logo">\n\n![Plot](figs/plot.png)',
      client,
    )
    expect(html).toContain('src="data:image/png;base64,AAAA"')
    expect(html).toContain('alt="Logo"')
    expect(html).toContain('src="https://storage.test/plot.png"')
  })

  it("leaves images from elsewhere alone and asks the hub for nothing", () => {
    const fetch = vi.spyOn(ProjectsService, "getProjectContents")
    const client = new QueryClient()
    const html = render("![Badge](https://img.shields.io/badge.svg)", client)
    expect(html).toContain('src="https://img.shields.io/badge.svg"')
    expect(fetch).not.toHaveBeenCalled()
    expect(client.getQueryCache().getAll()).toHaveLength(0)
    fetch.mockRestore()
  })
})
