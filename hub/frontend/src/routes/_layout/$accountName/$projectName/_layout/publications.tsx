import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  HStack,
  Heading,
  Icon,
  Link,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Portal,
  Text,
  VStack,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import Tooltip from "../../../../../components/Common/Tooltip"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { FaCodeBranch, FaPlus, FaSync } from "react-icons/fa"
import { FiFile } from "react-icons/fi"
import { MdEdit } from "react-icons/md"
import { SiOverleaf } from "react-icons/si"
import { z } from "zod"

import type { Publication } from "../../../../../client"
import { ProjectsService } from "../../../../../client"
import type { ApiError } from "../../../../../client/core/ApiError"
import { ArtifactCompareModal } from "../../../../../components/Common/ArtifactCompareModal"
import CommentsPanel, {
  projectCommentToPanelComment,
} from "../../../../../components/Common/CommentsPanel"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
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
  // Derive the LaTeX source path from the publication output path
  // (e.g. paper.pdf -> paper.tex). Phase-1 heuristic; a later version can
  // resolve the source from the publication's pipeline-stage deps.
  const texPath = publication.path
    ? publication.path.replace(/\.[^/.]+$/, ".tex")
    : null

  const overleafSyncMutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectOverleafSync({
        ownerName,
        projectName,
        requestBody: { path: publication.path },
      }),
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
    onError: (err: ApiError) => handleError(err, showToast),
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
  // Derive the LaTeX source path from the output path (e.g. paper.pdf ->
  // paper.tex), matching the heuristic used by the editor in the info panel.
  const texPath = selectedPub?.path
    ? selectedPub.path.replace(/\.[^/.]+$/, ".tex")
    : null
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
        ownerName: accountName,
        projectName,
        artifactType: "publication",
        artifactPath: selectedPub!.path,
      }),
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
        ownerName: accountName,
        projectName,
        commentId,
        requestBody: { resolved },
      }),
    onSuccess: invalidateComments,
  })
  const postCommentMutation = useMutation({
    mutationFn: (vars: { body: string; createIssue: boolean }) =>
      ProjectsService.postProjectComment({
        ownerName: accountName,
        projectName,
        requestBody: {
          artifact_path: selectedPub!.path,
          artifact_type: "publication",
          comment: vars.body,
          create_github_issue: vars.createIssue,
          git_ref: ref ?? null,
        },
      }),
    onSuccess: invalidateComments,
  })
  const replyCommentMutation = useMutation({
    mutationFn: (vars: { commentId: string; body: string }) =>
      ProjectsService.postProjectCommentReply({
        ownerName: accountName,
        projectName,
        commentId: vars.commentId,
        requestBody: { body: vars.body },
      }),
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
              <Flex
                align="center"
                justify="center"
                height="300px"
                color="gray.500"
              >
                <Text>No publications found</Text>
              </Flex>
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
