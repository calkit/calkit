import { Box, Flex, Text } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import axios from "axios"
import { Suspense, lazy } from "react"
import SyntaxHighlighter from "react-syntax-highlighter"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"

import { type Notebook } from "../../client"
import { decodeBase64Utf8 } from "../../lib/strings"
import LoadingSpinner from "../Common/LoadingSpinner"
import { getLanguage } from "../Files/FileContent"

const IpynbRenderer = lazy(() =>
  import("react-ipynb-renderer").then(async (m) => {
    await import("react-ipynb-renderer/dist/styles/monokai.css")
    return { default: m.IpynbRenderer }
  }),
)

interface NotebookViewProps {
  notebook: Notebook
}

function NotebookView({ notebook }: NotebookViewProps) {
  // A notebook over the inline size limit comes back as a link to the raw
  // .ipynb instead of its content. That is still a notebook to render, not a
  // page to open: handing the URL to an iframe just makes the browser
  // download the file. Fetch it and render it the same way as an inlined one.
  const isLinkedNotebook =
    notebook.output_format === "notebook" &&
    !notebook.content &&
    Boolean(notebook.url)
  const linkedQuery = useQuery({
    queryKey: ["notebook-content", notebook.path, notebook.url],
    queryFn: () => axios.get(String(notebook.url)).then((r) => r.data),
    enabled: isLinkedNotebook,
    staleTime: 5 * 60 * 1000,
  })
  if (isLinkedNotebook) {
    if (linkedQuery.isPending) {
      return <LoadingSpinner />
    }
    if (linkedQuery.data) {
      // axios parses a JSON response for us, but a presigned URL can serve
      // the same bytes as text, so accept either.
      const json =
        typeof linkedQuery.data === "string"
          ? JSON.parse(linkedQuery.data)
          : linkedQuery.data
      return (
        <Box
          overflowY="auto"
          overflowX="hidden"
          borderRadius="lg"
          height="100%"
        >
          <Suspense fallback={<LoadingSpinner />}>
            <IpynbRenderer ipynb={json} syntaxTheme="atomDark" />
          </Suspense>
        </Box>
      )
    }
    if (linkedQuery.isError) {
      return (
        <Flex align="center" justify="center" height="300px" color="gray.500">
          <Text>This notebook couldn't be loaded.</Text>
        </Flex>
      )
    }
  }
  if (notebook.output_format === "notebook" && notebook.content) {
    try {
      const json = JSON.parse(decodeBase64Utf8(notebook.content))
      return (
        <Box
          overflowY="auto"
          overflowX="hidden"
          borderRadius="lg"
          height="100%"
          sx={{
            ".ipynb-renderer-root": { borderRadius: "var(--chakra-radii-lg)" },
            ".ipynb-renderer-root #notebook-container": {
              width: "100%",
              marginLeft: 0,
              marginRight: 0,
            },
            ".ipynb-renderer-root pre, .ipynb-renderer-root .CodeMirror": {
              fontSize: "13px !important",
              lineHeight: "1.5 !important",
            },
          }}
        >
          <Suspense fallback={<LoadingSpinner />}>
            <IpynbRenderer ipynb={json} syntaxTheme="atomDark" />
          </Suspense>
        </Box>
      )
    } catch {
      // Fall through to the other renderers below
    }
  }
  // A marimo notebook is a Python module whose stage builds an app, so its
  // source is the notebook itself rather than a rendering of a run
  if (notebook.output_format === "source" && notebook.content) {
    return (
      <Box borderRadius="lg" overflow="hidden" height="100%" fontSize="sm">
        <SyntaxHighlighter
          language={getLanguage(notebook.path)}
          style={atomOneDark}
          customStyle={{
            height: "100%",
            margin: 0,
            borderRadius: "8px",
            overflowX: "auto",
            overflowY: "auto",
          }}
        >
          {decodeBase64Utf8(notebook.content)}
        </SyntaxHighlighter>
      </Box>
    )
  }
  if (notebook.output_format === "html" && notebook.content) {
    return (
      <embed
        height="100%"
        width="100%"
        type="text/html"
        src={`data:text/html;base64,${notebook.content}`}
        style={{ borderRadius: "0px" }}
      />
    )
  }
  // An HTML rendering stored outside Git (e.g., in DVC) comes back as a URL,
  // and that one really is a page to embed. A raw .ipynb is handled above.
  if (notebook.url && notebook.output_format !== "notebook") {
    return (
      <iframe
        height="100%"
        width="100%"
        title="notebook"
        src={String(notebook.url)}
        style={{ border: "none" }}
      />
    )
  }
  return (
    <Flex align="center" justify="center" height="300px" color="gray.500">
      <Text>
        No rendered output found. Run the notebook and commit the HTML output to
        view it here.
      </Text>
    </Flex>
  )
}

export default NotebookView
