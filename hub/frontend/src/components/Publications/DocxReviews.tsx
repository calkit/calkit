import {
  Badge,
  Box,
  Button,
  ButtonGroup,
  Checkbox,
  Code,
  Flex,
  HStack,
  Heading,
  Icon,
  IconButton,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  VStack,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { useMemo, useRef, useState } from "react"
import { FaUpload } from "react-icons/fa"
import { FiFileText } from "react-icons/fi"

import {
  type LatexDocxComment,
  type LatexDocxEdit,
  type LatexReview,
  type LatexReviewPlan,
  ProjectsService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import Tooltip from "../Common/Tooltip"

interface DocxReviewsProps {
  ownerName: string
  projectName: string
  // The main .tex the publication is built from; reviews are listed for it
  source: string
  userHasWriteAccess: boolean
}

// A word-level diff of two paragraphs, as runs of equal, removed, and added
// words. Paragraphs are short, so the plain LCS table is fine.
type Run = { kind: "equal" | "del" | "ins"; text: string }

function wordDiff(a: string, b: string): Run[] {
  const aw = a.split(/\s+/).filter(Boolean)
  const bw = b.split(/\s+/).filter(Boolean)
  const n = aw.length
  const m = bw.length
  const lcs: number[][] = Array.from({ length: n + 1 }, () =>
    new Array(m + 1).fill(0),
  )
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] =
        aw[i] === bw[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const runs: Run[] = []
  const push = (kind: Run["kind"], word: string) => {
    const last = runs[runs.length - 1]
    if (last && last.kind === kind) last.text += ` ${word}`
    else runs.push({ kind, text: word })
  }
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (aw[i] === bw[j]) {
      push("equal", aw[i])
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      push("del", aw[i])
      i++
    } else {
      push("ins", bw[j])
      j++
    }
  }
  while (i < n) push("del", aw[i++])
  while (j < m) push("ins", bw[j++])
  return runs
}

function DiffText({ sent, proposed }: { sent: string; proposed: string }) {
  const runs = useMemo(() => wordDiff(sent, proposed), [sent, proposed])
  const delBg = useColorModeValue("red.100", "red.900")
  const insBg = useColorModeValue("green.100", "green.900")
  return (
    <Text fontSize="sm" lineHeight="tall">
      {runs.map((r, idx) =>
        r.kind === "equal" ? (
          <span key={idx}>{r.text} </span>
        ) : r.kind === "del" ? (
          <Box as="s" key={idx} bg={delBg} px={0.5} borderRadius="sm">
            {r.text}{" "}
          </Box>
        ) : (
          <Box as="span" key={idx} bg={insBg} px={0.5} borderRadius="sm">
            {r.text}{" "}
          </Box>
        ),
      )}
    </Text>
  )
}

const EDIT_STATUS: Record<string, { label: string; color: string }> = {
  applicable: { label: "Accepted in Word", color: "green" },
  pending: { label: "Tracked change", color: "orange" },
  "already-applied": { label: "Already in source", color: "gray" },
  unplaced: { label: "Apply by hand", color: "red" },
  rejected: { label: "Rejected", color: "gray" },
}

const COMMENT_STATUS: Record<string, { label: string; color: string }> = {
  new: { label: "New", color: "blue" },
  updated: { label: "Changed", color: "blue" },
  unchanged: { label: "In source", color: "gray" },
  unplaced: { label: "No anchor", color: "red" },
  dismissed: { label: "Dismissed", color: "gray" },
}

type Decision = "accept" | "reject" | undefined

interface TriageProps {
  ownerName: string
  projectName: string
  path: string
  isOpen: boolean
  onClose: () => void
  onMerged: () => void
}

function ReviewTriage({
  ownerName,
  projectName,
  path,
  isOpen,
  onClose,
  onMerged,
}: TriageProps) {
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [dismissed, setDismissed] = useState<Record<string, boolean>>({})
  const cardBg = useColorModeValue("gray.50", "whiteAlpha.50")
  const planQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "latex-reviews", path],
    queryFn: () =>
      ProjectsService.getProjectLatexReview({
        owner_name: ownerName,
        project_name: projectName,
        path,
      }).then((r) => r.data),
    enabled: isOpen,
  })
  const plan: LatexReviewPlan | undefined = planQuery.data
  const openEdits = (plan?.edits ?? []).filter(
    (e) => e.status === "applicable" || e.status === "pending",
  )
  const accept = openEdits
    .filter((e) => decisions[e.key] === "accept")
    .map((e) => e.key)
  const reject = openEdits
    .filter((e) => decisions[e.key] === "reject")
    .map((e) => e.key)
  const openComments = (plan?.comments ?? []).filter(
    (c) => c.status === "new" || c.status === "updated",
  )
  const dismiss = openComments.filter((c) => dismissed[c.key]).map((c) => c.key)
  const nDecisions = accept.length + reject.length + dismiss.length
  const commentsToWrite = openComments.length - dismiss.length
  const mergeMutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectLatexReviewMerge({
        owner_name: ownerName,
        project_name: projectName,
        path,
        latexReviewMergePost: { accept, reject, dismiss },
      }).then((r) => r.data),
    onSuccess: (result) => {
      const applied = (result.record.changes ?? []).filter(
        (c) => c.status === "applied",
      ).length
      const comments =
        (result.record.comments_added ?? 0) +
        (result.record.comments_updated ?? 0)
      showToast(
        result.commit ? "Merged" : "Nothing to merge",
        result.commit
          ? `${applied} edit${applied === 1 ? "" : "s"} applied and ${comments} comment${comments === 1 ? "" : "s"} written to the LaTeX source.`
          : "No changes were made.",
        "success",
      )
      setDecisions({})
      setDismissed({})
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "latex-reviews"],
      })
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "publications"],
      })
      onMerged()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const decideAll = (d: Decision) =>
    setDecisions(Object.fromEntries(openEdits.map((e) => [e.key, d])))
  const renderEdit = (e: LatexDocxEdit) => {
    const open = e.status === "applicable" || e.status === "pending"
    const status = EDIT_STATUS[e.status] ?? { label: e.status, color: "gray" }
    return (
      <Box key={e.key} bg={cardBg} borderRadius="md" p={3}>
        <Flex align="center" mb={2} gap={2} wrap="wrap">
          <Code fontSize="xs">
            {e.path}:{e.lineno}
          </Code>
          <Badge colorScheme={status.color}>{status.label}</Badge>
          {(e.authors ?? []).length > 0 && (
            <Text fontSize="xs" color="gray.500">
              {(e.authors ?? []).join(", ")}
            </Text>
          )}
          {open && (
            <ButtonGroup size="xs" isAttached ml="auto">
              <Button
                colorScheme={decisions[e.key] === "accept" ? "green" : "gray"}
                variant={decisions[e.key] === "accept" ? "solid" : "outline"}
                onClick={() =>
                  setDecisions((d) => ({
                    ...d,
                    [e.key]: d[e.key] === "accept" ? undefined : "accept",
                  }))
                }
              >
                Accept
              </Button>
              <Button
                colorScheme={decisions[e.key] === "reject" ? "red" : "gray"}
                variant={decisions[e.key] === "reject" ? "solid" : "outline"}
                onClick={() =>
                  setDecisions((d) => ({
                    ...d,
                    [e.key]: d[e.key] === "reject" ? undefined : "reject",
                  }))
                }
              >
                Reject
              </Button>
            </ButtonGroup>
          )}
        </Flex>
        <DiffText sent={e.sent} proposed={e.proposed} />
        {e.reason && (
          <Text fontSize="xs" color="red.400" mt={1}>
            {e.reason}. The source reads:
          </Text>
        )}
        {e.reason && (e.source ?? []).length > 0 && (
          <Code
            display="block"
            whiteSpace="pre-wrap"
            fontSize="xs"
            mt={1}
            p={2}
          >
            {(e.source ?? []).join("\n")}
          </Code>
        )}
      </Box>
    )
  }
  const renderComment = (c: LatexDocxComment) => {
    const open = c.status === "new" || c.status === "updated"
    const status = COMMENT_STATUS[c.status] ?? {
      label: c.status,
      color: "gray",
    }
    return (
      <Box key={c.key} bg={cardBg} borderRadius="md" p={3}>
        <Flex align="center" mb={2} gap={2} wrap="wrap">
          {c.path && (
            <Code fontSize="xs">
              {c.path}:{c.lineno}
            </Code>
          )}
          <Badge colorScheme={status.color}>{status.label}</Badge>
          {c.resolved && <Badge>Resolved</Badge>}
          {open && (
            <Checkbox
              size="sm"
              ml="auto"
              isChecked={!dismissed[c.key]}
              onChange={(ev) =>
                setDismissed((d) => ({ ...d, [c.key]: !ev.target.checked }))
              }
            >
              Write to source
            </Checkbox>
          )}
        </Flex>
        {c.highlight && (
          <Text fontSize="xs" color="gray.500" mb={1}>
            On: “{c.highlight}”
          </Text>
        )}
        <VStack align="stretch" spacing={1}>
          {c.entries.map((entry, idx) => (
            <Box key={idx} pl={idx > 0 ? 3 : 0}>
              <Text fontSize="xs" fontWeight="semibold">
                {entry.author}
                {entry.date && (
                  <Text as="span" fontWeight="normal" color="gray.500">
                    {" "}
                    {entry.date}
                  </Text>
                )}
              </Text>
              <Text fontSize="sm">{entry.text}</Text>
            </Box>
          ))}
        </VStack>
      </Box>
    )
  }
  return (
    <Modal isOpen={isOpen} onClose={onClose} size="4xl" scrollBehavior="inside">
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>
          <Text>Review {path.split("/").pop()}</Text>
          {plan && (
            <Text fontSize="sm" fontWeight="normal" color="gray.500">
              {plan.authors.length > 0
                ? `Marked up by ${plan.authors.join(", ")}`
                : "No tracked changes or comments"}
              {plan.last_modified_by &&
                `, last saved by ${plan.last_modified_by}`}
            </Text>
          )}
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          {planQuery.isPending ? (
            <Flex justify="center" py={8}>
              <Spinner />
            </Flex>
          ) : planQuery.isError ? (
            <Text color="red.400">
              This document can't be read against the current source.
            </Text>
          ) : plan ? (
            <VStack align="stretch" spacing={4}>
              {(plan.media_changed ?? []).length > 0 && (
                <Text fontSize="sm" color="orange.400">
                  Figures were changed in Word and can't be merged; edit the
                  pipeline instead: {(plan.media_changed ?? []).join(", ")}
                </Text>
              )}
              <Box>
                <Flex align="center" mb={2}>
                  <Heading size="sm">
                    Edits{" "}
                    <Text as="span" fontWeight="normal" color="gray.500">
                      ({openEdits.length} to decide)
                    </Text>
                  </Heading>
                  {openEdits.length > 1 && (
                    <ButtonGroup size="xs" variant="ghost" ml="auto">
                      <Button onClick={() => decideAll("accept")}>
                        Accept all
                      </Button>
                      <Button onClick={() => decideAll("reject")}>
                        Reject all
                      </Button>
                      <Button onClick={() => decideAll(undefined)}>
                        Clear
                      </Button>
                    </ButtonGroup>
                  )}
                </Flex>
                {plan.edits.length === 0 ? (
                  <Text fontSize="sm" color="gray.500">
                    No paragraphs were changed.
                  </Text>
                ) : (
                  <VStack align="stretch" spacing={2}>
                    {plan.edits.map(renderEdit)}
                  </VStack>
                )}
              </Box>
              <Box>
                <Heading size="sm" mb={2}>
                  Comments{" "}
                  <Text as="span" fontWeight="normal" color="gray.500">
                    ({openComments.length} to write)
                  </Text>
                </Heading>
                {plan.comments.length === 0 ? (
                  <Text fontSize="sm" color="gray.500">
                    No comments were left.
                  </Text>
                ) : (
                  <VStack align="stretch" spacing={2}>
                    {plan.comments.map(renderComment)}
                  </VStack>
                )}
              </Box>
              <Text fontSize="xs" color="gray.500">
                Accepted edits and comments are written to the LaTeX source as a
                commit. Rejected edits and dismissed comments won't be offered
                again. Anything left undecided stays open for later, here or
                with <Code fontSize="xs">calkit latex merge-docx</Code>.
              </Text>
            </VStack>
          ) : null}
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" mr={3} onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            isDisabled={!plan || (nDecisions === 0 && commentsToWrite === 0)}
            isLoading={mergeMutation.isPending}
            onClick={() => mergeMutation.mutate()}
          >
            Merge
            {nDecisions + commentsToWrite > 0 &&
              ` ${nDecisions + commentsToWrite} item${nDecisions + commentsToWrite === 1 ? "" : "s"}`}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default function DocxReviews({
  ownerName,
  projectName,
  source,
  userHasWriteAccess,
}: DocxReviewsProps) {
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const triage = useDisclosure()
  const [selected, setSelected] = useState<string | null>(null)
  const reviewsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "latex-reviews", { source }],
    queryFn: () =>
      ProjectsService.getProjectLatexReviews({
        owner_name: ownerName,
        project_name: projectName,
        source,
      }).then((r) => r.data),
    enabled: userHasWriteAccess,
  })
  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      ProjectsService.postProjectLatexReview({
        owner_name: ownerName,
        project_name: projectName,
        bodyProjectsPostProjectLatexReview: { file },
      }).then((r) => r.data),
    onSuccess: (plan) => {
      showToast(
        "Review added",
        `${plan.path} was saved to the project. ${plan.open_edits} edit${plan.open_edits === 1 ? "" : "s"} and ${plan.open_comments} comment${plan.open_comments === 1 ? "" : "s"} to go through.`,
        "success",
      )
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "latex-reviews"],
      })
      setSelected(plan.path)
      triage.onOpen()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  if (!userHasWriteAccess) return null
  const reviews: LatexReview[] = reviewsQuery.data ?? []
  return (
    <Box>
      <Flex align="center" mb={1}>
        <Heading size="sm">Word reviews</Heading>
        <Tooltip label="Upload a reviewed Word copy of this document">
          <IconButton
            aria-label="Upload reviewed Word document"
            icon={<FaUpload />}
            size="xs"
            variant="primary"
            ml={2}
            isLoading={uploadMutation.isPending}
            onClick={() => fileInput.current?.click()}
          />
        </Tooltip>
        <input
          ref={fileInput}
          type="file"
          accept=".docx"
          hidden
          onChange={(ev) => {
            const file = ev.target.files?.[0]
            if (file) uploadMutation.mutate(file)
            ev.target.value = ""
          }}
        />
      </Flex>
      {reviewsQuery.isPending ? (
        <Spinner size="sm" />
      ) : reviews.length === 0 ? (
        <Text fontSize="xs" color="gray.500">
          Export with <Code fontSize="xs">calkit latex to-docx</Code>, send it
          around, and upload what comes back.
        </Text>
      ) : (
        <VStack align="stretch" spacing={1}>
          {reviews.map((r) => {
            const open = r.open_edits + r.open_comments
            return (
              <HStack
                key={r.path}
                spacing={2}
                cursor="pointer"
                _hover={{ color: "blue.500" }}
                onClick={() => {
                  setSelected(r.path)
                  triage.onOpen()
                }}
              >
                <Icon as={FiFileText} flexShrink={0} />
                <Box minW={0}>
                  <Text fontSize="sm" noOfLines={1}>
                    {r.path.split("/").pop()}
                  </Text>
                  <Text fontSize="xs" color="gray.500" noOfLines={1}>
                    {r.authors.length > 0 ? r.authors.join(", ") : "No markup"}
                  </Text>
                </Box>
                <Badge
                  ml="auto"
                  flexShrink={0}
                  colorScheme={open > 0 ? "orange" : "green"}
                >
                  {open > 0 ? `${open} open` : "Done"}
                </Badge>
              </HStack>
            )
          })}
        </VStack>
      )}
      {selected && (
        <ReviewTriage
          ownerName={ownerName}
          projectName={projectName}
          path={selected}
          isOpen={triage.isOpen}
          onClose={triage.onClose}
          onMerged={() => {}}
        />
      )}
    </Box>
  )
}
