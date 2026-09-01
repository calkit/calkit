import { Box, Button, Flex, Icon, IconButton, Text } from "@chakra-ui/react"
import { select } from "d3-selection"
import {
  type D3ZoomEvent,
  type ZoomBehavior,
  zoom,
  zoomIdentity,
} from "d3-zoom"
import { useEffect, useRef, useState } from "react"
import { FaExclamationTriangle, FaExpandAlt, FaHome } from "react-icons/fa"

import Tooltip from "./Tooltip"

// Past this many stages the graph is a hairball: every node is a few pixels
// wide, the edges cross everything, and it takes seconds to lay out. The
// stage list beside it stays readable at any size, so that leads instead and
// the diagram becomes something you ask for.
export const MAX_READABLE_STAGES = 50

interface MermaidProps {
  children: string
  isDiagramExpanded: boolean
  setIsDiagramExpanded: Function
  /** Stages the diagram draws, used to decide whether it's worth drawing. */
  stageCount?: number
  /** Draw it even when there are more stages than that. */
  isOversizedShown?: boolean
  setIsOversizedShown?: (shown: boolean) => void
  /** Pan/zoom the diagram to center the node for this pipeline stage. */
  zoomToStage?: string
  /**
   * Called with the stage name when a stage node is clicked. The diagram also
   * contains file nodes, so `stageNames` decides which nodes are clickable.
   */
  onStageClick?: (stageName: string) => void
  stageNames?: Set<string>
}

// The stage a node represents, or null if it isn't a stage node. Matrix
// stages are drawn as `name@item`, and belong to the stage before the `@`.
function nodeStage(node: SVGGElement, stageNames: Set<string>): string | null {
  const label = (node.textContent ?? "").trim()
  if (stageNames.has(label)) {
    return label
  }
  const base = label.split("@")[0]
  return stageNames.has(base) ? base : null
}

const Mermaid = ({
  children,
  isDiagramExpanded,
  setIsDiagramExpanded,
  stageCount,
  isOversizedShown,
  setIsOversizedShown,
  zoomToStage,
  onStageClick,
  stageNames,
}: MermaidProps) => {
  const isOversized =
    stageCount !== undefined && stageCount > MAX_READABLE_STAGES
  // Drawn only on request once it's this big, so the page doesn't spend
  // seconds laying out a picture nobody can read.
  const isSuppressed = isOversized && !isOversizedShown
  const zoomBehaviorRef = useRef<ZoomBehavior<Element, unknown> | null>(null)
  // Bumped each time the diagram finishes rendering so the zoom-to-stage
  // effect can re-run against the freshly drawn SVG.
  const [renderTick, setRenderTick] = useState(0)
  // Set when mermaid refuses to draw the graph, so a pipeline too big for it
  // says so instead of leaving an empty box on the page.
  const [renderError, setRenderError] = useState<string | null>(null)

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
    if (isSuppressed) {
      return
    }
    const renderDiagram = async () => {
      try {
        const { default: mermaid } = await import("mermaid")
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "loose",
          fontFamily: "monospace",
          // Mermaid's own default is 500, past which it throws instead of
          // drawing anything. A real pipeline crosses that easily -- a
          // hundred-odd stages wired to their inputs and outputs is a few
          // hundred edges -- and the graph is the project's own, not
          // untrusted input, so the guard only costs us the diagram.
          maxEdges: 5000,
        })
        setRenderError(null)
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
        setRenderError(
          error instanceof Error ? error.message : String(error ?? "Unknown"),
        )
      }
    }
    renderDiagram()
    return () => {
      select(".mermaid svg").on("zoom", null)
    }
  }, [children, isSuppressed])

  // Make stage nodes clickable, once the diagram is rendered. Listeners go on
  // the nodes themselves (rather than one delegated handler) so the pointer
  // cursor only appears on the nodes that actually do something. renderTick
  // isn't read here but is the point: mermaid replaces the SVG on each render,
  // so the listeners have to go back onto the new nodes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: renderTick re-attaches after a redraw
  useEffect(() => {
    const svgEl = select<SVGSVGElement, unknown>(".mermaid svg").node()
    if (!svgEl || !onStageClick || !stageNames?.size) {
      return
    }
    const cleanups: Array<() => void> = []
    for (const node of Array.from(
      svgEl.querySelectorAll<SVGGElement>(".node"),
    )) {
      const name = nodeStage(node, stageNames)
      if (!name) {
        continue
      }
      const handler = () => onStageClick(name)
      // Enter and Space are what a button responds to, and Space would
      // otherwise scroll the page.
      const keyHandler = (e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onStageClick(name)
        }
      }
      node.addEventListener("click", handler)
      node.addEventListener("keydown", keyHandler)
      // Button semantics so the action is reachable by keyboard and announced
      // by screen readers. The label goes on aria-label rather than a <title>
      // child: both this and the zoom-to-stage effect read a node's name off
      // its textContent, which a <title> child would join.
      node.setAttribute("tabindex", "0")
      node.setAttribute("role", "button")
      node.setAttribute("aria-label", `Edit stage ${name}`)
      node.style.cursor = "pointer"
      cleanups.push(() => {
        node.removeEventListener("click", handler)
        node.removeEventListener("keydown", keyHandler)
        node.removeAttribute("tabindex")
        node.removeAttribute("role")
        node.removeAttribute("aria-label")
        node.style.cursor = ""
      })
    }
    return () => {
      for (const cleanup of cleanups) {
        cleanup()
      }
    }
  }, [onStageClick, stageNames, renderTick])

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
      <Flex position="relative" direction={"row-reverse"} h={0} zIndex={1}>
        <IconButton
          aria-label="expand"
          height="25px"
          icon={<FaExpandAlt />}
          onClick={toggleisDiagramExpanded}
          ml={1}
        />
        {isOversized ? (
          <Tooltip
            label={`This pipeline has ${stageCount} stages, more than the ${MAX_READABLE_STAGES} a diagram stays readable at.`}
          >
            <Flex align="center" h="25px" ml={1}>
              <Icon
                as={FaExclamationTriangle}
                color="orange.400"
                aria-label="Too many stages to draw clearly"
              />
            </Flex>
          </Tooltip>
        ) : null}
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
        // Kept mounted so mermaid can retry into it, but hidden when there
        // is nothing drawn in it: the element still holds the raw diagram
        // source, which is not what anyone wants to look at.
        visibility={
          renderError === null && !isSuppressed ? "visible" : "hidden"
        }
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
      {isSuppressed ? (
        <Flex
          position="absolute"
          inset={0}
          direction="column"
          align="center"
          justify="center"
          gap={3}
          px={6}
        >
          <Text fontSize="sm" color="gray.500" textAlign="center">
            {stageCount} stages is more than a diagram can show clearly. The
            stage list has all of them.
          </Text>
          {setIsOversizedShown ? (
            <Button size="sm" onClick={() => setIsOversizedShown(true)}>
              Draw it anyway
            </Button>
          ) : null}
        </Flex>
      ) : null}
      {renderError !== null ? (
        <Flex
          position="absolute"
          inset={0}
          align="center"
          justify="center"
          px={6}
        >
          <Text fontSize="sm" color="gray.500" textAlign="center">
            This pipeline's diagram couldn't be drawn: {renderError}
          </Text>
        </Flex>
      ) : null}
    </Box>
  )
}

export default Mermaid
