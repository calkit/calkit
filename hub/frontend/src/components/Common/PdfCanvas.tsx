/**
 * PdfCanvas--renders a PDF as a stack of canvas elements using pdfjs-dist.
 *
 * Each page is rasterized to an off-screen canvas and exposed as a blob URL.
 * Use this component when you need a lightweight, annotation-free PDF preview
 * (e.g., in file-browser thumbnails or figure previews). For interactive
 * annotation (highlights, comments), use PdfAnnotator instead.
 */
import { useEffect, useState } from "react"
import { Box, Text } from "@chakra-ui/react"
import * as pdfjsLib from "pdfjs-dist"

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString()

interface PdfCanvasProps {
  /** A URL or base64 data URI for the PDF. */
  src: string
  width?: string
  /** Constrain by height instead of width. Pages scale to this height with auto width. */
  height?: string
  /** Maximum number of pages to render. Defaults to all pages. */
  maxPages?: number
}

function PdfCanvas({ src, width = "100%", height, maxPages }: PdfCanvasProps) {
  const [pageUrls, setPageUrls] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(false)
    setPageUrls([])

    async function render() {
      try {
        const pdf = await pdfjsLib.getDocument(src).promise
        const urls: string[] = []
        const limit = maxPages ? Math.min(maxPages, pdf.numPages) : pdf.numPages
        for (let i = 1; i <= limit; i++) {
          const page = await pdf.getPage(i)
          const viewport = page.getViewport({ scale: 2 })
          const canvas = document.createElement("canvas")
          canvas.width = viewport.width
          canvas.height = viewport.height
          await page.render({
            canvasContext: canvas.getContext("2d")!,
            viewport,
          }).promise
          urls.push(canvas.toDataURL())
        }
        if (!cancelled) {
          setPageUrls(urls)
          setLoading(false)
        }
      } catch {
        if (!cancelled) {
          setError(true)
          setLoading(false)
        }
      }
    }

    render()
    return () => {
      cancelled = true
    }
  }, [src, maxPages])

  if (loading) return <Text color="gray.500">Loading…</Text>
  if (error) return <Text color="gray.500">Could not render PDF.</Text>

  if (height) {
    return (
      <Box
        height={height}
        display="flex"
        alignItems="center"
        justifyContent="center"
        overflow="hidden"
      >
        {pageUrls.map((url, i) => (
          <img
            key={i}
            src={url}
            alt={`Page ${i + 1}`}
            style={{ maxHeight: "100%", width: "auto", display: "block" }}
          />
        ))}
      </Box>
    )
  }

  return (
    <Box width={width}>
      {pageUrls.map((url, i) => (
        <img
          key={i}
          src={url}
          alt={`Page ${i + 1}`}
          style={{ width: "100%", display: "block" }}
        />
      ))}
    </Box>
  )
}

export default PdfCanvas
