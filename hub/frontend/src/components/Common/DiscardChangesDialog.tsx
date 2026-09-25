// The confirmation for leaving unsaved work behind. Shared rather than
// repeated: the browser's own confirm() can't say what is about to be lost,
// can't be styled, and looks like the page has been taken over by something
// else at the moment someone is deciding whether to throw away their work.
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
} from "@chakra-ui/react"
import type { ReactNode } from "react"
import { useRef } from "react"

interface DiscardChangesDialogProps {
  isOpen: boolean
  /** "Keep editing": the work stays and the editor stays open. */
  onKeepEditing: () => void
  /** "Discard": the work goes and whatever was being left goes ahead. */
  onDiscard: () => void
  title?: string
  children?: ReactNode
}

const DiscardChangesDialog = ({
  isOpen,
  onKeepEditing,
  onDiscard,
  title = "Discard unsaved changes?",
  children = "These edits haven't been committed.",
}: DiscardChangesDialogProps) => {
  // Focus lands on "Keep editing", so a stray Enter keeps the work.
  const keepEditingRef = useRef<HTMLButtonElement>(null)
  return (
    <AlertDialog
      isOpen={isOpen}
      leastDestructiveRef={keepEditingRef}
      onClose={onKeepEditing}
      isCentered
      // No fade: see EditQuestion
      motionPreset="none"
    >
      <AlertDialogOverlay>
        <AlertDialogContent>
          <AlertDialogHeader fontSize="lg">{title}</AlertDialogHeader>
          <AlertDialogBody>{children}</AlertDialogBody>
          <AlertDialogFooter gap={3}>
            <Button ref={keepEditingRef} onClick={onKeepEditing}>
              Keep editing
            </Button>
            <Button colorScheme="red" onClick={onDiscard}>
              Discard
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialogOverlay>
    </AlertDialog>
  )
}

export default DiscardChangesDialog
