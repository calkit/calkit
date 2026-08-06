import {
  Badge,
  Box,
  Button,
  Collapse,
  Flex,
  FormLabel,
  HStack,
  Input,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Switch,
  Text,
  VStack,
  useDisclosure,
} from "@chakra-ui/react"
import { StreamLanguage } from "@codemirror/language"
import { stex } from "@codemirror/legacy-modes/mode/stex"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { EditorView, basicSetup } from "codemirror"
import mixpanel from "mixpanel-browser"
import { merge as diff3Merge } from "node-diff3"
import { type MutableRefObject, useEffect, useRef, useState } from "react"

import { ProjectsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import {
  LatexCompiler,
  type LatexFile,
  findMissingPackages,
} from "../../lib/latexCompiler"
import { loadLatexProject } from "../../lib/latexProject"
import { handleError } from "../../lib/errors"
import PdfDocumentViewer from "../Common/PdfDocumentViewer"

interface LatexEditorProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  texPath: string
  // The publication's pipeline-stage deps, if any — used to load figures and
  // other inputs that live outside the .tex's own directory.
  deps?: string[] | null
}

// Display a repo path relative to the main file's directory, surfacing `../`
// for files that live above the paper directory.
function relativeTo(fromDir: string, to: string): string {
  const fromParts = fromDir ? fromDir.split("/") : []
  const toParts = to.split("/")
  let i = 0
  while (
    i < fromParts.length &&
    i < toParts.length - 1 &&
    fromParts[i] === toParts[i]
  ) {
    i++
  }
  return "../".repeat(fromParts.length - i) + toParts.slice(i).join("/")
}

function EditorPane({
  initialDoc,
  viewRef,
  onChange,
}: {
  initialDoc: string
  viewRef: MutableRefObject<EditorView | null>
  onChange: (text: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) {
      return
    }
    const view = new EditorView({
      doc: initialDoc,
      extensions: [
        basicSetup,
        StreamLanguage.define(stex),
        EditorView.lineWrapping,
        EditorView.updateListener.of((u) => {
          if (u.docChanged) {
            onChange(u.state.doc.toString())
          }
        }),
      ],
      parent: ref.current,
    })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
  }, [])
  return <Box ref={ref} height="100%" overflowY="auto" fontSize="sm" />
}

const LatexEditor = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  texPath,
  deps,
}: LatexEditorProps) => {
  // Files are keyed by their full repo path so relative refs (e.g.
  // \includegraphics{../figures/x.png}) resolve against the real layout.
  const viewRef = useRef<EditorView | null>(null)
  const compilerRef = useRef<LatexCompiler | null>(null)
  const buffersRef = useRef<Map<string, string>>(new Map())
  // Base (last-reconciled) content per text file — the common ancestor for
  // 3-way merging in others' concurrent changes without losing local edits.
  const baseBuffersRef = useRef<Map<string, string>>(new Map())
  const baseShaRef = useRef<string | null>(null)
  const binariesRef = useRef<Map<string, Uint8Array>>(new Map())
  const initializedRef = useRef(false)
  const compilingRef = useRef(false)
  const pendingCompileRef = useRef(false)
  const compileTimerRef = useRef<number | null>(null)
  // Mirror of the latest pdfUrl so the unmount cleanup can revoke the current
  // object URL (an effect with an empty dep array would capture the initial
  // null and leak the blob).
  const pdfUrlRef = useRef<string | null>(null)
  const commitInputRef = useRef<HTMLInputElement>(null)
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  const logPanel = useDisclosure()
  const commitModal = useDisclosure()
  const [textPaths, setTextPaths] = useState<string[]>([])
  const [activePath, setActivePath] = useState<string>(texPath)
  const [mainPath, setMainPath] = useState<string>(texPath)
  const [ready, setReady] = useState(false)
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const dirtyRef = useRef(dirty)
  dirtyRef.current = dirty
  const [log, setLog] = useState("")
  const [status, setStatus] = useState("")
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [compiling, setCompiling] = useState(false)
  const [autoCompile, setAutoCompile] = useState(true)
  const [commitMessage, setCommitMessage] = useState("")
  // Concurrent-editing: origin advanced past what we loaded, and files that
  // came back with conflict markers from the last pull. mergeNonce forces the
  // CodeMirror pane to remount with merged content.
  const [updatesAvailable, setUpdatesAvailable] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [conflicts, setConflicts] = useState<Set<string>>(new Set())
  const [mergeNonce, setMergeNonce] = useState(0)

  const { data: projectFiles } = useQuery({
    queryKey: ["projects", ownerName, projectName, "latex-project", texPath],
    queryFn: () => loadLatexProject(ownerName, projectName, texPath, deps),
    enabled: isOpen,
    staleTime: 0,
  })

  useEffect(() => {
    if (!projectFiles || initializedRef.current) {
      return
    }
    initializedRef.current = true
    const texts: string[] = []
    for (const f of projectFiles) {
      if (f.kind === "text") {
        buffersRef.current.set(f.path, f.text ?? "")
        baseBuffersRef.current.set(f.path, f.text ?? "")
        texts.push(f.path)
      } else if (f.bytes) {
        binariesRef.current.set(f.path, f.bytes)
      }
    }
    texts.sort()
    // Resolve the main file robustly: prefer the publication's path if it is a
    // real root document (has both \documentclass and \begin{document}, so a
    // short stub/wrapper isn't picked), else the first such .tex.
    const looksMain = (p: string) => {
      const c = buffersRef.current.get(p) ?? ""
      return c.includes("\\documentclass") && c.includes("\\begin{document}")
    }
    let main = texPath
    if (!texts.includes(main) || !looksMain(main)) {
      main = texts.find(looksMain) ?? texts[0] ?? texPath
    }
    setTextPaths(texts)
    setMainPath(main)
    setActivePath(main)
    setReady(true)
  }, [projectFiles, texPath])

  useEffect(() => {
    pdfUrlRef.current = pdfUrl
  }, [pdfUrl])

  // Usage analytics: one event per time the editor is opened.
  useEffect(() => {
    if (isOpen) {
      mixpanel.track("Opened LaTeX editor", {
        project: `${ownerName}/${projectName}`,
        tex_path: texPath,
      })
    }
  }, [isOpen, ownerName, projectName, texPath])

  useEffect(() => {
    return () => {
      if (compileTimerRef.current) {
        window.clearTimeout(compileTimerRef.current)
      }
      compilerRef.current?.terminate()
      compilerRef.current = null
      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current)
      }
    }
  }, [])

  const compile = async (trigger: "manual" | "auto" = "manual") => {
    // Serialize compiles; if one is requested while another runs, recompile
    // once it finishes (so the preview reflects the latest edits).
    if (compilingRef.current) {
      pendingCompileRef.current = true
      return
    }
    compilingRef.current = true
    setCompiling(true)
    setLog("")
    setStatus("Compiling…")
    const startedAt = performance.now()
    let succeeded = false
    try {
      if (!compilerRef.current) {
        compilerRef.current = new LatexCompiler({
          onLog: (line) => setLog((l) => `${l}${line}\n`),
        })
      }
      const files: LatexFile[] = []
      for (const [path, text] of buffersRef.current) {
        files.push({ path, contents: text })
      }
      for (const [path, bytes] of binariesRef.current) {
        files.push({ path, contents: bytes })
      }
      const result = await compilerRef.current.compile(files, mainPath)
      // exit_code can be 0 with an empty PDF (busytex returns an empty array
      // when no PDF was written) — treat that as a failure, not a blank preview.
      if (result.exitCode === 0 && result.pdf && result.pdf.byteLength > 0) {
        const pdfBytes = new Uint8Array(result.pdf)
        const blob = new Blob([pdfBytes], { type: "application/pdf" })
        setPdfUrl((prev) => {
          if (prev) {
            URL.revokeObjectURL(prev)
          }
          return URL.createObjectURL(blob)
        })
        setStatus("Compiled ✓")
        succeeded = true
      } else {
        const missing = findMissingPackages(result.log)
        setStatus(
          missing.length > 0
            ? `Missing from the in-browser TeX bundle: ${missing.join(", ")}`
            : result.exitCode === 0
              ? "Compiled, but no PDF was produced — see log"
              : `Compile failed (exit ${result.exitCode})`,
        )
        setLog(result.log)
        logPanel.onOpen()
      }
    } catch (e) {
      setStatus("Engine error")
      setLog(String(e))
      logPanel.onOpen()
    } finally {
      compilingRef.current = false
      setCompiling(false)
      mixpanel.track("Compiled LaTeX preview", {
        project: `${ownerName}/${projectName}`,
        trigger,
        succeeded,
        seconds: Math.round((performance.now() - startedAt) / 1000),
      })
      if (pendingCompileRef.current) {
        pendingCompileRef.current = false
        compile(trigger)
      }
    }
  }

  const scheduleCompile = () => {
    if (!autoCompile) {
      return
    }
    if (compileTimerRef.current) {
      window.clearTimeout(compileTimerRef.current)
    }
    compileTimerRef.current = window.setTimeout(() => compile("auto"), 1500)
  }

  const markDirty = (path: string, text: string) => {
    buffersRef.current.set(path, text)
    setDirty((d) => (d.has(path) ? d : new Set(d).add(path)))
    // Clear the conflict flag once the user has removed the markers.
    setConflicts((c) => {
      if (!c.has(path) || text.includes("<<<<<<<")) {
        return c
      }
      const next = new Set(c)
      next.delete(path)
      return next
    })
    scheduleCompile()
  }

  const saveMutation = useMutation({
    mutationFn: async (message: string) => {
      for (const repoPath of dirtyRef.current) {
        const text = buffersRef.current.get(repoPath) ?? ""
        // Skip files already identical to origin (nothing to commit), so one
        // unchanged file doesn't fail the whole save with a "not different"
        // error from the backend.
        if (text === baseBuffersRef.current.get(repoPath)) {
          continue
        }
        const file = new File([text], repoPath.split("/").pop() || repoPath, {
          type: "text/plain",
        })
        await ProjectsService.putProjectContents({
          ownerName,
          projectName,
          path: repoPath,
          contentLength: file.size,
          formData: { file, message: message || null },
        })
      }
    },
    onSuccess: async () => {
      // Our just-saved content is now the committed baseline. Advance the base
      // buffers and the remote-head marker to it so the poll doesn't flag our
      // own push as an update to pull. Do this before clearing dirty so we
      // still know which files we saved.
      for (const repoPath of dirtyRef.current) {
        baseBuffersRef.current.set(
          repoPath,
          buffersRef.current.get(repoPath) ?? "",
        )
      }
      const sha = await fetchRemoteHead()
      if (sha) {
        baseShaRef.current = sha
      }
      setUpdatesAvailable(false)
      setDirty(new Set())
      setCommitMessage("")
      commitModal.onClose()
      showToast("Saved", "Your changes were committed.", "success")
      mixpanel.track("Saved LaTeX changes", {
        project: `${ownerName}/${projectName}`,
        file_count: dirtyRef.current.size,
      })
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName],
      })
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
  })

  // Concurrent editing: detect others' pushes and 3-way merge them in.
  const fetchRemoteHead = async (): Promise<string | null> => {
    try {
      const head = await ProjectsService.getProjectGitRemoteHead({
        ownerName,
        projectName,
      })
      return head.sha ?? null
    } catch {
      return null
    }
  }

  // Record the loaded commit, then poll origin for others' pushes.
  useEffect(() => {
    if (!ready || !isOpen) {
      return
    }
    let cancelled = false
    fetchRemoteHead().then((sha) => {
      if (!cancelled && sha) {
        baseShaRef.current = sha
      }
    })
    const timer = window.setInterval(async () => {
      const sha = await fetchRemoteHead()
      if (
        !cancelled &&
        sha &&
        baseShaRef.current &&
        sha !== baseShaRef.current
      ) {
        setUpdatesAvailable(true)
      }
    }, 20000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, isOpen])

  // Pull others' changes and 3-way merge them into the buffers, preserving
  // local edits. Clean merges apply silently; overlaps get conflict markers.
  const pullUpdates = async () => {
    if (pulling) {
      return
    }
    setPulling(true)
    setStatus("Pulling latest changes…")
    try {
      const files = await loadLatexProject(
        ownerName,
        projectName,
        texPath,
        deps,
        { fresh: true },
      )
      const nextConflicts = new Set<string>()
      const newTexts: string[] = []
      let merged = 0
      for (const f of files) {
        if (f.kind !== "text") {
          if (f.bytes) {
            binariesRef.current.set(f.path, f.bytes)
          }
          continue
        }
        const remote = f.text ?? ""
        const base = baseBuffersRef.current.get(f.path)
        const local = buffersRef.current.get(f.path)
        if (base === undefined || local === undefined) {
          buffersRef.current.set(f.path, remote)
          baseBuffersRef.current.set(f.path, remote)
          newTexts.push(f.path)
        } else if (local === base) {
          buffersRef.current.set(f.path, remote)
          baseBuffersRef.current.set(f.path, remote)
        } else if (remote !== base) {
          const r = diff3Merge(
            local.split("\n"),
            base.split("\n"),
            remote.split("\n"),
            {
              excludeFalseConflicts: true,
              label: { a: "You (unsaved)", b: "Latest from others" },
            },
          )
          const mergedText = r.result.join("\n")
          buffersRef.current.set(f.path, mergedText)
          baseBuffersRef.current.set(f.path, remote)
          if (r.conflict) {
            nextConflicts.add(f.path)
            setDirty((d) => new Set(d).add(f.path))
          } else if (mergedText === remote) {
            // The merge resolved to exactly origin's content, so there's
            // nothing left to save. Drop any stale dirty flag, otherwise Save
            // would try to commit an unchanged file and the backend rejects it.
            setDirty((d) => {
              if (!d.has(f.path)) {
                return d
              }
              const next = new Set(d)
              next.delete(f.path)
              return next
            })
            merged++
          } else {
            // Local edits survived on top of others' changes: still unsaved.
            setDirty((d) => new Set(d).add(f.path))
            merged++
          }
        }
        // else: only local changed (remote unchanged) — keep local edits.
      }
      if (newTexts.length > 0) {
        setTextPaths((prev) => [...new Set([...prev, ...newTexts])].sort())
      }
      const sha = await fetchRemoteHead()
      if (sha) {
        baseShaRef.current = sha
      }
      setConflicts(nextConflicts)
      setUpdatesAvailable(false)
      setMergeNonce((n) => n + 1)
      setStatus("")
      if (nextConflicts.size > 0) {
        showToast(
          "Pulled with conflicts",
          `${nextConflicts.size} file(s) need conflict resolution (see <<<<<<< markers).`,
          "error",
        )
      } else {
        showToast(
          "Up to date",
          merged > 0
            ? `Merged others' changes into ${merged} file(s).`
            : "Loaded the latest changes.",
          "success",
        )
        if (autoCompile) {
          compile("auto")
        }
      }
    } catch (e) {
      showToast("Pull failed", String(e), "error")
      setStatus("")
    } finally {
      setPulling(false)
    }
  }

  // Ctrl/Cmd+S (and the Save button) ask for a commit message before saving.
  const requestSave = () => {
    // Block saving while unresolved conflict markers remain in any buffer.
    const unresolved = [...dirtyRef.current].filter((p) =>
      (buffersRef.current.get(p) ?? "").includes("<<<<<<<"),
    )
    if (unresolved.length > 0) {
      showToast(
        "Resolve conflicts first",
        `Remove the conflict markers (<<<<<<<) in: ${unresolved.join(", ")}`,
        "error",
      )
      return
    }
    if (dirtyRef.current.size > 0) {
      commitModal.onOpen()
    }
  }

  useEffect(() => {
    if (ready && autoCompile) {
      compile("auto")
    }
    // Compile once on launch when auto-compile is on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready])

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])

  const handleClose = () => {
    if (dirty.size > 0 && !window.confirm("Discard unsaved changes?")) {
      return
    }
    onClose()
  }

  const mainDir = mainPath.includes("/")
    ? mainPath.slice(0, mainPath.lastIndexOf("/"))
    : ""
  const displayPath = (p: string) => relativeTo(mainDir, p)

  return (
    <>
      <Modal isOpen={isOpen} onClose={handleClose} size="full">
        <ModalOverlay />
        <ModalContent>
          <Flex align="center" gap={3} px={4} py={2} borderBottomWidth="1px">
            <Text fontWeight="bold">{displayPath(activePath || mainPath)}</Text>
            {dirty.size > 0 && (
              <Badge colorScheme="orange" variant="subtle">
                {dirty.size} unsaved
              </Badge>
            )}
            {conflicts.size > 0 && (
              <Badge colorScheme="red" variant="solid">
                {conflicts.size} conflict{conflicts.size > 1 ? "s" : ""}
              </Badge>
            )}
            {updatesAvailable && (
              <Button
                size="sm"
                colorScheme="blue"
                variant="solid"
                onClick={pullUpdates}
                isLoading={pulling}
                title="Someone else pushed changes. Pull and merge them in."
              >
                ↻ Pull updates
              </Button>
            )}
            <Button
              size="sm"
              variant="primary"
              onClick={() => compile("manual")}
              isLoading={compiling}
              isDisabled={!ready}
            >
              Compile preview
            </Button>
            <HStack spacing={1}>
              <Switch
                id="auto-compile"
                size="sm"
                isChecked={autoCompile}
                onChange={(e) => setAutoCompile(e.target.checked)}
              />
              <FormLabel htmlFor="auto-compile" m={0} fontSize="sm">
                Auto
              </FormLabel>
            </HStack>
            <Button
              size="sm"
              onClick={requestSave}
              isLoading={saveMutation.isPending}
              isDisabled={dirty.size === 0}
            >
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={logPanel.onToggle}>
              {logPanel.isOpen ? "Hide log" : "Show log"}
            </Button>
            <Text fontSize="sm" color="ui.dim">
              {status}
            </Text>
            <Box flex="1" />
            <Text fontSize="xs" color="ui.dim">
              Draft preview (run pipeline to generate official PDF)
            </Text>
            {/* Courtesy credit + source pointer for the in-browser engine.
                busytex (MIT) + TeX Live; see public/tex/LICENSE-busytex. */}
            <Link
              href="https://github.com/busytex/busytex"
              isExternal
              fontSize="xs"
              color="ui.dim"
              mx={3}
            >
              LaTeX by busytex + TeX Live
            </Link>
            <ModalCloseButton position="static" />
          </Flex>
          <ModalBody p={0} overflow="hidden">
            {!ready ? (
              <Flex height="calc(100vh - 49px)" align="center" justify="center">
                <Spinner />
              </Flex>
            ) : (
              <Flex height="calc(100vh - 49px)">
                <Box
                  width="220px"
                  borderRightWidth="1px"
                  overflowY="auto"
                  p={2}
                  flexShrink={0}
                >
                  <Text fontSize="xs" color="ui.dim" mb={1} px={1}>
                    Files
                  </Text>
                  <VStack align="stretch" spacing={0}>
                    {textPaths.map((p) => (
                      <Button
                        key={p}
                        size="xs"
                        variant={p === activePath ? "solid" : "ghost"}
                        justifyContent="flex-start"
                        fontWeight={p === mainPath ? "bold" : "normal"}
                        color={conflicts.has(p) ? "red.500" : undefined}
                        onClick={() => setActivePath(p)}
                        title={
                          conflicts.has(p)
                            ? "Has merge conflicts to resolve"
                            : undefined
                        }
                      >
                        {conflicts.has(p) ? "⚠ " : dirty.has(p) ? "• " : ""}
                        {displayPath(p)}
                      </Button>
                    ))}
                    {[...binariesRef.current.keys()].sort().map((p) => (
                      <Text
                        key={p}
                        fontSize="xs"
                        color="ui.dim"
                        px={3}
                        py={1}
                        isTruncated
                      >
                        {displayPath(p)}
                      </Text>
                    ))}
                  </VStack>
                </Box>
                <Box flex="1" borderRightWidth="1px" minW={0}>
                  <EditorPane
                    key={`${activePath}:${mergeNonce}`}
                    initialDoc={buffersRef.current.get(activePath) ?? ""}
                    viewRef={viewRef}
                    onChange={(text) => markDirty(activePath, text)}
                  />
                </Box>
                <Box flex="1" minW={0} position="relative" bg="blackAlpha.50">
                  {pdfUrl ? (
                    <PdfDocumentViewer
                      url={pdfUrl}
                      source="latex-editor-preview"
                      allowDownload={false}
                      downloadDisabledHint="This is a live preview and its figures may be stale. Run the pipeline to generate the official PDF with all figures up to date."
                    />
                  ) : (
                    <Flex
                      height="100%"
                      align="center"
                      justify="center"
                      direction="column"
                      gap={2}
                      color="ui.dim"
                    >
                      <Text>No preview yet.</Text>
                      <Text fontSize="sm">
                        Click "Compile preview" to render the PDF.
                      </Text>
                    </Flex>
                  )}
                  <Collapse
                    in={logPanel.isOpen}
                    style={{
                      position: "absolute",
                      bottom: 0,
                      left: 0,
                      right: 0,
                      zIndex: 20,
                    }}
                  >
                    <Box
                      maxH="40vh"
                      overflowY="auto"
                      bg="gray.900"
                      color="gray.100"
                      fontFamily="mono"
                      fontSize="xs"
                      whiteSpace="pre-wrap"
                      boxShadow="dark-lg"
                      p={2}
                    >
                      <Button
                        size="xs"
                        position="sticky"
                        top={0}
                        float="right"
                        ml={2}
                        onClick={() => {
                          navigator.clipboard
                            .writeText(log)
                            .then(() =>
                              showToast(
                                "Copied",
                                "Compile log copied to clipboard.",
                                "success",
                              ),
                            )
                            .catch(() =>
                              showToast(
                                "Copy failed",
                                "Could not access the clipboard.",
                                "error",
                              ),
                            )
                        }}
                        isDisabled={!log}
                      >
                        Copy log
                      </Button>
                      {log || "(no output)"}
                    </Box>
                  </Collapse>
                </Box>
              </Flex>
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
              placeholder="Ex: Add paragraph about the boundary conditions"
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

export default LatexEditor
