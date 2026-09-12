import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Heading,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Text,
  VStack,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { FaSync, FaTrash } from "react-icons/fa"

import type { AxiosError } from "axios"
import { ProjectsService, type References } from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError, isProviderNotConnected } from "../../lib/errors"
import ConnectZoteroPrompt from "../Common/ConnectZoteroPrompt"
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
  const connectZoteroDisclosure = useDisclosure()
  const path = references.path
  const stages = references.stages ?? []
  const zoteroSyncMutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectZoteroSync({
        owner_name: ownerName,
        project_name: projectName,
        zoteroSyncPost: { path },
      }).then((response) => response.data),
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
    onError: (err: AxiosError) => {
      // A missing Zotero connection isn't an error to report, it's a
      // connect button; the modal below offers it in place of a toast
      // that says what's wrong but not what to do.
      if (isProviderNotConnected(err, "Zotero")) {
        connectZoteroDisclosure.onOpen()
        return
      }
      handleError(err, showToast)
    },
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
        owner_name: ownerName,
        project_name: projectName,
        artifact_type: "references",
        artifact_path: path,
      }).then((response) => response.data),
    enabled: Boolean(path),
  })
  const invalidateComments = () =>
    queryClient.invalidateQueries({ queryKey: commentsKey })
  const postCommentMutation = useMutation({
    mutationFn: (vars: { body: string; createIssue: boolean }) =>
      ProjectsService.postProjectComment({
        owner_name: ownerName,
        project_name: projectName,
        projectCommentPost: {
          artifact_path: path,
          artifact_type: "references",
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
        owner_name: ownerName,
        project_name: projectName,
        comment_id: vars.commentId,
        commentReply: { body: vars.body },
      }).then((response) => response.data),
    onSuccess: invalidateComments,
  })
  const resolveCommentMutation = useMutation({
    mutationFn: (vars: { commentId: string; resolved: boolean }) =>
      ProjectsService.patchProjectComment({
        owner_name: ownerName,
        project_name: projectName,
        comment_id: vars.commentId,
        projectCommentPatch: { resolved: vars.resolved },
      }).then((response) => response.data),
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
                  <Code fontSize="xs" cursor="pointer" wordBreak="break-all">
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
      <Modal
        isOpen={connectZoteroDisclosure.isOpen}
        onClose={connectZoteroDisclosure.onClose}
        isCentered
      >
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Connect Zotero</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <ConnectZoteroPrompt action="sync this collection" />
          </ModalBody>
        </ModalContent>
      </Modal>
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
