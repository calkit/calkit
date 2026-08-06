import {
  Alert,
  AlertIcon,
  Box,
  Center,
  IconButton,
  Image,
  Spinner,
  Text,
} from "@chakra-ui/react"
import { init as initPptxPreview } from "pptx-preview"
import { useCallback, useEffect, useRef, useState } from "react"
import { FiChevronLeft, FiChevronRight } from "react-icons/fi"

import type { Presentation } from "../../client"
import PdfDocumentViewer from "../Common/PdfDocumentViewer"

interface PresentationViewProps {
  presentation: Presentation
}

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

function PptxView({ presentation }: PresentationViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const slidesRef = useRef<HTMLElement[]>([])
  const currentRef = useRef(0)
  const [width, setWidth] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [current, setCurrent] = useState(0)
  const [total, setTotal] = useState(0)

  // Measure the available width from the container and re-measure on resize.
  // pptx-preview renders slides at a fixed pixel width, so we must pass the
  // real container width or slides overflow horizontally.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    let raf: number | null = null
    const measure = () => {
      raf = null
      const w = Math.floor(el.clientWidth)
      // Ignore sub-threshold jitter to avoid thrashing the pptx re-render.
      setWidth((prev) => (Math.abs(prev - w) >= 8 ? w : prev))
    }
    const ro = new ResizeObserver(() => {
      if (raf === null) raf = requestAnimationFrame(measure)
    })
    ro.observe(el)
    measure()
    return () => {
      ro.disconnect()
      if (raf !== null) cancelAnimationFrame(raf)
    }
  }, [])

  const applyVisibility = useCallback((idx: number) => {
    slidesRef.current.forEach((slide, i) => {
      slide.style.display = i === idx ? "block" : "none"
      slide.style.margin = "0 auto"
    })
  }, [])

  // Show only the active slide; pptx-preview renders every slide stacked, so
  // we turn it into a carousel by toggling visibility.
  useEffect(() => {
    currentRef.current = current
    applyVisibility(current)
  }, [current, applyVisibility])

  const go = useCallback((delta: number) => {
    setCurrent((c) => {
      const next = c + delta
      if (next < 0 || next >= slidesRef.current.length) return c
      return next
    })
  }, [])

  useEffect(() => {
    if (total <= 1) return
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (e.key === "ArrowLeft") {
        e.preventDefault()
        go(-1)
      } else if (e.key === "ArrowRight") {
        e.preventDefault()
        go(1)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [total, go])

  useEffect(() => {
    if (width <= 0) return
    let cancelled = false
    const el = wrapperRef.current
    if (!el) return
    // Clear any previously rendered slides (e.g. when switching presentations
    // or re-rendering at a new width).
    el.innerHTML = ""
    slidesRef.current = []
    setIsLoading(true)
    setError(null)

    const render = async () => {
      try {
        let data: ArrayBuffer
        if (presentation.content) {
          data = base64ToArrayBuffer(presentation.content)
        } else if (presentation.url) {
          const resp = await fetch(String(presentation.url))
          if (!resp.ok) {
            throw new Error(`Failed to fetch presentation (${resp.status})`)
          }
          data = await resp.arrayBuffer()
        } else {
          throw new Error("no-content")
        }
        if (cancelled || !wrapperRef.current) return
        const previewer = initPptxPreview(wrapperRef.current, {
          width,
          height: Math.round((width * 9) / 16),
        })
        await previewer.preview(data)
        if (cancelled || !wrapperRef.current) return
        // Constrain pptx-preview's fixed-width wrapper so it can never cause
        // horizontal overflow within our container.
        const ppWrap = wrapperRef.current.querySelector<HTMLElement>(
          ".pptx-preview-wrapper",
        )
        if (ppWrap) {
          ppWrap.style.maxWidth = "100%"
          ppWrap.style.overflow = "hidden"
        }
        const slides = Array.from(
          wrapperRef.current.querySelectorAll<HTMLElement>(
            ".pptx-preview-slide-wrapper",
          ),
        )
        slidesRef.current = slides
        const start = Math.min(
          currentRef.current,
          Math.max(slides.length - 1, 0),
        )
        applyVisibility(start)
        setTotal(slides.length)
        setCurrent(start)
      } catch (e) {
        if (!cancelled) {
          setError(
            e instanceof Error && e.message === "no-content"
              ? "no-content"
              : "render-failed",
          )
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    render()
    return () => {
      cancelled = true
    }
  }, [presentation.content, presentation.url, width, applyVisibility])

  if (error === "no-content") {
    return (
      <Alert mt={2} status="warning" borderRadius="xl">
        <AlertIcon />
        No content found. Perhaps the presentation hasn't been built and pushed
        yet?
      </Alert>
    )
  }

  return (
    <Box
      ref={containerRef}
      position="relative"
      height="100%"
      width="100%"
      overflow="hidden"
      display="flex"
      alignItems="center"
      justifyContent="center"
    >
      {isLoading && (
        <Center position="absolute" inset={0} zIndex={2}>
          <Spinner />
        </Center>
      )}
      {error === "render-failed" && (
        <Alert mt={2} status="error" borderRadius="xl">
          <AlertIcon />
          Could not render this presentation. Try downloading the file instead.
        </Alert>
      )}
      <Box
        ref={wrapperRef}
        width="100%"
        display="flex"
        justifyContent="center"
        overflow="hidden"
      />
      {total > 1 && (
        <>
          <IconButton
            aria-label="Previous slide"
            icon={<FiChevronLeft />}
            onClick={() => go(-1)}
            isDisabled={current === 0}
            position="absolute"
            left={2}
            top="50%"
            transform="translateY(-50%)"
            zIndex={1}
            borderRadius="full"
            size="lg"
            opacity={0.7}
            _hover={{ opacity: 1 }}
          />
          <IconButton
            aria-label="Next slide"
            icon={<FiChevronRight />}
            onClick={() => go(1)}
            isDisabled={current === total - 1}
            position="absolute"
            right={2}
            top="50%"
            transform="translateY(-50%)"
            zIndex={1}
            borderRadius="full"
            size="lg"
            opacity={0.7}
            _hover={{ opacity: 1 }}
          />
          <Text
            position="absolute"
            bottom={2}
            left="50%"
            transform="translateX(-50%)"
            zIndex={1}
            fontSize="sm"
            px={2}
            py={0.5}
            borderRadius="md"
            bg="blackAlpha.600"
            color="white"
          >
            {current + 1} / {total}
          </Text>
        </>
      )}
    </Box>
  )
}

function PresentationView({ presentation }: PresentationViewProps) {
  const path = presentation.path.toLowerCase()
  const hasContent = Boolean(presentation.content || presentation.url)

  if (path.endsWith(".pptx") || path.endsWith(".ppt")) {
    return <PptxView presentation={presentation} />
  }
  if (path.endsWith(".pdf") && hasContent) {
    // Render slide-by-slide (prev/next arrows + arrow keys) with the internal
    // PDF viewer rather than a scrolling document embed.
    return (
      <PdfDocumentViewer
        url={
          presentation.content
            ? `data:application/pdf;base64,${presentation.content}`
            : String(presentation.url)
        }
        pagedNav
        source="presentation"
      />
    )
  }
  if (path.endsWith(".html") && hasContent) {
    return (
      <embed
        height="100%"
        width="100%"
        type="text/html"
        src={
          presentation.url
            ? String(presentation.url)
            : `data:text/html;base64,${presentation.content}`
        }
      />
    )
  }
  if (
    (path.endsWith(".png") ||
      path.endsWith(".jpg") ||
      path.endsWith(".jpeg")) &&
    hasContent
  ) {
    const imageMime = path.endsWith(".png") ? "image/png" : "image/jpeg"
    return (
      <Image
        alt={presentation.title}
        src={
          presentation.content
            ? `data:${imageMime};base64,${presentation.content}`
            : String(presentation.url)
        }
      />
    )
  }
  return (
    <Alert mt={2} status="warning" borderRadius="xl">
      <AlertIcon />
      No preview available for this presentation
      {presentation.url ? "; use the download link in the info panel." : "."}
    </Alert>
  )
}

export default PresentationView
