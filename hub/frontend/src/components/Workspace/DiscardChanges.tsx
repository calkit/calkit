import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogCloseButton,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
  Code,
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
    onSuccess: (result: { stashed?: boolean; moved_to?: string | null }) => {
      const kept = [
        result?.stashed ? "Git changes are in the stash" : "",
        result?.moved_to ? `changed data is in ${result.moved_to}` : "",
      ].filter(Boolean)
      showToast(
        "Changes discarded",
        kept.length ? `To get them back: ${kept.join("; ")}.` : "",
        "success",
      )
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
              This puts the workspace back to its last commit. Changes to files
              tracked with Git are stashed, so <Code>git stash pop</Code> brings
              them back, and changed data tracked with DVC is moved to{" "}
              <Code>.calkit/local/discarded</Code>. New files are left alone.
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
