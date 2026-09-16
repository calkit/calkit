import {
  Avatar,
  Box,
  Button,
  Checkbox,
  Divider,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  Icon,
  IconButton,
  Input,
  Link,
  Spinner,
  Switch,
  Text,
  Textarea,
  VStack,
  useColorModeValue,
} from "@chakra-ui/react"
import { ExternalLinkIcon } from "@chakra-ui/icons"
import { type ReactNode, useState } from "react"
import { FaCheck, FaGithub, FaReply, FaUndo } from "react-icons/fa"

import type { ProjectComment } from "../../client"
import LoadingSpinner from "./LoadingSpinner"

// Normalized comment shape the panel renders, independent of which backend
// (ProjectComment vs ReleaseComment) produced it. Callers map their SDK type
// into this and back in the mutation callbacks.
export interface PanelComment {
  id: string
  parentId: string | null
  authorName: string | null
  comment: string
  created: string | null
  resolved: string | null
  externalUrl: string | null
  // Set when the comment is anchored to a highlight (e.g. a PDF selection).
  hasHighlight?: boolean
  // Pre-extracted highlight text to quote in the card, if any.
  highlightText?: string | null
}

// Map a ProjectComment (figures, publications, presentations, member releases)
// into the panel's normalized shape.
export function projectCommentToPanelComment(c: ProjectComment): PanelComment {
  const highlight = c.highlight as { content?: { text?: string } } | null
  return {
    id: c.id ?? "",
    parentId: c.parent_id ?? null,
    authorName: c.user_full_name ?? c.user_github_username ?? null,
    comment: c.comment,
    created: c.created ?? null,
    resolved: c.resolved ?? null,
    externalUrl: c.external_url ?? null,
    hasHighlight: !!c.highlight,
    highlightText: highlight?.content?.text ?? null,
  }
}

interface CommentsPanelProps {
  comments: PanelComment[]
  isLoading?: boolean
  // Capabilities.
  canComment: boolean
  // Defaults to canComment when omitted.
  canReply?: boolean
  canResolve?: boolean
  // Hide-resolved-by-default state, owned by the caller (so it can live in a
  // query param).
  showResolved: boolean
  onShowResolvedChange: (showResolved: boolean) => void
  // Optional anonymous-author name field (release share-link viewers).
  askAuthorName?: boolean
  // Optional "Commenting as x" attribution line.
  commentingAsLabel?: string | null
  // Optional "Create GitHub issue" checkbox (member project comments).
  showCreateIssueCheckbox?: boolean
  // Called when a comment anchored to a highlight is clicked.
  onHighlightClick?: (comment: PanelComment) => void
  // Mutations -- the caller wires the SDK call and query invalidation.
  onPostComment: (
    body: string,
    opts: { authorName: string | null; createIssue: boolean },
  ) => void | Promise<unknown>
  postingComment?: boolean
  onPostReply: (
    parentId: string,
    body: string,
    opts: { authorName: string | null },
  ) => void | Promise<unknown>
  postingReplyForId?: string | null
  onResolve?: (id: string, resolved: boolean) => void
  resolvingId?: string | null
  // Copy.
  heading?: string
  emptyText?: string
  composerPlaceholder?: string
  addCommentLabel?: string
  postLabel?: string
  viewOnlyText?: ReactNode
  // PDF panels fill their column and scroll; inline panels size to content.
  fillHeight?: boolean
}

// A single comment thread UI, shared across figures, publications,
// presentations, and releases. Owns only ephemeral composer state (which reply
// box is open, drafts); all data and persistence flow through props.
export default function CommentsPanel({
  comments,
  isLoading,
  canComment,
  canReply,
  canResolve,
  showResolved,
  onShowResolvedChange,
  askAuthorName,
  commentingAsLabel,
  showCreateIssueCheckbox,
  onHighlightClick,
  onPostComment,
  postingComment,
  onPostReply,
  postingReplyForId,
  onResolve,
  resolvingId,
  heading = "Comments",
  emptyText = "No comments yet.",
  composerPlaceholder = "Leave a comment",
  addCommentLabel = "+ Add comment",
  postLabel = "Post comment",
  viewOnlyText = "This is view-only.",
  fillHeight,
}: CommentsPanelProps) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const [replyingToId, setReplyingToId] = useState<string | null>(null)
  const [replyDraft, setReplyDraft] = useState("")
  const [addingComment, setAddingComment] = useState(false)
  const [newDraft, setNewDraft] = useState("")
  const [createIssue, setCreateIssue] = useState(true)
  const [authorName, setAuthorName] = useState("")
  const replyEnabled = canReply ?? canComment
  const openCount = comments.filter((c) => !c.resolved).length
  const topLevel = comments.filter((c) => !c.parentId)
  const repliesFor = (parentId: string) =>
    comments.filter((c) => c.parentId === parentId)
  const visible = showResolved ? topLevel : topLevel.filter((c) => !c.resolved)
  const submitNew = async () => {
    if (!newDraft.trim()) return
    try {
      await onPostComment(newDraft.trim(), {
        authorName: authorName.trim() || null,
        createIssue,
      })
      setNewDraft("")
      setAddingComment(false)
    } catch {
      // Keep the draft so the user can retry; the error toast is shown by the
      // caller's mutation.
    }
  }
  const submitReply = async (parentId: string) => {
    if (!replyDraft.trim()) return
    try {
      await onPostReply(parentId, replyDraft.trim(), {
        authorName: authorName.trim() || null,
      })
      setReplyDraft("")
      setReplyingToId(null)
    } catch {
      // Keep the draft for retry.
    }
  }
  const renderCard = (c: PanelComment, isReply: boolean) => {
    const isResolved = !!c.resolved
    const clickable = !!(onHighlightClick && c.hasHighlight)
    return (
      <Flex key={c.id} gap={2}>
        <Avatar
          name={c.authorName ?? undefined}
          size="xs"
          mt={0.5}
          flexShrink={0}
        />
        <Box
          flex={1}
          borderWidth={1}
          borderColor={isResolved ? "green.200" : borderColor}
          borderRadius="md"
          p={isReply ? 2 : 3}
          opacity={isResolved ? 0.7 : 1}
          cursor={clickable ? "pointer" : "default"}
          _hover={clickable ? { borderColor: "yellow.400" } : undefined}
          onClick={() => clickable && onHighlightClick?.(c)}
        >
          <Flex align="center" gap={1} mb={1} wrap="wrap">
            <Text fontSize="xs" fontWeight="bold" mr={1}>
              {c.authorName || "Anonymous"}
            </Text>
            <Text fontSize="xs" color="gray.500" mr="auto">
              {c.created ? new Date(c.created).toLocaleDateString() : ""}
            </Text>
            {c.externalUrl && (
              <Link
                href={c.externalUrl}
                isExternal
                color="gray.500"
                onClick={(e) => e.stopPropagation()}
              >
                <Flex align="center" gap={0.5}>
                  <Icon as={FaGithub} boxSize={3} />
                  <ExternalLinkIcon boxSize={2.5} />
                </Flex>
              </Link>
            )}
            {canResolve &&
              onResolve &&
              !isReply &&
              (resolvingId === c.id ? (
                <Spinner size="xs" color="ui.main" />
              ) : (
                <IconButton
                  aria-label={isResolved ? "Unresolve" : "Resolve"}
                  icon={isResolved ? <FaUndo /> : <FaCheck />}
                  size="xs"
                  variant="ghost"
                  colorScheme={isResolved ? "gray" : "green"}
                  onClick={(e) => {
                    e.stopPropagation()
                    onResolve(c.id, !isResolved)
                  }}
                />
              ))}
          </Flex>
          {c.highlightText && (
            <Box
              mb={1}
              pl={2}
              borderLeftWidth={2}
              borderColor="yellow.400"
              fontSize="xs"
              color="gray.500"
              fontStyle="italic"
              noOfLines={2}
            >
              {c.highlightText}
            </Box>
          )}
          <Text fontSize="sm" whiteSpace="pre-wrap">
            {c.comment}
          </Text>
        </Box>
      </Flex>
    )
  }
  const renderThread = (c: PanelComment) => {
    const replies = repliesFor(c.id)
    return (
      <Box key={c.id}>
        {renderCard(c, false)}
        {replies.length > 0 && (
          <VStack align="stretch" spacing={1} mt={1} ml={6}>
            {replies.map((r) => renderCard(r, true))}
          </VStack>
        )}
        {replyEnabled && (
          <Box mt={1} ml={6}>
            {replyingToId === c.id ? (
              <Box onClick={(e) => e.stopPropagation()}>
                <Textarea
                  size="xs"
                  placeholder="Add a reply…"
                  value={replyDraft}
                  autoFocus
                  onChange={(e) => setReplyDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault()
                      submitReply(c.id)
                    }
                  }}
                  rows={2}
                  mb={1}
                />
                <Flex align="center" gap={3} mb={2}>
                  <Button
                    size="xs"
                    variant="primary"
                    isDisabled={!replyDraft.trim()}
                    isLoading={postingReplyForId === c.id}
                    onClick={() => submitReply(c.id)}
                  >
                    Post
                  </Button>
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() => {
                      setReplyingToId(null)
                      setReplyDraft("")
                    }}
                  >
                    Cancel
                  </Button>
                </Flex>
              </Box>
            ) : (
              <Button
                size="xs"
                variant="ghost"
                leftIcon={<Icon as={FaReply} />}
                onClick={(e) => {
                  e.stopPropagation()
                  setReplyingToId(c.id)
                  setReplyDraft("")
                }}
              >
                Reply
              </Button>
            )}
          </Box>
        )}
      </Box>
    )
  }
  return (
    <Flex direction="column" h={fillHeight ? "100%" : undefined}>
      <Flex align="center" justify="space-between" mb={3}>
        <Heading size="sm">
          {heading} ({openCount} open)
        </Heading>
        <Flex align="center" gap={1}>
          <Text fontSize="xs" color="gray.500">
            Resolved
          </Text>
          <Switch
            size="sm"
            isChecked={showResolved}
            onChange={(e) => onShowResolvedChange(e.target.checked)}
          />
        </Flex>
      </Flex>
      <VStack
        align="stretch"
        spacing={2}
        flex={fillHeight ? 1 : undefined}
        overflowY={fillHeight ? "auto" : undefined}
        mb={3}
      >
        {isLoading ? (
          <LoadingSpinner height="80px" />
        ) : visible.length === 0 ? (
          <Text fontSize="sm" color="gray.500">
            {comments.length === 0 ? emptyText : "No open comments."}
          </Text>
        ) : (
          visible.map((c) => renderThread(c))
        )}
      </VStack>
      {canComment ? (
        <Box>
          <Divider mb={3} />
          {commentingAsLabel && (
            <Text fontSize="xs" color="gray.500" mb={2}>
              Commenting as {commentingAsLabel}
            </Text>
          )}
          {askAuthorName && (
            <FormControl mb={2}>
              <FormLabel fontSize="sm" mb={1}>
                Name (optional)
              </FormLabel>
              <Input
                autoComplete="off"
                size="sm"
                value={authorName}
                onChange={(e) => setAuthorName(e.target.value)}
                placeholder="Your name"
              />
            </FormControl>
          )}
          {!addingComment ? (
            <Button
              size="xs"
              variant="ghost"
              w="100%"
              onClick={() => setAddingComment(true)}
            >
              {addCommentLabel}
            </Button>
          ) : (
            <Box>
              <Textarea
                size="sm"
                placeholder={composerPlaceholder}
                value={newDraft}
                autoFocus
                onChange={(e) => setNewDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault()
                    submitNew()
                  }
                }}
                rows={3}
                mb={2}
              />
              {showCreateIssueCheckbox && (
                <Checkbox
                  size="sm"
                  mb={3}
                  isChecked={createIssue}
                  onChange={(e) => setCreateIssue(e.target.checked)}
                >
                  Create GitHub issue
                </Checkbox>
              )}
              <Flex align="center" gap={2} mb={2}>
                <Button
                  size="sm"
                  variant="primary"
                  isDisabled={!newDraft.trim()}
                  isLoading={postingComment}
                  onClick={submitNew}
                >
                  {postLabel}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setAddingComment(false)
                    setNewDraft("")
                  }}
                >
                  Cancel
                </Button>
              </Flex>
            </Box>
          )}
        </Box>
      ) : (
        <Text fontSize="sm" color="gray.500">
          {viewOnlyText}
        </Text>
      )}
    </Flex>
  )
}
