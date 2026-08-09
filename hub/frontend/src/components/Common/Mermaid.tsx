import { Box, Flex, IconButton } from "@chakra-ui/react"
import { select } from "d3-selection"
import {
  type D3ZoomEvent,
  type ZoomBehavior,
  zoom,
  zoomIdentity,
} from "d3-zoom"
import { useEffect, useRef, useState } from "react"
import { FaExpandAlt, FaHome } from "react-icons/fa"

interface MermaidProps {
  children: string
  isDiagramExpanded: boolean
  setIsDiagramExpanded: Function
  /** Pan/zoom the diagram to center the node for this pipeline stage. */
  zoomToStage?: string
}

const Mermaid = ({
  children,
  isDiagramExpanded,
  setIsDiagramExpanded,
  zoomToStage,
}: MermaidProps) => {
  const zoomBehaviorRef = useRef<ZoomBehavior<Element, unknown> | null>(null)
  // Bumped each time the diagram finishes rendering so the zoom-to-stage
  // effect can re-run against the freshly drawn SVG.
  const [renderTick, setRenderTick] = useState(0)

  const handleResetZoom = () => {
    const svgSelection = select<Element, unknown>(".mermaid svg")
    if (zoomBehaviorRef.current != null) {
      svgSelection.call(zoomBehaviorRef.current.transform, zoomIdentity)
    }
  }

  const toggleisDiagramExpanded = () => {
    setIsDiagramExpanded(!isDiagramExpanded)
  }

  useEffect(() => {
    const renderDiagram = async () => {
      try {
        const { default: mermaid } = await import("mermaid")
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "loose",
          fontFamily: "monospace",
        })
        await mermaid.run({ querySelector: ".mermaid" })
        const svgSelection = select<Element, unknown>(".mermaid svg")
        // Remove max-width set by mermaid-js
        svgSelection.style("max-width", "none")

        const zoomBehavior = zoom<Element, unknown>().on(
          "zoom",
          (event: D3ZoomEvent<Element, unknown>) => {
            const transform = event.transform
            const gSelection = svgSelection.select("g")
            gSelection.attr("transform", transform.toString())
          },
        )

        svgSelection.call(zoomBehavior)
        zoomBehaviorRef.current = zoomBehavior
        setRenderTick((t) => t + 1)
      } catch (error) {
        console.error("Error rendering Mermaid diagram:", error)
      }
    }
    renderDiagram()
    return () => {
      select(".mermaid svg").on("zoom", null)
    }
  }, [children])

  // Pan/zoom to the requested stage's node and outline it, once the diagram
  // is rendered.
  useEffect(() => {
    const svgEl = select<SVGSVGElement, unknown>(".mermaid svg").node()
    if (!svgEl) return
    // Clear any previous highlight so only the current stage is outlined.
    svgEl
      .querySelectorAll(".node")
      .forEach((n) => n.classList.remove("ck-stage-highlight"))
    if (!zoomToStage || !zoomBehaviorRef.current) return
    const gEl = svgEl.querySelector("g")
    if (!gEl) return
    const nodes = Array.from(svgEl.querySelectorAll<SVGGElement>(".node"))
    const label = (n: SVGGElement) => (n.textContent ?? "").trim()
    const match =
      nodes.find((n) => label(n) === zoomToStage) ??
      nodes.find((n) => label(n).split("@")[0] === zoomToStage)
    if (!match) return
    // Outline the node (fill is left alone so it still shows staleness).
    match.classList.add("ck-stage-highlight")
    const gCTM = gEl.getCTM()
    const nCTM = match.getCTM()
    if (!gCTM || !nCTM) return
    // Node center in the coordinate space the zoom transform writes into
    // (g's parent / SVG user space). g's own transform cancels out here.
    const m = gCTM.inverse().multiply(nCTM)
    const bbox = match.getBBox()
    let pt = svgEl.createSVGPoint()
    pt.x = bbox.x + bbox.width / 2
    pt.y = bbox.y + bbox.height / 2
    pt = pt.matrixTransform(m)
    const vb = svgEl.viewBox.baseVal
    const hasVb = vb != null && vb.width > 0
    const vbW = hasVb ? vb.width : svgEl.clientWidth
    const vbH = hasVb ? vb.height : svgEl.clientHeight
    const cx = (hasVb ? vb.x : 0) + vbW / 2
    const cy = (hasVb ? vb.y : 0) + vbH / 2
    // Scale so the node fills ~45% of the view, clamped to a sane range.
    const k = Math.max(
      1,
      Math.min(
        2.5,
        (vbW * 0.45) / (bbox.width || 1),
        (vbH * 0.45) / (bbox.height || 1),
      ),
    )
    const tx = cx - k * pt.x
    const ty = cy - k * pt.y
    select<Element, unknown>(svgEl).call(
      zoomBehaviorRef.current.transform,
      zoomIdentity.translate(tx, ty).scale(k),
    )
  }, [zoomToStage, renderTick])

  return (
    <Box
      borderRadius="lg"
      borderWidth={1}
      aspectRatio={isDiagramExpanded ? 2 / 1 : 1 / 1}
      boxSizing="border-box"
      overflow={"hidden"}
      px={3}
      py={2}
      position={"relative"}
    >
      <Flex position="relative" direction={"row-reverse"} h={0}>
        <IconButton
          aria-label="expand"
          height="25px"
          icon={<FaExpandAlt />}
          onClick={toggleisDiagramExpanded}
          ml={1}
        />
        <IconButton
          aria-label="refresh"
          height="25px"
          icon={<FaHome />}
          onClick={handleResetZoom}
          mr={1}
        />
      </Flex>
      <Box
        className="mermaid"
        aria-label="Mermaid diagram"
        role="img"
        h={"100%"}
        w={"100%"}
        sx={{
          "& svg": {
            height: "100%",
            width: "100%",
          },
          // Highlighted stage: a bold orange outline only, leaving the fill
          // (which encodes staleness status) untouched.
          "& .node.ck-stage-highlight rect, & .node.ck-stage-highlight polygon, & .node.ck-stage-highlight circle, & .node.ck-stage-highlight path":
            {
              stroke: "#ff8c00 !important",
              strokeWidth: "3.5px !important",
            },
        }}
      >
        {children}
      </Box>
    </Box>
  )
}

export default Mermaid
