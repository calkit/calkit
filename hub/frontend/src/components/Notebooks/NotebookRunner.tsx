import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Box,
  Button,
  Code,
  Flex,
  HStack,
  IconButton,
  Image,
  Kbd,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import type { EditorView } from "codemirror"
import mixpanel from "mixpanel-browser"
import { useEffect, useMemo, useRef, useState } from "react"
import { FaPlay } from "react-icons/fa"

import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import {
  type NotebookCell,
  type ParsedNotebook,
  parseNotebook,
  serializeNotebook,
} from "../../lib/notebook"
import {
  type CellRun,
  PRELUDE,
  PROJECT_DIR,
  getPyodide,
  preloadPackages,
  runCell,
  writeProjectFiles,
} from "../../lib/pyodide"
import { decodeBase64Utf8 } from "../../lib/strings"
import CodeEditorPane from "../Common/CodeEditorPane"
import LoadingSpinner from "../Common/LoadingSpinner"
import Markdown from "../Common/Markdown"
import { envPackages, pickPythonEnv } from "../../lib/figureScript"

// Inputs are what the code reads, so the caps are about what a browser can
// hold, not about tidiness: a profiler's sqlite or a results HDF5 can run
// to hundreds of megabytes and still be exactly what's needed.
const MAX_INPUT_BYTES = 512 * 1024 * 1024
const MAX_TOTAL_INPUT_BYTES = 1536 * 1024 * 1024
const MAX_INPUT_FILES = 5000

const bytesOf = (item: any): Promise<Uint8Array | null> => {
  if (item.content) {
    const binary = atob(item.content)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    return Promise.resolve(bytes)
  }
  if (item.url) {
    return fetch(String(item.url)).then(async (resp) =>
      resp.ok ? new Uint8Array(await resp.arrayBuffer()) : null,
    )
  }
  return Promise.resolve(null)
}

/**
 * Every file under a repo path, as bytes at their repo paths.
 *
 * A stage input is as often a directory (a stage's output folder, a
 * results tree) as a single file, and a notebook reading from it expects
 * the files inside. Missing a file is worse than it looks: sqlite, for
 * one, quietly creates an empty database at a path that isn't there.
 */
async function fetchTree(
  ownerName: string,
  projectName: string,
  path: string,
  budget: { bytes: number; files: number },
  onStatus: (status: string) => void,
  problems: string[],
): Promise<{ path: string; data: Uint8Array }[]> {
  let item: any
  try {
    item = await ProjectsService.getProjectContents({
      owner_name: ownerName,
      project_name: projectName,
      path,
    }).then((response) => response.data as any)
  } catch {
    problems.push(`${path}: not found in the project`)
    return []
  }
  if (!item) return []
  if (item.type === "dir") {
    const out: { path: string; data: Uint8Array }[] = []
    for (const child of (item.dir_items ?? []) as any[]) {
      if (budget.files <= 0 || budget.bytes <= 0) {
        problems.push(`${path}: not fully loaded, the input budget ran out`)
        break
      }
      out.push(
        ...(await fetchTree(
          ownerName,
          projectName,
          String(child.path),
          budget,
          onStatus,
          problems,
        )),
      )
    }
    return out
  }
  if (item.size && item.size > MAX_INPUT_BYTES) {
    problems.push(
      `${path}: ${(item.size / 1e6).toFixed(0)} MB is over the ${
        MAX_INPUT_BYTES / 1024 / 1024
      } MB per-file limit`,
    )
    return []
  }
  if (!item.content && !item.url) {
    problems.push(
      `${path}: this version isn't in the hub's storage; ` +
        "push it with `calkit dvc push` (against this hub) and reopen",
    )
    return []
  }
  onStatus(`Loading ${path}`)
  let data: Uint8Array | null = null
  try {
    data = await bytesOf(item)
  } catch (e) {
    problems.push(`${path}: download failed (${(e as Error).message})`)
    return []
  }
  if (!data) {
    problems.push(`${path}: download failed`)
    return []
  }
  budget.files -= 1
  budget.bytes -= data.length
  return [{ path, data }]
}

interface NotebookRunnerProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  /** Repo path of the .ipynb. */
  path: string
  /** The stage that runs it, for the header and for its inputs. */
  stage?: string | null
  /** Files the stage reads, written into the in-browser filesystem. */
  inputs?: string[]
}

/**
 * Run a notebook in the browser, cell by cell, on the shared Python
 * runtime, and save edits back to the repo.
 *
 * The same idea as the figure editor: iterate with nothing installed, in
 * an environment mirrored from the project's, and let the pipeline run be
 * the reproducible one. State carries between cells as in a kernel.
 * Outputs shown here aren't saved; a cell whose source changed has its
 * stored outputs cleared on save, since they no longer describe the code.
 */
const NotebookRunner = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  path,
  stage,
  inputs = [],
}: NotebookRunnerProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const cellBg = useColorModeValue("white", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const outputBg = useColorModeValue("gray.50", "gray.800")
  const [parsed, setParsed] = useState<ParsedNotebook | null>(null)
  const [cells, setCells] = useState<NotebookCell[]>([])
  const [runs, setRuns] = useState<Record<string, CellRun | "running">>({})
  // Execution counts as Jupyter shows them: the order cells were run in,
  // not their position, so a re-run cell gets a new number.
  const [counts, setCounts] = useState<Record<string, number>>({})
  const execCounter = useRef(0)
  const [status, setStatus] = useState("")
  const [ready, setReady] = useState(false)
  const [runningAll, setRunningAll] = useState(false)
  // Inputs that couldn't be put in place, shown rather than swallowed: a
  // missing file fails in ways that don't name it (sqlite makes an empty
  // database, pandas finds an empty folder).
  const [inputProblems, setInputProblems] = useState<string[]>([])
  const viewRefs = useRef<Record<string, EditorView | null>>({})
  // Markdown cells render until clicked; then they edit like code cells
  // and render again on Shift+Enter or ⌘+Enter, as in Jupyter.
  const [editingMarkdown, setEditingMarkdown] = useState<Set<string>>(new Set())
  const setMarkdownEditing = (id: string, editing: boolean) =>
    setEditingMarkdown((prev) => {
      const next = new Set(prev)
      if (editing) next.add(id)
      else next.delete(id)
      return next
    })
  // Shift+Enter runs a cell and moves to the next one, which means
  // focusing the next editor (and opening a markdown cell for editing if
  // that's what's next, since that's where the cursor lands in Jupyter).
  const focusCell = (index: number) => {
    const next = cells[index]
    if (!next) return
    if (next.type === "markdown") setMarkdownEditing(next.id, true)
    requestAnimationFrame(() => viewRefs.current[next.id]?.focus())
  }
  const discardDialog = useDisclosure()
  const keepEditingRef = useRef<HTMLButtonElement>(null)
  const notebookQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "contents", path],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: ownerName,
        project_name: projectName,
        path,
      }).then((response) => response.data as any),
    enabled: isOpen,
    retry: false,
  })
  useEffect(() => {
    if (!notebookQuery.data?.content || parsed) return
    try {
      const nb = parseNotebook(decodeBase64Utf8(notebookQuery.data.content))
      setParsed(nb)
      setCells(nb.cells)
    } catch (e) {
      showToast("Couldn't read the notebook", String(e), "error")
    }
  }, [notebookQuery.data, parsed, showToast])
  const environmentsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "environments"],
    queryFn: () =>
      ProjectsService.getProjectEnvironments({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: isOpen,
  })
  const pythonEnv = useMemo(
    () => pickPythonEnv(environmentsQuery.data ?? []),
    [environmentsQuery.data],
  )
  const envPackageNames = useMemo(() => envPackages(pythonEnv), [pythonEnv])
  // The runtime is prepared once per open: packages from the environment,
  // the stage's inputs written into place, and the interpreter in the
  // project directory. Cells then run against that.
  const prepare = async () => {
    if (ready) return
    setStatus("Loading the Python runtime")
    const pyodide = await getPyodide(setStatus)
    if (envPackageNames.length) {
      setStatus(`Loading ${pythonEnv?.name ?? "environment"} packages`)
      await preloadPackages(envPackageNames)
    }
    const files: { path: string; data: Uint8Array }[] = []
    // Every input the stage declares, as is, directories walked: these are
    // what the code reads, not a list for a person, so nothing is filtered.
    const budget = { bytes: MAX_TOTAL_INPUT_BYTES, files: MAX_INPUT_FILES }
    const problems: string[] = []
    for (const inputPath of inputs) {
      files.push(
        ...(await fetchTree(
          ownerName,
          projectName,
          inputPath,
          budget,
          setStatus,
          problems,
        )),
      )
    }
    setInputProblems(problems)
    writeProjectFiles(pyodide, files)
    await pyodide.runPythonAsync(PRELUDE)
    // Jupyter runs a notebook in its own folder, and so does the pipeline's
    // nbconvert, so relative paths in the cells are relative to it.
    const notebookDir = path.split("/").slice(0, -1).join("/")
    const cwd = notebookDir ? `${PROJECT_DIR}/${notebookDir}` : PROJECT_DIR
    await pyodide.runPythonAsync(
      [
        "import os",
        `os.makedirs(${JSON.stringify(cwd)}, exist_ok=True)`,
        `os.chdir(${JSON.stringify(cwd)})`,
      ].join("\n"),
    )
    setStatus("")
    setReady(true)
    return pyodide
  }
  const run = async (cell: NotebookCell) => {
    if (cell.type !== "code") return
    setRuns((r) => ({ ...r, [cell.id]: "running" }))
    const pyodide = (await prepare()) ?? (await getPyodide())
    const result = await runCell(pyodide, cell.source)
    execCounter.current += 1
    const n = execCounter.current
    setCounts((c) => ({ ...c, [cell.id]: n }))
    setRuns((r) => ({ ...r, [cell.id]: result }))
    mixpanel.track("Ran notebook cell", {
      ok: result.error === null,
      duration_ms: result.durationMs,
    })
    return result
  }
  const runAll = async () => {
    setRunningAll(true)
    for (const cell of cells) {
      if (cell.type !== "code") continue
      const result = await run(cell)
      // A failed cell stops the run, as "Run all" does in Jupyter
      if (result?.error) break
    }
    setRunningAll(false)
  }
  const dirty = useMemo(
    () =>
      Boolean(parsed) &&
      cells.some(
        (c) => c.source !== parsed?.cells.find((o) => o.id === c.id)?.source,
      ),
    [cells, parsed],
  )
  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!parsed) return
      const text = serializeNotebook(parsed, cells)
      const file = new File([text], path.split("/").pop() || path, {
        type: "application/json",
      })
      await ProjectsService.putProjectContents({
        owner_name: ownerName,
        project_name: projectName,
        path,
        "content-length": file.size,
        bodyProjectsPutProjectContents: {
          file,
          message: `Update ${path}`,
        },
      }).then((response) => response.data)
    },
    onSuccess: () => {
      showToast("Saved", `${path} was committed.`, "success")
      mixpanel.track("Saved notebook from runner", { stage })
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName],
      })
      // What's saved is now the baseline
      setParsed((p) => (p ? { ...p, cells: cells.map((c) => ({ ...c })) } : p))
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const requestClose = () => {
    if (dirty) {
      discardDialog.onOpen()
      return
    }
    onClose()
  }
  const setSource = (id: string, source: string) =>
    setCells((cs) => cs.map((c) => (c.id === id ? { ...c, source } : c)))
  const editorRef = (id: string) => ({
    get current() {
      return viewRefs.current[id] ?? null
    },
    set current(view: EditorView | null) {
      viewRefs.current[id] = view
    },
  })
  return (
    <Modal
      isOpen={isOpen}
      onClose={requestClose}
      size="6xl"
      scrollBehavior="inside"
      isCentered
    >
      <ModalOverlay />
      {/* A notebook reads best at a page's width, not a table's */}
      <ModalContent
        maxW={{ base: "100%", lg: "min(1100px, 85vw)" }}
        h="92vh"
        maxH="92vh"
      >
        <ModalHeader pb={1}>
          Notebook: <Code fontSize="md">{path}</Code>
          <Flex gap={3} fontSize="xs" color="ui.dim" fontWeight="normal" mt={1}>
            {stage ? (
              <Text as="span">
                Stage{" "}
                <Link
                  as={RouterLink}
                  to={`/${ownerName}/${projectName}/pipeline` as any}
                  search={{ stage } as any}
                >
                  <Code fontSize="xs">{stage}</Code>
                </Link>
              </Text>
            ) : null}
            {pythonEnv ? (
              <Text as="span">
                Runs in environment <Code fontSize="xs">{pythonEnv.name}</Code>
              </Text>
            ) : null}
            {inputs.length ? (
              <Text as="span">
                {inputs.length} input {inputs.length === 1 ? "file" : "files"}
              </Text>
            ) : null}
          </Flex>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pt={2} pb={4}>
          <HStack mb={3} spacing={3}>
            <Button
              size="sm"
              variant="primary"
              onClick={runAll}
              isLoading={runningAll}
              loadingText={status || "Running"}
              isDisabled={!cells.length}
            >
              Run all
            </Button>
            <Text fontSize="xs" color="ui.dim">
              <Kbd>⌘</Kbd>+<Kbd>Enter</Kbd> runs a cell, <Kbd>Shift</Kbd>+
              <Kbd>Enter</Kbd> runs and moves on
            </Text>
            {status && !runningAll ? (
              <Text fontSize="xs" color="ui.dim">
                {status}
              </Text>
            ) : null}
            <Text fontSize="xs" color="ui.dim" ml="auto">
              Python runs in your browser. Outputs here aren't saved; the
              pipeline's run is the one that counts.
            </Text>
          </HStack>
          {inputProblems.length ? (
            <Box
              mb={3}
              p={3}
              borderRadius="md"
              borderWidth={1}
              borderColor="orange.300"
              fontSize="sm"
            >
              <Text fontWeight="semibold" mb={1}>
                Some inputs couldn't be loaded
              </Text>
              {inputProblems.map((p) => (
                <Text key={p} fontFamily="mono" fontSize="xs">
                  {p}
                </Text>
              ))}
            </Box>
          ) : null}
          {notebookQuery.isPending || (!parsed && !notebookQuery.isError) ? (
            <LoadingSpinner height="40vh" />
          ) : notebookQuery.isError ? (
            <Text color="red.400" fontSize="sm">
              Couldn't load the notebook.
            </Text>
          ) : (
            cells.map((cell, index) => {
              const state = runs[cell.id]
              return (
                <Box
                  key={cell.id}
                  mb={3}
                  borderWidth={1}
                  borderColor={borderColor}
                  borderRadius="md"
                  bg={cellBg}
                  overflow="hidden"
                >
                  {cell.type === "markdown" ? (
                    editingMarkdown.has(cell.id) ? (
                      <Box minH="60px" maxH="50vh" overflow="auto">
                        <CodeEditorPane
                          initialDoc={cell.source}
                          path={`${cell.id}.md`}
                          viewRef={editorRef(cell.id)}
                          onChange={(text) => setSource(cell.id, text)}
                          onModEnter={() => setMarkdownEditing(cell.id, false)}
                          onShiftEnter={() => {
                            setMarkdownEditing(cell.id, false)
                            focusCell(index + 1)
                          }}
                        />
                      </Box>
                    ) : (
                      <Box
                        px={4}
                        py={2}
                        sx={{ "& p": { my: 1 } }}
                        cursor="text"
                        title="Click to edit"
                        onClick={() => setMarkdownEditing(cell.id, true)}
                      >
                        <Markdown>
                          {cell.source || "*Empty markdown cell*"}
                        </Markdown>
                      </Box>
                    )
                  ) : cell.type === "raw" ? (
                    <Box px={4} py={2} fontFamily="mono" fontSize="sm">
                      <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                        {cell.source}
                      </pre>
                    </Box>
                  ) : (
                    <>
                      <Flex>
                        <Flex
                          direction="column"
                          align="center"
                          px={2}
                          py={2}
                          minW="56px"
                          fontSize="xs"
                          color="ui.dim"
                        >
                          <Text mb={1} fontFamily="mono">
                            [
                            {state === "running"
                              ? "*"
                              : counts[cell.id] !== undefined
                                ? counts[cell.id]
                                : " "}
                            ]
                          </Text>
                          <IconButton
                            aria-label="Run cell"
                            title="Run cell (⌘+Enter)"
                            icon={<FaPlay />}
                            size="xs"
                            height="22px"
                            minW="22px"
                            fontSize="9px"
                            variant="primary"
                            onClick={() => run(cell)}
                            isLoading={state === "running"}
                          />
                        </Flex>
                        <Box
                          flex={1}
                          minW={0}
                          minH="60px"
                          maxH="50vh"
                          overflow="auto"
                        >
                          <CodeEditorPane
                            initialDoc={cell.source}
                            path={`${cell.id}.py`}
                            viewRef={editorRef(cell.id)}
                            onChange={(text) => setSource(cell.id, text)}
                            onModEnter={() => run(cell)}
                            onShiftEnter={() => {
                              run(cell)
                              focusCell(index + 1)
                            }}
                          />
                        </Box>
                      </Flex>
                      {state && state !== "running" ? (
                        <Box
                          bg={outputBg}
                          borderTopWidth={1}
                          borderColor={borderColor}
                          px={4}
                          py={2}
                          fontSize="sm"
                        >
                          {state.stdout ? (
                            <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                              {state.stdout}
                            </pre>
                          ) : null}
                          {state.stderr ? (
                            <pre
                              style={{
                                whiteSpace: "pre-wrap",
                                margin: 0,
                                opacity: 0.7,
                              }}
                            >
                              {state.stderr}
                            </pre>
                          ) : null}
                          {state.error ? (
                            <pre
                              style={{
                                whiteSpace: "pre-wrap",
                                margin: 0,
                                color: "var(--chakra-colors-red-400)",
                              }}
                            >
                              {state.error}
                            </pre>
                          ) : null}
                          {state.images.map((png, i) => (
                            <Image
                              key={i}
                              src={`data:image/png;base64,${png}`}
                              alt={`Output ${i + 1}`}
                              maxW="100%"
                              my={2}
                            />
                          ))}
                          {state.result ? (
                            <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                              {state.result}
                            </pre>
                          ) : null}
                          {!state.stdout &&
                          !state.stderr &&
                          !state.error &&
                          !state.images.length &&
                          !state.result ? (
                            <Text fontSize="xs" color="ui.dim">
                              Ran in {state.durationMs} ms, no output.
                            </Text>
                          ) : null}
                        </Box>
                      ) : state === "running" ? (
                        <Flex
                          px={4}
                          py={2}
                          gap={2}
                          align="center"
                          fontSize="xs"
                          color="ui.dim"
                        >
                          <Spinner size="xs" /> {status || "Running"}
                        </Flex>
                      ) : null}
                    </>
                  )}
                </Box>
              )
            })
          )}
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            onClick={() => saveMutation.mutate()}
            isLoading={saveMutation.isPending}
            isDisabled={!dirty}
            title={dirty ? undefined : "No changes to save"}
          >
            Save notebook
          </Button>
          <Button onClick={requestClose}>Close</Button>
        </ModalFooter>
      </ModalContent>
      <AlertDialog
        isOpen={discardDialog.isOpen}
        leastDestructiveRef={keepEditingRef}
        onClose={discardDialog.onClose}
        isCentered
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader fontSize="lg">Discard edits?</AlertDialogHeader>
            <AlertDialogBody>
              The notebook has edits that haven't been saved. Closing now drops
              them.
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button ref={keepEditingRef} onClick={discardDialog.onClose}>
                Keep editing
              </Button>
              <Button
                colorScheme="red"
                onClick={() => {
                  discardDialog.onClose()
                  onClose()
                }}
              >
                Discard
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Modal>
  )
}

export default NotebookRunner
