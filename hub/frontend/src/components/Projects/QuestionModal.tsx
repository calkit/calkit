import {
  Box,
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
import { Link as RouterLink } from "@tanstack/react-router"
import { FaArrowLeft, FaChevronLeft, FaChevronRight } from "react-icons/fa"
import { FaExternalLinkAlt, FaRegFileAlt } from "react-icons/fa"
import { FiGrid } from "react-icons/fi"
import { MdEdit } from "react-icons/md"

import type { QuestionEvidence, QuestionPublic } from "../../client"
import {
  useProjectPublications,
  useProjectTables,
} from "../../hooks/useProject"
import LoadingSpinner from "../Common/LoadingSpinner"
import Markdown from "../Common/Markdown"
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

/** One evidence item in the question's grid.
 *
 * A card opens the item in place rather than linking away: the question is
 * what the reader is in the middle of, and leaving the page to look at a
 * figure means coming back to find it again.
 */
function EvidenceCard({
  evidence,
  onOpen,
}: {
  evidence: QuestionEvidence
  onOpen: () => void
}) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const bg = useColorModeValue("white", "gray.800")
  const subtleColor = useColorModeValue("gray.600", "gray.400")
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
  return (
    <Box
      as="button"
      type="button"
      textAlign="left"
      onClick={onOpen}
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="md"
      overflow="hidden"
      bg={bg}
      p={3}
      _hover={{ shadow: "md" }}
    >
      {preview}
      <Flex align="center" gap={1.5}>
        {icon}
        <Text fontSize="sm" fontWeight="semibold" noOfLines={1}>
          {evidenceTitle(evidence)}
        </Text>
      </Flex>
      <Text fontSize="xs" color={subtleColor} noOfLines={1}>
        {evidence.path}
        {evidence.key ? `:${evidence.key}` : ""}
      </Text>
      {refBadge}
      {evidence.explanation ? (
        <Box fontSize="xs" color={subtleColor} mt={1}>
          <Markdown noOfLines={3}>{evidence.explanation}</Markdown>
        </Box>
      ) : null}
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
      <Box height="100%">
        <FigureView figure={evidence.figure} fillHeight />
      </Box>
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
          <Markdown>{evidence.result.description}</Markdown>
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
}: QuestionModalProps) {
  const subtleColor = useColorModeValue("gray.600", "gray.400")
  const evidence = question?.evidence ?? []
  const openEvidence =
    evidenceIndex !== undefined ? evidence[evidenceIndex] : undefined
  const openRef = openEvidence ? evidenceRefOf(openEvidence, gitRef) : undefined
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
      <ModalContent maxW={{ base: "100%", lg: "92vw" }} h="92vh" maxH="92vh">
        <ModalHeader pb={2}>
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
                <Heading size="md" noOfLines={1}>
                  <Markdown inline>{evidenceTitle(openEvidence)}</Markdown>
                </Heading>
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
              <Box minW={0} flex="1" sx={{ "& p": { my: 0 } }}>
                <Heading size="md" as="div">
                  <Markdown>
                    {`${question?.number}. ${question?.question ?? ""}`}
                  </Markdown>
                </Heading>
              </Box>
              {onEdit ? (
                <IconButton
                  aria-label="Edit question"
                  icon={<MdEdit />}
                  size="sm"
                  variant="ghost"
                  onClick={onEdit}
                />
              ) : null}
            </Flex>
          )}
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pt={0} pb={4}>
          {openEvidence ? (
            <Box height="100%">
              {openEvidence.explanation ? (
                <Box fontSize="sm" color={subtleColor} mb={3}>
                  <Markdown>{openEvidence.explanation}</Markdown>
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
            <>
              {question?.hypothesis ? (
                <Box mb={4}>
                  <Text fontSize="xs" fontWeight="bold" color={subtleColor}>
                    Hypothesis
                  </Text>
                  <Box mt={1}>
                    <Markdown>{question.hypothesis}</Markdown>
                  </Box>
                </Box>
              ) : null}
              {question?.answer ? (
                <Box mb={4}>
                  <Text fontSize="xs" fontWeight="bold" color={subtleColor}>
                    Answer
                  </Text>
                  <Box mt={1}>
                    <Markdown>{question.answer}</Markdown>
                  </Box>
                </Box>
              ) : (
                <Text fontSize="sm" color={subtleColor} mb={4}>
                  Not yet answered.
                </Text>
              )}
              {evidence.length ? (
                <Box>
                  <Text fontSize="xs" fontWeight="bold" color={subtleColor}>
                    Evidence
                  </Text>
                  <SimpleGrid
                    columns={{ base: 1, md: 2, xl: 3 }}
                    spacing={3}
                    mt={2}
                  >
                    {evidence.map((ev, i) => (
                      <EvidenceCard
                        key={`${ev.kind}:${ev.path}:${i}`}
                        evidence={ev}
                        onOpen={() => onEvidenceIndexChange(i)}
                      />
                    ))}
                  </SimpleGrid>
                </Box>
              ) : (
                <Text fontSize="sm" color={subtleColor}>
                  No evidence linked yet.
                </Text>
              )}
            </>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default QuestionModal
