import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Heading,
  Link,
  Text,
  VStack,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { FaSync, FaTrash } from "react-icons/fa"

import { type ApiError, ProjectsService, type References } from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import CommentsPanel, {
  projectCommentToPanelComment,
} from "../Common/CommentsPanel"
import DeleteReferencesCollectionDialog from "./DeleteReferencesCollectionDialog"

interface ReferencesInfoPanelProps {
  references: References
  ownerName: string
  projectName: string
  gitRef?: string
  userHasWriteAccess: boolean
  showResolved: boolean
  onShowResolvedChange: (showResolved: boolean) => void
  // Called after the collection is deleted (e.g. to clear the selection).
  onDeleted?: () => void
}

// Info + comments panel for a selected references collection, mirroring the
// publications page's info panel.
const ReferencesInfoPanel = ({
  references,
  ownerName,
  projectName,
  gitRef,
  userHasWriteAccess,
  showResolved,
  onShowResolvedChange,
  onDeleted,
}: ReferencesInfoPanelProps) => {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { user } = useAuth()
  const deleteDisclosure = useDisclosure()
  const path = references.path
  const stages = references.stages ?? []
  const zoteroSyncMutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectZoteroSync({
        ownerName,
        projectName,
        requestBody: { path },
      }),
    onSuccess: (data) => {
      showToast(
        "Success!",
        data.committed
          ? "Synced references from Zotero."
          : "Already up to date with Zotero.",
        "success",
      )
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "references"],
      })
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })
  const commentsKey = [
    "projects",
    ownerName,
    projectName,
    "comments",
    "references",
    path,
  ]
  const commentsQuery = useQuery({
    queryKey: commentsKey,
    queryFn: () =>
      ProjectsService.getProjectComments({
        ownerName,
        projectName,
        artifactType: "references",
        artifactPath: path,
      }),
    enabled: Boolean(path),
  })
  const invalidateComments = () =>
    queryClient.invalidateQueries({ queryKey: commentsKey })
  const postCommentMutation = useMutation({
    mutationFn: (vars: { body: string; createIssue: boolean }) =>
      ProjectsService.postProjectComment({
        ownerName,
        projectName,
        requestBody: {
          artifact_path: path,
          artifact_type: "references",
          comment: vars.body,
          create_github_issue: vars.createIssue,
          git_ref: gitRef ?? null,
        },
      }),
    onSuccess: invalidateComments,
  })
  const replyCommentMutation = useMutation({
    mutationFn: (vars: { commentId: string; body: string }) =>
      ProjectsService.postProjectCommentReply({
        ownerName,
        projectName,
        commentId: vars.commentId,
        requestBody: { body: vars.body },
      }),
    onSuccess: invalidateComments,
  })
  const resolveCommentMutation = useMutation({
    mutationFn: (vars: { commentId: string; resolved: boolean }) =>
      ProjectsService.patchProjectComment({
        ownerName,
        projectName,
        commentId: vars.commentId,
        requestBody: { resolved: vars.resolved },
      }),
    onSuccess: invalidateComments,
  })
  const comments = commentsQuery.data ?? []

  return (
    <VStack align="stretch" spacing={3}>
      <Box bg={secBgColor} borderRadius="lg" p={3} h="fit-content">
        <Heading size="sm" mb={2}>
          Info
        </Heading>
        <Text fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Path:
          </Text>{" "}
          <Link as={RouterLink} to="../files" search={{ path } as any}>
            {path}
          </Link>
        </Text>
        <Box fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Input for stage:
          </Text>{" "}
          {stages.length > 0 ? (
            <Flex as="span" display="inline-flex" gap={1} wrap="wrap">
              {stages.map((stage) => (
                <Link
                  key={stage}
                  as={RouterLink}
                  to="../pipeline"
                  search={{ stage } as any}
                >
                  <Code fontSize="xs" cursor="pointer">
                    {stage}
                  </Code>
                </Link>
              ))}
            </Flex>
          ) : (
            <Text as="span" color="gray.500">
              None
            </Text>
          )}
        </Box>
        {references.zotero ? (
          <Box mt={2}>
            <Text fontSize="sm" mb={1}>
              <Text as="span" fontWeight="semibold">
                Zotero:
              </Text>{" "}
              <Text as="span" color="gray.500">
                {references.zotero.collection_name ??
                  references.zotero.collection_key}
              </Text>
              <Badge ml={1} colorScheme="red" fontSize="0.6em">
                Linked
              </Badge>
            </Text>
            {references.zotero.last_synced ? (
              <Text fontSize="xs" color="gray.500" mb={1}>
                Last synced{" "}
                {new Date(references.zotero.last_synced).toLocaleString()}
              </Text>
            ) : null}
            {userHasWriteAccess ? (
              <Button
                size="xs"
                onClick={() => zoteroSyncMutation.mutate()}
                isLoading={zoteroSyncMutation.isPending}
                rightIcon={<FaSync />}
              >
                Sync
              </Button>
            ) : null}
          </Box>
        ) : null}
        {userHasWriteAccess ? (
          <Button
            size="xs"
            mt={3}
            variant="ghost"
            colorScheme="red"
            leftIcon={<FaTrash />}
            onClick={deleteDisclosure.onOpen}
          >
            Delete collection
          </Button>
        ) : null}
      </Box>
      {userHasWriteAccess ? (
        <DeleteReferencesCollectionDialog
          isOpen={deleteDisclosure.isOpen}
          onClose={deleteDisclosure.onClose}
          ownerName={ownerName}
          projectName={projectName}
          path={path}
          onDeleted={onDeleted}
        />
      ) : null}
      <CommentsPanel
        comments={comments.map(projectCommentToPanelComment)}
        isLoading={commentsQuery.isPending}
        canComment={!!user}
        canResolve={!!user}
        showResolved={showResolved}
        onShowResolvedChange={onShowResolvedChange}
        showCreateIssueCheckbox
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
    </VStack>
  )
}

export default ReferencesInfoPanel
