/**
 * Shared PDF document viewer built on react-pdf-highlighter (pdf.js).
 *
 * Provides a navigation toolbar (section/bookmark outline, zoom, page jump,
 * download / open externally) on top of the highlighter engine, so the same
 * rich viewing experience is available everywhere a full PDF is shown.
 *
 * Highlighting is optional: pass the `highlights` / `highlightTransform` /
 * `onSelectionFinished` props (as PdfAnnotator does) to enable text-selection
 * comments, or omit them for a read-only viewer (e.g. the file browser). For
 * lightweight, non-interactive previews (figure thumbnails) use PdfCanvas
 * instead.
 */
import {
  Box,
  Flex,
  IconButton,
  Input,
  Link,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import LoadingSpinner from "./LoadingSpinner"
import Tooltip from "./Tooltip"
import mixpanel from "mixpanel-browser"
import type { PDFDocumentProxy } from "pdfjs-dist"
import {
  type MutableRefObject,
  type ReactElement,
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import {
  type IHighlight,
  type LTWH,
  type LTWHP,
  PdfHighlighter,
  PdfLoader,
  type Position,
  type Scaled,
  type ScaledPosition,
} from "react-pdf-highlighter"
import "react-pdf-highlighter/dist/style.css"
import {
  FiChevronDown,
  FiChevronLeft,
  FiChevronRight,
  FiChevronUp,
  FiDownload,
  FiExternalLink,
  FiLayers,
  FiList,
  FiMaximize,
  FiPrinter,
  FiSearch,
  FiX,
  FiZoomIn,
  FiZoomOut,
} from "react-icons/fi"

// react-pdf-highlighter does not export its prop callback types directly, so
// mirror the two we forward here. With T_HT = IHighlight the viewport highlight
// is just IHighlight plus a resolved viewport `position`.
export type ViewportHighlight = IHighlight & { position: Position }

export type HighlightTransform = (
  highlight: ViewportHighlight,
  index: number,
  setTip: (
    highlight: ViewportHighlight,
    callback: (highlight: ViewportHighlight) => JSX.Element,
  ) => void,
  hideTip: () => void,
  viewportToScaled: (rect: LTWHP) => Scaled,
  screenshot: (position: LTWH) => string,
  isScrolledTo: boolean,
) => JSX.Element

export type OnSelectionFinished = (
  position: ScaledPosition,
  content: { text?: string; image?: string },
  hideTipAndSelection: () => void,
  transformSelection: () => void,
) => JSX.Element | null

// ---------------------------------------------------------------------------
// PDF outline (bookmarks / sections) resolution
// ---------------------------------------------------------------------------
export interface OutlineNode {
  title: string
  pageNumber: number | null
  items: OutlineNode[]
}

// Resolve pdf.js' raw outline tree into one carrying concrete page numbers so
// clicking a section can scroll straight to it. Destinations may be a named
// string (needs a getDestination lookup) or an explicit array whose first
// element is a page reference.
async function resolveOutline(
  pdfDocument: PDFDocumentProxy,
): Promise<OutlineNode[]> {
  const raw = await pdfDocument.getOutline()
  if (!raw) return []

  const resolveNodes = async (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    items: any[],
  ): Promise<OutlineNode[]> =>
    Promise.all(
      items.map(async (item) => {
        let pageNumber: number | null = null
        try {
          let dest = item.dest
          if (typeof dest === "string") {
            dest = await pdfDocument.getDestination(dest)
          }
          if (Array.isArray(dest) && dest[0] != null) {
            const ref = dest[0]
            const index =
              typeof ref === "object"
                ? await pdfDocument.getPageIndex(ref)
                : Number(ref)
            if (Number.isFinite(index)) pageNumber = index + 1
          }
        } catch {
          // Leave pageNumber null if the destination can't be resolved.
        }
        return {
          title: item.title,
          pageNumber,
          items: item.items?.length ? await resolveNodes(item.items) : [],
        }
      }),
    )

  return resolveNodes(raw)
}

function OutlineTree({
  nodes,
  currentPage,
  onSelect,
}: {
  nodes: OutlineNode[]
  currentPage: number
  onSelect: (pageNumber: number) => void
}) {
  return (
    <>
      {nodes.map((node, i) => (
        <Box key={`${node.title}-${i}`} pl={2}>
          {node.pageNumber ? (
            <Box
              as="button"
              type="button"
              display="block"
              textAlign="left"
              width="100%"
              fontSize="xs"
              py={0.5}
              noOfLines={2}
              cursor="pointer"
              color={node.pageNumber === currentPage ? "ui.main" : undefined}
              _hover={{ color: "ui.main" }}
              onClick={() => onSelect(node.pageNumber as number)}
            >
              {node.title}
            </Box>
          ) : (
            <Text fontSize="xs" py={0.5} noOfLines={2} color="gray.500">
              {node.title}
            </Text>
          )}
          {node.items.length > 0 && (
            <OutlineTree
              nodes={node.items}
              currentPage={currentPage}
              onSelect={onSelect}
            />
          )}
        </Box>
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface PdfDocumentViewerProps {
  url: string
  // Optional highlight integration. Omit for a read-only viewer.
  highlights?: Array<IHighlight>
  highlightTransform?: HighlightTransform
  onSelectionFinished?: OnSelectionFinished
  enableAreaSelection?: (event: MouseEvent) => boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  externalScrollRef?: MutableRefObject<(h: any) => void>
  // When true, render page-by-page navigation (prev/next arrows + arrow keys)
  // like a slide carousel instead of the scrolling toolbar view. Used for
  // presentation PDFs.
  pagedNav?: boolean
  // Where the viewer is used (e.g. "publication", "presentation", "file").
  // Sent along with analytics events.
  source?: string
  // Initial zoom (a pdf.js scale value, e.g. "auto", "page-width",
  // "page-fit", or a number). Defaults to "auto".
  defaultScale?: string
  // Optional element rendered at the start of the toolbar's right-aligned
  // action group, e.g. an "Edit LaTeX" button for publications.
  toolbarAction?: ReactNode
  // When false, the download action is disabled (e.g. an in-editor preview that
  // shouldn't be mistaken for the official, pipeline-built PDF). The tooltip
  // then shows `downloadDisabledHint`.
  allowDownload?: boolean
  downloadDisabledHint?: ReactNode
  // Optional panel beside the document, toggled from the toolbar. It is
  // given the page currently in view, so it can show what is on the page
  // the reader is looking at, and a way to jump to another one.
  sidePanel?: (ctx: {
    currentPage: number
    goToPage: (pageNumber: number) => void
  }) => ReactNode
  // Tooltip and accessible name for the panel's toolbar toggle.
  sidePanelLabel?: string
  sidePanelIcon?: ReactElement
  // Rendered on the panel's toggle, for something the reader should see
  // without opening it first -- a count of what has gone out of date.
  sidePanelBadge?: ReactNode
}

const highlightSx = {
  ".Highlight__part": {
    opacity: 0.45,
    background: "rgba(246, 224, 94, 0.85)",
  },
}

const noopTransform: HighlightTransform = () => <></>
const noopSelection: OnSelectionFinished = () => null

export default function PdfDocumentViewer({
  url,
  highlights,
  highlightTransform,
  onSelectionFinished,
  enableAreaSelection,
  externalScrollRef,
  pagedNav = false,
  source = "pdf",
  defaultScale = "auto",
  toolbarAction,
  allowDownload = true,
  downloadDisabledHint,
  sidePanel,
  sidePanelLabel = "Panel",
  sidePanelIcon,
  sidePanelBadge,
}: PdfDocumentViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // Gate rendering until the next animation frame. In React StrictMode dev,
  // the throwaway mount is torn down before RAF, so PdfLoader/PdfHighlighter
  // initialize only once on the real mount and avoid duplicate page nodes.
  // Re-gating on `url` fully tears down and rebuilds the PDF subtree when the
  // document changes (e.g. switching publications), so it re-initializes
  // exactly like a first load instead of reusing stale viewer state — otherwise
  // highlights only rendered on the first document.
  const [pdfReady, setPdfReady] = useState(false)
  useLayoutEffect(() => {
    const rafId = requestAnimationFrame(() => setPdfReady(true))
    return () => {
      cancelAnimationFrame(rafId)
      setPdfReady(false)
    }
  }, [url])

  return (
    <Box
      ref={containerRef}
      position="relative"
      height="100%"
      overflow="hidden"
      display="flex"
      flexDirection="column"
      sx={highlightSx}
    >
      {pdfReady && (
        <PdfLoader
          url={url}
          beforeLoad={<LoadingSpinner />}
          errorMessage={
            // Without this, a PDF that can't be fetched or parsed (e.g. an
            // external, CORS-blocked, or auth-gated URL) would hang on the
            // spinner forever. Show a message and, for http(s) sources, a way
            // to open it directly.
            <Box p={4} textAlign="center">
              <Text fontSize="sm" color="gray.500" mb={2}>
                Couldn't load this PDF.
              </Text>
              {/^https?:/.test(url) && (
                <Link href={url} isExternal color="blue.500" fontSize="sm">
                  Open it in a new tab
                </Link>
              )}
            </Box>
          }
        >
          {(pdfDocument) => (
            <PdfViewerInner
              key={url}
              url={url}
              pdfDocument={pdfDocument}
              containerRef={containerRef}
              highlights={highlights}
              highlightTransform={highlightTransform}
              onSelectionFinished={onSelectionFinished}
              enableAreaSelection={enableAreaSelection}
              externalScrollRef={externalScrollRef}
              pagedNav={pagedNav}
              source={source}
              defaultScale={defaultScale}
              toolbarAction={toolbarAction}
              allowDownload={allowDownload}
              downloadDisabledHint={downloadDisabledHint}
              sidePanel={sidePanel}
              sidePanelLabel={sidePanelLabel}
              sidePanelIcon={sidePanelIcon}
              sidePanelBadge={sidePanelBadge}
            />
          )}
        </PdfLoader>
      )}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Inner viewer (only mounted once the document has loaded)
// ---------------------------------------------------------------------------
interface PdfViewerInnerProps extends PdfDocumentViewerProps {
  pdfDocument: PDFDocumentProxy
  containerRef: RefObject<HTMLDivElement>
}

function PdfViewerInner({
  url,
  pdfDocument,
  containerRef,
  highlights,
  highlightTransform,
  onSelectionFinished,
  enableAreaSelection,
  externalScrollRef,
  pagedNav = false,
  source = "pdf",
  defaultScale = "auto",
  toolbarAction,
  allowDownload = true,
  downloadDisabledHint,
  sidePanel,
  sidePanelLabel = "Panel",
  sidePanelIcon,
  sidePanelBadge,
}: PdfViewerInnerProps) {
  const toolbarBg = useColorModeValue("ui.secondary", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  // The 16:9-ish viewport box for paged ("carousel") mode; its height is
  // clamped to a single page so only one page shows at a time.
  const pdfBoxRef = useRef<HTMLDivElement>(null)
  const [highlightsKey, setHighlightsKey] = useState(0)

  // Toolbar state.
  const [scaleValue, setScaleValue] = useState<string>(defaultScale)
  const [outline, setOutline] = useState<OutlineNode[]>([])
  const [outlineOpen, setOutlineOpen] = useState(false)
  const [sidePanelOpen, setSidePanelOpen] = useState(false)
  const [pageNav, setPageNav] = useState({
    current: 1,
    total: pdfDocument.numPages,
  })
  const [pageInput, setPageInput] = useState("1")
  // Latest page index, tracked outside React state so layout/scale changes
  // can re-snap to the right slide without re-subscribing effects.
  const currentPageRef = useRef(1)

  // Full-document text search. react-pdf-highlighter builds its viewer without
  // a pdf.js find controller, and the browser's native find only sees rendered
  // pages, so we index every page's text ourselves and jump between matches.
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [matchPages, setMatchPages] = useState<number[]>([])
  const [matchIdx, setMatchIdx] = useState(0)
  const [searching, setSearching] = useState(false)
  // Lazily-built per-page lowercased text, cached for the document's lifetime.
  const textIndexRef = useRef<string[] | null>(null)
  // Monotonic token so out-of-order async searches can drop stale results.
  const searchSeqRef = useRef(0)

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const scrollRef = useRef<(h: any) => void>(() => {})
  const highlighterRef = useRef<PdfHighlighter<IHighlight>>(null)

  // Give PdfHighlighter a fresh array reference whenever highlightsKey bumps
  // (after deduplication) so componentDidUpdate re-renders highlight layers
  // against the surviving page nodes. highlightsKey is a deliberate trigger;
  // referencing it here keeps it a real dependency.
  const renderedHighlights = useMemo(() => {
    void highlightsKey
    return highlights ? [...highlights] : []
  }, [highlights, highlightsKey])

  // Apply zoom changes directly to the pdf.js viewer. PdfHighlighter only
  // re-applies pdfScaleValue on initial load or on a container resize (not on a
  // prop change), so without this the toolbar zoom wouldn't take effect until
  // the next layout change.
  useEffect(() => {
    if (pagedNav) return
    const viewer = highlighterRef.current?.viewer
    if (viewer) viewer.currentScaleValue = scaleValue
  }, [scaleValue, pagedNav])

  // Load the section outline (bookmarks) once per document.
  useEffect(() => {
    let cancelled = false
    resolveOutline(pdfDocument)
      .then((o) => {
        if (!cancelled) setOutline(o)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [pdfDocument])

  const getPdfPages = useCallback((): HTMLElement[] => {
    const root = containerRef.current
    if (!root) return []
    const seen = new Set<string>()
    const pages: HTMLElement[] = []
    for (const p of root.querySelectorAll<HTMLElement>(
      ".pdfViewer .page[data-page-number]",
    )) {
      const n = p.dataset.pageNumber
      if (!n || seen.has(n)) continue
      seen.add(n)
      pages.push(p)
    }
    return pages.sort(
      (a, b) => Number(a.dataset.pageNumber) - Number(b.dataset.pageNumber),
    )
  }, [containerRef])

  // react-pdf-highlighter v8 styles its scroll container with a hashed CSS
  // module class, so we can't select it by name. It is always the direct
  // parent of the `.pdfViewer` element.
  const getScrollEl = useCallback((): HTMLElement | null => {
    const root = containerRef.current
    if (!root) return null
    const viewer = root.querySelector<HTMLElement>(".pdfViewer")
    return (viewer?.parentElement as HTMLElement | null) ?? null
  }, [containerRef])

  // Scroll a specific (1-based) page to the top of the scroll container.
  const goToPage = useCallback(
    (target: number) => {
      const scrollEl = getScrollEl()
      const pages = getPdfPages()
      if (!scrollEl || pages.length === 0) return
      const clamped = Math.min(Math.max(target, 1), pages.length)
      const page = pages[clamped - 1]
      if (!page) return
      currentPageRef.current = clamped
      scrollEl.scrollTop +=
        page.getBoundingClientRect().top - scrollEl.getBoundingClientRect().top
      setPageNav((prev) => ({ ...prev, current: clamped }))
    },
    [getPdfPages, getScrollEl],
  )

  const goByDelta = useCallback(
    (delta: number) => goToPage(currentPageRef.current + delta),
    [goToPage],
  )

  // Keep the page-jump input in sync with the detected current page.
  useEffect(() => {
    setPageInput(String(pageNav.current))
  }, [pageNav.current])

  // Remove duplicate rendered PDF pages and re-trigger highlight rendering
  // once pages are actually ready.
  useEffect(() => {
    const root = containerRef.current
    if (!root) return
    let textLayerBumpDone = false
    // Track the first page's rendered height. PdfHighlighter's internal
    // ResizeObserver fires handleScaleValue (debounced 500 ms) which corrects
    // the PDF.js viewport scale, causing pages to re-render at a different
    // height. We detect that change and re-bump highlightsKey so
    // renderHighlightLayers() uses the corrected viewport — otherwise
    // scaledToViewport produces wrong pixel positions until the first click.
    let lastPageHeight = 0

    const dedupeAndSync = () => {
      const pages = Array.from(
        root.querySelectorAll<HTMLElement>(
          ".pdfViewer .page[data-page-number]",
        ),
      )
      if (pages.length === 0) return

      // Keep the LAST occurrence of each page number. PDF.js renders into the
      // most-recently created page divs (from the latest setDocument call), so
      // removing the earlier duplicates is correct.
      const seen = new Map<string, HTMLElement>()
      let removed = false
      for (const page of pages) {
        const pageNumber = page.dataset.pageNumber
        if (!pageNumber) continue
        if (seen.has(pageNumber)) {
          seen.get(pageNumber)!.remove()
          removed = true
        }
        seen.set(pageNumber, page)
      }
      if (removed) setHighlightsKey((k) => k + 1)

      // Only proceed with highlight sync once text layers exist — that is when
      // renderHighlightLayers() has real DOM targets to work with.
      if (!root.querySelector(".pdfViewer .page .textLayer")) return

      const firstPage = root.querySelector<HTMLElement>(
        ".pdfViewer .page[data-page-number]",
      )
      const currentHeight = firstPage?.clientHeight ?? 0

      if (!textLayerBumpDone) {
        textLayerBumpDone = true
        lastPageHeight = currentHeight
        setHighlightsKey((k) => k + 1)
      } else if (currentHeight > 0 && currentHeight !== lastPageHeight) {
        lastPageHeight = currentHeight
        setHighlightsKey((k) => k + 1)
      }
    }

    dedupeAndSync()
    const observer = new MutationObserver(dedupeAndSync)
    observer.observe(root, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [containerRef])

  // Highlights only sit at the right place once a page is at its final rendered
  // size. Page geometry settles asynchronously (initial render, then a debounced
  // re-scale, plus zoom) and the exact timing is racy, which is why highlights
  // showed up only sometimes. Observe the first page's size directly and force a
  // highlight re-render whenever it changes, so they render against the current
  // viewport regardless of when it settles. Bumping doesn't resize the page, so
  // this can't loop.
  useEffect(() => {
    if (pagedNav) return
    const root = containerRef.current
    if (!root) return
    let observedPage: HTMLElement | null = null
    let raf: number | null = null
    const bump = () => {
      raf = null
      setHighlightsKey((k) => k + 1)
    }
    const schedule = () => {
      if (raf === null) raf = requestAnimationFrame(bump)
    }
    const ro = new ResizeObserver(schedule)
    const attach = () => {
      // The first page div is recreated on re-scale, so re-observe the current
      // one whenever it changes.
      const page = root.querySelector<HTMLElement>(
        ".pdfViewer .page[data-page-number]",
      )
      if (page && page !== observedPage) {
        if (observedPage) ro.unobserve(observedPage)
        observedPage = page
        ro.observe(page)
      }
    }
    attach()
    const mo = new MutationObserver(attach)
    mo.observe(root, { childList: true, subtree: true })
    return () => {
      mo.disconnect()
      ro.disconnect()
      if (raf !== null) cancelAnimationFrame(raf)
    }
  }, [pagedNav, containerRef])

  // Track the current page from scroll position, and (in paged mode) clamp the
  // viewport to a single page so only one slide shows at a time.
  useEffect(() => {
    const root = containerRef.current
    if (!root) return
    let scrollEl: HTMLElement | null = null
    let raf: number | null = null

    const recompute = () => {
      raf = null
      if (!scrollEl) return
      const pages = getPdfPages()
      if (pages.length === 0) return
      const containerTop = scrollEl.getBoundingClientRect().top
      let best = 1
      let bestDist = Number.POSITIVE_INFINITY
      for (let i = 0; i < pages.length; i += 1) {
        const dist = Math.abs(
          pages[i].getBoundingClientRect().top - containerTop,
        )
        if (dist < bestDist) {
          bestDist = dist
          best = i + 1
        }
      }
      currentPageRef.current = best
      setPageNav((prev) =>
        prev.current === best ? prev : { ...prev, current: best },
      )
    }
    const onScroll = () => {
      if (raf === null) raf = requestAnimationFrame(recompute)
    }

    // The scrollable element is created asynchronously by react-pdf-highlighter.
    const attach = () => {
      const el = getScrollEl()
      if (el && el !== scrollEl) {
        scrollEl?.removeEventListener("scroll", onScroll)
        scrollEl = el
        scrollEl.addEventListener("scroll", onScroll, { passive: true })
      }
      if (scrollEl && pagedNav) {
        // Lock free vertical scrolling. With page-width scaling each page's
        // height is deterministic, so we size the viewport box to exactly one
        // page's height — the next page then sits entirely below the clipped
        // fold and only one page is ever visible.
        scrollEl.style.overflow = "hidden"
        const pages = getPdfPages()
        const page = pages[currentPageRef.current - 1]
        const box = pdfBoxRef.current
        if (page && box) {
          const ph = page.getBoundingClientRect().height
          if (ph > 0) {
            const cap = containerRef.current?.clientHeight ?? ph
            box.style.height = `${Math.min(Math.round(ph), cap)}px`
          }
          scrollEl.scrollTop +=
            page.getBoundingClientRect().top -
            scrollEl.getBoundingClientRect().top
        }
      }
      recompute()
    }
    attach()
    const observer = new MutationObserver(attach)
    observer.observe(root, { childList: true, subtree: true })
    return () => {
      observer.disconnect()
      scrollEl?.removeEventListener("scroll", onScroll)
      if (raf !== null) cancelAnimationFrame(raf)
    }
  }, [pagedNav, getPdfPages, getScrollEl, containerRef])

  // Arrow-key navigation for paged (carousel) mode.
  useEffect(() => {
    if (!pagedNav || pageNav.total <= 1) return
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA") return
      if (e.key === "ArrowLeft") {
        e.preventDefault()
        goByDelta(-1)
      } else if (e.key === "ArrowRight") {
        e.preventDefault()
        goByDelta(1)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [pagedNav, pageNav.total, goByDelta])

  const zoomBy = useCallback((delta: number) => {
    setScaleValue((prev) => {
      const cur = Number.parseFloat(prev)
      const base = Number.isFinite(cur) ? cur : 1
      const next = Math.min(Math.max(base + delta, 0.25), 4)
      return next.toFixed(2)
    })
  }, [])

  const zoomLabel = useMemo(() => {
    const cur = Number.parseFloat(scaleValue)
    return Number.isFinite(cur) ? `${Math.round(cur * 100)}%` : "Fit"
  }, [scaleValue])

  // Print via a hidden iframe. We print the raw bytes pulled from the loaded
  // document (getData) wrapped in a same-origin blob URL — printing the
  // original (often cross-origin, signed) URL is blocked by the browser, which
  // is why it previously only opened a new tab.
  const handlePrint = useCallback(async () => {
    mixpanel.track("Printed PDF", { source })
    let blobUrl: string
    try {
      const data = await pdfDocument.getData()
      blobUrl = URL.createObjectURL(
        new Blob([data], { type: "application/pdf" }),
      )
    } catch {
      window.open(url, "_blank", "noopener")
      return
    }
    const iframe = document.createElement("iframe")
    iframe.style.position = "fixed"
    iframe.style.width = "0"
    iframe.style.height = "0"
    iframe.style.border = "0"
    iframe.style.right = "0"
    iframe.style.bottom = "0"
    iframe.src = blobUrl
    iframe.onload = () => {
      try {
        iframe.contentWindow?.focus()
        iframe.contentWindow?.print()
      } catch {
        window.open(blobUrl, "_blank", "noopener")
      }
      // Leave the iframe mounted briefly so the print dialog keeps its document.
      window.setTimeout(() => {
        iframe.remove()
        URL.revokeObjectURL(blobUrl)
      }, 60000)
    }
    document.body.appendChild(iframe)
  }, [pdfDocument, url, source])

  const submitPageInput = useCallback(() => {
    const n = Number.parseInt(pageInput, 10)
    if (Number.isFinite(n)) goToPage(n)
    else setPageInput(String(pageNav.current))
  }, [pageInput, goToPage, pageNav.current])

  // Build (once) a per-page text index for searching.
  const ensureTextIndex = useCallback(async (): Promise<string[]> => {
    if (textIndexRef.current) return textIndexRef.current
    const pages: string[] = []
    for (let i = 1; i <= pdfDocument.numPages; i += 1) {
      const page = await pdfDocument.getPage(i)
      const content = await page.getTextContent()
      pages.push(
        content.items
          .map((item) => ("str" in item ? item.str : ""))
          .join(" ")
          .toLowerCase(),
      )
    }
    textIndexRef.current = pages
    return pages
  }, [pdfDocument])

  const runSearch = useCallback(
    async (q: string) => {
      const term = q.trim().toLowerCase()
      const seq = ++searchSeqRef.current
      if (!term) {
        setMatchPages([])
        setMatchIdx(0)
        return
      }
      setSearching(true)
      try {
        const pages = await ensureTextIndex()
        // Drop results if a newer search started while we were indexing.
        if (seq !== searchSeqRef.current) return
        const hits: number[] = []
        pages.forEach((text, i) => {
          if (text.includes(term)) hits.push(i + 1)
        })
        setMatchPages(hits)
        setMatchIdx(0)
        if (hits.length > 0) goToPage(hits[0])
        mixpanel.track("Searched PDF", {
          source,
          query_length: term.length,
          num_matching_pages: hits.length,
        })
      } finally {
        if (seq === searchSeqRef.current) setSearching(false)
      }
    },
    [ensureTextIndex, goToPage, source],
  )

  // Debounce searches while typing.
  useEffect(() => {
    if (!searchOpen) return
    const t = window.setTimeout(() => runSearch(query), 250)
    return () => window.clearTimeout(t)
  }, [query, searchOpen, runSearch])

  const handleSectionSelect = useCallback(
    (pageNumber: number) => {
      mixpanel.track("Navigated PDF section", { source })
      goToPage(pageNumber)
    },
    [goToPage, source],
  )

  const gotoMatch = useCallback(
    (delta: number) => {
      if (matchPages.length === 0) return
      const next = (matchIdx + delta + matchPages.length) % matchPages.length
      setMatchIdx(next)
      goToPage(matchPages[next])
    },
    [matchPages, matchIdx, goToPage],
  )

  const closeSearch = useCallback(() => {
    setSearchOpen(false)
    setQuery("")
    setMatchPages([])
    setMatchIdx(0)
  }, [])

  // Register the search-highlight color once (the ::highlight() pseudo needs a
  // real stylesheet rule, not an inline style).
  useEffect(() => {
    const id = "pdf-search-highlight-style"
    if (document.getElementById(id)) return
    const style = document.createElement("style")
    style.id = id
    style.textContent =
      "::highlight(pdf-search){background-color:rgba(255,165,0,0.45);}"
    document.head.appendChild(style)
  }, [])

  // Visually highlight matches within the rendered text layers using the CSS
  // Custom Highlight API. This paints over existing text nodes without
  // mutating the DOM, so it doesn't interfere with text selection (and the
  // comment-highlight feature). Matches spanning multiple text spans aren't
  // covered, and unsupported browsers simply skip highlighting.
  useEffect(() => {
    if (pagedNav) return
    const root = containerRef.current
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const registry = (CSS as any)?.highlights
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const HighlightCtor = (window as any).Highlight
    if (!root || !registry || !HighlightCtor) return
    const term = query.trim().toLowerCase()
    if (!searchOpen || term.length === 0) {
      registry.delete("pdf-search")
      return
    }

    let raf: number | null = null
    const apply = () => {
      raf = null
      const ranges: Range[] = []
      for (const layer of root.querySelectorAll<HTMLElement>(
        ".pdfViewer .page .textLayer",
      )) {
        const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT)
        let node = walker.nextNode() as Text | null
        while (node) {
          const data = node.data.toLowerCase()
          let idx = data.indexOf(term)
          while (idx !== -1) {
            const range = document.createRange()
            range.setStart(node, idx)
            range.setEnd(node, idx + term.length)
            ranges.push(range)
            idx = data.indexOf(term, idx + term.length)
          }
          node = walker.nextNode() as Text | null
        }
      }
      if (ranges.length > 0)
        registry.set("pdf-search", new HighlightCtor(...ranges))
      else registry.delete("pdf-search")
    }
    const schedule = () => {
      if (raf === null) raf = requestAnimationFrame(apply)
    }

    apply()
    // Re-apply as pages/text layers render in or re-render (scroll, scale).
    const observer = new MutationObserver(schedule)
    observer.observe(root, { childList: true, subtree: true })
    return () => {
      observer.disconnect()
      if (raf !== null) cancelAnimationFrame(raf)
      registry.delete("pdf-search")
    }
  }, [searchOpen, query, pagedNav, containerRef])

  const pdfViewer = (
    <PdfHighlighter<IHighlight>
      key={url}
      ref={highlighterRef}
      pdfDocument={pdfDocument}
      enableAreaSelection={enableAreaSelection ?? (() => false)}
      pdfScaleValue={pagedNav ? "page-width" : scaleValue}
      onScrollChange={() => {}}
      scrollRef={(fn) => {
        scrollRef.current = fn
        if (externalScrollRef) externalScrollRef.current = fn
      }}
      onSelectionFinished={onSelectionFinished ?? noopSelection}
      highlightTransform={highlightTransform ?? noopTransform}
      highlights={renderedHighlights}
    />
  )

  // --- Paged ("carousel") layout for presentations --------------------------
  if (pagedNav) {
    return (
      <Flex align="center" justify="center" w="100%" flex="1" minH={0}>
        <Flex w="32px" flexShrink={0} align="center" justify="center">
          {pageNav.total > 1 && (
            <IconButton
              aria-label="Previous page"
              icon={<FiChevronLeft />}
              size="sm"
              variant="ghost"
              onClick={() => goByDelta(-1)}
              isDisabled={pageNav.current <= 1}
            />
          )}
        </Flex>
        <Flex
          direction="column"
          align="center"
          justify="center"
          flex="1"
          minW={0}
          minH={0}
          height="100%"
        >
          <Box
            ref={pdfBoxRef}
            position="relative"
            w="100%"
            height="100%"
            maxH="100%"
            overflow="hidden"
          >
            {pdfViewer}
          </Box>
          {pageNav.total > 1 && (
            <Text mt={2} fontSize="sm" color="gray.500" flexShrink={0}>
              {pageNav.current} / {pageNav.total}
            </Text>
          )}
        </Flex>
        <Flex w="32px" flexShrink={0} align="center" justify="center">
          {pageNav.total > 1 && (
            <IconButton
              aria-label="Next page"
              icon={<FiChevronRight />}
              size="sm"
              variant="ghost"
              onClick={() => goByDelta(1)}
              isDisabled={pageNav.current >= pageNav.total}
            />
          )}
        </Flex>
      </Flex>
    )
  }

  // --- Toolbar + (optional) outline + scrolling document --------------------
  return (
    <>
      <Flex
        align="center"
        gap={1}
        rowGap={1}
        flexWrap="wrap"
        px={2}
        py={1}
        bg={toolbarBg}
        borderBottomWidth={1}
        borderColor={borderColor}
        borderTopRadius="lg"
        flexShrink={0}
      >
        {outline.length > 0 && (
          <Tooltip label="Sections">
            <IconButton
              aria-label="Toggle sections"
              icon={<FiList />}
              size="xs"
              variant={outlineOpen ? "solid" : "ghost"}
              onClick={() => setOutlineOpen((o) => !o)}
            />
          </Tooltip>
        )}
        {sidePanel && (
          <Flex align="center" gap={0.5}>
            <Tooltip label={sidePanelLabel}>
              <IconButton
                aria-label={`Toggle ${sidePanelLabel.toLowerCase()}`}
                icon={sidePanelIcon ?? <FiLayers />}
                size="xs"
                variant={sidePanelOpen ? "solid" : "ghost"}
                onClick={() => setSidePanelOpen((o) => !o)}
              />
            </Tooltip>
            {sidePanelBadge}
          </Flex>
        )}
        <Flex
          align="center"
          gap={0.5}
          ml={outline.length > 0 || sidePanel ? 1 : 0}
        >
          <IconButton
            aria-label="Previous page"
            icon={<FiChevronLeft />}
            size="xs"
            variant="ghost"
            onClick={() => goByDelta(-1)}
            isDisabled={pageNav.current <= 1}
          />
          <Input
            autoComplete="off"
            size="xs"
            width="44px"
            textAlign="center"
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value)}
            onBlur={submitPageInput}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                submitPageInput()
              }
            }}
          />
          <Text fontSize="xs" color="gray.500" whiteSpace="nowrap">
            / {pageNav.total}
          </Text>
          <IconButton
            aria-label="Next page"
            icon={<FiChevronRight />}
            size="xs"
            variant="ghost"
            onClick={() => goByDelta(1)}
            isDisabled={pageNav.current >= pageNav.total}
          />
        </Flex>

        <Flex align="center" gap={0.5} ml={2}>
          <IconButton
            aria-label="Zoom out"
            icon={<FiZoomOut />}
            size="xs"
            variant="ghost"
            onClick={() => zoomBy(-0.2)}
          />
          <Text
            fontSize="xs"
            color="gray.500"
            minW="34px"
            textAlign="center"
            cursor="pointer"
            onClick={() => setScaleValue("auto")}
          >
            {zoomLabel}
          </Text>
          <IconButton
            aria-label="Zoom in"
            icon={<FiZoomIn />}
            size="xs"
            variant="ghost"
            onClick={() => zoomBy(0.2)}
          />
          <Tooltip label="Fit width">
            <IconButton
              aria-label="Fit width"
              icon={<FiMaximize />}
              size="xs"
              variant="ghost"
              onClick={() => setScaleValue("page-width")}
            />
          </Tooltip>
        </Flex>

        {searchOpen && (
          <Flex align="center" gap={0.5} ml={2}>
            <Input
              autoComplete="off"
              size="xs"
              width="150px"
              placeholder="Search document…"
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  gotoMatch(e.shiftKey ? -1 : 1)
                } else if (e.key === "Escape") {
                  closeSearch()
                }
              }}
            />
            <Text
              fontSize="xs"
              color="gray.500"
              minW="48px"
              textAlign="center"
              whiteSpace="nowrap"
            >
              {searching
                ? "…"
                : matchPages.length > 0
                  ? `${matchIdx + 1} / ${matchPages.length}`
                  : query
                    ? "0 / 0"
                    : ""}
            </Text>
            <IconButton
              aria-label="Previous match"
              icon={<FiChevronUp />}
              size="xs"
              variant="ghost"
              isDisabled={matchPages.length === 0}
              onClick={() => gotoMatch(-1)}
            />
            <IconButton
              aria-label="Next match"
              icon={<FiChevronDown />}
              size="xs"
              variant="ghost"
              isDisabled={matchPages.length === 0}
              onClick={() => gotoMatch(1)}
            />
            <IconButton
              aria-label="Close search"
              icon={<FiX />}
              size="xs"
              variant="ghost"
              onClick={closeSearch}
            />
          </Flex>
        )}

        <Flex align="center" gap={0.5} ml="auto">
          {toolbarAction}
          <Tooltip label="Search">
            <IconButton
              aria-label="Search"
              icon={<FiSearch />}
              size="xs"
              variant={searchOpen ? "solid" : "ghost"}
              onClick={() => (searchOpen ? closeSearch() : setSearchOpen(true))}
            />
          </Tooltip>
          {/* Print and open-in-new-tab are also ways to save the file, so they
              are hidden alongside download for preview-only viewers. */}
          {allowDownload && (
            <>
              <Tooltip label="Print">
                <IconButton
                  aria-label="Print"
                  icon={<FiPrinter />}
                  size="xs"
                  variant="ghost"
                  onClick={handlePrint}
                />
              </Tooltip>
              <Tooltip label="Open in new tab">
                <IconButton
                  as={Link}
                  href={url}
                  isExternal
                  aria-label="Open in new tab"
                  icon={<FiExternalLink />}
                  size="xs"
                  variant="ghost"
                  onClick={() =>
                    mixpanel.track("Opened PDF in new tab", { source })
                  }
                />
              </Tooltip>
            </>
          )}
          {allowDownload ? (
            <Tooltip label="Download">
              <IconButton
                as={Link}
                href={url}
                download
                aria-label="Download"
                icon={<FiDownload />}
                size="xs"
                variant="ghost"
                onClick={() => mixpanel.track("Downloaded PDF", { source })}
              />
            </Tooltip>
          ) : (
            <Tooltip
              label={
                downloadDisabledHint ??
                "Download is disabled for previews. Run the pipeline to generate the official PDF."
              }
              shouldWrapChildren
            >
              <IconButton
                aria-label="Download disabled"
                icon={<FiDownload />}
                size="xs"
                variant="ghost"
                isDisabled
              />
            </Tooltip>
          )}
        </Flex>
      </Flex>

      <Flex flex="1" minH={0}>
        {outlineOpen && outline.length > 0 && (
          <Box
            width="220px"
            flexShrink={0}
            overflowY="auto"
            borderRightWidth={1}
            borderColor={borderColor}
            bg={toolbarBg}
            py={2}
            pr={1}
          >
            <OutlineTree
              nodes={outline}
              currentPage={pageNav.current}
              onSelect={handleSectionSelect}
            />
          </Box>
        )}
        <Box position="relative" flex="1" minW={0} overflow="hidden">
          {pdfViewer}
        </Box>
        {sidePanelOpen && sidePanel && (
          <Box
            width="300px"
            flexShrink={0}
            overflowY="auto"
            borderLeftWidth={1}
            borderColor={borderColor}
            bg={toolbarBg}
            p={2}
          >
            {sidePanel({ currentPage: pageNav.current, goToPage })}
          </Box>
        )}
      </Flex>
    </>
  )
}
