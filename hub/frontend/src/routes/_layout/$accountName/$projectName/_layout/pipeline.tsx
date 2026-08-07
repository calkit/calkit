import { Alert, AlertIcon, Box, Flex, Heading, Link } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink, createFileRoute } from "@tanstack/react-router"
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react"
import React from "react"
import { Light as SyntaxHighlighter } from "react-syntax-highlighter"
import yaml from "react-syntax-highlighter/dist/esm/languages/hljs/yaml"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"
import { z } from "zod"

import { ProjectsService } from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Mermaid from "../../../../../components/Common/Mermaid"
import { useProjectEnvironments } from "../../../../../hooks/useProject"
import {
  extractEnvRefs,
  extractFilePaths,
  findStageLineRange,
} from "../../../../../lib/pipelineYaml"

SyntaxHighlighter.registerLanguage("yaml", yaml)

function makeRenderer(
  paths: Set<string>,
  filesTo: string,
  envRefs: Set<string>,
  envNames: Set<string>,
  envTo: string,
  highlightRange: [number, number] | null,
  firstHighlightRef: React.RefObject<HTMLSpanElement>,
) {
  return ({
    rows,
    stylesheet,
    useInlineStyles,
  }: {
    rows: unknown[]
    stylesheet: Record<string, React.CSSProperties>
    useInlineStyles: boolean
  }) => {
    function renderNode(node: unknown, key: string): ReactNode {
      const n = node as {
        type?: string
        value?: string
        tagName?: string
        properties?: { className?: string[]; style?: React.CSSProperties }
        children?: unknown[]
      }

      if (n.type === "text") {
        const val = n.value ?? ""
        if (paths.has(val)) {
          return (
            <RouterLink key={key} to={filesTo} search={{ path: val } as never}>
              <span style={{ textDecoration: "underline" }}>{val}</span>
            </RouterLink>
          )
        }
        // Environment reference, possibly composite ("outer:inner"). Link each
        // segment that names a known environment; leave the rest as plain text.
        if (envRefs.has(val)) {
          const segments = val.split(":")
          return (
            <React.Fragment key={key}>
              {segments.map((seg, i) => (
                <React.Fragment key={`${key}-env-${i}`}>
                  {i > 0 ? ":" : null}
                  {envNames.has(seg) ? (
                    <RouterLink to={envTo} search={{ name: seg } as never}>
                      <span style={{ textDecoration: "underline" }}>{seg}</span>
                    </RouterLink>
                  ) : (
                    seg
                  )}
                </React.Fragment>
              ))}
            </React.Fragment>
          )
        }
        return val
      }

      if (n.type === "element" || n.tagName) {
        const children = n.children?.map((child, i) =>
          renderNode(child, `${key}-${i}`),
        )
        let style: React.CSSProperties = {}
        if (useInlineStyles) {
          for (const cls of n.properties?.className ?? []) {
            if (stylesheet[`.${cls}`])
              style = { ...style, ...stylesheet[`.${cls}`] }
            else if (stylesheet[cls]) style = { ...style, ...stylesheet[cls] }
          }
          if (n.properties?.style) style = { ...style, ...n.properties.style }
        }
        return React.createElement(
          n.tagName ?? "span",
          {
            key,
            className: !useInlineStyles
              ? n.properties?.className?.join(" ")
              : undefined,
            style: useInlineStyles
              ? Object.keys(style).length
                ? style
                : undefined
              : undefined,
          },
          ...(children ?? []),
        )
      }

      return null
    }

    return (
      <code>
        {rows.map((row, i) => {
          const highlighted =
            highlightRange != null &&
            i >= highlightRange[0] &&
            i < highlightRange[1]
          if (highlighted) {
            return (
              <span
                key={i}
                ref={i === highlightRange[0] ? firstHighlightRef : undefined}
                style={{
                  display: "block",
                  backgroundColor: "rgba(255, 213, 0, 0.16)",
                  boxShadow:
                    i === highlightRange[0]
                      ? "inset 3px 0 0 rgba(255, 213, 0, 0.9)"
                      : undefined,
                }}
              >
                {renderNode(row, `r${i}`)}
              </span>
            )
          }
          return (
            <React.Fragment key={i}>{renderNode(row, `r${i}`)}</React.Fragment>
          )
        })}
      </code>
    )
  }
}

// ---------------------------------------------------------------------------
// Linked YAML block
// ---------------------------------------------------------------------------
function LinkedYaml({
  content,
  filesTo,
  envNames,
  envTo,
  highlightStage,
}: {
  content: string
  filesTo: string
  envNames: Set<string>
  envTo: string
  highlightStage?: string
}) {
  const paths = useMemo(() => extractFilePaths(content), [content])
  const envRefs = useMemo(() => extractEnvRefs(content), [content])
  const highlightRange = useMemo(
    () => (highlightStage ? findStageLineRange(content, highlightStage) : null),
    [content, highlightStage],
  )
  const firstHighlightRef = useRef<HTMLSpanElement>(null)
  const renderer = useMemo(
    () =>
      makeRenderer(
        paths,
        filesTo,
        envRefs,
        envNames,
        envTo,
        highlightRange,
        firstHighlightRef,
      ),
    [paths, filesTo, envRefs, envNames, envTo, highlightRange],
  )

  useEffect(() => {
    if (highlightRange && firstHighlightRef.current) {
      firstHighlightRef.current.scrollIntoView({
        block: "center",
        behavior: "smooth",
      })
    }
  }, [highlightRange])

  return (
    <Box height="80vh" overflowY="auto" borderRadius="lg">
      <SyntaxHighlighter
        language="yaml"
        style={atomOneDark}
        renderer={renderer}
        useInlineStyles={true}
        customStyle={{
          borderRadius: "var(--chakra-radii-lg)",
          height: "100%",
          margin: 0,
          fontSize: "13px",
        }}
      >
        {content}
      </SyntaxHighlighter>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
const pipelineSearchSchema = z.object({
  ref: z.string().optional(),
  stage: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/pipeline",
)({
  component: ProjectPipeline,
  validateSearch: (search) => pipelineSearchSchema.parse(search),
})

function ProjectPipeline() {
  const { accountName, projectName } = Route.useParams()
  const { ref, stage } = Route.useSearch()
  const pipelineQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "pipeline", ref],
    queryFn: () =>
      ProjectsService.getProjectPipeline({
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
  })
  const { environmentsRequest } = useProjectEnvironments(
    accountName,
    projectName,
    ref,
  )
  const envNames = useMemo(
    () => new Set(environmentsRequest.data?.map((e) => e.name) ?? []),
    [environmentsRequest.data],
  )
  const [isDiagramExpanded, setIsDiagramExpanded] = useState(false)

  const filesTo = `/${accountName}/${projectName}/files`
  const envTo = `/${accountName}/${projectName}/environments`

  return (
    <>
      {pipelineQuery.isPending ? (
        <LoadingSpinner height="100vh" />
      ) : (
        <Flex flexDir={isDiagramExpanded ? "column" : "row"} gap={4}>
          {pipelineQuery.data ? (
            <>
              <Box flex={1} minW={0}>
                <Mermaid
                  isDiagramExpanded={isDiagramExpanded}
                  setIsDiagramExpanded={setIsDiagramExpanded}
                  zoomToStage={stage}
                >
                  {String(pipelineQuery.data.mermaid)}
                </Mermaid>
              </Box>
              <Box flex={1} minW={0}>
                {pipelineQuery.data.calkit_yaml ? (
                  <>
                    <Heading size="md" my={2}>
                      calkit.yaml
                    </Heading>
                    <LinkedYaml
                      content={String(pipelineQuery.data.calkit_yaml)}
                      filesTo={filesTo}
                      envNames={envNames}
                      envTo={envTo}
                      highlightStage={stage}
                    />
                  </>
                ) : (
                  <>
                    <Heading size="md" my={2}>
                      dvc.yaml
                    </Heading>
                    <LinkedYaml
                      content={String(pipelineQuery.data.dvc_yaml)}
                      filesTo={filesTo}
                      envNames={envNames}
                      envTo={envTo}
                      highlightStage={stage}
                    />
                  </>
                )}
              </Box>
            </>
          ) : (
            <Alert mt={2} status="warning" borderRadius="xl">
              <AlertIcon />A pipeline has not yet been defined for this project.
              To create one, see the{" "}
              <Link
                ml={1}
                isExternal
                variant="blue"
                href="https://docs.calkit.org/pipeline/"
              >
                pipeline documentation
              </Link>
              .
            </Alert>
          )}
        </Flex>
      )}
    </>
  )
}
