import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Flex,
  HStack,
  Heading,
  Icon,
  IconButton,
  Image,
  Link,
  Text,
  VStack,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { type ReactNode, useState } from "react"
import { FaFile, FaFolder } from "react-icons/fa"
import {
  FiArrowUp,
  FiDownload,
  FiExternalLink,
  FiFolder,
  FiX,
} from "react-icons/fi"

import {
  type ContentsItem,
  type ProjectComment,
  ProjectsService,
  type ReleaseCommentPublic,
  type ReleaseListItem,
  type ReleaseView,
  ReleasesService,
} from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import {
  formatReleaseDate,
  releaseDownloadName,
  releaseLocation,
} from "../../lib/releases"
import SyntaxHighlighter from "react-syntax-highlighter"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"
import { decodeBase64Utf8 } from "../../lib/strings"
import SharedCommentsPanel, { type PanelComment } from "../Common/CommentsPanel"
import LoadingSpinner from "../Common/LoadingSpinner"
import Markdown from "../Common/Markdown"
import PdfDocumentViewer from "../Common/PdfDocumentViewer"
import { getLanguage, qmdToMarkdown } from "../Files/FileContent"
import ProjectShowcase from "../Projects/ProjectShowcase"
import PresentationView from "../Presentations/PresentationView"
import ReleasePdfAnnotator from "./ReleasePdfAnnotator"

export interface ReleaseLocator {
  ownerName: string
  projectName: string
  releaseName: string
  token?: string
}

function dataUri(item: ContentsItem, mime: string): string | null {
  if (item.url) return item.url
  if (item.content) return `data:${mime};base64,${item.content}`
  return null
}

function ArtifactView({
  path,
  item,
  kind,
}: {
  path: string
  item: ContentsItem
  kind?: string | null
}) {
  const lower = path.toLowerCase()
  const isPptx = lower.endsWith(".pptx") || lower.endsWith(".ppt")
  // A presentation is shown as slides (left/right nav) regardless of format;
  // pptx is always slides. PresentationView handles pptx/pdf/html internally.
  const asSlides =
    isPptx ||
    (kind === "presentation" &&
      (lower.endsWith(".pdf") ||
        lower.endsWith(".html") ||
        lower.endsWith(".htm")))
  if (asSlides) {
    return (
      <Box h="100%" w="100%">
        <PresentationView
          presentation={{
            path: item.path,
            title: item.name,
            content: item.content ?? null,
            url: item.url ?? null,
          }}
        />
      </Box>
    )
  }
  if (lower.endsWith(".pdf")) {
    const src = dataUri(item, "application/pdf")
    if (src)
      return (
        <Box h="100%" w="100%">
          <PdfDocumentViewer
            url={src}
            source="release"
            defaultScale="page-width"
          />
        </Box>
      )
  } else if (lower.endsWith(".html") || lower.endsWith(".htm")) {
    // Prefer the hosted URL; fall back to inline content. Sandboxed (no
    // allow-same-origin) so shared HTML runs in an opaque origin and can't
    // reach the host page, while scripts still run to render the doc.
    const src = item.url
      ? item.url
      : item.content
        ? `data:text/html;base64,${item.content}`
        : null
    if (src)
      return (
        <iframe
          title="release"
          style={{ height: "100%", width: "100%", border: "none" }}
          src={src}
          sandbox="allow-scripts allow-popups"
        />
      )
  } else if (/\.(png|jpe?g|gif|webp|svg)$/.test(lower)) {
    const src = dataUri(item, "image/png")
    if (src) return <Image alt={path} src={src} maxH="100%" mx="auto" />
  } else if (
    (lower.endsWith(".md") || lower.endsWith(".qmd")) &&
    item.content
  ) {
    const decoded = decodeBase64Utf8(item.content)
    return (
      <Box h="100%" w="100%" overflowY="auto" py={2} px={4}>
        <Markdown>
          {lower.endsWith(".qmd") ? qmdToMarkdown(decoded) : decoded}
        </Markdown>
      </Box>
    )
  } else if (item.content != null) {
    // Any other text file (source, config, data, plain text): show it
    // syntax-highlighted rather than forcing a download.
    return (
      <Box h="100%" w="100%" overflow="hidden" fontSize="sm">
        <SyntaxHighlighter
          language={getLanguage(item.name)}
          style={atomOneDark}
          customStyle={{ height: "100%", margin: 0, overflow: "auto" }}
        >
          {decodeBase64Utf8(item.content)}
        </SyntaxHighlighter>
      </Box>
    )
  }
  return (
    <Flex align="center" justify="center" h="100%">
      <Alert status="info" borderRadius="lg" maxW="md">
        <AlertIcon />
        This file type can't be previewed. Use the download button to view it.
      </Alert>
    </Flex>
  )
}

// Downloads an artifact with a guaranteed filename. The browser ignores an
// <a download> name for cross-origin storage URLs (and chaining downloads can
// trip the "multiple files" block), so fetch the bytes and save a blob.
function DownloadButton({ href, name }: { href: string; name: string }) {
  const showToast = useCustomToast()
  const [busy, setBusy] = useState(false)
  const onClick = async () => {
    setBusy(true)
    try {
      const resp = await fetch(href)
      if (!resp.ok) throw new Error(String(resp.status))
      const blob = await resp.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = objectUrl
      a.download = name
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(objectUrl)
    } catch {
      showToast("Error", "Couldn't download the file.", "error")
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button
      size="sm"
      leftIcon={<FiDownload />}
      onClick={onClick}
      isLoading={busy}
    >
      Download
    </Button>
  )
}

function CommentsPanel({
  loc,
  release,
}: {
  loc: ReleaseLocator
  release: ReleaseView
}) {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { user } = useAuth()
  const [showResolved, setShowResolved] = useState(false)
  const commentsKey = [
    "releases",
    loc.ownerName,
    loc.projectName,
    loc.releaseName,
    "comments",
  ]
  const commentsQuery = useQuery({
    queryKey: commentsKey,
    queryFn: () =>
      ReleasesService.getReleaseComments({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        releaseName: loc.releaseName,
        token: loc.token,
      }),
  })
  const postMutation = useMutation({
    mutationFn: (vars: {
      body: string
      parentId?: string
      authorName: string | null
    }) =>
      ReleasesService.postReleaseComment({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        releaseName: loc.releaseName,
        token: loc.token,
        requestBody: {
          comment: vars.body,
          author_name: vars.authorName,
          parent_id: vars.parentId ?? null,
        },
      }),
    // Write the server's comment straight into the cache instead of
    // invalidating, so the posted comment appears the moment the request
    // returns (and the composer closes) with no refetch gap in between.
    onSuccess: (data) => {
      showToast("Success!", "Your comment was posted.", "success")
      queryClient.setQueryData<ReleaseCommentPublic[]>(commentsKey, (old) => [
        ...(old ?? []),
        data,
      ])
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })
  const resolveMutation = useMutation({
    mutationFn: (vars: { id: string; resolved: boolean }) =>
      ReleasesService.resolveReleaseComment({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        releaseName: loc.releaseName,
        commentId: vars.id,
        requestBody: { resolved: vars.resolved },
      }),
    onSuccess: (data, vars) => {
      showToast(
        "Success!",
        vars.resolved ? "Thread resolved." : "Thread reopened.",
        "success",
      )
      // Reflect the returned state without a refetch; the backend cascades
      // resolve to replies, so mirror that onto this thread's replies too.
      queryClient.setQueryData<ReleaseCommentPublic[]>(commentsKey, (old) =>
        (old ?? []).map((c) =>
          c.id === data.id
            ? data
            : c.parent_id === vars.id
              ? { ...c, resolved: data.resolved }
              : c,
        ),
      )
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })
  // The page payload already encodes whether this viewer may comment.
  const canComment =
    release.permission === "comment" || release.permission === "manage"
  const canManage = release.permission === "manage"
  // A token bound to an email identifies the commenter; only truly anonymous
  // viewers (no login, no token email) need to type a name.
  const needsName = !user && !release.viewer_email
  const comments: PanelComment[] = (commentsQuery.data ?? []).map((c) => ({
    id: c.id,
    parentId: c.parent_id ?? null,
    authorName: c.author_name ?? null,
    comment: c.comment,
    created: c.created,
    resolved: c.resolved ?? null,
    externalUrl: c.external_url ?? null,
  }))
  return (
    <SharedCommentsPanel
      comments={comments}
      isLoading={commentsQuery.isPending}
      fillHeight
      canComment={canComment}
      canResolve={canManage}
      showResolved={showResolved}
      onShowResolvedChange={setShowResolved}
      askAuthorName={needsName}
      commentingAsLabel={release.viewer_email ?? null}
      emptyText="No comments yet. Be the first to leave feedback."
      postLabel="Post comment"
      viewOnlyText="This link is view-only."
      onPostComment={(body, opts) =>
        postMutation.mutateAsync({ body, authorName: opts.authorName })
      }
      postingComment={
        postMutation.isPending && !postMutation.variables?.parentId
      }
      onPostReply={(parentId, body, opts) =>
        postMutation.mutateAsync({
          body,
          parentId,
          authorName: opts.authorName,
        })
      }
      postingReplyForId={
        postMutation.isPending ? postMutation.variables?.parentId ?? null : null
      }
      onResolve={(id, resolved) => resolveMutation.mutate({ id, resolved })}
      resolvingId={
        resolveMutation.isPending ? resolveMutation.variables?.id ?? null : null
      }
    />
  )
}

// Comments for a calkit.yaml release, via the generic project-comment system
// (artifact_type "release", keyed by the release name). Login required to post
// -- these releases are members-only, unlike the token-shared cloud releases.
function MemberCommentsPanel({
  loc,
  release,
}: {
  loc: ReleaseLocator
  release: ReleaseListItem
}) {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { user } = useAuth()
  const [showResolved, setShowResolved] = useState(false)
  const commentsKey = [
    "projects",
    loc.ownerName,
    loc.projectName,
    "comments",
    "release",
    release.name,
  ]
  const commentsQuery = useQuery({
    queryKey: commentsKey,
    queryFn: () =>
      ProjectsService.getProjectComments({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        artifactType: "release",
        artifactPath: release.name,
      }),
  })
  const postMutation = useMutation({
    mutationFn: (vars: {
      body: string
      parentId?: string
      createIssue: boolean
    }) =>
      vars.parentId
        ? ProjectsService.postProjectCommentReply({
            ownerName: loc.ownerName,
            projectName: loc.projectName,
            commentId: vars.parentId,
            requestBody: { body: vars.body },
          })
        : ProjectsService.postProjectComment({
            ownerName: loc.ownerName,
            projectName: loc.projectName,
            requestBody: {
              comment: vars.body,
              artifact_type: "release",
              artifact_path: release.name,
              git_ref: release.git_rev ?? release.git_rev_abbrev ?? null,
              create_github_issue: vars.createIssue,
            },
          }),
    // Write the server's comment straight into the cache instead of
    // invalidating, so it appears the moment the request returns (and the
    // composer closes) with no refetch gap in between.
    onSuccess: (data) => {
      showToast("Success!", "Your comment was posted.", "success")
      queryClient.setQueryData<ProjectComment[]>(commentsKey, (old) => [
        ...(old ?? []),
        data,
      ])
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })
  const resolveMutation = useMutation({
    mutationFn: (vars: { id: string; resolved: boolean }) =>
      ProjectsService.patchProjectComment({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        commentId: vars.id,
        requestBody: { resolved: vars.resolved },
      }),
    onSuccess: (data, vars) => {
      // Reflect the returned state without a refetch; the backend cascades
      // resolve to replies, so mirror that onto this thread's replies too.
      queryClient.setQueryData<ProjectComment[]>(commentsKey, (old) =>
        (old ?? []).map((c) =>
          c.id === data.id
            ? data
            : c.parent_id === vars.id
              ? { ...c, resolved: data.resolved }
              : c,
        ),
      )
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })
  const comments: PanelComment[] = (commentsQuery.data ?? []).map((c) => ({
    id: c.id ?? "",
    parentId: c.parent_id ?? null,
    authorName: c.user_full_name ?? c.user_github_username ?? null,
    comment: c.comment,
    created: c.created ?? null,
    resolved: c.resolved ?? null,
    externalUrl: c.external_url ?? null,
    hasHighlight: !!c.highlight,
    highlightText:
      (c.highlight as { content?: { text?: string } } | null)?.content?.text ??
      null,
  }))
  return (
    <SharedCommentsPanel
      comments={comments}
      isLoading={commentsQuery.isPending}
      fillHeight
      canComment={!!user}
      canResolve={!!user}
      showResolved={showResolved}
      onShowResolvedChange={setShowResolved}
      showCreateIssueCheckbox
      emptyText="No comments yet."
      postLabel="Post"
      viewOnlyText={
        <>
          <Link href="/login" color="blue.500">
            Log in
          </Link>{" "}
          to leave a comment.
        </>
      }
      onPostComment={(body, opts) =>
        postMutation.mutateAsync({ body, createIssue: opts.createIssue })
      }
      postingComment={
        postMutation.isPending && !postMutation.variables?.parentId
      }
      onPostReply={(parentId, body) =>
        postMutation.mutateAsync({ body, parentId, createIssue: false })
      }
      postingReplyForId={
        postMutation.isPending ? postMutation.variables?.parentId ?? null : null
      }
      onResolve={(id, resolved) => resolveMutation.mutate({ id, resolved })}
      resolvingId={
        resolveMutation.isPending ? resolveMutation.variables?.id ?? null : null
      }
    />
  )
}

// Read-only browser over a whole-project release's files at its pinned ref.
function ProjectBrowser({ loc }: { loc: ReleaseLocator }) {
  const [path, setPath] = useState<string | undefined>(undefined)
  const {
    data: item,
    isPending,
    isError,
  } = useQuery({
    queryKey: [
      "releases",
      loc.ownerName,
      loc.projectName,
      loc.releaseName,
      "contents",
      path ?? "",
    ],
    queryFn: () =>
      ReleasesService.getReleaseContents({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        releaseName: loc.releaseName,
        token: loc.token,
        path,
      }),
    retry: false,
  })
  const parts = path ? path.split("/") : []
  const goUp = () =>
    setPath(parts.length > 1 ? parts.slice(0, -1).join("/") : undefined)
  if (isPending) return <LoadingSpinner height="100%" />
  if (isError || !item) {
    return (
      <Flex align="center" justify="center" h="100%" p={4}>
        <Alert status="warning" borderRadius="lg" maxW="md">
          <AlertIcon />
          Couldn't load the project files.
        </Alert>
      </Flex>
    )
  }
  const isDir = item.type === "dir" || item.dir_items != null
  if (!isDir) {
    return (
      <Flex direction="column" h="100%">
        <Button
          onClick={goUp}
          leftIcon={<Icon as={FiArrowUp} />}
          size="sm"
          variant="ghost"
          m={2}
          alignSelf="flex-start"
        >
          Back to {parts.length > 1 ? parts.slice(0, -1).join("/") : "files"}
        </Button>
        <Box flex={1} minH={0}>
          <ArtifactView path={item.path} item={item} />
        </Box>
      </Flex>
    )
  }
  const entries = [...(item.dir_items ?? [])].sort((a, b) => {
    const ad = a.type === "dir" ? 0 : 1
    const bd = b.type === "dir" ? 0 : 1
    return ad - bd || a.name.localeCompare(b.name)
  })
  return (
    <Box p={4} h="100%" overflowY="auto">
      <Text fontSize="sm" color="gray.500" mb={2}>
        /{path ?? ""}
      </Text>
      <VStack align="stretch" spacing={0} maxW="container.sm">
        {path && (
          <Flex
            align="center"
            gap={2}
            py={1.5}
            px={2}
            cursor="pointer"
            borderRadius="md"
            _hover={{ bg: "blackAlpha.50" }}
            onClick={goUp}
          >
            <Icon as={FiArrowUp} color="gray.400" />
            <Text fontSize="sm">..</Text>
          </Flex>
        )}
        {entries.map((e) => (
          <Flex
            key={e.path}
            align="center"
            gap={2}
            py={1.5}
            px={2}
            cursor="pointer"
            borderRadius="md"
            _hover={{ bg: "blackAlpha.50" }}
            onClick={() => setPath(e.path)}
          >
            <Icon
              as={e.type === "dir" ? FaFolder : FaFile}
              color={e.type === "dir" ? "blue.400" : "gray.400"}
              flexShrink={0}
            />
            <Text fontSize="sm" noOfLines={1}>
              {e.name}
            </Text>
          </Flex>
        ))}
      </VStack>
    </Box>
  )
}

// Main view for a whole-project release: the project's showcase at the pinned
// commit if it has one, otherwise the supplied fallback (file browser or a
// browse prompt). The showcase needs project read access, so no-signup token
// viewers of a private project fall through to the fallback.
function WholeProjectView({
  loc,
  gitRev,
  fallback,
}: {
  loc: ReleaseLocator
  gitRev?: string
  fallback: ReactNode
}) {
  const showcaseQuery = useQuery({
    queryKey: ["projects", loc.ownerName, loc.projectName, "showcase", gitRev],
    queryFn: () =>
      ProjectsService.getProjectShowcase({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        ref: gitRev,
      }),
    retry: false,
  })
  if (showcaseQuery.isPending) return <LoadingSpinner height="100%" />
  if ((showcaseQuery.data?.elements?.length ?? 0) > 0) {
    return (
      <Box h="100%" overflowY="auto" p={4}>
        <ProjectShowcase
          ownerName={loc.ownerName}
          projectName={loc.projectName}
          gitRef={gitRev}
        />
      </Box>
    )
  }
  return <>{fallback}</>
}

interface ReleaseViewerProps {
  loc: ReleaseLocator
  // When set, a close affordance is shown (used when embedded in a modal).
  onClose?: () => void
}

function ReleaseUnavailable({
  onClose,
  isLoggedIn,
}: {
  onClose?: () => void
  isLoggedIn: boolean
}) {
  return (
    <Flex direction="column" h="100%">
      {onClose && (
        <Flex justify="flex-end" p={2}>
          <IconButton
            aria-label="Close"
            icon={<FiX />}
            size="sm"
            variant="ghost"
            onClick={onClose}
          />
        </Flex>
      )}
      <Flex align="center" justify="center" flex={1} p={4}>
        <Alert status="error" borderRadius="lg" maxW="md">
          <AlertIcon />
          {isLoggedIn
            ? "This release couldn't be loaded. It may have been deleted, or you may not have access to it."
            : "This release is unavailable, or you need a valid share link to view it."}
        </Alert>
      </Flex>
    </Flex>
  )
}

// Resolves a release and renders the right view: a cloud (internal, hosted)
// release with its artifact/project browser and comments, or a release
// declared in calkit.yaml (published to an external venue, or a CLI-made
// snapshot) shown as metadata with a link to browse the project at its commit.
export default function ReleaseViewer({ loc, onClose }: ReleaseViewerProps) {
  const { user } = useAuth()
  const viewQuery = useQuery({
    queryKey: [
      "releases",
      loc.ownerName,
      loc.projectName,
      loc.releaseName,
      loc.token,
    ],
    queryFn: () =>
      ReleasesService.getReleaseView({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        releaseName: loc.releaseName,
        token: loc.token,
      }),
    // A 404 means there's no cloud release for this name; fall back to the
    // calkit.yaml listing immediately. Other errors (transient 5xx/network)
    // are worth retrying, so a member viewing their own release doesn't get
    // bounced to the "unavailable" screen by a one-off hiccup.
    retry: (failureCount, error: ApiError) =>
      error?.status !== 404 && failureCount < 2,
  })
  // calkit.yaml releases have no cloud row, so getReleaseView 404s; fall back
  // to their metadata from the project's releases listing.
  const listQuery = useQuery({
    queryKey: [
      "projects",
      loc.ownerName,
      loc.projectName,
      "releases",
      undefined,
    ],
    queryFn: () =>
      ReleasesService.getProjectReleases({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
      }),
    enabled: viewQuery.isError,
    retry: false,
  })

  if (viewQuery.isPending) return <LoadingSpinner height="100%" />
  if (viewQuery.data)
    return (
      <CloudReleaseView loc={loc} release={viewQuery.data} onClose={onClose} />
    )
  if (listQuery.isPending) return <LoadingSpinner height="100%" />
  const calkit = (listQuery.data ?? []).find(
    (r) => r.name === loc.releaseName && r.source !== "cloud",
  )
  if (calkit)
    return <CalkitReleaseView loc={loc} release={calkit} onClose={onClose} />
  return <ReleaseUnavailable onClose={onClose} isLoggedIn={!!user} />
}

// Header button that opens the project's Files view at the release's commit.
// For a whole-project release we always offer it (alwaysShow): if the release
// pins to a commit/tag we browse at it, otherwise we browse the project's
// latest -- a version-less project release with a showcase still deserves a way
// in.
function BrowseProjectButton({
  loc,
  gitRev,
  alwaysShow = false,
}: {
  loc: ReleaseLocator
  gitRev?: string
  alwaysShow?: boolean
}) {
  if (!gitRev && !alwaysShow) return null
  return (
    <Link
      as={RouterLink}
      to={`/${loc.ownerName}/${loc.projectName}` as any}
      search={(gitRev ? { ref: gitRev } : {}) as any}
    >
      <Button size="sm" variant="outline" leftIcon={<FiFolder />}>
        {gitRev ? "Browse project at this version" : "Browse project"}
      </Button>
    </Link>
  )
}

// A release declared in calkit.yaml (published externally, or a CLI snapshot):
// renders the released artifact at its pinned commit when it's a single file,
// alongside a metadata sidebar showing where it went and a link to browse the
// whole project at that commit.
function CalkitReleaseView({
  loc,
  release,
  onClose,
}: {
  loc: ReleaseLocator
  release: ReleaseListItem
  onClose?: () => void
}) {
  const dest = releaseLocation(release)
  // Fall back through every recorded ref so the "browse at this version" button
  // appears whenever the release pins to anything (a commit or just a tag);
  // externally-published releases often record only git_ref.
  const gitRev =
    release.git_rev ?? release.git_rev_abbrev ?? release.git_ref ?? undefined
  const refLabel = release.git_ref ?? release.git_rev_abbrev ?? ""
  const isWholeProject = !release.path || release.path === "."
  // For a single-artifact release, fetch the file at the pinned commit via the
  // project's contents API (no cloud row, so no release-content endpoint).
  const contentQuery = useQuery({
    queryKey: [
      "projects",
      loc.ownerName,
      loc.projectName,
      "contents",
      release.path,
      gitRev,
    ],
    queryFn: () =>
      ProjectsService.getProjectContents({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        path: release.path,
        ref: gitRev,
      }),
    enabled: !isWholeProject && Boolean(release.path),
    retry: false,
  })
  const item = contentQuery.data
  const downloadHref = item
    ? item.url ??
      (item.content
        ? `data:application/octet-stream;base64,${item.content}`
        : undefined)
    : undefined
  const downloadName = release.path
    ? releaseDownloadName(loc.projectName, release.name, release.path)
    : undefined

  return (
    <Flex direction="column" h="100%">
      <Flex
        as="header"
        align="center"
        justify="space-between"
        px={4}
        py={2}
        borderBottomWidth="1px"
        gap={3}
        flexWrap="wrap"
      >
        <Box minW={0}>
          <Heading size="sm" noOfLines={1}>
            {release.name}
          </Heading>
          <Text fontSize="xs" color="gray.500" noOfLines={1}>
            {loc.ownerName} / {loc.projectName}
            {isWholeProject ? " · whole project" : ` · ${release.path}`}
          </Text>
        </Box>
        <HStack spacing={3} flexShrink={0}>
          {refLabel && (
            <HStack spacing={1}>
              <Text fontSize="sm" color="gray.500">
                Version
              </Text>
              <Badge>{refLabel}</Badge>
            </HStack>
          )}
          <BrowseProjectButton
            loc={loc}
            gitRev={gitRev}
            alwaysShow={isWholeProject}
          />
          {downloadHref && downloadName && (
            <DownloadButton href={downloadHref} name={downloadName} />
          )}
          {onClose && (
            <IconButton
              aria-label="Close"
              icon={<FiX />}
              size="sm"
              variant="ghost"
              onClick={onClose}
            />
          )}
        </HStack>
      </Flex>

      <Flex flex={1} minH={0}>
        <Box flex={1} minW={0}>
          {isWholeProject ? (
            <WholeProjectView
              loc={loc}
              gitRev={gitRev}
              fallback={
                <Flex
                  align="center"
                  justify="center"
                  h="100%"
                  p={6}
                  textAlign="center"
                >
                  <Text fontSize="sm" color="gray.500">
                    This release is the whole project at{" "}
                    <Badge>{refLabel || "this commit"}</Badge>. Use “Browse
                    project at this version” above to explore it.
                  </Text>
                </Flex>
              }
            />
          ) : contentQuery.isPending ? (
            <LoadingSpinner height="100%" />
          ) : item ? (
            <ArtifactView
              path={release.path ?? ""}
              item={item}
              kind={release.kind}
            />
          ) : (
            <Flex align="center" justify="center" h="100%" p={4}>
              <Alert status="warning" borderRadius="lg" maxW="md">
                <AlertIcon />
                Couldn't load the released file.
              </Alert>
            </Flex>
          )}
        </Box>

        <Flex
          w="340px"
          flexShrink={0}
          borderLeftWidth="1px"
          direction="column"
          minH={0}
        >
          <Box p={4} borderBottomWidth="1px">
            <VStack align="stretch" spacing={4}>
              <Box>
                <Text fontSize="xs" color="gray.500" textTransform="uppercase">
                  Location
                </Text>
                <HStack mt={1}>
                  <Badge colorScheme={dest.internal ? "blue" : "purple"}>
                    {dest.label}
                  </Badge>
                  {dest.href && (
                    <Link
                      href={dest.href}
                      isExternal
                      color="blue.500"
                      fontSize="sm"
                      display="inline-flex"
                      alignItems="center"
                      gap={1}
                    >
                      {release.doi ?? "View"}
                      <Icon as={FiExternalLink} />
                    </Link>
                  )}
                </HStack>
              </Box>
              {release.kind && (
                <Box>
                  <Text
                    fontSize="xs"
                    color="gray.500"
                    textTransform="uppercase"
                  >
                    Kind
                  </Text>
                  <Text fontSize="sm">{release.kind}</Text>
                </Box>
              )}
              {release.date && (
                <Box>
                  <Text
                    fontSize="xs"
                    color="gray.500"
                    textTransform="uppercase"
                  >
                    Released
                  </Text>
                  <Text fontSize="sm">{formatReleaseDate(release.date)}</Text>
                </Box>
              )}
              {release.description && (
                <Box>
                  <Text
                    fontSize="xs"
                    color="gray.500"
                    textTransform="uppercase"
                  >
                    Description
                  </Text>
                  <Box fontSize="sm">
                    <Markdown>{release.description}</Markdown>
                  </Box>
                </Box>
              )}
            </VStack>
          </Box>
          <Box flex={1} minH={0} p={4}>
            <MemberCommentsPanel loc={loc} release={release} />
          </Box>
        </Flex>
      </Flex>
    </Flex>
  )
}

function CloudReleaseView({
  loc,
  release,
  onClose,
}: {
  loc: ReleaseLocator
  release: ReleaseView
  onClose?: () => void
}) {
  const isWholeProject = !release.path || release.path === "."
  const contentQuery = useQuery({
    queryKey: [
      "releases",
      loc.ownerName,
      loc.projectName,
      loc.releaseName,
      "content",
    ],
    queryFn: () =>
      ReleasesService.getReleaseContent({
        ownerName: loc.ownerName,
        projectName: loc.projectName,
        releaseName: loc.releaseName,
        token: loc.token,
      }),
    enabled: Boolean(release.path) && !isWholeProject,
    retry: false,
  })

  const refLabel = release.git_ref ?? release.git_rev_abbrev ?? ""
  const gitRev = release.git_ref ?? release.git_rev_abbrev ?? undefined
  const item = contentQuery.data
  const downloadHref = item
    ? item.url ??
      (item.content
        ? `data:application/octet-stream;base64,${item.content}`
        : undefined)
    : undefined
  const downloadName = release.path
    ? releaseDownloadName(loc.projectName, release.name, release.path)
    : undefined
  // A single-file PDF release (not a slide deck) gets the annotatable viewer so
  // reviewers can leave comments anchored to highlights, pinned to this version.
  const isPdfArtifact =
    (release.path ?? "").toLowerCase().endsWith(".pdf") &&
    release.kind !== "presentation"
  const pdfSrc = item && isPdfArtifact ? dataUri(item, "application/pdf") : null
  // Every release accepts comments; whether this viewer may post is decided by
  // their permission (share-link view/comment scope, or membership).
  const canComment =
    release.permission === "comment" || release.permission === "manage"

  return (
    <Flex direction="column" h="100%">
      {/* Header / provenance bar */}
      <Flex
        as="header"
        align="center"
        justify="space-between"
        px={4}
        py={2}
        borderBottomWidth="1px"
        gap={3}
        flexWrap="wrap"
      >
        <Box minW={0}>
          <Heading size="sm" noOfLines={1}>
            {release.name}
          </Heading>
          <Text fontSize="xs" color="gray.500" noOfLines={1}>
            {release.owner_account_display_name} / {release.project_name}
            {isWholeProject ? " · whole project" : ` · ${release.path}`}
          </Text>
        </Box>
        <HStack spacing={3} flexShrink={0}>
          <HStack spacing={1}>
            <Text fontSize="sm" color="gray.500">
              Version
            </Text>
            <Badge>{refLabel}</Badge>
          </HStack>
          <BrowseProjectButton
            loc={loc}
            gitRev={gitRev}
            alwaysShow={isWholeProject}
          />
          {downloadHref && downloadName && (
            <DownloadButton href={downloadHref} name={downloadName} />
          )}
          {onClose && (
            <IconButton
              aria-label="Close"
              icon={<FiX />}
              size="sm"
              variant="ghost"
              onClick={onClose}
            />
          )}
        </HStack>
      </Flex>

      {/* Body: artifact + optional comments */}
      <Flex flex={1} minH={0}>
        <Box flex={1} minW={0}>
          {isWholeProject ? (
            <WholeProjectView
              loc={loc}
              gitRev={gitRev}
              fallback={<ProjectBrowser loc={loc} />}
            />
          ) : contentQuery.isPending ? (
            <LoadingSpinner height="100%" />
          ) : pdfSrc ? (
            <ReleasePdfAnnotator
              url={pdfSrc}
              ownerName={loc.ownerName}
              projectName={loc.projectName}
              releaseName={loc.releaseName}
              token={loc.token}
              canComment={canComment}
            />
          ) : item ? (
            <ArtifactView
              path={release.path ?? ""}
              item={item}
              kind={release.kind}
            />
          ) : (
            <Flex align="center" justify="center" h="100%" p={4}>
              <Alert status="warning" borderRadius="lg" maxW="md">
                <AlertIcon />
                Couldn't load the released file.
              </Alert>
            </Flex>
          )}
        </Box>
        <Box
          w="340px"
          flexShrink={0}
          borderLeftWidth="1px"
          p={4}
          overflowY="auto"
        >
          <CommentsPanel loc={loc} release={release} />
        </Box>
      </Flex>
    </Flex>
  )
}
