// Edit a text file in the project and commit it, without leaving the app.
// The LaTeX editor is the specialized version of this for papers; this is the
// general one, for calkit.yaml, scripts, READMEs, and anything else textual.
import {
  Badge,
  Box,
  Button,
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
import { useEffect, useRef, useState } from "react"

import type { AxiosError } from "axios"
import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { refreshProjectContents } from "../../lib/api"
import { handleError } from "../../lib/errors"
import { decodeBase64Utf8, trimForSave } from "../../lib/strings"
import CodeEditorPane from "../Common/CodeEditorPane"

// Extensions and bare filenames the built-in editor will open. Deliberately a
// list rather than "anything that isn't a known binary": opening a file that
// turns out to be binary would show mojibake and saving it would corrupt it.
const EDITABLE_EXTS = new Set([
  "bib",
  "bst",
  "cfg",
  "cls",
  "cff",
  "clo",
  "csv",
  "def",
  "html",
  "ini",
  "jl",
  "js",
  "json",
  "lock",
  "m",
  "md",
  "properties",
  "py",
  "qmd",
  "r",
  "rmd",
  "sh",
  "sty",
  "tex",
  "toml",
  "ts",
  "tsv",
  "txt",
  "yaml",
  "yml",
])
const EDITABLE_NAMES = new Set([
  ".dvcignore",
  ".gitignore",
  "dockerfile",
  "license",
  "makefile",
  "readme",
])

export function isEditableText(path: string): boolean {
  const name = (path.split("/").pop() ?? "").toLowerCase()
  if (EDITABLE_NAMES.has(name)) {
    return true
  }
  const i = name.lastIndexOf(".")
  return i > 0 && EDITABLE_EXTS.has(name.slice(i + 1))
}

interface FileEditorModalProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  path: string
}

const FileEditorModal = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  path,
}: FileEditorModalProps) => {
  const viewRef = useRef<EditorView | null>(null)
  // The current text lives in a ref so every keystroke doesn't re-render the
  // modal; `dirty` is the only thing the UI needs from it.
  const textRef = useRef<string>("")
  const baseRef = useRef<string>("")
  const commitInputRef = useRef<HTMLInputElement>(null)
  const [dirty, setDirty] = useState(false)
  const [commitMessage, setCommitMessage] = useState("")
  const commitModal = useDisclosure()
  const showToast = useCustomToast()
  const queryClient = useQueryClient()

  const { data: initialDoc, isPending } = useQuery({
    queryKey: ["projects", ownerName, projectName, "file-editor", path],
    queryFn: async () => {
      const res = await ProjectsService.getProjectContents({
        owner_name: ownerName,
        project_name: projectName,
        path,
      }).then((response) => response.data)
      // Files over the API's inline-content limit come back as a signed URL
      // with no content, so fetch those rather than opening an empty editor.
      if (res.content) {
        return decodeBase64Utf8(res.content)
      }
      if (res.url) {
        return await (await fetch(res.url)).text()
      }
      return ""
    },
    enabled: isOpen,
    staleTime: 0,
  })

  useEffect(() => {
    if (initialDoc !== undefined) {
      textRef.current = initialDoc
      baseRef.current = initialDoc
      setDirty(false)
    }
  }, [initialDoc])

  const saveMutation = useMutation({
    mutationFn: async (message: string) => {
      const text = trimForSave(textRef.current)
      const file = new File([text], path.split("/").pop() || path, {
        type: "text/plain",
      })
      await ProjectsService.putProjectContents({
        owner_name: ownerName,
        project_name: projectName,
        path,
        "content-length": file.size,
        bodyProjectsPutProjectContents: { file, message: message || null },
      }).then((response) => response.data)
    },
    onSuccess: () => {
      baseRef.current = trimForSave(textRef.current)
      setDirty(false)
      setCommitMessage("")
      commitModal.onClose()
      showToast("Saved", "Your changes were committed.", "success")
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

  // Ctrl/Cmd+S saves, matching the LaTeX editor (and every other editor).
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

  return (
    <>
      {/* Unlike the LaTeX editor there's no preview beside the source, so a
          reading-width column is plenty — full width would just stretch the
          lines out. */}
      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        size={{ base: "full", md: "4xl" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent maxH="90vh">
          <Flex align="center" gap={3} px={4} py={2} borderBottomWidth="1px">
            <Text fontWeight="bold" isTruncated>
              {path}
            </Text>
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
            <Box flex="1" />
            <ModalCloseButton position="static" />
          </Flex>
          <ModalBody p={0} overflow="hidden">
            {isPending || initialDoc === undefined ? (
              <Flex height="70vh" align="center" justify="center">
                <Spinner />
              </Flex>
            ) : (
              <Box height="70vh">
                <CodeEditorPane
                  key={path}
                  initialDoc={initialDoc}
                  path={path}
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
              placeholder="Ex: Add the paper's class file as a stage input"
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

export default FileEditorModal
