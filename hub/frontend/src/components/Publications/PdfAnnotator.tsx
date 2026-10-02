/**
 * PDF viewer with text-highlight annotation support.
 *
 * Highlights and comments are stored in the database via the
 * project comments API. The highlight JSON is kept in a portable format
 * (react-pdf-highlighter's ScaledPosition + content.text) so it can later be
 * serialised to git objects and synced to external trackers without a schema
 * change.
 */
import {
  Avatar,
  Box,
  Button,
  Checkbox,
  Flex,
  Icon,
  IconButton,
  Link,
  Spinner,
  Text,
  Textarea,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  type MutableRefObject,
  type ReactElement,
  type ReactNode,
  useCallback,
  useMemo,
  useState,
} from "react"
import {
  AreaHighlight,
  Highlight,
  type IHighlight,
  type NewHighlight,
  Popup,
} from "react-pdf-highlighter"
import "react-pdf-highlighter/dist/style.css"
import { ExternalLinkIcon } from "@chakra-ui/icons"
import { FaCheck, FaGithub, FaUndo } from "react-icons/fa"

import {
  type CommentHighlight,
  type ProjectComment,
  ProjectsService,
} from "../../client"
import useAuth from "../../hooks/useAuth"
import PdfDocumentViewer, {
  type HighlightTransform,
  type OnSelectionFinished,
  type PdfDocumentViewerProps,
} from "../Common/PdfDocumentViewer"

// ---------------------------------------------------------------------------
// Highlight shape that extends IHighlight with our DB id / comment body
// ---------------------------------------------------------------------------
export interface AnnotationHighlight extends IHighlight {
  dbId: string
  commentBody: string
  authorName: string | null
  createdAt: string
  resolved: boolean
  externalUrl: string | null
}

export function commentToHighlight(
  c: ProjectComment,
): AnnotationHighlight | null {
  if (!c.highlight || !c.id) return null
  const h = c.highlight as unknown as {
    position: IHighlight["position"]
    content: IHighlight["content"]
  }
  if (!h.position) return null
  return {
    id: c.id,
    dbId: c.id,
    position: h.position,
    content: h.content ?? {},
    comment: { text: c.comment, emoji: "" },
    commentBody: c.comment,
    authorName: c.user_full_name ?? c.user_github_username ?? null,
    createdAt: c.created ?? "",
    resolved: !!c.resolved,
    externalUrl: c.external_url ?? null,
  }
}

// ---------------------------------------------------------------------------
// Inline tip shown when user finishes selecting text
// ---------------------------------------------------------------------------
export function AddCommentTip({
  onConfirm,
  onCancel,
  hideIssueCheckbox = false,
}: {
  onConfirm: (text: string, createIssue: boolean) => void
  onCancel: () => void
  // Hide the "Create GitHub issue" checkbox (e.g. for release review, where
  // issue mirroring is handled server-side and isn't a reviewer choice).
  hideIssueCheckbox?: boolean
}) {
  const [text, setText] = useState("")
  const [createIssue, setCreateIssue] = useState(true)
  const bg = useColorModeValue("white", "gray.800")
  const borderColor = useColorModeValue("gray.200", "gray.600")

  return (
    <Box
      bg={bg}
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="md"
      p={3}
      boxShadow="lg"
      w="260px"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <Textarea
        autoFocus
        placeholder="Add a comment…"
        size="sm"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim()) {
            e.preventDefault()
            onConfirm(text.trim(), createIssue)
          }
        }}
        mb={2}
      />
      {!hideIssueCheckbox && (
        <Checkbox
          size="sm"
          mb={2}
          isChecked={createIssue}
          onChange={(e) => setCreateIssue(e.target.checked)}
        >
          Create GitHub issue
        </Checkbox>
      )}
      <Flex gap={2}>
        <Button
          size="xs"
          variant="primary"
          isDisabled={!text.trim()}
          onClick={() => onConfirm(text.trim(), createIssue)}
        >
          Save
        </Button>
        <Button size="xs" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </Flex>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Popup shown when hovering / clicking an existing highlight
// ---------------------------------------------------------------------------
export function HighlightPopup({
  highlight,
  canResolve,
  isResolved,
  isResolving,
  onResolve,
}: {
  highlight: AnnotationHighlight
  canResolve: boolean
  isResolved: boolean
  isResolving?: boolean
  onResolve: (resolved: boolean) => void
}) {
  const bg = useColorModeValue("white", "gray.800")
  const borderColor = useColorModeValue("gray.200", "gray.600")

  return (
    <Box
      bg={bg}
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="md"
      p={3}
      boxShadow="lg"
      maxW="260px"
    >
      <Flex align="flex-start" gap={2} mb={1}>
        <Avatar name={highlight.authorName ?? undefined} size="xs" mt={0.5} />
        <Box flex={1}>
          <Flex align="center" gap={1} wrap="wrap">
            <Text fontSize="xs" fontWeight="bold" mr={1}>
              {highlight.authorName ?? "Unknown"}
            </Text>
            <Text fontSize="xs" color="gray.500" mr="auto">
              {highlight.createdAt
                ? new Date(highlight.createdAt).toLocaleDateString()
                : ""}
            </Text>
            {highlight.externalUrl && (
              <Link href={highlight.externalUrl} isExternal color="gray.500">
                <Flex align="center" gap={0.5}>
                  <Icon as={FaGithub} boxSize={3} />
                  <ExternalLinkIcon boxSize={2.5} />
                </Flex>
              </Link>
            )}
          </Flex>
        </Box>
        {canResolve &&
          (isResolving ? (
            <Spinner size="xs" color="ui.main" />
          ) : (
            <IconButton
              aria-label={isResolved ? "Unresolve" : "Resolve"}
              icon={isResolved ? <FaUndo /> : <FaCheck />}
              size="xs"
              variant="ghost"
              colorScheme={isResolved ? "gray" : "green"}
              onClick={() => onResolve(!isResolved)}
            />
          ))}
      </Flex>
      <Text fontSize="sm" whiteSpace="pre-wrap">
        {highlight.commentBody}
      </Text>
      {highlight.content.text && (
        <Box
          mt={2}
          pl={2}
          borderLeftWidth={2}
          borderColor="yellow.400"
          fontSize="xs"
          color="gray.500"
          fontStyle="italic"
          noOfLines={3}
        >
          {highlight.content.text}
        </Box>
      )}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
interface PdfAnnotatorProps {
  url: string
  ownerName: string
  projectName: string
  publicationPath: string
  artifactType?: "publication" | "presentation"
  gitRef?: string | null
  showResolved?: boolean
  // When true, render page-by-page navigation (prev/next arrows + arrow keys)
  // like a slide carousel. Used for presentation PDFs; off for publications.
  pagedNav?: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  externalScrollRef?: MutableRefObject<(h: any) => void>
  // Optional element rendered in the viewer toolbar, e.g. an "Edit LaTeX"
  // button.
  toolbarAction?: ReactNode
  // Optional panel beside the document, given the page in view. Forwarded
  // to the viewer; publications use it for the page's components.
  sidePanel?: PdfDocumentViewerProps["sidePanel"]
  sidePanelLabel?: string
  sidePanelIcon?: ReactElement
  sidePanelBadge?: ReactNode
}

export default function PdfAnnotator({
  url,
  ownerName,
  projectName,
  publicationPath,
  artifactType = "publication",
  gitRef,
  showResolved = false,
  pagedNav = false,
  externalScrollRef,
  toolbarAction,
  sidePanel,
  sidePanelLabel,
  sidePanelIcon,
  sidePanelBadge,
}: PdfAnnotatorProps) {
  const { user } = useAuth()
  const queryClient = useQueryClient()

  const commentsQuery = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "comments",
      artifactType,
      publicationPath,
    ],
    queryFn: () =>
      ProjectsService.getProjectComments({
        owner_name: ownerName,
        project_name: projectName,
        artifact_type: artifactType,
        artifact_path: publicationPath,
      }).then((response) => response.data),
  })

  const postMutation = useMutation({
    mutationFn: (data: {
      comment: string
      highlight: CommentHighlight | null
      create_github_issue: boolean
    }) =>
      ProjectsService.postProjectComment({
        owner_name: ownerName,
        project_name: projectName,
        projectCommentPost: {
          artifact_path: publicationPath,
          artifact_type: artifactType,
          comment: data.comment,
          highlight: data.highlight,
          create_github_issue: data.create_github_issue,
          git_ref: gitRef ?? null,
        },
      }).then((response) => response.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: [
          "projects",
          ownerName,
          projectName,
          "comments",
          artifactType,
          publicationPath,
        ],
      })
    },
  })

  const resolveMutation = useMutation({
    mutationFn: ({
      commentId,
      resolved,
    }: { commentId: string; resolved: boolean }) =>
      ProjectsService.patchProjectComment({
        owner_name: ownerName,
        project_name: projectName,
        comment_id: commentId,
        projectCommentPatch: { resolved },
      }).then((response) => response.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: [
          "projects",
          ownerName,
          projectName,
          "comments",
          artifactType,
          publicationPath,
        ],
      })
    },
  })

  const comments: ProjectComment[] = commentsQuery.data ?? []
  // Derive highlights straight from the query data so the array only changes
  // when the comments (or the resolved filter) actually change, not on every
  // parent render.
  const highlights: AnnotationHighlight[] = useMemo(
    () =>
      comments
        .filter((c) => showResolved || !c.resolved)
        .map(commentToHighlight)
        .filter((h): h is AnnotationHighlight => h !== null),
    [comments, showResolved],
  )

  const handleAddHighlight = useCallback(
    (newHighlight: NewHighlight, commentText: string, createIssue: boolean) => {
      postMutation.mutate({
        comment: commentText,
        highlight: {
          position: newHighlight.position as unknown as Record<string, unknown>,
          content: newHighlight.content as unknown as Record<string, unknown>,
        } as CommentHighlight,
        create_github_issue: createIssue,
      })
    },
    [postMutation],
  )

  const onSelectionFinished: OnSelectionFinished = useCallback(
    (position, content, hideTip, transformSelection) => {
      // transformSelection sets ghostHighlight on PdfHighlighter so the yellow
      // selection remains visible while the user types in the comment box
      // (typing clears document.getSelection(), which otherwise makes
      // isCollapsed=true and drops the visual selection).
      transformSelection()
      return user ? (
        <AddCommentTip
          onConfirm={(text, createIssue) => {
            handleAddHighlight(
              { position, content, comment: { text, emoji: "" } },
              text,
              createIssue,
            )
            hideTip()
          }}
          onCancel={hideTip}
        />
      ) : null
    },
    [user, handleAddHighlight],
  )

  const highlightTransform: HighlightTransform = useCallback(
    (
      highlight,
      _index,
      setTip,
      hideTip,
      _viewportToScaled,
      _screenshot,
      isScrolledTo,
    ) => {
      const annotHL = highlight as unknown as AnnotationHighlight
      const isArea = Boolean(highlight.content?.image)
      const component = isArea ? (
        <AreaHighlight
          isScrolledTo={isScrolledTo}
          highlight={highlight}
          onChange={() => {}}
        />
      ) : (
        <Highlight
          isScrolledTo={isScrolledTo}
          position={highlight.position}
          comment={highlight.comment}
        />
      )
      return (
        <Popup
          popupContent={
            <HighlightPopup
              highlight={annotHL}
              canResolve={!!user}
              isResolved={annotHL.resolved}
              isResolving={
                resolveMutation.isPending &&
                resolveMutation.variables?.commentId === annotHL.dbId
              }
              onResolve={(resolved) => {
                resolveMutation.mutate({
                  commentId: annotHL.dbId,
                  resolved,
                })
                hideTip()
              }}
            />
          }
          onMouseOver={(popupContent) => setTip(highlight, () => popupContent)}
          onMouseOut={hideTip}
          key={highlight.id}
        >
          {component}
        </Popup>
      )
    },
    [user, resolveMutation],
  )

  return (
    <PdfDocumentViewer
      url={url}
      highlights={highlights}
      highlightTransform={highlightTransform}
      onSelectionFinished={onSelectionFinished}
      enableAreaSelection={(e) => e.altKey}
      externalScrollRef={externalScrollRef}
      pagedNav={pagedNav}
      source={artifactType}
      toolbarAction={toolbarAction}
      sidePanel={sidePanel}
      sidePanelLabel={sidePanelLabel}
      sidePanelIcon={sidePanelIcon}
      sidePanelBadge={sidePanelBadge}
    />
  )
}
