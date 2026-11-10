import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Code,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  Heading,
  Icon,
  IconButton,
  Input,
  Link,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  SimpleGrid,
  Text,
  VStack,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { useRef, useState } from "react"
import { FaPlus } from "react-icons/fa"
import { FiDownload, FiExternalLink, FiMonitor } from "react-icons/fi"
import { z } from "zod"

import type { Presentation } from "../../../../../client"
import { ProjectsService, UsersService } from "../../../../../client"
import CommentsPanel, {
  projectCommentToPanelComment,
} from "../../../../../components/Common/CommentsPanel"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import PdfCanvas from "../../../../../components/Common/PdfCanvas"
import PresentationView from "../../../../../components/Presentations/PresentationView"
import PdfAnnotator, {
  commentToHighlight,
  type AnnotationHighlight,
} from "../../../../../components/Publications/PdfAnnotator"
import ArtifactReleasesPanel from "../../../../../components/Releases/ArtifactReleasesPanel"
import useAuth from "../../../../../hooks/useAuth"
import useCustomToast from "../../../../../hooks/useCustomToast"
import useProject, {
  useProjectPresentations,
} from "../../../../../hooks/useProject"
import { handleError } from "../../../../../lib/errors"
import { safeHref } from "../../../../../lib/strings"

const presSearchSchema = z.object({
  path: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/presentations",
)({
  component: Presentations,
  validateSearch: (search) => presSearchSchema.parse(search),
})

interface PresInfoProps {
  presentation: Presentation
}

function PresInfo({ presentation }: PresInfoProps) {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  return (
    <Box bg={secBgColor} borderRadius="lg" p={3} h="fit-content">
      <Heading size="sm" mb={2}>
        Info
      </Heading>
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Title:
        </Text>{" "}
        <Text as="span" color="gray.500">
          {presentation.title ?? ""}
        </Text>
      </Text>
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Description:
        </Text>{" "}
        <Text as="span" color="gray.500">
          {presentation.description ?? ""}
        </Text>
      </Text>
      {presentation.path && (
        <Text fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Path:
          </Text>{" "}
          <Link
            as={RouterLink}
            to="../files"
            search={{ path: presentation.path } as any}
          >
            {presentation.path}
          </Link>
        </Text>
      )}
      {presentation.kind && (
        <Text fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Type:
          </Text>{" "}
          <Badge>{presentation.kind}</Badge>
        </Text>
      )}
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Pipeline stage:
        </Text>{" "}
        {presentation.stage ? (
          <Code fontSize="xs">{presentation.stage}</Code>
        ) : (
          <Text as="span" color="red.500">
            Not in pipeline
          </Text>
        )}
      </Text>
      {presentation.edit_url && (
        <Box mt={3}>
          <Button
            as="a"
            href={safeHref(presentation.edit_url)}
            target="_blank"
            rel="noopener noreferrer"
            size="sm"
            leftIcon={<FiExternalLink />}
          >
            Open in Google Slides
          </Button>
        </Box>
      )}
      {presentation.url && (
        <Box mt={3}>
          <Button
            as="a"
            href={safeHref(String(presentation.url))}
            download
            target="_blank"
            rel="noopener noreferrer"
            size="sm"
            leftIcon={<FiDownload />}
          >
            Download
          </Button>
        </Box>
      )}
    </Box>
  )
}

/** Where an exported presentation lives, from its title. */
function getDefaultPath(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
  return slug ? `presentations/${slug}.pdf` : ""
}

interface NewGoogleSlidesProps {
  isOpen: boolean
  onClose: () => void
  accountName: string
  projectName: string
}

function NewGoogleSlides({
  isOpen,
  onClose,
  accountName,
  projectName,
}: NewGoogleSlidesProps) {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [title, setTitle] = useState("")
  const [path, setPath] = useState("")
  const [pathEdited, setPathEdited] = useState(false)
  const [kind, setKind] = useState<"slides" | "poster">("slides")
  const connectedAccountsQuery = useQuery({
    queryFn: () =>
      UsersService.getUserConnectedAccounts().then((response) => response.data),
    queryKey: ["user", "connected-accounts"],
    enabled: isOpen,
  })
  // Signing in with Google isn't enough, since it doesn't reach Drive
  const googleConnected = connectedAccountsQuery.data?.google ?? false
  const close = () => {
    setTitle("")
    setPath("")
    setPathEdited(false)
    setKind("slides")
    onClose()
  }
  const mutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectGoogleSlidesPresentation({
        owner_name: accountName,
        project_name: projectName,
        googleSlidesPresentationPost: { title, path, kind },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast(
        "Success!",
        "Presentation created. Open it in Google Slides to start editing.",
        "success",
      )
      close()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "presentations"],
      })
    },
  })
  return (
    <Modal isOpen={isOpen} onClose={close} size="md" isCentered>
      <ModalOverlay />
      <ModalContent
        as="form"
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
      >
        <ModalHeader>New Google Slides presentation</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          {connectedAccountsQuery.isSuccess && !googleConnected && (
            <Alert status="warning" mb={4} borderRadius="md" fontSize="sm">
              <AlertIcon />
              <Text>
                Connect Google Drive in{" "}
                <Link
                  as={RouterLink}
                  to="/settings"
                  search={{ tab: "connected-accounts" } as any}
                  textDecoration="underline"
                >
                  your settings
                </Link>{" "}
                first.
              </Text>
            </Alert>
          )}
          <FormControl isRequired>
            <FormLabel>Title</FormLabel>
            <Input
              value={title}
              autoComplete="off"
              placeholder="My poster"
              onChange={(e) => {
                setTitle(e.target.value)
                if (!pathEdited) setPath(getDefaultPath(e.target.value))
              }}
            />
          </FormControl>
          <FormControl mt={4}>
            <FormLabel>Kind</FormLabel>
            <Select
              value={kind}
              onChange={(e) => setKind(e.target.value as "slides" | "poster")}
            >
              <option value="slides">Slides</option>
              <option value="poster">Poster</option>
            </Select>
          </FormControl>
          <FormControl mt={4} isRequired>
            <FormLabel>PDF path</FormLabel>
            <Input
              value={path}
              autoComplete="off"
              placeholder="presentations/my-poster.pdf"
              onChange={(e) => {
                setPath(e.target.value)
                setPathEdited(true)
              }}
            />
            <FormHelperText>
              Where the pipeline exports it in the project, with a PowerPoint
              copy beside it.
            </FormHelperText>
          </FormControl>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={mutation.isPending}
            isDisabled={!googleConnected || !title || !path}
          >
            Create
          </Button>
          <Button onClick={close}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

interface PresCardProps {
  presentation: Presentation
  onClick: () => void
}

function PresCard({ presentation, onClick }: PresCardProps) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const bg = useColorModeValue("white", "gray.800")
  const hoverBg = useColorModeValue("gray.50", "gray.700")
  const isPdf = presentation.path.toLowerCase().endsWith(".pdf")
  const src = presentation.content
    ? `data:application/pdf;base64,${presentation.content}`
    : presentation.url
      ? String(presentation.url)
      : null
  return (
    <Box
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="lg"
      overflow="hidden"
      bg={bg}
      cursor="pointer"
      _hover={{ bg: hoverBg, shadow: "md" }}
      onClick={onClick}
      transition="all 0.15s"
    >
      <Box height="160px" overflow="hidden" bg="gray.50">
        {isPdf && src ? (
          <PdfCanvas src={src} maxPages={1} />
        ) : (
          <Flex
            height="100%"
            direction="column"
            align="center"
            justify="center"
            color="gray.400"
            gap={2}
          >
            <Icon as={FiMonitor} fontSize="3xl" />
            {!src && (
              <Text fontSize="xs" textAlign="center" px={3}>
                Not exported yet; run the pipeline to export it
              </Text>
            )}
          </Flex>
        )}
      </Box>
      <Box p={3}>
        <Flex align="center" gap={2}>
          <Text fontWeight="semibold" fontSize="sm" noOfLines={1} flex={1}>
            {presentation.title}
          </Text>
          {presentation.kind && (
            <Badge fontSize="xs" flexShrink={0}>
              {presentation.kind}
            </Badge>
          )}
          {presentation.edit_url && (
            <IconButton
              as="a"
              href={safeHref(presentation.edit_url)}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Open in Google Slides"
              title="Open in Google Slides"
              icon={<FiExternalLink />}
              size="xs"
              variant="ghost"
              onClick={(e) => e.stopPropagation()}
            />
          )}
        </Flex>
        <Text fontSize="xs" color="gray.500" noOfLines={1}>
          {presentation.path}
        </Text>
      </Box>
    </Box>
  )
}

function Presentations() {
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const { presentationsRequest } = useProjectPresentations(
    accountName,
    projectName,
    ref,
  )
  const { path: selectedPath } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const setSelectedPath = (p: string | undefined) =>
    navigate({ search: (prev) => ({ ...prev, path: p }) })
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const newGoogleSlidesModal = useDisclosure()
  const [showResolved, setShowResolved] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pdfScrollRef = useRef<(h: any) => void>(() => {})

  const selectedPres = presentationsRequest.data?.find(
    (p) => p.path === selectedPath,
  )

  const isPdf = selectedPres?.path?.toLowerCase().endsWith(".pdf") ?? false
  const commentsQuery = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "comments",
      "presentation",
      selectedPres?.path ?? "",
    ],
    queryFn: () =>
      ProjectsService.getProjectComments({
        owner_name: accountName,
        project_name: projectName,
        artifact_type: "presentation",
        artifact_path: selectedPres!.path,
      }).then((response) => response.data),
    enabled: !!selectedPres,
  })

  const invalidateComments = () =>
    queryClient.invalidateQueries({
      queryKey: [
        "projects",
        accountName,
        projectName,
        "comments",
        "presentation",
        selectedPres?.path,
      ],
    })
  const resolveCommentMutation = useMutation({
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
          artifact_path: selectedPres!.path,
          artifact_type: "presentation",
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

  const comments = commentsQuery.data ?? []
  const highlights: AnnotationHighlight[] = comments
    .map(commentToHighlight)
    .filter((h): h is AnnotationHighlight => h !== null)

  return (
    <>
      <Box>
        <Flex align="center" mb={4} gap={2}>
          <Heading size="md">Presentations</Heading>
          {userHasWriteAccess && !ref && (
            <Menu>
              <MenuButton
                as={Button}
                variant="primary"
                height="25px"
                width="9px"
                px={1}
                aria-label="New presentation"
              >
                <Icon as={FaPlus} fontSize="xs" />
              </MenuButton>
              <MenuList>
                <MenuItem onClick={newGoogleSlidesModal.onOpen}>
                  New Google Slides presentation
                </MenuItem>
              </MenuList>
            </Menu>
          )}
        </Flex>
        <NewGoogleSlides
          isOpen={newGoogleSlidesModal.isOpen}
          onClose={newGoogleSlidesModal.onClose}
          accountName={accountName}
          projectName={projectName}
        />
        {presentationsRequest.isPending ? (
          <LoadingSpinner height="300px" />
        ) : presentationsRequest.data?.length ? (
          <SimpleGrid columns={{ base: 1, md: 2, lg: 3, xl: 4 }} spacing={4}>
            {presentationsRequest.data.map((pres) => (
              <PresCard
                key={pres.path}
                presentation={pres}
                onClick={() => setSelectedPath(pres.path)}
              />
            ))}
          </SimpleGrid>
        ) : (
          <NoArtifactFound
            icon={FiMonitor}
            title="No presentations found"
            hint={
              <>
                Declare slides or a poster in the <Code>presentations</Code>{" "}
                section of <Code>calkit.yaml</Code> to show them here.
              </>
            }
            docsUrl="https://docs.calkit.org/calkit-yaml/"
          >
            {userHasWriteAccess && !ref && (
              <Button
                mt={3}
                size="sm"
                variant="primary"
                onClick={newGoogleSlidesModal.onOpen}
              >
                New Google Slides presentation
              </Button>
            )}
          </NoArtifactFound>
        )}
      </Box>
      <Modal
        isOpen={!!selectedPres}
        onClose={() => setSelectedPath(undefined)}
        size="full"
      >
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>{selectedPres?.title}</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            {selectedPres && (
              <Flex height="100%" gap={6}>
                <Box flex={1} minW={0} minH={0}>
                  {isPdf && selectedPres.url ? (
                    <Box height="82vh">
                      <PdfAnnotator
                        url={String(selectedPres.url)}
                        ownerName={accountName}
                        projectName={projectName}
                        publicationPath={selectedPres.path}
                        artifactType="presentation"
                        gitRef={ref}
                        showResolved={showResolved}
                        pagedNav
                        externalScrollRef={pdfScrollRef}
                      />
                    </Box>
                  ) : selectedPres.url || selectedPres.content ? (
                    <Box height="82vh" borderRadius="lg" overflow="hidden">
                      <PresentationView presentation={selectedPres} />
                    </Box>
                  ) : (
                    <NoArtifactFound
                      icon={FiMonitor}
                      title="Not exported yet"
                      hint="Run the pipeline to export it."
                    />
                  )}
                </Box>
                <Box w="280px" flexShrink={0} overflowY="auto">
                  <VStack align="stretch" spacing={3}>
                    <PresInfo presentation={selectedPres} />
                    {selectedPres.path && (
                      <Box bg={secBgColor} borderRadius="lg" p={3}>
                        <ArtifactReleasesPanel
                          ownerName={accountName}
                          projectName={projectName}
                          path={selectedPres.path}
                          userHasWriteAccess={userHasWriteAccess}
                          kind="presentation"
                        />
                      </Box>
                    )}
                    <CommentsPanel
                      comments={comments.map(projectCommentToPanelComment)}
                      isLoading={commentsQuery.isPending}
                      canComment={!!user}
                      canResolve={!!user}
                      showResolved={showResolved}
                      onShowResolvedChange={setShowResolved}
                      showCreateIssueCheckbox
                      emptyText="Select text in the PDF or use the button below to add a comment."
                      onHighlightClick={(c) => {
                        const h = highlights.find((x) => x.dbId === c.id)
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
                        resolveCommentMutation.mutate({
                          commentId: id,
                          resolved,
                        })
                      }
                      resolvingId={
                        resolveCommentMutation.isPending
                          ? resolveCommentMutation.variables?.commentId ?? null
                          : null
                      }
                    />
                  </VStack>
                </Box>
              </Flex>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  )
}
