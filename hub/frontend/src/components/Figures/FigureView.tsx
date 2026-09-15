import { Box, Image, Text } from "@chakra-ui/react"
import axios from "axios"
import { Suspense, lazy } from "react"

const Plot = lazy(() => import("react-plotly.js"))
import { useQuery } from "@tanstack/react-query"
import { getRouteApi } from "@tanstack/react-router"

import type { Figure } from "../../client"
import PdfCanvas from "../Common/PdfCanvas"

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
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const boxWidth = width ? width : "100%"
  // Hooks must run in the same order on every render, so fetch HTML-figure
  // content unconditionally and gate it with `enabled`; otherwise paging
  // between a non-HTML and an HTML figure changes the hook count and
  // triggers React error #310.
  const lowerPath = figure.path.toLowerCase()
  const isHtml = lowerPath.endsWith(".html")
  const { data: htmlData, isPending: htmlIsPending } = useQuery({
    queryFn: () => axios.get(String(figure.url)),
    queryKey: [
      "projects",
      accountName,
      projectName,
      "figure-content",
      figure.path,
      figure.url,
    ],
    enabled: isHtml && Boolean(!figure.content && figure.url),
  })
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
    let figContent = figure.content
    if (!figure.content && figure.url) {
      figContent = htmlData?.data
    } else {
      figContent = "No content found"
    }
    figView = (
      <Box width={boxWidth} height="400px">
        {figContent ? (
          <iframe
            width="100%"
            height="100%"
            title="figure"
            srcDoc={figContent}
          />
        ) : htmlIsPending ? (
          "Loading..."
        ) : (
          ""
        )}
      </Box>
    )
  } else {
    figView = <Text>Cannot render this type of figure</Text>
  }
  return figView
}

export default FigureView
