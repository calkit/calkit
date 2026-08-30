import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
  Box,
  Flex,
  Heading,
  Link,
  Text,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
} from "@tanstack/react-router"
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import React from "react"
import { Light as SyntaxHighlighter } from "react-syntax-highlighter"
import yaml from "react-syntax-highlighter/dist/esm/languages/hljs/yaml"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"
import { z } from "zod"

import { ProjectsService } from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Mermaid from "../../../../../components/Common/Mermaid"
import StageEditorModal from "../../../../../components/Pipeline/StageEditorModal"
import useProject, {
  useProjectEnvironments,
} from "../../../../../hooks/useProject"
import { dataOrNull } from "../../../../../lib/api"
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
  stage_editor_open: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/pipeline",
)({
  component: ProjectPipeline,
  validateSearch: (search) => pipelineSearchSchema.parse(search),
})

function ProjectPipeline() {
  const { accountName, projectName } = Route.useParams()
  const { ref, stage, stage_editor_open } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const pipelineQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "pipeline", ref],
    queryFn: () =>
      ProjectsService.getProjectPipeline({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then(dataOrNull),
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

  // Which diagram nodes are stages (the rest are files), so only those become
  // clickable. The editor only knows calkit.yaml stages, so use those rather
  // than the compiled DVC names, which also cover stages Calkit generates
  // (LaTeX diffs) and hand-written dvc.yaml ones -- clicking either 404s.
  // Matrix stages are drawn as `name@item`; Mermaid maps those back itself.
  const stageNames = useMemo(
    () => new Set(pipelineQuery.data?.ck_stages ?? []),
    [pipelineQuery.data?.ck_stages],
  )
  // Editing writes to calkit.yaml, so it's only offered for projects that
  // define their pipeline there, and never while viewing an older revision.
  const canEditStages =
    userHasWriteAccess && !ref && Boolean(pipelineQuery.data?.calkit_yaml)
  const openStageEditor = useCallback(
    (stageName: string) =>
      navigate({
        search: (prev) => ({
          ...prev,
          stage: stageName,
          stage_editor_open: true,
        }),
      }),
    [navigate],
  )
  const closeStageEditor = () =>
    navigate({ search: (prev) => ({ ...prev, stage_editor_open: undefined }) })

  return (
    <>
      {pipelineQuery.isPending ? (
        <LoadingSpinner height="100vh" />
      ) : (
        <Flex flexDir={isDiagramExpanded ? "column" : "row"} gap={4}>
          {pipelineQuery.data ? (
            <>
              <Box flex={1} minW={0}>
                {pipelineQuery.data.error ? (
                  // DVC couldn't build the graph, so there's no diagram to
                  // draw. Show why, since it's the user's pipeline to fix.
                  <Alert
                    status="warning"
                    borderRadius="md"
                    alignItems="flex-start"
                  >
                    <AlertIcon />
                    <Box>
                      <AlertTitle>This pipeline isn't valid</AlertTitle>
                      <AlertDescription
                        whiteSpace="pre-wrap"
                        fontSize="sm"
                        display="block"
                      >
                        {pipelineQuery.data.error}
                      </AlertDescription>
                    </Box>
                  </Alert>
                ) : (
                  <>
                    <Mermaid
                      isDiagramExpanded={isDiagramExpanded}
                      setIsDiagramExpanded={setIsDiagramExpanded}
                      zoomToStage={stage}
                      stageNames={canEditStages ? stageNames : undefined}
                      onStageClick={canEditStages ? openStageEditor : undefined}
                    >
                      {String(pipelineQuery.data.mermaid)}
                    </Mermaid>
                    {canEditStages && (
                      <Text mt={1} fontSize="xs" color="ui.dim">
                        Click a stage to edit it.
                      </Text>
                    )}
                  </>
                )}
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
      {stage_editor_open && stage && canEditStages && (
        <StageEditorModal
          isOpen={Boolean(stage_editor_open)}
          onClose={closeStageEditor}
          ownerName={accountName}
          projectName={projectName}
          stageName={stage}
        />
      )}
    </>
  )
}
