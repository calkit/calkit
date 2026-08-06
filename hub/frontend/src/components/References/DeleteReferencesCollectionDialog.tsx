import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRef } from "react"

import { type ApiError, ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface DeleteReferencesCollectionDialogProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  path: string
  // Called after a successful delete (e.g. to clear the selected collection).
  onDeleted?: () => void
}

const DeleteReferencesCollectionDialog = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  path,
  onDeleted,
}: DeleteReferencesCollectionDialogProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const cancelRef = useRef<HTMLButtonElement | null>(null)
  const mutation = useMutation({
    mutationFn: () =>
      ProjectsService.deleteProjectReferences({
        ownerName,
        projectName,
        path,
      }),
    onSuccess: () => {
      showToast("Success!", "References collection deleted.", "success")
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "references"],
      })
      onDeleted?.()
      onClose()
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })

  return (
    <AlertDialog
      isOpen={isOpen}
      onClose={onClose}
      leastDestructiveRef={cancelRef}
      isCentered
    >
      <AlertDialogOverlay>
        <AlertDialogContent>
          <AlertDialogHeader>Delete references collection</AlertDialogHeader>
          <AlertDialogBody>
            Delete <strong>{path}</strong>? This removes the .bib file and
            unlinks it from Zotero (the Zotero collection itself is left
            untouched). It's committed to Git, so you can restore it from the
            project history if needed.
          </AlertDialogBody>
          <AlertDialogFooter gap={3}>
            <Button
              variant="danger"
              isLoading={mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              Delete
            </Button>
            <Button
              ref={cancelRef}
              onClick={onClose}
              isDisabled={mutation.isPending}
            >
              Cancel
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialogOverlay>
    </AlertDialog>
  )
}

export default DeleteReferencesCollectionDialog
