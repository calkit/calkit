import { Box, Flex, Icon, Image, Text } from "@chakra-ui/react"
import { Suspense, lazy, useEffect, useState } from "react"
import { FiFile } from "react-icons/fi"

const Plot = lazy(() => import("react-plotly.js"))

import type { Figure } from "../../client"
import { decodeBase64Utf8 } from "../../lib/strings"
import LoadingSpinner from "../Common/LoadingSpinner"
import PdfCanvas from "../Common/PdfCanvas"
import SandboxedHtml from "../Common/SandboxedHtml"

// A Plotly figure is data, not pixels, so the API has nothing to rasterize and
// its thumbnail is drawn here instead, for the figure gallery and evidence
// cards alike.
//
// It is drawn once into an image rather than left as a live plot: a gallery
// tile is 140px tall and a page holds twenty of them, and twenty Plotly instances
// build twenty SVG scene graphs that stay on the page. Rendered to a data URL
// the tile costs no more than any other thumbnail.
//
// At this size the chrome is what has to go -- the default margins alone are
// most of a 140px canvas, before a title or tick labels. What makes a plot
// recognisable that small is the shape of its traces.
const thumbnailLayout = (layout: Record<string, unknown>) => {
  // Every axis, not just the first: a figure with stacked subplots carries
  // xaxis2, yaxis3 and so on, and each keeps its own ticks and title. Left
  // in, they overlap the traces and each other at this size.
  const hidden = { visible: false, title: undefined }
  const axes: Record<string, unknown> = { xaxis: hidden, yaxis: hidden }
  for (const key of Object.keys(layout)) {
    if (/^[xy]axis\d*$/.test(key)) {
      axes[key] = { ...(layout[key] as object), ...hidden }
    }
  }
  return {
    ...layout,
    title: undefined,
    showlegend: false,
    margin: { l: 2, r: 2, t: 2, b: 2 },
    ...axes,
    // Subplot titles are annotations rather than titles, so they survive
    // everything above and land on top of what they label.
    annotations: [],
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
  }
}

export function PlotlyThumbnail({
  figure,
  height = 140,
}: {
  figure: Figure
  height?: number
}) {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    // Start over whenever the figure's content does: this component is
    // reused across a ref change or a refetch, and without the reset it
    // would keep showing the previous image, or stay stuck on a failure
    // that no longer applies.
    setSrc(null)
    setFailed(false)
    if (!figure.content) {
      setFailed(true)
      return
    }
    let cancelled = false
    const draw = async () => {
      try {
        const spec = JSON.parse(decodeBase64Utf8(String(figure.content)))
        if (!spec.data || !spec.layout) throw new Error("not a Plotly figure")
        // The prebuilt bundle, which is what react-plotly.js imports too --
        // bare "plotly.js" resolves to its unbuilt source entry, which is a
        // second copy of the library with different interop. It carries no
        // types of its own; the API is the one "plotly.js" declares.
        const Plotly =
          // @ts-expect-error -- prebuilt bundle, untyped; see above
          (await import("plotly.js/dist/plotly"))
            .default as typeof import("plotly.js")
        const url = await Plotly.toImage(
          { data: spec.data, layout: thumbnailLayout(spec.layout) },
          { format: "webp", width: 320, height: 200 },
        )
        if (!cancelled) setSrc(url)
      } catch {
        if (!cancelled) setFailed(true)
      }
    }
    draw()
    return () => {
      cancelled = true
    }
  }, [figure.content])
  // A .json that turns out not to be a Plotly figure, or one Plotly can't
  // draw, falls back to the same icon as any other format with no preview.
  if (failed) {
    return (
      <Flex
        height={`${height}px`}
        align="center"
        justify="center"
        color="gray.400"
        fontSize="3xl"
      >
        <Icon as={FiFile} />
      </Flex>
    )
  }
  if (!src) {
    return (
      <Flex height={`${height}px`} align="center" justify="center">
        <LoadingSpinner />
      </Flex>
    )
  }
  return (
    <Flex height={`${height}px`} align="center" justify="center">
      <Image
        src={src}
        alt={figure.title}
        objectFit="contain"
        maxW="100%"
        maxH={`${height}px`}
      />
    </Flex>
  )
}

interface FigureViewProps {
  figure: Figure
  width?: string
  /**
   * Fit the figure to the height of its (height-bounded) container instead of
   * its intrinsic height. Used in the figure modal so tall Plotly figures
   * resize down rather than overflowing vertically.
   */
  fillHeight?: boolean
}

function FigureView({ figure, width, fillHeight }: FigureViewProps) {
  const boxWidth = width ? width : "100%"
  const lowerPath = figure.path.toLowerCase()
  const isHtml = lowerPath.endsWith(".html")
  let figView = <>Not set</>
  if (lowerPath.endsWith(".pdf")) {
    figView = (
      <PdfCanvas
        src={
          figure.content
            ? `data:application/pdf;base64,${figure.content}`
            : String(figure.url)
        }
        width={boxWidth}
      />
    )
  } else if (
    lowerPath.endsWith(".png") ||
    lowerPath.endsWith(".jpg") ||
    lowerPath.endsWith(".jpeg")
  ) {
    const mime = lowerPath.endsWith(".png") ? "image/png" : "image/jpeg"
    figView = (
      <Box width="100%" height="100%">
        <Image
          alt={figure.title}
          src={
            figure.content
              ? `data:${mime};base64,${figure.content}`
              : String(figure.url)
          }
          width="100%"
          height="100%"
          objectFit="contain"
          display="block"
        />
      </Box>
    )
  } else if (lowerPath.endsWith(".svg")) {
    figView = (
      <Box width="100%" height="100%">
        <Image
          alt={figure.title}
          src={
            figure.content
              ? `data:image/svg+xml;base64,${figure.content}`
              : String(figure.url)
          }
          width="100%"
          height="100%"
          objectFit="contain"
          display="block"
        />
      </Box>
    )
  } else if (lowerPath.endsWith(".json")) {
    try {
      const figObject = JSON.parse(atob(String(figure.content)))
      if (figObject.data && figObject.layout) {
        if (fillHeight) {
          // Render at the figure's natural height (Plotly's default is 450px
          // when none is set), but cap it to the container and center it
          // vertically so short figures keep their proportions and only tall
          // ones are squished down to fit.
          const naturalHeight =
            typeof figObject.layout.height === "number"
              ? figObject.layout.height
              : 450
          const layout = {
            ...figObject.layout,
            autosize: true,
            height: undefined,
            width: undefined,
          }
          figView = (
            <Box
              width={boxWidth}
              height="100%"
              minH={0}
              display="flex"
              alignItems="center"
              justifyContent="center"
              overflow="hidden"
            >
              <Box width="100%" height={`${naturalHeight}px`} maxH="100%">
                <Suspense fallback={<Text>Loading...</Text>}>
                  <Plot
                    data={figObject.data}
                    layout={layout}
                    config={{ displayModeBar: false, responsive: true }}
                    style={{ width: "100%", height: "100%" }}
                    useResizeHandler={true}
                  />
                </Suspense>
              </Box>
            </Box>
          )
        } else {
          figView = (
            <Box width={boxWidth}>
              <Suspense fallback={<Text>Loading...</Text>}>
                <Plot
                  data={figObject.data}
                  layout={figObject.layout}
                  config={{ displayModeBar: false }}
                  style={{ width: "100%", height: "100%" }}
                  useResizeHandler={true}
                />
              </Suspense>
            </Box>
          )
        }
      } else {
        figView = <Text>Cannot render this type of figure</Text>
      }
    } catch {
      figView = <Text>Cannot render this type of figure</Text>
    }
  } else if (isHtml) {
    figView = (
      <Box width={boxWidth} height="400px">
        <SandboxedHtml
          title={figure.title || figure.path}
          content={figure.content}
          url={figure.url}
        />
      </Box>
    )
  } else {
    figView = <Text>Cannot render this type of figure</Text>
  }
  return figView
}

export default FigureView
