import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogCloseButton,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
} from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import { useRef } from "react"

import useCustomToast from "../../hooks/useCustomToast"

interface DiscardChangesProps {
  request: (type: string, fields?: object) => Promise<any>
  onDone: () => void
  isOpen: boolean
  onClose: () => void
}

const DiscardChanges = ({
  isOpen,
  onClose,
  request,
  onDone,
}: DiscardChangesProps) => {
  const showToast = useCustomToast()
  const mutation = useMutation({
    mutationFn: () => {
      return request("workspace.discard")
    },
    onSuccess: () => {
      showToast("Success!", "Changes discarded.", "success")
      onClose()
    },
    onError: (err: Error) => {
      showToast("Error", err.message, "error")
    },
    onSettled: onDone,
  })
  const cancelRef = useRef<HTMLButtonElement | null>(null)

  return (
    <>
      <AlertDialog
        isOpen={isOpen}
        leastDestructiveRef={cancelRef}
        onClose={onClose}
        isCentered
        motionPreset="none"
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader fontSize="lg" fontWeight="bold">
              Discard changes
            </AlertDialogHeader>
            <AlertDialogCloseButton />
            <AlertDialogBody>
              Are you sure? You can't undo this action afterwards.
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button
                variant="danger"
                type="submit"
                onClick={() => mutation.mutate()}
                isLoading={mutation.isPending}
              >
                Discard
              </Button>
              <Button
                ref={cancelRef}
                onClick={onClose}
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  )
}

export default DiscardChanges
