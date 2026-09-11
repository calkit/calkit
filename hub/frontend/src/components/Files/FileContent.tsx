import { Box, Image } from "@chakra-ui/react"
import SyntaxHighlighter from "react-syntax-highlighter"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"

import type { ContentsItem } from "../../client"
import { decodeBase64Utf8 } from "../../lib/strings"
import Markdown from "../Common/Markdown"
import PdfDocumentViewer from "../Common/PdfDocumentViewer"
import PresentationView from "../Presentations/PresentationView"

interface FileContentProps {
  item: ContentsItem
}

// Render a Quarto/R Markdown source as Markdown while keeping the leading
// YAML front matter block verbatim (shown as a fenced code block rather than
// being parsed/consumed by the Markdown renderer).
export function qmdToMarkdown(src: string): string {
  const match = src.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/)
  if (!match) return src
  const frontMatter = match[1]
  const body = src.slice(match[0].length)
  return `\`\`\`yaml\n${frontMatter}\n\`\`\`\n\n${body}`
}

export function getLanguage(name: string): string {
  // Compare case-insensitively so all-caps names map to the right language.
  const n = name.toLowerCase()
  if (n.endsWith(".py")) return "python"
  if (n.endsWith(".ts") || n.endsWith(".tsx")) return "typescript"
  if (n.endsWith(".js") || n.endsWith(".jsx")) return "javascript"
  if (n.endsWith(".yaml") || n.endsWith(".yml") || n === "dvc.lock")
    return "yaml"
  if (n.endsWith(".json")) return "json"
  if (n.endsWith(".sh") || n.endsWith(".bash")) return "bash"
  if (n.endsWith(".r")) return "r"
  if (n.endsWith(".toml")) return "ini"
  if (n === "dockerfile") return "dockerfile"
  if (n.endsWith(".cpp") || n.endsWith(".cc")) return "cpp"
  if (n.endsWith(".c")) return "c"
  if (n.endsWith(".go")) return "go"
  if (n.endsWith(".java")) return "java"
  if (n.endsWith(".rs")) return "rust"
  if (n.endsWith(".css")) return "css"
  if (n.endsWith(".html")) return "html"
  if (n.endsWith(".tex")) return "latex"
  return "text"
}

function FileContent({ item }: FileContentProps) {
  const { name, content, url } = item
  // Match extensions case-insensitively so all-caps names (FOO.PDF, IMG.PNG,
  // SLIDES.PPTX, …) render the same as their lowercase equivalents.
  const lowerName = name.toLowerCase()
  if (lowerName.endsWith(".png")) {
    return (
      <Image
        src={content ? `data:image/png;base64,${content}` : String(url)}
        width={"100%"}
      />
    )
  }
  if (lowerName.endsWith(".jpg") || lowerName.endsWith(".jpeg")) {
    return (
      <Image
        src={content ? `data:image/jpeg;base64,${content}` : String(url)}
        width={"100%"}
      />
    )
  }
  if (lowerName.endsWith(".svg")) {
    return (
      <Image
        src={content ? `data:image/svg+xml;base64,${content}` : String(url)}
        width={"100%"}
      />
    )
  }
  if (lowerName.endsWith(".pdf")) {
    return (
      <Box
        height="calc(100vh - 160px)"
        width="100%"
        borderRadius="lg"
        overflow="hidden"
      >
        <PdfDocumentViewer
          url={content ? `data:application/pdf;base64,${content}` : String(url)}
          source="file"
        />
      </Box>
    )
  }
  if (lowerName.endsWith(".pptx") || lowerName.endsWith(".ppt")) {
    return (
      <Box
        height="calc(100vh - 160px)"
        width="100%"
        borderRadius="lg"
        overflow="hidden"
      >
        <PresentationView
          presentation={{
            path: item.path,
            title: name,
            content: content ?? null,
            url: url ?? null,
          }}
        />
      </Box>
    )
  }
  if ((lowerName.endsWith(".md") || lowerName.endsWith(".qmd")) && content) {
    const decoded = decodeBase64Utf8(content)
    return (
      <Box
        height="calc(100vh - 160px)"
        width="100%"
        overflowY="auto"
        py={2}
        px={4}
      >
        <Markdown>
          {lowerName.endsWith(".qmd") ? qmdToMarkdown(decoded) : decoded}
        </Markdown>
      </Box>
    )
  }
  return (
    <Box
      borderRadius="lg"
      overflow="hidden"
      height="calc(100vh - 160px)"
      fontSize="sm"
    >
      <SyntaxHighlighter
        language={getLanguage(name)}
        style={atomOneDark}
        customStyle={{
          height: "100%",
          margin: 0,
          borderRadius: "8px",
          overflowX: "auto",
          overflowY: "auto",
        }}
      >
        {content ? decodeBase64Utf8(content) : ""}
      </SyntaxHighlighter>
    </Box>
  )
}

export default FileContent
