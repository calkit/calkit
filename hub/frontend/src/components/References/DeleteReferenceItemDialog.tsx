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

import type { AxiosError } from "axios"
import { ProjectsService, type ReferenceEntry } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface DeleteReferenceItemDialogProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  bibPath: string
  entry?: ReferenceEntry
}

const DeleteReferenceItemDialog = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  bibPath,
  entry,
}: DeleteReferenceItemDialogProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const cancelRef = useRef<HTMLButtonElement | null>(null)
  const mutation = useMutation({
    mutationFn: () =>
      ProjectsService.deleteProjectReferenceItem({
        owner_name: ownerName,
        project_name: projectName,
        bib_key: entry!.key,
        path: bibPath,
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Reference deleted.", "success")
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "references"],
      })
      onClose()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
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
          <AlertDialogHeader>Delete reference</AlertDialogHeader>
          <AlertDialogBody>
            Delete <strong>{entry?.key}</strong> from this collection? It's
            committed to Git, so you can restore it from the project history if
            needed.
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

export default DeleteReferenceItemDialog
