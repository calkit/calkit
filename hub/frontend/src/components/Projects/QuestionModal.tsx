import {
  Badge,
  Box,
  Code,
  Flex,
  Heading,
  Icon,
  IconButton,
  Image,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  SimpleGrid,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { FaArrowLeft, FaChevronLeft, FaChevronRight } from "react-icons/fa"
import { FaExternalLinkAlt, FaRegFileAlt } from "react-icons/fa"
import { FiGrid } from "react-icons/fi"
import { MdEdit } from "react-icons/md"
import { TiFlowMerge } from "react-icons/ti"

import { ProjectsService } from "../../client"
import type { QuestionEvidence, QuestionPublic } from "../../client"
import useAuth from "../../hooks/useAuth"
import {
  useProjectPublications,
  useProjectTables,
} from "../../hooks/useProject"
import CommentsPanel, {
  projectCommentToPanelComment,
} from "../Common/CommentsPanel"
import LoadingSpinner from "../Common/LoadingSpinner"
import Markdown from "../Common/Markdown"
import Tooltip from "../Common/Tooltip"
import FigureView from "../Figures/FigureView"
import PublicationView from "../Publications/PublicationView"
import TableView from "../Tables/TableView"

const IMG_MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  svg: "image/svg+xml",
}

/** Where an evidence item's artifact lives.
 *
 * Its own ref when it names one, e.g. the tag an answer was written against,
 * otherwise the ref the project is being browsed at. Everything about the
 * item -- the artifact it resolved to, the page it opens, the listing its
 * content is fetched from -- has to agree on this, or the card shows one
 * version and opens another.
 */
const evidenceRefOf = (evidence: QuestionEvidence, gitRef?: string) =>
  evidence.git_ref ?? gitRef

/** Whether what an evidence item cites can be taken at face value.
 *
 * An answer resting on an artifact the pipeline considers out of date is
 * worth flagging: the code or data behind it has moved since it was made,
 * so what the reader is looking at isn't what the project would produce now.
 * The backend works out which of the two ways that can happen applies.
 */
export const isEvidenceStale = (evidence: QuestionEvidence) =>
  evidence.stale_reason != null

const STALE_TIPS: Record<string, string> = {
  pipeline:
    "This is out of date with respect to the pipeline. Re-run the pipeline to rebuild it.",
  frozen:
    "This comes from a frozen stage, or one downstream of a frozen stage, so the pipeline will never report it out of date no matter how far its inputs have moved. Cite it at a Git ref to pin which version this refers to.",
}

/** The page an evidence item has its own full view on. */
const evidencePage = (evidence: QuestionEvidence) => {
  if (evidence.kind === "figure") {
    return "figures"
  }
  if (evidence.kind === "table") {
    return "tables"
  }
  if (evidence.kind === "publication") {
    return "publications"
  }
  return "files"
}

const evidenceTitle = (evidence: QuestionEvidence) => {
  if (evidence.kind === "figure") {
    return evidence.figure?.title ?? evidence.path
  }
  if (evidence.kind === "publication") {
    return evidence.publication?.title ?? evidence.path
  }
  return evidence.result?.title ?? evidence.path
}

function StaleBadge({ evidence }: { evidence: QuestionEvidence }) {
  const frozen = evidence.stale_reason === "frozen"
  return (
    <Tooltip label={STALE_TIPS[evidence.stale_reason ?? "pipeline"]}>
      <Badge colorScheme="orange" fontSize="2xs" flexShrink={0}>
        {frozen ? "Frozen" : "Stale"}
      </Badge>
    </Tooltip>
  )
}

/** One evidence item in the question's grid.
 *
 * A card opens the item in place rather than linking away: the question is
 * what the reader is in the middle of, and leaving the page to look at a
 * figure means coming back to find it again.
 */
function EvidenceCard({
  evidence,
  accountName,
  projectName,
  gitRef,
  onOpen,
}: {
  evidence: QuestionEvidence
  accountName: string
  projectName: string
  gitRef?: string
  onOpen: () => void
}) {
  const defaultBorderColor = useColorModeValue("gray.200", "gray.600")
  const staleBorderColor = useColorModeValue("orange.400", "orange.300")
  const bg = useColorModeValue("white", "gray.800")
  const subtleColor = useColorModeValue("gray.600", "gray.400")
  const stale = isEvidenceStale(evidence)
  // A cited value is the whole artifact -- there is nothing to open that the
  // card doesn't already show -- so it links out to the file it was read
  // from instead of expanding, and names the stage that wrote it.
  const isValue = evidence.value != null
  const pathLabel = `${evidence.path}${evidence.key ? `:${evidence.key}` : ""}`
  const pathLine = isValue ? (
    <Link
      as={RouterLink}
      to={`/${accountName}/${projectName}/${evidencePage(evidence)}`}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      search={
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        {
          path: evidence.path,
          ref: evidenceRefOf(evidence, gitRef),
        } as any
      }
      fontSize="xs"
      color={subtleColor}
      noOfLines={1}
    >
      {pathLabel} <Icon as={FaExternalLinkAlt} boxSize={2.5} />
    </Link>
  ) : (
    <Text fontSize="xs" color={subtleColor} noOfLines={1}>
      {pathLabel}
    </Text>
  )
  const stageLine =
    isValue && evidence.stage ? (
      <Flex align="center" gap={1} mt={1} fontSize="xs" color={subtleColor}>
        <Icon as={TiFlowMerge} flexShrink={0} />
        <Link
          as={RouterLink}
          to={`/${accountName}/${projectName}/pipeline`}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          search={
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            {
              stage: evidence.stage,
              ref: evidenceRefOf(evidence, gitRef),
            } as any
          }
        >
          <Code fontSize="2xs" cursor="pointer" noOfLines={1}>
            {evidence.stage}
          </Code>
        </Link>
      </Flex>
    ) : null
  const refBadge = evidence.git_ref ? (
    <Text fontSize="xs" color={subtleColor} noOfLines={1}>
      at {evidence.git_ref}
    </Text>
  ) : null
  let preview = null
  if (evidence.kind === "figure") {
    const fig = evidence.figure
    const ext = evidence.path.toLowerCase().split(".").pop() ?? ""
    const imgSrc =
      fig && ext in IMG_MIME
        ? fig.content
          ? `data:${IMG_MIME[ext]};base64,${fig.content}`
          : fig.url ?? undefined
        : undefined
    let thumb
    if (imgSrc) {
      // Raster/SVG images render directly for reliable, cheap thumbnails.
      thumb = (
        <Image
          src={imgSrc}
          alt={fig?.title ?? evidence.path}
          width="100%"
          height="100%"
          objectFit="contain"
        />
      )
    } else if (fig && (fig.content || fig.url)) {
      // Plotly JSON, PDFs, etc. go through the shared figure renderer.
      thumb = <FigureView figure={fig} fillHeight />
    } else {
      thumb = (
        <Flex height="100%" align="center" justify="center" color="gray.400">
          <Icon as={FaExternalLinkAlt} />
        </Flex>
      )
    }
    preview = (
      // pointerEvents off so a click hits the card, not the Plotly plot
      <Box height="150px" overflow="hidden" pointerEvents="none" mb={1}>
        {thumb}
      </Box>
    )
  } else if (evidence.value != null) {
    preview = (
      <Text fontSize="3xl" fontWeight="bold" lineHeight="1.1" noOfLines={1}>
        {evidence.value}
      </Text>
    )
  }
  let icon = null
  if (evidence.kind === "table") {
    icon = <Icon as={FiGrid} color="gray.500" flexShrink={0} />
  } else if (evidence.kind === "publication") {
    icon = <Icon as={FaRegFileAlt} color="gray.500" flexShrink={0} />
  }
  const body = (
    <>
      {preview}
      <Flex align="center" gap={1.5}>
        {icon}
        <Text fontSize="sm" fontWeight="semibold" noOfLines={1}>
          <Markdown inline>{evidenceTitle(evidence)}</Markdown>
        </Text>
        {stale ? <StaleBadge evidence={evidence} /> : null}
      </Flex>
      {pathLine}
      {stageLine}
      {refBadge}
      {evidence.explanation ? (
        <Box fontSize="xs" color={subtleColor} mt={1}>
          <Markdown noOfLines={3} foldedProse>
            {evidence.explanation}
          </Markdown>
        </Box>
      ) : null}
    </>
  )
  const cardProps = {
    textAlign: "left" as const,
    // A stale item keeps its place in the grid but says so at a glance,
    // since the whole card is what the answer is leaning on. Color rather
    // than a thicker border, so nothing shifts when a card goes stale.
    borderWidth: 1,
    borderColor: stale ? staleBorderColor : defaultBorderColor,
    borderRadius: "md",
    overflow: "hidden",
    bg,
    p: 3,
  }
  // A value card holds links of its own and has nothing more to show when
  // opened, so it isn't a button.
  if (isValue) {
    return <Box {...cardProps}>{body}</Box>
  }
  return (
    <Box
      as="button"
      type="button"
      onClick={onOpen}
      _hover={{ shadow: "md" }}
      {...cardProps}
    >
      {body}
    </Box>
  )
}

/** The full view of one evidence item, inside the question modal.
 *
 * Mounted only while an item is open, so the listings a table or publication
 * needs its content from are fetched when someone actually looks at one, and
 * at that item's own ref rather than the page's.
 */
function EvidenceDetail({
  evidence,
  accountName,
  projectName,
  gitRef,
}: {
  evidence: QuestionEvidence
  accountName: string
  projectName: string
  gitRef?: string
}) {
  const ref = evidenceRefOf(evidence, gitRef)
  // Evidence carries its figure's content already, but a table's rows and a
  // publication's PDF come from the listings, which is where content is
  // resolved. Both are gated so only the kind on screen is fetched.
  const { tablesRequest } = useProjectTables(
    accountName,
    projectName,
    ref,
    true,
    evidence.kind === "table",
  )
  const { publicationsRequest } = useProjectPublications(
    accountName,
    projectName,
    ref,
    evidence.kind === "publication",
  )
  if (evidence.kind === "figure") {
    if (!evidence.figure) {
      return <NotFound evidence={evidence} />
    }
    return (
      <Flex direction="column" height="100%" minH={0}>
        <Box flex="1" minH={0}>
          <FigureView figure={evidence.figure} fillHeight />
        </Box>
        {evidence.figure.description ? (
          <Box mt={2} fontSize="sm">
            <Markdown foldedProse>{evidence.figure.description}</Markdown>
          </Box>
        ) : null}
      </Flex>
    )
  }
  if (evidence.kind === "table") {
    if (tablesRequest.isPending) {
      return <LoadingSpinner height="200px" />
    }
    const table = tablesRequest.data?.find((t) => t.path === evidence.path)
    if (!table) {
      return <NotFound evidence={evidence} />
    }
    return <TableView table={table} maxHeight="calc(92vh - 300px)" />
  }
  if (evidence.kind === "publication") {
    if (publicationsRequest.isPending) {
      return <LoadingSpinner height="200px" />
    }
    const pub = publicationsRequest.data?.find((p) => p.path === evidence.path)
    if (!pub) {
      return <NotFound evidence={evidence} />
    }
    return (
      <Box height="100%">
        <PublicationView publication={pub} />
      </Box>
    )
  }
  // A result: the value it was cited for is the whole point of it, so that's
  // what gets the room. The file behind it is a click away in the header.
  return (
    <Box>
      {evidence.value != null ? (
        <Text fontSize="5xl" fontWeight="bold" lineHeight="1.1">
          {evidence.value}
        </Text>
      ) : (
        <NotFound evidence={evidence} />
      )}
      {evidence.result?.description ? (
        <Box mt={2} fontSize="sm">
          <Markdown foldedProse>{evidence.result.description}</Markdown>
        </Box>
      ) : null}
    </Box>
  )
}

function NotFound({ evidence }: { evidence: QuestionEvidence }) {
  return (
    <Text fontSize="sm" color="gray.500">
      Nothing was found at {evidence.path}
      {evidence.git_ref ? ` at ${evidence.git_ref}` : ""}. It may not have been
      run or pushed yet.
    </Text>
  )
}

/** The discussion on one question.
 *
 * Questions are the one artifact identified by number rather than path, so
 * that number is what a comment hangs off of. Everything else about the
 * thread -- replies, resolving, GitHub issues -- is the shared panel.
 */
function QuestionComments({
  accountName,
  projectName,
  questionNumber,
  gitRef,
}: {
  accountName: string
  projectName: string
  questionNumber: number
  gitRef?: string
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [showResolved, setShowResolved] = useState(false)
  const artifactPath = String(questionNumber)
  const commentsKey = [
    "projects",
    accountName,
    projectName,
    "comments",
    "question",
    artifactPath,
  ]
  const commentsQuery = useQuery({
    queryKey: commentsKey,
    queryFn: () =>
      ProjectsService.getProjectComments({
        owner_name: accountName,
        project_name: projectName,
        artifact_type: "question",
        artifact_path: artifactPath,
      }).then((response) => response.data),
  })
  const invalidateComments = () =>
    queryClient.invalidateQueries({ queryKey: commentsKey })
  const postCommentMutation = useMutation({
    mutationFn: (vars: { body: string; createIssue: boolean }) =>
      ProjectsService.postProjectComment({
        owner_name: accountName,
        project_name: projectName,
        projectCommentPost: {
          artifact_path: artifactPath,
          artifact_type: "question",
          comment: vars.body,
          create_github_issue: vars.createIssue,
          git_ref: gitRef ?? null,
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
  const resolveCommentMutation = useMutation({
    mutationFn: (vars: { commentId: string; resolved: boolean }) =>
      ProjectsService.patchProjectComment({
        owner_name: accountName,
        project_name: projectName,
        comment_id: vars.commentId,
        projectCommentPatch: { resolved: vars.resolved },
      }).then((response) => response.data),
    onSuccess: invalidateComments,
  })
  const comments = commentsQuery.data ?? []
  return (
    <CommentsPanel
      comments={comments.map(projectCommentToPanelComment)}
      isLoading={commentsQuery.isPending}
      canComment={!!user}
      canResolve={!!user}
      showResolved={showResolved}
      onShowResolvedChange={setShowResolved}
      showCreateIssueCheckbox
      heading="Discussion"
      emptyText="No comments on this question yet."
      onPostComment={(body, opts) =>
        postCommentMutation.mutateAsync({
          body,
          createIssue: opts.createIssue,
        })
      }
      postingComment={postCommentMutation.isPending}
      onPostReply={(parentId, body) =>
        replyCommentMutation.mutateAsync({ commentId: parentId, body })
      }
      postingReplyForId={
        replyCommentMutation.isPending
          ? replyCommentMutation.variables?.commentId ?? null
          : null
      }
      onResolve={(id, resolved) =>
        resolveCommentMutation.mutate({ commentId: id, resolved })
      }
      resolvingId={
        resolveCommentMutation.isPending
          ? resolveCommentMutation.variables?.commentId ?? null
          : null
      }
    />
  )
}

interface QuestionModalProps {
  question: QuestionPublic | null
  isOpen: boolean
  onClose: () => void
  accountName: string
  projectName: string
  gitRef?: string
  // Index of the evidence item being viewed, or undefined for the question
  // itself. In the URL, so a link reproduces what's on screen.
  evidenceIndex?: number
  onEvidenceIndexChange: (index?: number) => void
  onEdit?: () => void
  // Step to the neighboring question; undefined at either end of the list.
  onPrevQuestion?: () => void
  onNextQuestion?: () => void
}

/** The detail view of one question: its hypothesis, answer, and evidence.
 *
 * A modal rather than an expanding row because a real answer with its
 * evidence is bigger than a list item, and because the evidence is worth
 * looking at rather than just naming.
 */
function QuestionModal({
  question,
  isOpen,
  onClose,
  accountName,
  projectName,
  gitRef,
  evidenceIndex,
  onEvidenceIndexChange,
  onEdit,
  onPrevQuestion,
  onNextQuestion,
}: QuestionModalProps) {
  const subtleColor = useColorModeValue("gray.600", "gray.400")
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const evidence = question?.evidence ?? []
  const openEvidence =
    evidenceIndex !== undefined ? evidence[evidenceIndex] : undefined
  const openRef = openEvidence ? evidenceRefOf(openEvidence, gitRef) : undefined
  const evidenceCount = evidence.length
  // Left and right step through whatever is on screen: the evidence items
  // when one is open, the questions themselves otherwise. Both are also
  // buttons in the header, since a keyboard shortcut nobody is told about
  // isn't a way to get around.
  useEffect(() => {
    if (!isOpen) {
      return
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return
      }
      // Never steal an arrow from someone typing, e.g. in the comment box.
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return
      }
      const back = event.key === "ArrowLeft"
      if (evidenceIndex !== undefined) {
        const next = evidenceIndex + (back ? -1 : 1)
        if (next >= 0 && next < evidenceCount) {
          onEvidenceIndexChange(next)
        }
        return
      }
      const step = back ? onPrevQuestion : onNextQuestion
      step?.()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [
    isOpen,
    evidenceIndex,
    evidenceCount,
    onEvidenceIndexChange,
    onPrevQuestion,
    onNextQuestion,
  ])
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="6xl"
      scrollBehavior="inside"
      isCentered
    >
      <ModalOverlay />
      {/* Fixed height so stepping between evidence items doesn't resize the
          dialog under the reader's cursor */}
      <ModalContent maxW={{ base: "100%", lg: "72vw" }} h="88vh" maxH="88vh">
        {/* Right padding clears the close button, so the header's own
            buttons don't end up crowded against it */}
        <ModalHeader pb={2} pr={20}>
          {openEvidence ? (
            <Flex align="center" gap={2}>
              <IconButton
                aria-label="Back to question"
                icon={<FaArrowLeft />}
                size="sm"
                variant="ghost"
                onClick={() => onEvidenceIndexChange(undefined)}
              />
              <IconButton
                aria-label="Previous evidence"
                icon={<FaChevronLeft />}
                size="sm"
                variant="ghost"
                isDisabled={(evidenceIndex ?? 0) <= 0}
                onClick={() => onEvidenceIndexChange((evidenceIndex ?? 0) - 1)}
              />
              <IconButton
                aria-label="Next evidence"
                icon={<FaChevronRight />}
                size="sm"
                variant="ghost"
                isDisabled={(evidenceIndex ?? 0) >= evidence.length - 1}
                onClick={() => onEvidenceIndexChange((evidenceIndex ?? 0) + 1)}
              />
              <Box minW={0}>
                <Flex align="center" gap={2} minW={0}>
                  <Heading size="md" noOfLines={1}>
                    <Markdown inline>{evidenceTitle(openEvidence)}</Markdown>
                  </Heading>
                  {isEvidenceStale(openEvidence) ? (
                    <StaleBadge evidence={openEvidence} />
                  ) : null}
                </Flex>
                <Flex align="center" gap={3} fontSize="xs" color={subtleColor}>
                  <Link
                    as={RouterLink}
                    to={`/${accountName}/${projectName}/${evidencePage(
                      openEvidence,
                    )}`}
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    search={
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      { path: openEvidence.path, ref: openRef } as any
                    }
                  >
                    {openEvidence.path}
                    {openEvidence.key ? `:${openEvidence.key}` : ""}{" "}
                    <Icon as={FaExternalLinkAlt} boxSize={2.5} />
                  </Link>
                  {openEvidence.git_ref ? (
                    <Text as="span">at {openEvidence.git_ref}</Text>
                  ) : null}
                </Flex>
              </Box>
            </Flex>
          ) : (
            <Flex align="center" gap={2}>
              <IconButton
                aria-label="Previous question"
                icon={<FaChevronLeft />}
                size="sm"
                variant="ghost"
                isDisabled={!onPrevQuestion}
                onClick={onPrevQuestion}
              />
              <IconButton
                aria-label="Next question"
                icon={<FaChevronRight />}
                size="sm"
                variant="ghost"
                isDisabled={!onNextQuestion}
                onClick={onNextQuestion}
              />
              <Box minW={0} flex="1" sx={{ "& p": { my: 0 } }}>
                <Heading size="md" as="div">
                  <Markdown>
                    {`${question?.number}. ${question?.question ?? ""}`}
                  </Markdown>
                </Heading>
              </Box>
            </Flex>
          )}
        </ModalHeader>
        <ModalCloseButton />
        {/* Up on the close button's row rather than in the title, so the
            question keeps the full width of the header */}
        {onEdit && !openEvidence ? (
          <IconButton
            aria-label="Edit question"
            icon={<MdEdit />}
            size="sm"
            variant="ghost"
            position="absolute"
            top={2}
            insetEnd={12}
            onClick={onEdit}
          />
        ) : null}
        <ModalBody pt={0} pb={4}>
          {openEvidence ? (
            <Box height="100%">
              {openEvidence.explanation ? (
                <Box fontSize="sm" color={subtleColor} mb={3}>
                  <Markdown foldedProse>{openEvidence.explanation}</Markdown>
                </Box>
              ) : null}
              <EvidenceDetail
                // Remount per item so a viewer's own state (a table's search,
                // a PDF's page) belongs to the item on screen.
                key={`${openEvidence.kind}:${openEvidence.path}:${evidenceIndex}`}
                evidence={openEvidence}
                accountName={accountName}
                projectName={projectName}
                gitRef={gitRef}
              />
            </Box>
          ) : (
            // The answer and the discussion of it are what's read, so they
            // get the width; the evidence is what's glanced at and clicked,
            // so it sits in a column beside them.
            <Flex
              direction={{ base: "column", md: "row" }}
              align="flex-start"
              gap={6}
            >
              <Box flex="2" minW={0} w="100%">
                {question?.hypothesis ? (
                  <Box mb={4}>
                    <Text fontSize="xs" fontWeight="bold" color={subtleColor}>
                      Hypothesis
                    </Text>
                    <Box mt={1}>
                      <Markdown foldedProse>{question.hypothesis}</Markdown>
                    </Box>
                  </Box>
                ) : null}
                {question?.answer ? (
                  <Box mb={4}>
                    <Text fontSize="xs" fontWeight="bold" color={subtleColor}>
                      Answer
                    </Text>
                    <Box mt={1}>
                      <Markdown foldedProse>{question.answer}</Markdown>
                    </Box>
                  </Box>
                ) : (
                  <Text fontSize="sm" color={subtleColor} mb={4}>
                    Not yet answered.
                  </Text>
                )}
                {question ? (
                  // Set off from the answer rather than running on from it:
                  // what the project concluded and what people are saying
                  // about it are different things.
                  <Box bg={secBgColor} borderRadius="lg" px={4} py={3} mt={6}>
                    <QuestionComments
                      // Per question, so switching questions doesn't carry a
                      // half-written comment onto the next one.
                      key={question.number}
                      accountName={accountName}
                      projectName={projectName}
                      questionNumber={question.number}
                      gitRef={gitRef}
                    />
                  </Box>
                ) : null}
              </Box>
              <Box flex="1" minW={0} w="100%">
                <Text fontSize="xs" fontWeight="bold" color={subtleColor}>
                  Evidence
                </Text>
                {evidence.length ? (
                  <SimpleGrid columns={1} spacing={3} mt={2}>
                    {evidence.map((ev, i) => (
                      <EvidenceCard
                        key={`${ev.kind}:${ev.path}:${i}`}
                        evidence={ev}
                        accountName={accountName}
                        projectName={projectName}
                        gitRef={gitRef}
                        onOpen={() => onEvidenceIndexChange(i)}
                      />
                    ))}
                  </SimpleGrid>
                ) : (
                  <Text fontSize="sm" color={subtleColor} mt={1}>
                    None linked yet.
                  </Text>
                )}
              </Box>
            </Flex>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default QuestionModal
