// Edit the whole `pipeline` block of calkit.yaml and commit it. Only that
// block is sent, so the datasets, figures, and publications sitting beside it
// in the same file can't be disturbed by an edit here. The backend validates
// against the same pipeline model the CLI uses, but writes back what was
// typed — key order and comments survive.
import {
  Badge,
  Box,
  Button,
  Flex,
  Input,
  Kbd,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Text,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import type { EditorView } from "codemirror"
import { useEffect, useRef, useState } from "react"

import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { refreshProjectContents } from "../../lib/api"
import { handleError } from "../../lib/errors"
import { trimForSave } from "../../lib/strings"
import CodeEditorPane from "../Common/CodeEditorPane"
import DiscardChangesDialog from "../Common/DiscardChangesDialog"

interface PipelineEditorModalProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  // The same YAML the page renders, passed in rather than re-fetched: the
  // pipeline endpoint compiles the diagram and statuses to answer, which is
  // a lot of work for text the page already has.
  content: string
}

const PipelineEditorModal = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  content,
}: PipelineEditorModalProps) => {
  const viewRef = useRef<EditorView | null>(null)
  // The current text lives in a ref so every keystroke doesn't re-render the
  // modal; `dirty` is the only thing the UI needs from it.
  const textRef = useRef<string>(content)
  const baseRef = useRef<string>(content)
  const commitInputRef = useRef<HTMLInputElement>(null)
  const [dirty, setDirty] = useState(false)
  // Pre-filled so saving is one keystroke away and the history stays
  // readable for anyone who doesn't stop to write one.
  const defaultMessage = "Update pipeline"
  const [commitMessage, setCommitMessage] = useState(defaultMessage)
  // Bumped to remount the editor when the pipeline is replaced under it.
  const [docNonce, setDocNonce] = useState(0)
  // What `content` was when the editor last loaded it. A background refetch
  // of the page's pipeline changes the prop while the modal is open, and
  // reloading on that would throw away whatever is being typed.
  const loadedRef = useRef<string | null>(null)
  const commitModal = useDisclosure()
  const discardDialog = useDisclosure()
  const showToast = useCustomToast()
  const queryClient = useQueryClient()

  // A save refetches the page's pipeline, so `content` comes back as what
  // was committed; reopening then starts from that rather than the old text.
  useEffect(() => {
    if (!isOpen) {
      loadedRef.current = null
      return
    }
    if (loadedRef.current !== null) {
      return
    }
    loadedRef.current = content
    textRef.current = content
    baseRef.current = content
    setDirty(false)
    setDocNonce((n) => n + 1)
  }, [isOpen, content])

  const saveMutation = useMutation({
    mutationFn: async (message: string) => {
      const saved = await ProjectsService.putProjectPipeline({
        owner_name: ownerName,
        project_name: projectName,
        pipelinePut: {
          yaml: trimForSave(textRef.current, loadedRef.current ?? content),
          message: message || null,
        },
      }).then((response) => response.data)
      // Part of the save rather than a follow-up, so the button keeps
      // spinning until a read can see the commit. Closing on the write alone
      // put the pipeline back in view still showing the old YAML.
      await refreshProjectContents(ownerName, projectName, queryClient)
      return saved
    },
    onSuccess: () => {
      setDirty(false)
      setCommitMessage(defaultMessage)
      commitModal.onClose()
      showToast("Saved", "Your changes were committed.", "success")
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })

  const requestSave = () => {
    if (saveMutation.isPending) {
      return
    }
    if (textRef.current !== baseRef.current) {
      commitModal.onOpen()
    }
  }

  // Ctrl/Cmd+S saves, matching the other editors.
  // biome-ignore lint/correctness/useExhaustiveDependencies: requestSave reads refs
  useEffect(() => {
    if (!isOpen) {
      return
    }
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault()
        requestSave()
      }
    }
    document.addEventListener("keydown", handler, true)
    return () => document.removeEventListener("keydown", handler, true)
  }, [isOpen])

  const handleClose = () => {
    if (dirty) {
      discardDialog.onOpen()
      return
    }
    onClose()
  }

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        size={{ base: "full", md: "3xl" }}
        isCentered
        motionPreset="none"
      >
        <ModalOverlay />
        <ModalContent maxH="90vh">
          <Flex align="center" gap={3} px={4} py={2} borderBottomWidth="1px">
            <Text fontWeight="bold">Pipeline</Text>
            {dirty && (
              <Badge colorScheme="orange" variant="subtle">
                unsaved
              </Badge>
            )}
            <Button
              size="sm"
              variant="primary"
              onClick={requestSave}
              isDisabled={!dirty}
              isLoading={saveMutation.isPending}
            >
              Save
            </Button>
            <Text fontSize="xs" color="ui.dim" whiteSpace="nowrap">
              <Kbd>⌘</Kbd>+<Kbd>Enter</Kbd> to save
            </Text>
            <Box flex="1" />
            <ModalCloseButton position="static" />
          </Flex>
          <ModalBody p={0} overflow="hidden">
            <Box height="60vh">
              <CodeEditorPane
                key={docNonce}
                initialDoc={loadedRef.current ?? content}
                path="calkit.yaml"
                viewRef={viewRef}
                onChange={(text) => {
                  textRef.current = text
                  setDirty(text !== baseRef.current)
                }}
                onModEnter={requestSave}
              />
            </Box>
          </ModalBody>
        </ModalContent>
      </Modal>
      <Modal
        isOpen={commitModal.isOpen}
        onClose={commitModal.onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
        initialFocusRef={commitInputRef}
        motionPreset="none"
      >
        <ModalOverlay />
        <ModalContent
          as="form"
          onSubmit={(e) => {
            e.preventDefault()
            saveMutation.mutate(commitMessage)
          }}
        >
          <ModalHeader>Describe your change</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <Input
              autoComplete="off"
              ref={commitInputRef}
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              placeholder={defaultMessage}
            />
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="primary"
              type="submit"
              isLoading={saveMutation.isPending}
            >
              Save
            </Button>
            <Button onClick={commitModal.onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      <DiscardChangesDialog
        isOpen={discardDialog.isOpen}
        onKeepEditing={discardDialog.onClose}
        onDiscard={() => {
          discardDialog.onClose()
          onClose()
        }}
      />
    </>
  )
}

export default PipelineEditorModal
