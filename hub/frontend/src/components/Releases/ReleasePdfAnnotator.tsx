/**
 * Annotated PDF viewer for a release: reviewers (including no-signup share-link
 * holders) can select text and leave comments anchored to a highlight. Comments
 * are stored as ReleaseComment rows pinned to the release's git_rev, so feedback
 * always traces to the exact reviewed version. Highlight JSON uses the portable
 * react-pdf-highlighter format, matching publication annotations.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { type MutableRefObject, useCallback, useMemo } from "react"
import {
  AreaHighlight,
  Highlight,
  type IHighlight,
  Popup,
} from "react-pdf-highlighter"
import "react-pdf-highlighter/dist/style.css"

import {
  type CommentHighlight,
  type ReleaseCommentPublic,
  ReleasesService,
} from "../../client"
import PdfDocumentViewer, {
  type HighlightTransform,
  type OnSelectionFinished,
} from "../Common/PdfDocumentViewer"
import {
  AddCommentTip,
  type AnnotationHighlight,
  HighlightPopup,
} from "../Publications/PdfAnnotator"

function releaseCommentToHighlight(
  c: ReleaseCommentPublic,
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
    authorName: c.author_name ?? null,
    createdAt: c.created ?? "",
    resolved: false,
    externalUrl: c.external_url ?? null,
  }
}

interface ReleasePdfAnnotatorProps {
  url: string
  ownerName: string
  projectName: string
  releaseName: string
  token?: string
  // Whether the current viewer may comment (vs. view-only).
  canComment: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  externalScrollRef?: MutableRefObject<(h: any) => void>
}

export default function ReleasePdfAnnotator({
  url,
  ownerName,
  projectName,
  releaseName,
  token,
  canComment,
  externalScrollRef,
}: ReleasePdfAnnotatorProps) {
  const queryClient = useQueryClient()
  // Shared with the release page's comments panel so both stay in sync.
  const commentsKey = [
    "releases",
    ownerName,
    projectName,
    releaseName,
    "comments",
  ]
  const commentsQuery = useQuery({
    queryKey: commentsKey,
    queryFn: () =>
      ReleasesService.getReleaseComments({
        ownerName,
        projectName,
        releaseName,
        token,
      }),
  })
  const postMutation = useMutation({
    mutationFn: (data: { comment: string; highlight: CommentHighlight }) =>
      ReleasesService.postReleaseComment({
        ownerName,
        projectName,
        releaseName,
        token,
        requestBody: { comment: data.comment, highlight: data.highlight },
      }),
    // Write the server's comment straight into the cache instead of
    // invalidating, so the highlight renders the moment the request returns
    // with no refetch gap in between.
    onSuccess: (data) => {
      queryClient.setQueryData<ReleaseCommentPublic[]>(commentsKey, (old) => [
        ...(old ?? []),
        data,
      ])
    },
  })
  const comments = commentsQuery.data ?? []
  const highlights: AnnotationHighlight[] = useMemo(
    () =>
      comments
        .map(releaseCommentToHighlight)
        .filter((h): h is AnnotationHighlight => h !== null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [comments],
  )

  const onSelectionFinished: OnSelectionFinished = useCallback(
    (position, content, hideTip, transformSelection) => {
      // Keep the yellow selection visible while the reviewer types.
      transformSelection()
      return canComment ? (
        <AddCommentTip
          hideIssueCheckbox
          onConfirm={(text) => {
            postMutation.mutate({
              comment: text,
              highlight: {
                position: position as unknown as Record<string, unknown>,
                content: content as unknown as Record<string, unknown>,
              } as CommentHighlight,
            })
            hideTip()
          }}
          onCancel={hideTip}
        />
      ) : null
    },
    [canComment, postMutation],
  )

  const highlightTransform: HighlightTransform = useCallback(
    (highlight, _index, setTip, hideTip, _v, _s, isScrolledTo) => {
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
              canResolve={false}
              isResolved={false}
              onResolve={() => {}}
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
    [],
  )

  return (
    <PdfDocumentViewer
      url={url}
      highlights={highlights}
      highlightTransform={highlightTransform}
      onSelectionFinished={onSelectionFinished}
      enableAreaSelection={(e) => e.altKey}
      externalScrollRef={externalScrollRef}
      source="release"
      defaultScale="page-width"
    />
  )
}
