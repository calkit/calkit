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

import type { AxiosError } from "axios"
import {
  type CommentHighlight,
  type LatexComments,
  type LatexCommentThread,
  type ProjectComment,
  ProjectsService,
} from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import type { PanelComment } from "../Common/CommentsPanel"
import PdfDocumentViewer, {
  type HighlightTransform,
  type OnSelectionFinished,
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

// A thread kept in a LaTeX source, as a highlight, if its place in the PDF
// was found
export function latexThreadToHighlight(
  t: LatexCommentThread,
): AnnotationHighlight | null {
  if (!t.position) return null
  const first = t.messages[0]
  return {
    id: t.key,
    dbId: t.key,
    position: t.position as unknown as IHighlight["position"],
    content: { text: t.highlight ?? undefined },
    comment: { text: first?.text ?? "", emoji: "" },
    commentBody: first?.text ?? "",
    authorName: first?.author ?? null,
    createdAt: first?.date ?? "",
    resolved: t.resolved,
    externalUrl: t.issue ?? null,
  }
}

// A thread kept in a LaTeX source as the comments panel shows it: its first
// message, then the replies to it
export function latexThreadToPanelComments(
  t: LatexCommentThread,
): PanelComment[] {
  return t.messages.map((m, i) => ({
    id: i ? `${t.key}#${i}` : t.key,
    parentId: i ? t.key : null,
    authorName: m.author,
    comment: m.text,
    created: m.date ?? null,
    resolved: t.resolved ? "resolved" : null,
    externalUrl: i ? null : t.issue ?? null,
    hasHighlight: !i && !!t.position,
    highlightText: i ? null : t.highlight ?? null,
  }))
}

// Comments on a PDF built from LaTeX, which live in its source at the ref
// being viewed. Each change is a commit there, and comes back with the
// threads as they are after it.
export function useLatexComments(
  ownerName: string,
  projectName: string,
  path: string,
  gitRef: string | null | undefined,
  enabled: boolean,
) {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const queryKey = [
    "projects",
    ownerName,
    projectName,
    "latex-comments",
    path,
    gitRef ?? null,
  ]
  const ids = { owner_name: ownerName, project_name: projectName }
  const ref = gitRef ?? null
  const handlers = {
    onSuccess: (data: LatexComments) =>
      queryClient.setQueryData(queryKey, data),
    onError: (err: AxiosError) => handleError(err, showToast),
  }
  const query = useQuery({
    queryKey,
    queryFn: () =>
      ProjectsService.getProjectLatexComments({ ...ids, path, ref }).then(
        (response) => response.data,
      ),
    enabled,
  })
  const post = useMutation({
    mutationFn: (vars: {
      comment: string
      highlight: CommentHighlight | null
      createIssue: boolean
    }) =>
      ProjectsService.postProjectLatexComment({
        ...ids,
        latexCommentPost: {
          path,
          ref,
          comment: vars.comment,
          highlight: vars.highlight,
          create_github_issue: vars.createIssue,
        },
      }).then((response) => response.data),
    ...handlers,
  })
  const reply = useMutation({
    mutationFn: (vars: { key: string; body: string }) =>
      ProjectsService.postProjectLatexCommentReply({
        ...ids,
        latexCommentReplyPost: { path, ref, key: vars.key, body: vars.body },
      }).then((response) => response.data),
    ...handlers,
  })
  const resolve = useMutation({
    mutationFn: (vars: { key: string; resolved: boolean }) =>
      ProjectsService.patchProjectLatexComment({
        ...ids,
        latexCommentPatch: {
          path,
          ref,
          key: vars.key,
          resolved: vars.resolved,
        },
      }).then((response) => response.data),
    ...handlers,
  })
  return { query, post, reply, resolve }
}

// ---------------------------------------------------------------------------
// Inline tip shown when user finishes selecting text
// ---------------------------------------------------------------------------
export function AddCommentTip({
  onConfirm,
  onCancel,
  hideIssueCheckbox = false,
  defaultCreateIssue = true,
}: {
  onConfirm: (text: string, createIssue: boolean) => void
  onCancel: () => void
  // Hide the "Create GitHub issue" checkbox (e.g. for release review, where
  // issue mirroring is handled server-side and isn't a reviewer choice).
  hideIssueCheckbox?: boolean
  defaultCreateIssue?: boolean
}) {
  const [text, setText] = useState("")
  const [createIssue, setCreateIssue] = useState(defaultCreateIssue)
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
  // Built from LaTeX, so comments live in its source rather than here
  latex?: boolean
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
  latex = false,
}: PdfAnnotatorProps) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const latexComments = useLatexComments(
    ownerName,
    projectName,
    publicationPath,
    gitRef,
    latex,
  )

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
    enabled: !latex,
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
  const latexThreads = latexComments.query.data?.threads
  const highlights: AnnotationHighlight[] = useMemo(
    () =>
      latex
        ? (latexThreads ?? [])
            .filter((t) => showResolved || !t.resolved)
            .map(latexThreadToHighlight)
            .filter((h): h is AnnotationHighlight => h !== null)
        : comments
            .filter((c) => showResolved || !c.resolved)
            .map(commentToHighlight)
            .filter((h): h is AnnotationHighlight => h !== null),
    [latex, latexThreads, comments, showResolved],
  )

  const handleAddHighlight = useCallback(
    (newHighlight: NewHighlight, commentText: string, createIssue: boolean) => {
      const highlight = {
        position: newHighlight.position as unknown as Record<string, unknown>,
        content: newHighlight.content as unknown as Record<string, unknown>,
      } as CommentHighlight
      if (latex) {
        latexComments.post.mutate({
          comment: commentText,
          highlight,
          createIssue,
        })
        return
      }
      postMutation.mutate({
        comment: commentText,
        highlight,
        create_github_issue: createIssue,
      })
    },
    [latex, latexComments.post, postMutation],
  )

  const onSelectionFinished: OnSelectionFinished = useCallback(
    (position, content, hideTip, transformSelection) => {
      // transformSelection sets ghostHighlight on PdfHighlighter so the yellow
      // selection remains visible while the user types in the comment box
      // (typing clears document.getSelection(), which otherwise makes
      // isCollapsed=true and drops the visual selection).
      transformSelection()
      const canComment = latex
        ? !!latexComments.query.data?.can_comment
        : !!user
      return canComment ? (
        <AddCommentTip
          defaultCreateIssue={!latex}
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
    [user, latex, latexComments.query.data, handleAddHighlight],
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
              canResolve={
                latex ? !!latexComments.query.data?.can_comment : !!user
              }
              isResolved={annotHL.resolved}
              isResolving={
                latex
                  ? latexComments.resolve.isPending &&
                    latexComments.resolve.variables?.key === annotHL.dbId
                  : resolveMutation.isPending &&
                    resolveMutation.variables?.commentId === annotHL.dbId
              }
              onResolve={(resolved) => {
                if (latex) {
                  latexComments.resolve.mutate({ key: annotHL.dbId, resolved })
                } else {
                  resolveMutation.mutate({
                    commentId: annotHL.dbId,
                    resolved,
                  })
                }
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
    [
      user,
      latex,
      latexComments.query.data,
      latexComments.resolve,
      resolveMutation,
    ],
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
    />
  )
}
