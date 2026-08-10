// Edit one pipeline stage's YAML and commit it. The backend validates against
// the same stage models the CLI uses, but writes back what was typed — key
// order and comments survive. Detecting inputs and dropping default-valued
// keys are buttons, so neither happens to the user's file uninvited.
import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { EditorView } from "codemirror"
import { useEffect, useMemo, useRef, useState } from "react"

import type { AxiosError } from "axios"
import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { refreshProjectContents } from "../../lib/api"
import { handleError } from "../../lib/errors"
import { stageKindFromYaml } from "../../lib/pipelineYaml"
import { trimForSave } from "../../lib/strings"
import CodeEditorPane from "../Common/CodeEditorPane"

interface StageEditorModalProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  stageName: string
}

const StageEditorModal = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  stageName,
}: StageEditorModalProps) => {
  const viewRef = useRef<EditorView | null>(null)
  // The current text lives in a ref so every keystroke doesn't re-render the
  // modal; `dirty` is the only thing the UI needs from it.
  const textRef = useRef<string>("")
  const baseRef = useRef<string>("")
  const commitInputRef = useRef<HTMLInputElement>(null)
  const [dirty, setDirty] = useState(false)
  const [commitMessage, setCommitMessage] = useState("")
  // Bumped to remount the editor with content we replaced wholesale (the
  // stage as loaded, or as returned by input detection).
  const [docNonce, setDocNonce] = useState(0)
  const [doc, setDoc] = useState<string | null>(null)
  const commitModal = useDisclosure()
  const showToast = useCustomToast()
  const queryClient = useQueryClient()

  const {
    data: stage,
    isPending,
    error: loadError,
  } = useQuery({
    queryKey: ["projects", ownerName, projectName, "pipeline-stage", stageName],
    queryFn: () =>
      ProjectsService.getProjectPipelineStage({
        owner_name: ownerName,
        project_name: projectName,
        stage_name: stageName,
      }).then((response) => response.data),
    enabled: isOpen,
    staleTime: 0,
  })

  // Load the stage into the editor, and reset when switching stages.
  useEffect(() => {
    if (stage?.yaml !== undefined) {
      textRef.current = stage.yaml
      baseRef.current = stage.yaml
      setDoc(stage.yaml)
      setDirty(false)
      setDocNonce((n) => n + 1)
    }
  }, [stage?.yaml])

  const replaceDoc = (next: string) => {
    textRef.current = next
    setDoc(next)
    setDirty(next !== baseRef.current)
    setDocNonce((n) => n + 1)
  }

  const detectMutation = useMutation({
    mutationFn: () =>
      ProjectsService.detectProjectPipelineStageInputs({
        owner_name: ownerName,
        project_name: projectName,
        stage_name: stageName,
        pipelineStageEdit: { yaml: trimForSave(textRef.current, stage?.yaml) },
      }).then((response) => response.data),
    onSuccess: (result) => {
      replaceDoc(result.yaml)
      showToast(
        result.changed.length > 0 ? "Inputs added" : "Nothing to add",
        result.changed.length > 0
          ? `Added ${result.changed.join(", ")}. Save to commit.`
          : "Every file the document reads is already declared or covered " +
              "by a directory that is.",
        "success",
      )
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })

  const removeDefaultsMutation = useMutation({
    mutationFn: () =>
      ProjectsService.removeProjectPipelineStageDefaults({
        owner_name: ownerName,
        project_name: projectName,
        stage_name: stageName,
        pipelineStageEdit: { yaml: trimForSave(textRef.current, stage?.yaml) },
      }).then((response) => response.data),
    onSuccess: (result) => {
      replaceDoc(result.yaml)
      showToast(
        result.changed.length > 0 ? "Keys removed" : "Nothing to remove",
        result.changed.length > 0
          ? `Removed ${result.changed.join(", ")}. Save to commit.`
          : "No keys are left at their default value.",
        "success",
      )
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })

  const saveMutation = useMutation({
    mutationFn: (message: string) =>
      ProjectsService.putProjectPipelineStage({
        owner_name: ownerName,
        project_name: projectName,
        stage_name: stageName,
        pipelineStagePut: {
          yaml: trimForSave(textRef.current, stage?.yaml),
          message: message || null,
        },
      }).then((response) => response.data),
    onSuccess: (saved) => {
      // The saved stage comes back normalized, so show what actually landed
      // in calkit.yaml rather than what was typed.
      baseRef.current = saved.yaml
      replaceDoc(saved.yaml)
      setDirty(false)
      setCommitMessage("")
      commitModal.onClose()
      showToast("Saved", `Stage ${stageName} was updated.`, "success")
      refreshProjectContents(ownerName, projectName, queryClient)
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })

  const requestSave = () => {
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
    if (dirty && !window.confirm("Discard unsaved changes?")) {
      return
    }
    onClose()
  }

  // Detection only means something for a LaTeX document; for any other kind
  // the backend has nothing to look for. Parsed rather than pattern-matched,
  // so a trailing comment, quotes, or odd spacing around the value don't hide
  // the button, and a kind that merely ends in "latex" (json-to-latex) doesn't
  // wrongly show it. `doc` only changes when content is loaded or replaced
  // wholesale, so this isn't re-parsed on every keystroke.
  const isLatexStage = useMemo(
    () => stageKindFromYaml(doc ?? "") === "latex",
    [doc],
  )

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        size={{ base: "full", md: "3xl" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent maxH="90vh">
          <Flex align="center" gap={3} px={4} py={2} borderBottomWidth="1px">
            <Text fontWeight="bold">
              Stage <Code>{stageName}</Code>
            </Text>
            {dirty && (
              <Badge colorScheme="orange" variant="subtle">
                unsaved
              </Badge>
            )}
            {isLatexStage && (
              <Button
                size="sm"
                onClick={() => detectMutation.mutate()}
                isLoading={detectMutation.isPending}
                title="Add the class, style, bibliography, and figure files the document reads"
              >
                Re-detect inputs
              </Button>
            )}
            <Button
              size="sm"
              onClick={() => removeDefaultsMutation.mutate()}
              isLoading={removeDefaultsMutation.isPending}
              title="Drop keys left at their default value, e.g. the nulls older versions wrote out"
            >
              Remove defaults
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={requestSave}
              isDisabled={!dirty}
              isLoading={saveMutation.isPending}
            >
              Save
            </Button>
            <Box flex="1" />
            <ModalCloseButton position="static" />
          </Flex>
          <ModalBody p={0} overflow="hidden">
            {loadError ? (
              // Without this the modal sits on a spinner forever, since the
              // query is no longer pending but never produced a document.
              <Flex height="60vh" align="center" justify="center" px={6}>
                <Text color="red.400" textAlign="center">
                  This stage couldn't be loaded for editing. Stages Calkit
                  generates, and any written directly in dvc.yaml, aren't in
                  calkit.yaml and so can't be edited here.
                </Text>
              </Flex>
            ) : isPending || doc === null ? (
              <Flex height="60vh" align="center" justify="center">
                <Spinner />
              </Flex>
            ) : (
              <Box height="60vh">
                <CodeEditorPane
                  key={`${stageName}:${docNonce}`}
                  initialDoc={doc}
                  path="stage.yaml"
                  viewRef={viewRef}
                  onChange={(text) => {
                    textRef.current = text
                    setDirty(text !== baseRef.current)
                  }}
                />
              </Box>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
      <Modal
        isOpen={commitModal.isOpen}
        onClose={commitModal.onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
        initialFocusRef={commitInputRef}
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
              ref={commitInputRef}
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              placeholder="Ex: Declare the paper's class file as an input"
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
    </>
  )
}

export default StageEditorModal
