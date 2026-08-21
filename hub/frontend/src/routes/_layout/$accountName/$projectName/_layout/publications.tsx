import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Heading,
  HStack,
  Icon,
  Link,
  ListItem,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Portal,
  Text,
  UnorderedList,
  useColorModeValue,
  useDisclosure,
  VStack,
} from "@chakra-ui/react"
import { load as yamlLoad } from "js-yaml"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { FaCodeBranch, FaPlus, FaSync } from "react-icons/fa"
import { FiBookOpen, FiFile } from "react-icons/fi"
import { MdEdit } from "react-icons/md"
import { SiOverleaf } from "react-icons/si"
import { z } from "zod"
import Tooltip from "../../../../../components/Common/Tooltip"

import type { AxiosError } from "axios"
import type { Publication } from "../../../../../client"
import { ProjectsService } from "../../../../../client"
import { ArtifactCompareModal } from "../../../../../components/Common/ArtifactCompareModal"
import CommentsPanel, {
  projectCommentToPanelComment,
} from "../../../../../components/Common/CommentsPanel"
import InputsRow, {
  type InputLink,
} from "../../../../../components/Common/InputsRow"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import PageMenu from "../../../../../components/Common/PageMenu"
import ImportOverleaf from "../../../../../components/Publications/ImportOverleaf"
import LatexEditor from "../../../../../components/Publications/LatexEditor"
import NewPublication from "../../../../../components/Publications/NewPublication"
import PdfAnnotator, {
  commentToHighlight,
  type AnnotationHighlight,
} from "../../../../../components/Publications/PdfAnnotator"
import PublicationView from "../../../../../components/Publications/PublicationView"
import ArtifactReleasesPanel from "../../../../../components/Releases/ArtifactReleasesPanel"
import useAuth from "../../../../../hooks/useAuth"
import useCustomToast from "../../../../../hooks/useCustomToast"
import useProject, {
  useProjectPublications,
} from "../../../../../hooks/useProject"
import { handleError } from "../../../../../lib/errors"
import { getLatexSourcePath } from "../../../../../lib/latexProject"
import {
  classifyPublicationDeps,
  findFeederStages,
  getStageDeps,
  getStageOuts,
} from "../../../../../lib/provenance"

const pubSearchSchema = z.object({
  path: z.string().optional(),
  compare_open: z.boolean().optional(),
  base_ref: z.string().optional(),
  compare_ref: z.string().optional(),
  editor_open: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/publications",
)({
  component: Publications,
  validateSearch: (search) => pubSearchSchema.parse(search),
})

interface PubInfoProps {
  publication: Publication
  ownerName: string
  projectName: string
  userHasWriteAccess: boolean
  onOpenCompare: () => void
}

/**
 * A stage's inputs as its author declared them, with another stage's
 * outputs expanded to the paths they are. Empty when the stage hasn't
 * loaded or declares none.
 */
function declaredInputs(
  stageYaml: string | undefined,
  dvcStages: Record<string, unknown>,
): string[] {
  if (!stageYaml) return []
  let parsed: { inputs?: unknown } = {}
  try {
    parsed = (yamlLoad(stageYaml) as { inputs?: unknown }) ?? {}
  } catch {
    return []
  }
  if (!Array.isArray(parsed.inputs)) return []
  const paths: string[] = []
  for (const input of parsed.inputs) {
    if (typeof input === "string") {
      paths.push(input)
    } else if (input && typeof input === "object") {
      const item = input as { path?: string; from_stage_outputs?: string }
      if (item.from_stage_outputs) {
        paths.push(...getStageOuts(dvcStages[item.from_stage_outputs] as any))
      } else if (item.path) {
        paths.push(item.path)
      }
    }
  }
  return paths.filter((p) => p && !p.startsWith(".calkit/"))
}

function PubInfo({
  publication,
  ownerName,
  projectName,
  userHasWriteAccess,
  onOpenCompare,
}: PubInfoProps) {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  // Editor open state lives in the URL (editor_open) so a session is shareable
  // and restorable by link, like the compare modal.
  const { editor_open: editorOpen } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const closeEditor = () =>
    navigate({ search: (prev) => ({ ...prev, editor_open: undefined }) })
  const texPath = getLatexSourcePath(publication)
  // What went into the publication: its stage's concrete inputs in dvc.yaml,
  // sorted against the declared figures, plus any stage that copies files
  // into the publication's folder (e.g., a map-paths stage).
  const pipelineQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "pipeline", undefined],
    queryFn: () =>
      ProjectsService.getProjectPipeline({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: Boolean(publication.stage),
    retry: false,
  })
  const figuresQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "figures"],
    queryFn: () =>
      ProjectsService.getProjectFigures({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: Boolean(publication.stage),
    retry: false,
  })
  // The stage as declared in calkit.yaml: its inputs are what the author
  // meant, whereas dvc.yaml's deps also carry what Calkit adds for itself
  // (environment locks, the script). `from_stage_outputs` is expanded
  // through the compiled pipeline.
  const stageQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "stage", publication.stage],
    queryFn: () =>
      ProjectsService.getProjectPipelineStage({
        owner_name: ownerName,
        project_name: projectName,
        stage_name: publication.stage!,
      }).then((response) => response.data),
    enabled: Boolean(publication.stage),
    retry: false,
  })
  const figureLinks: InputLink[] = []
  const referenceLinks: InputLink[] = []
  const otherLinks: InputLink[] = []
  let feederStages: string[] = []
  if (publication.stage) {
    const dvcStages = pipelineQuery.data?.dvc_stages ?? {}
    // stage_info carries the deps too, so the rows can show before the
    // pipeline has loaded
    const stage = dvcStages[publication.stage] ?? publication.stage_info
    const deps = declaredInputs(stageQuery.data?.yaml, dvcStages).length
      ? declaredInputs(stageQuery.data?.yaml, dvcStages)
      : getStageDeps(stage).filter((d) => !d.startsWith(".calkit/"))
    const inputs = classifyPublicationDeps(deps, figuresQuery.data?.items ?? [])
    for (const { path, figure } of inputs.figures) {
      figureLinks.push(
        figure
          ? {
              key: path,
              to: "../figures",
              search: { path },
              label: figure.title || path,
              tooltipPath: figure.title ? path : undefined,
              code: !figure.title,
            }
          : {
              key: path,
              to: "../files",
              search: { path },
              label: path,
              code: true,
            },
      )
    }
    for (const path of inputs.references)
      referenceLinks.push({
        key: path,
        to: "../files",
        search: { path },
        label: path,
        code: true,
      })
    for (const path of inputs.other)
      otherLinks.push({
        key: path,
        to: "../files",
        search: { path },
        label: path,
        code: true,
      })
    feederStages = findFeederStages(
      publication.stage,
      dvcStages,
      publication.path,
    )
  }

  const overleafSyncMutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectOverleafSync({
        owner_name: ownerName,
        project_name: projectName,
        overleafSyncPost: { path: publication.path },
      }).then((response) => response.data),
    onSuccess: (data) => {
      let message = "Synced with Overleaf."
      if (data.commits_from_overleaf > 0)
        message = `Applied ${data.commits_from_overleaf} changes from Overleaf.`
      if (data.committed_overleaf)
        message += ` Updated Overleaf to rev ${data.overleaf_commit.slice(0, 7)}.`
      if (data.committed_project)
        message += ` Updated project to rev ${data.project_commit.slice(0, 7)}.`
      if (
        !data.commits_from_overleaf &&
        !data.committed_overleaf &&
        !data.committed_project
      )
        message += " No changes made."
      showToast("Success!", message, "success")
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "publications"],
      })
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })

  return (
    <Box bg={secBgColor} borderRadius="lg" p={3} h="fit-content">
      <Heading size="sm" mb={2}>
        Info
      </Heading>
      {userHasWriteAccess && texPath && editorOpen && (
        <LatexEditor
          isOpen={Boolean(editorOpen)}
          onClose={closeEditor}
          ownerName={ownerName}
          projectName={projectName}
          texPath={texPath}
          deps={publication.stage_info?.deps ?? undefined}
        />
      )}
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Title:
        </Text>{" "}
        <Text as="span" color="gray.500">
          {publication.title ?? ""}
        </Text>
      </Text>
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Description:
        </Text>{" "}
        <Text as="span" color="gray.500">
          {publication.description ?? ""}
        </Text>
      </Text>
      {publication.path && (
        <Text fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Path:
          </Text>{" "}
          <Link
            as={RouterLink}
            to="../files"
            search={{ path: publication.path } as any}
          >
            {publication.path}
          </Link>
        </Text>
      )}
      {publication.type && (
        <Text fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Type:
          </Text>{" "}
          <Badge>{publication.type}</Badge>
        </Text>
      )}
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Pipeline stage:
        </Text>{" "}
        {publication.stage ? (
          <Link
            as={RouterLink}
            to="../pipeline"
            search={{ stage: publication.stage } as any}
          >
            <Code fontSize="xs" cursor="pointer">
              {publication.stage}
            </Code>
          </Link>
        ) : (
          <Text as="span" color="red.500">
            Not in pipeline
          </Text>
        )}
      </Text>
      <InputsRow label="Figures" items={figureLinks} />
      <InputsRow label="References" items={referenceLinks} />
      <InputsRow label="Other inputs" items={otherLinks} />
      {feederStages.length > 0 && (
        <Box fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Copied in by stages:
          </Text>
          <UnorderedList mt={0.5} mb={0} pl={1}>
            {feederStages.map((name) => (
              <ListItem key={name}>
                <Link
                  as={RouterLink}
                  to="../pipeline"
                  search={{ stage: name } as any}
                >
                  <Code fontSize="xs" cursor="pointer">
                    {name}
                  </Code>
                </Link>
              </ListItem>
            ))}
          </UnorderedList>
        </Box>
      )}
      {publication.overleaf?.project_id && (
        <Box mt={2}>
          <Flex align="center" gap={1}>
            <Link
              isExternal
              href={`https://www.overleaf.com/project/${publication.overleaf.project_id}`}
              fontSize="sm"
            >
              <Flex align="center" gap={1}>
                <Icon as={SiOverleaf} color="green.500" />
                <Text>View on Overleaf</Text>
                <Icon as={ExternalLinkIcon} />
              </Flex>
            </Link>
            {userHasWriteAccess && (
              <Button
                size="xs"
                onClick={() => overleafSyncMutation.mutate()}
                isLoading={overleafSyncMutation.isPending}
                rightIcon={<FaSync />}
                ml={1}
              >
                Sync
              </Button>
            )}
          </Flex>
        </Box>
      )}
      <Button mt={3} size="sm" onClick={onOpenCompare}>
        <Icon as={FaCodeBranch} mr={1} />
        Browse history
      </Button>
    </Box>
  )
}

function Publications() {
  const uploadPubModal = useDisclosure()
  const labelPubModal = useDisclosure()
  const newPubTemplateModal = useDisclosure()
  const overleafImportModal = useDisclosure()
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const { publicationsRequest } = useProjectPublications(
    accountName,
    projectName,
    ref,
  )
  const {
    path: selectedPath,
    compare_open,
    base_ref,
    compare_ref,
  } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const setSelectedPath = (p: string) =>
    navigate({ search: (prev) => ({ ...prev, path: p }) })

  const openCompare = (pubPath: string) =>
    navigate({
      search: (prev) => ({ ...prev, path: pubPath, compare_open: true }),
    })

  const closeCompare = () =>
    navigate({
      search: (prev) => ({
        ...prev,
        compare_open: undefined,
        base_ref: undefined,
        compare_ref: undefined,
      }),
    })
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [showResolved, setShowResolved] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pdfScrollRef = useRef<(h: any) => void>(() => {})

  const selectedPub =
    publicationsRequest.data?.find((p) => p.path === selectedPath) ??
    publicationsRequest.data?.[0]

  // Arriving from a question's evidence (or right after committing an edit)
  // can transiently return an empty list; if we expected a specific
  // publication (path in the URL) but got none, refetch once so it appears
  // without a manual page refresh.
  const emptyRetriedRef = useRef(false)
  useEffect(() => {
    if (
      publicationsRequest.isSuccess &&
      (publicationsRequest.data?.length ?? 0) === 0 &&
      selectedPath &&
      !emptyRetriedRef.current
    ) {
      emptyRetriedRef.current = true
      publicationsRequest.refetch()
    }
  }, [
    publicationsRequest.isSuccess,
    publicationsRequest.data,
    publicationsRequest.refetch,
    selectedPath,
  ])

  const isPdf = selectedPub?.path?.endsWith(".pdf") ?? false
  const texPath = selectedPub ? getLatexSourcePath(selectedPub) : null
  const canEditLatex = userHasWriteAccess && !!texPath
  const isStale = selectedPub?.stage_status?.status === "stale"
  const toolbarAction =
    isStale || canEditLatex ? (
      <HStack spacing={2}>
        {isStale && (
          <Tooltip label="This publication is out of date. Re-run the pipeline to rebuild it.">
            <Badge colorScheme="orange">Stale</Badge>
          </Tooltip>
        )}
        {canEditLatex && (
          <Button
            size="xs"
            variant="ghost"
            onClick={() =>
              navigate({ search: (prev) => ({ ...prev, editor_open: true }) })
            }
          >
            <Icon as={MdEdit} mr={1} />
            Edit LaTeX
          </Button>
        )}
      </HStack>
    ) : undefined

  const commentsQuery = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "comments",
      "publication",
      selectedPub?.path ?? "",
    ],
    queryFn: () =>
      ProjectsService.getProjectComments({
        owner_name: accountName,
        project_name: projectName,
        artifact_type: "publication",
        artifact_path: selectedPub!.path,
      }).then((response) => response.data),
    enabled: !!selectedPub,
  })

  const invalidateComments = () =>
    queryClient.invalidateQueries({
      queryKey: [
        "projects",
        accountName,
        projectName,
        "comments",
        "publication",
        selectedPub?.path,
      ],
    })
  const resolvePubCommentMutation = useMutation({
    mutationFn: ({
      commentId,
      resolved,
    }: {
      commentId: string
      resolved: boolean
    }) =>
      ProjectsService.patchProjectComment({
        owner_name: accountName,
        project_name: projectName,
        comment_id: commentId,
        projectCommentPatch: { resolved },
      }).then((response) => response.data),
    onSuccess: invalidateComments,
  })
  const postCommentMutation = useMutation({
    mutationFn: (vars: { body: string; createIssue: boolean }) =>
      ProjectsService.postProjectComment({
        owner_name: accountName,
        project_name: projectName,
        projectCommentPost: {
          artifact_path: selectedPub!.path,
          artifact_type: "publication",
          comment: vars.body,
          create_github_issue: vars.createIssue,
          git_ref: ref ?? null,
        },
      }).then((response) => response.data),
    onSuccess: invalidateComments,
  })
  const replyCommentMutation = useMutation({
    mutationFn: (vars: { commentId: string; body: string }) =>
      ProjectsService.postProjectCommentReply({
        owner_name: accountName,
        project_name: projectName,
        comment_id: vars.commentId,
        commentReply: { body: vars.body },
      }).then((response) => response.data),
    onSuccess: invalidateComments,
  })

  const pdfComments = commentsQuery.data ?? []
  const pdfHighlights: AnnotationHighlight[] = pdfComments
    .map(commentToHighlight)
    .filter((h): h is AnnotationHighlight => h !== null)

  return (
    <>
      {publicationsRequest.isPending ? (
        <LoadingSpinner height="100vh" />
      ) : (
        <Flex height="100%" gap={0}>
          {/* Left: tree index */}
          <PageMenu>
            <Flex align="center" mb={2}>
              <Heading size="md">Publications</Heading>
              {userHasWriteAccess && (
                <>
                  <Menu>
                    <MenuButton
                      as={Button}
                      variant="primary"
                      height="25px"
                      width="9px"
                      px={1}
                      ml={2}
                    >
                      <Icon as={FaPlus} fontSize="xs" />
                    </MenuButton>
                    <Portal>
                      <MenuList zIndex="popover">
                        <MenuItem onClick={newPubTemplateModal.onOpen}>
                          Create new from template
                        </MenuItem>
                        <MenuItem onClick={overleafImportModal.onOpen}>
                          Import from Overleaf
                        </MenuItem>
                        <MenuItem onClick={uploadPubModal.onOpen}>
                          Upload
                        </MenuItem>
                        <MenuItem onClick={labelPubModal.onOpen}>
                          Label existing file
                        </MenuItem>
                      </MenuList>
                    </Portal>
                  </Menu>
                  <NewPublication
                    isOpen={newPubTemplateModal.isOpen}
                    onClose={newPubTemplateModal.onClose}
                    variant="template"
                  />
                  <ImportOverleaf
                    isOpen={overleafImportModal.isOpen}
                    onClose={overleafImportModal.onClose}
                  />
                  <NewPublication
                    isOpen={uploadPubModal.isOpen}
                    onClose={uploadPubModal.onClose}
                    variant="upload"
                  />
                  <NewPublication
                    isOpen={labelPubModal.isOpen}
                    onClose={labelPubModal.onClose}
                    variant="label"
                  />
                </>
              )}
            </Flex>
            {publicationsRequest.data?.map((pub) => {
              const isSelected = pub.path === selectedPub?.path
              return (
                <Tooltip key={pub.path} label={pub.title} placement="right">
                  <HStack
                    px={1}
                    py={0.5}
                    borderRadius="md"
                    cursor="pointer"
                    fontWeight={isSelected ? "semibold" : "normal"}
                    _hover={{ color: "blue.500" }}
                    onClick={() => setSelectedPath(pub.path)}
                    spacing={1}
                  >
                    <Icon as={FiFile} flexShrink={0} />
                    <Text fontSize="sm" noOfLines={1}>
                      {pub.title}
                    </Text>
                  </HStack>
                </Tooltip>
              )
            })}
          </PageMenu>

          {/* Center: publication viewer */}
          <Box flex={1} minW={0} mr={6} minH={0}>
            {selectedPub ? (
              <>
                {isPdf && selectedPub.url ? (
                  <Box height="82vh">
                    <PdfAnnotator
                      url={String(selectedPub.url)}
                      ownerName={accountName}
                      projectName={projectName}
                      publicationPath={selectedPub.path}
                      gitRef={ref}
                      showResolved={showResolved}
                      externalScrollRef={pdfScrollRef}
                      toolbarAction={toolbarAction}
                    />
                  </Box>
                ) : (
                  <Box height="82vh" borderRadius="lg" overflow="hidden">
                    <PublicationView
                      publication={selectedPub}
                      toolbarAction={toolbarAction}
                    />
                  </Box>
                )}
              </>
            ) : publicationsRequest.isFetching ? (
              // A background refetch (e.g. after arriving from a question's
              // evidence, or a just-committed edit) can briefly leave the list
              // empty; show loading rather than a false "not found" that sticks
              // until a manual refresh.
              <LoadingSpinner height="300px" />
            ) : (
              <NoArtifactFound
                icon={FiBookOpen}
                title="No publications found"
                hint="Start one from a template, or link the Overleaf project you're already writing in."
                docsUrl="https://docs.calkit.org/latex/"
              />
            )}
          </Box>

          {/* Right: info + compare + comments */}
          {selectedPub && (
            <Box w="280px" flexShrink={0} overflowY="auto">
              <VStack align="stretch" spacing={3}>
                <PubInfo
                  publication={selectedPub}
                  ownerName={accountName}
                  projectName={projectName}
                  userHasWriteAccess={userHasWriteAccess}
                  onOpenCompare={() => openCompare(selectedPub.path)}
                />
                <ArtifactCompareModal
                  isOpen={Boolean(compare_open)}
                  onClose={closeCompare}
                  ownerName={accountName}
                  projectName={projectName}
                  path={selectedPub.path}
                  kind="publication"
                  initialRef={base_ref}
                  initialRef2={compare_ref}
                  initialArtifact={selectedPub}
                  onRefsChange={(r1, r2) =>
                    navigate({
                      search: (prev) => ({
                        ...prev,
                        base_ref: r1,
                        compare_ref: r2,
                      }),
                    })
                  }
                />
                {selectedPub.path && (
                  <Box bg={secBgColor} borderRadius="lg" p={3}>
                    <ArtifactReleasesPanel
                      ownerName={accountName}
                      projectName={projectName}
                      path={selectedPub.path}
                      userHasWriteAccess={userHasWriteAccess}
                      kind="publication"
                    />
                  </Box>
                )}
                {selectedPub && (
                  <CommentsPanel
                    comments={pdfComments.map(projectCommentToPanelComment)}
                    isLoading={commentsQuery.isPending}
                    canComment={!!user}
                    canResolve={!!user}
                    showResolved={showResolved}
                    onShowResolvedChange={setShowResolved}
                    showCreateIssueCheckbox
                    emptyText="Select text in the PDF or use the button below to add a comment."
                    onHighlightClick={(c) => {
                      const h = pdfHighlights.find((x) => x.dbId === c.id)
                      if (h) pdfScrollRef.current(h)
                    }}
                    onPostComment={(body, opts) =>
                      postCommentMutation.mutateAsync({
                        body,
                        createIssue: opts.createIssue,
                      })
                    }
                    postingComment={postCommentMutation.isPending}
                    onPostReply={(parentId, body) =>
                      replyCommentMutation.mutateAsync({
                        commentId: parentId,
                        body,
                      })
                    }
                    postingReplyForId={
                      replyCommentMutation.isPending
                        ? replyCommentMutation.variables?.commentId ?? null
                        : null
                    }
                    onResolve={(id, resolved) =>
                      resolvePubCommentMutation.mutate({
                        commentId: id,
                        resolved,
                      })
                    }
                    resolvingId={
                      resolvePubCommentMutation.isPending
                        ? resolvePubCommentMutation.variables?.commentId ?? null
                        : null
                    }
                  />
                )}
              </VStack>
            </Box>
          )}
        </Flex>
      )}
    </>
  )
}
