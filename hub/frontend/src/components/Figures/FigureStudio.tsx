import {
  Alert,
  AlertDescription,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertIcon,
  Box,
  Button,
  Checkbox,
  CheckboxGroup,
  Code,
  Collapse,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  Grid,
  GridItem,
  HStack,
  IconButton,
  Image,
  Input,
  Kbd,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Popover,
  PopoverArrow,
  PopoverBody,
  PopoverCloseButton,
  PopoverContent,
  PopoverHeader,
  PopoverTrigger,
  Spinner,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  Wrap,
  WrapItem,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { InfoOutlineIcon } from "@chakra-ui/icons"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import type { EditorView } from "codemirror"
import mixpanel from "mixpanel-browser"
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react"

import { ProjectsService, type StudioFigure } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { isSubmitChord } from "../../hooks/useSubmitOnCmdEnter"
import { numericColumns, previewCsv } from "../../lib/csv"
import { bytesToText, fetchTree, newBudget } from "../../lib/projectFiles"
import { handleError } from "../../lib/errors"
import {
  type RunResult,
  packagesFromImports,
  preloadPackages,
  runFigureScript,
} from "../../lib/pyodide"
import {
  defaultScript,
  envPackages,
  isCsvPath,
  pickPythonEnv,
  readDataPaths,
  savefigPath,
  slug,
  stem,
  withDatasetLines,
} from "../../lib/figureScript"
import CodeEditorPane from "../Common/CodeEditorPane"
import PdfCanvas from "../Common/PdfCanvas"
import { FaPlus } from "react-icons/fa"
import PathPicker from "../Releases/PathPicker"

const AUTO_RUN_KEY = "figure-studio-auto-run"
const AUTO_RUN_DELAY_MS = 1200

const Plot = lazy(() => import("react-plotly.js"))

const MAX_DATA_BYTES = 20 * 1024 * 1024

/** A repo file's text, from the inline content or its storage URL. */
async function fetchFileText(
  accountName: string,
  projectName: string,
  path: string,
): Promise<string> {
  const item = await ProjectsService.getProjectContents({
    owner_name: accountName,
    project_name: projectName,
    path,
  }).then((response) => response.data as any)
  if (item?.size && item.size > MAX_DATA_BYTES) {
    throw new Error(`${path} is too large to load in the browser.`)
  }
  if (item?.content) {
    return atob(item.content)
  }
  if (item?.url) {
    const resp = await fetch(String(item.url))
    if (!resp.ok) throw new Error(`Could not fetch ${path}.`)
    return resp.text()
  }
  throw new Error(`No content available for ${path}.`)
}

/**
 * A glance at a dataset: its columns and first rows, behind an info icon.
 *
 * Picking what to plot means knowing what's in the file, and opening the
 * datasets page to find out would lose the script in progress.
 */
function DatasetPeek({
  accountName,
  projectName,
  path,
}: {
  accountName: string
  projectName: string
  path: string
}) {
  const [open, setOpen] = useState(false)
  const peekQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "studio-data", [path]],
    queryFn: async () => ({
      [path]: await fetchFileText(accountName, projectName, path),
    }),
    enabled: open,
    retry: false,
    staleTime: 60_000,
  })
  const text = peekQuery.data?.[path]
  const preview = text ? previewCsv(text, 5) : null
  const rowCount = text ? Math.max(0, text.trimEnd().split("\n").length - 1) : 0
  return (
    <Popover
      isOpen={open}
      onOpen={() => setOpen(true)}
      onClose={() => setOpen(false)}
      placement="bottom-start"
      isLazy
    >
      <PopoverTrigger>
        <IconButton
          aria-label={`Peek at ${path}`}
          icon={<InfoOutlineIcon />}
          size="xs"
          variant="ghost"
          ml={1}
        />
      </PopoverTrigger>
      <PopoverContent width="auto" maxW="min(90vw, 640px)">
        <PopoverArrow />
        <PopoverCloseButton />
        <PopoverHeader fontSize="sm" fontWeight="semibold" pr={8}>
          <Code fontSize="xs">{path}</Code>
          {preview ? (
            <Text as="span" color="ui.dim" fontWeight="normal" ml={2}>
              {preview.columns.length} columns, {rowCount}{" "}
              {rowCount === 1 ? "row" : "rows"}
            </Text>
          ) : null}
        </PopoverHeader>
        <PopoverBody>
          {peekQuery.isPending ? (
            <Spinner size="sm" />
          ) : peekQuery.isError ? (
            <Text fontSize="sm" color="red.400">
              {(peekQuery.error as Error).message}
            </Text>
          ) : preview ? (
            <TableContainer maxW="100%">
              <Table size="sm" variant="simple">
                <Thead>
                  <Tr>
                    {preview.columns.map((c) => (
                      <Th key={c} fontSize="xs">
                        {c}
                      </Th>
                    ))}
                  </Tr>
                </Thead>
                <Tbody>
                  {preview.rows.map((row, r) => (
                    <Tr key={r}>
                      {preview.columns.map((_, c) => (
                        <Td key={c} fontSize="xs" fontFamily="mono">
                          {row[c] ?? ""}
                        </Td>
                      ))}
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </TableContainer>
          ) : null}
        </PopoverBody>
      </PopoverContent>
    </Popover>
  )
}

/** An existing script stage to edit, rather than a new figure to make. */
export interface StudioEdit {
  stage: string
  scriptPath: string
  figurePath: string
  datasetPaths: string[]
  /** The stage's own environment, kept on save. */
  environment?: string | null
  title?: string | null
  description?: string | null
}

interface FigureStudioProps {
  isOpen: boolean
  onClose: () => void
  /** Supplied when rendered outside the project route. */
  ownerName?: string
  projectName?: string
  /** Dataset to open on; the first CSV dataset otherwise. */
  initialDataset?: string
  /** Open on an existing stage's script; saving updates that stage. */
  edit?: StudioEdit
  onSaved?: (result: StudioFigure) => void
}

/**
 * Draft a figure in the browser, then commit it as a pipeline stage.
 *
 * The whole point of an environment is that a script runs the same
 * everywhere, but nobody wants to set one up before they've seen a single
 * plot. So the plot comes first, on a Python that needs no install, and
 * the environment is created (or amended) the moment the figure is saved,
 * as part of making it a stage. What gets committed is exactly the script
 * that ran here; what runs in the pipeline is the real environment.
 */
const FigureStudio = ({
  isOpen,
  onClose,
  ownerName,
  projectName: projectNameProp,
  initialDataset,
  edit,
  onSaved,
}: FigureStudioProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeParams = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const accountName = ownerName ?? routeParams.accountName ?? ""
  const projectName = projectNameProp ?? routeParams.projectName ?? ""
  const previewBg = useColorModeValue("gray.50", "gray.800")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const [datasetPaths, setDatasetPaths] = useState<string[]>(
    edit?.datasetPaths ?? (initialDataset ? [initialDataset] : []),
  )
  const [title, setTitle] = useState(edit?.title ?? "")
  const [description, setDescription] = useState(edit?.description ?? "")
  const [code, setCode] = useState("")
  // An existing script counts as touched from the start: it is the user's,
  // and nothing here should regenerate it.
  const [codeTouched, setCodeTouched] = useState(Boolean(edit))
  const [editorKey, setEditorKey] = useState(0)
  const [status, setStatus] = useState("")
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunResult | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  // A plotly figure arrives as JSON rather than pixels; it's parsed once
  // per run and drawn with plotly.js, the way the figures page draws it.
  const [plotSpec, setPlotSpec] = useState<{
    data: unknown[]
    layout: Record<string, unknown>
  } | null>(null)
  const [htmlDoc, setHtmlDoc] = useState<string | null>(null)
  const [showOutput, setShowOutput] = useState(false)
  // The script as first shown is not the script to auto-run: a new figure's
  // template is regenerated once the data's columns are known, and an
  // existing script arrives from the repo. This flips when that's done.
  const [codeSettled, setCodeSettled] = useState(false)
  const viewRef = useRef<EditorView | null>(null)
  const discardDialog = useDisclosure()
  const keepEditingRef = useRef<HTMLButtonElement>(null)
  const datasetsQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "datasets"],
    queryFn: () =>
      ProjectsService.getProjectDatasets({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: isOpen && Boolean(accountName && projectName),
  })
  const declaredDatasets = useMemo(
    () => (datasetsQuery.data ?? []).map((d) => d.path),
    [datasetsQuery.data],
  )
  // The stage will run in the project's Python environment when there is
  // one, so the browser run loads that environment's packages first and
  // the save names it explicitly rather than leaving the choice implicit.
  const environmentsQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "environments"],
    queryFn: () =>
      ProjectsService.getProjectEnvironments({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: isOpen && Boolean(accountName && projectName),
  })
  const pythonEnv = useMemo(
    () => pickPythonEnv(environmentsQuery.data ?? []),
    [environmentsQuery.data],
  )
  const envPackageNames = useMemo(() => envPackages(pythonEnv), [pythonEnv])
  // What the stage will run in: its own environment when editing (which
  // may be a Docker image, not something to swap for a venv), else the
  // Python one the save will name.
  const runEnvName = edit?.environment ?? pythonEnv?.name
  // The first CSV is the default for a new figure, which on a template
  // project is the data its own pipeline plots (a CSV because that's what
  // the template script knows how to read); failing that, the first
  // dataset of any kind. An existing stage's inputs are whatever they
  // are; nothing gets picked for it.
  useEffect(() => {
    if (!edit && !datasetPaths.length && declaredDatasets.length) {
      setDatasetPaths([
        initialDataset ??
          declaredDatasets.find(isCsvPath) ??
          declaredDatasets[0],
      ])
    }
  }, [declaredDatasets, datasetPaths.length, initialDataset, edit])
  // What's offered: the declared datasets, plus anything already selected
  // that isn't declared as a dataset (a stage input that's the output of
  // another stage, say), so it can be seen and unticked.
  const datasetOptions = useMemo(
    () => [
      ...datasetPaths.filter((p) => !declaredDatasets.includes(p)),
      ...declaredDatasets,
    ],
    [datasetPaths, declaredDatasets],
  )
  const primaryPath = datasetPaths[0] ?? ""
  // Editing starts from the script as committed.
  const scriptQuery = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "studio-script",
      edit?.scriptPath,
    ],
    queryFn: () => fetchFileText(accountName, projectName, edit!.scriptPath),
    enabled: isOpen && Boolean(edit),
    retry: false,
    staleTime: 60_000,
  })
  useEffect(() => {
    if (scriptQuery.data !== undefined && !code) {
      setCode(scriptQuery.data)
      setEditorKey((k) => k + 1)
      setCodeSettled(true)
      // The script is the last word on what it reads. The stage definition
      // is asked first, but a dvc.yaml that predates the stage, or inputs
      // declared as another stage's outputs, can leave that list short.
      const fromScript = readDataPaths(scriptQuery.data)
      setDatasetPaths((current) => [
        ...current,
        ...fromScript.filter((p) => !current.includes(p)),
      ])
    }
  }, [scriptQuery.data, code])
  // Every chosen input is fetched up front, as bytes, and written into the
  // in-browser filesystem at its repo path, so the script reads it exactly
  // as it will in the pipeline. An input can be anything a script reads:
  // an HDF5 file, a folder of simulation output, a sqlite database. What
  // can't be fetched is reported rather than silently left out.
  const dataQuery = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "studio-data",
      [...datasetPaths].sort(),
    ],
    queryFn: async () => {
      const budget = newBudget()
      const problems: string[] = []
      const files: { path: string; data: Uint8Array }[] = []
      for (const path of datasetPaths) {
        files.push(
          ...(await fetchTree(
            accountName,
            projectName,
            path,
            budget,
            setStatus,
            problems,
          )),
        )
      }
      setStatus("")
      return { files, problems }
    },
    enabled: isOpen && datasetPaths.length > 0,
    retry: false,
    staleTime: 60_000,
  })
  // Columns are only a CSV's to show; other inputs are the script's
  // business to open.
  const preview = useMemo(() => {
    if (!isCsvPath(primaryPath)) return null
    const file = dataQuery.data?.files.find((f) => f.path === primaryPath)
    return file ? previewCsv(bytesToText(file.data)) : null
  }, [dataQuery.data, primaryPath])
  const inputsReady = datasetPaths.length === 0 || Boolean(dataQuery.data)
  // A new selection of inputs, from the checkboxes or the picker. An
  // edited script keeps its edits and only has its loading lines swapped,
  // written through the editor so undo history and cursor survive. An
  // untouched one is regenerated wholesale by the effect above.
  const applyInputs = (ordered: string[]) => {
    setDatasetPaths(ordered)
    setResult(null)
    const view = viewRef.current
    if (codeTouched && view) {
      view.dispatch({
        changes: {
          from: 0,
          to: view.state.doc.length,
          insert: withDatasetLines(code, ordered),
        },
      })
    }
  }
  // Defaults follow the first dataset until the user has edited something.
  useEffect(() => {
    if (!primaryPath) return
    const numeric = preview ? numericColumns(preview.columns, preview.rows) : []
    const [x, y] = numeric.length >= 2 ? numeric : [undefined, undefined]
    const nextFigure = `figures/${slug(stem(primaryPath))}.png`
    setTitle(
      (current) => current || (x && y ? `${y} vs. ${x}` : stem(primaryPath)),
    )
    if (!codeTouched) {
      setCode(defaultScript({ datasetPaths, figurePath: nextFigure, x, y }))
      setEditorKey((k) => k + 1)
      // Only the version written with the columns in hand is worth running
      // (for a CSV; anything else has no columns to wait for).
      if (preview || !isCsvPath(primaryPath)) setCodeSettled(true)
    }
  }, [primaryPath, datasetPaths, preview, codeTouched])
  useEffect(() => {
    setPlotSpec(null)
    setHtmlDoc(null)
    if (!result?.image) {
      setImageUrl(null)
      return
    }
    if (result.image.type === "application/json") {
      setImageUrl(null)
      result.image.text().then((text) => {
        try {
          const parsed = JSON.parse(text)
          setPlotSpec({ data: parsed.data ?? [], layout: parsed.layout ?? {} })
        } catch {
          setPlotSpec(null)
        }
      })
      return
    }
    if (result.image.type === "text/html") {
      setImageUrl(null)
      result.image.text().then(setHtmlDoc)
      return
    }
    const url = URL.createObjectURL(result.image)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [result])
  const figurePath = savefigPath(code) ?? (edit ? edit.figurePath : "")
  const scriptPath =
    edit?.scriptPath ?? `scripts/plot-${slug(stem(figurePath || "figure"))}.py`
  const packages = useMemo(() => packagesFromImports(code), [code])
  const canRun = Boolean(inputsReady && figurePath && code.trim())
  // One run on launch, as soon as the data and script are in, so the
  // studio opens on a figure rather than on an empty pane.
  const autoRan = useRef(false)
  // Re-run on edit, a moment after typing stops, for those who'd rather
  // watch the figure follow the script than press a key. Remembered across
  // sessions, since it's a way of working rather than a per-figure choice.
  const [autoRun, setAutoRun] = useState(() => {
    try {
      return localStorage.getItem(AUTO_RUN_KEY) === "true"
    } catch {
      return false
    }
  })
  const toggleAutoRun = (on: boolean) => {
    setAutoRun(on)
    mixpanel.track("Toggled studio auto-run", { on })
    try {
      localStorage.setItem(AUTO_RUN_KEY, String(on))
    } catch {
      // Private mode or blocked storage: the choice lasts the session
    }
  }
  const lastRunCode = useRef<string | null>(null)
  const run = async () => {
    if (!inputsReady || !figurePath || running) return
    setRunning(true)
    setResult(null)
    lastRunCode.current = code
    const started = performance.now()
    if (envPackageNames.length) {
      setStatus(`Loading ${pythonEnv?.name} packages`)
      await preloadPackages(envPackageNames)
    }
    const res = await runFigureScript({
      code,
      files: dataQuery.data?.files ?? [],
      figurePath,
      onStatus: setStatus,
    })
    setStatus("")
    setRunning(false)
    setResult(res)
    mixpanel.track("Ran studio figure", {
      ok: res.error === null,
      duration_ms: Math.round(performance.now() - started),
      n_packages: packages.length,
      n_datasets: datasetPaths.length,
    })
  }
  // biome-ignore lint/correctness/useExhaustiveDependencies: fire once, when runnable
  useEffect(() => {
    if (isOpen && canRun && codeSettled && !autoRan.current && !running) {
      autoRan.current = true
      run()
    }
  }, [isOpen, canRun, codeSettled])
  // The debounced re-run: waits out a pause in typing, then runs the
  // script as it stands, unless that exact text already ran. A run in
  // progress isn't interrupted; the next keystroke restarts the wait.
  const runRef = useRef(run)
  runRef.current = run
  useEffect(() => {
    if (!autoRun || !canRun || !codeSettled || !codeTouched) return
    if (code === lastRunCode.current) return
    const timer = setTimeout(() => {
      if (!running) runRef.current()
    }, AUTO_RUN_DELAY_MS)
    return () => clearTimeout(timer)
  }, [autoRun, code, canRun, codeSettled, codeTouched, running])
  const saveMutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectStudioFigure({
        owner_name: accountName,
        project_name: projectName,
        studioFigurePost: {
          figure_path: figurePath,
          title,
          description: description || null,
          script_path: scriptPath,
          script_content: code,
          inputs: datasetPaths,
          packages,
          // An existing stage keeps the environment it runs in
          environment: edit?.environment ?? pythonEnv?.name ?? null,
          stage: edit?.stage ?? null,
        },
      }).then((response) => response.data),
    onSuccess: (data) => {
      const envNote = data.environment_created
        ? ` A Python environment "${data.environment}" was created for it.`
        : ""
      showToast(
        "Saved to the pipeline",
        `Stage ${data.stage_name} will produce ${data.figure.path} on the ` +
          `next run.${envNote}`,
        "success",
      )
      for (const key of [
        "figures",
        "pipeline",
        "environments",
        "repro-check",
        "contents",
      ]) {
        queryClient.invalidateQueries({
          queryKey: ["projects", accountName, projectName, key],
        })
      }
      onSaved?.(data)
      onClose()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const canSave = Boolean(
    result?.image && !result.error && title.trim() && figurePath,
  )
  // An edited script or a figure that rendered but was never saved is work
  // that closing would throw away; a generated script nobody touched isn't.
  const hasUnsavedWork = codeTouched || Boolean(result?.image)
  // What "Discard" should do: close, or leave for somewhere else. A link
  // out of the studio is the same question as closing it, so it goes
  // through the same confirmation.
  const pendingLeave = useRef<() => void>(onClose)
  const requestLeave = (leave: () => void) => {
    if (hasUnsavedWork && !saveMutation.isSuccess) {
      pendingLeave.current = leave
      discardDialog.onOpen()
      return
    }
    leave()
  }
  const requestClose = () => requestLeave(onClose)
  const navigate = useNavigate()
  const goToEnvironment = () =>
    navigate({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      to: `/${accountName}/${projectName}/environments` as any,
      search: { name: pythonEnv?.name } as any,
    })
  const output = [result?.stdout, result?.stderr].filter(Boolean).join("")
  const outputLines = output ? output.trimEnd().split("\n").length : 0
  return (
    <Modal
      isOpen={isOpen}
      onClose={requestClose}
      // The figure is the point, so the studio gets most of the viewport,
      // while still reading as a dialog over the page it came from.
      size="6xl"
      scrollBehavior="inside"
      isCentered
    >
      <ModalOverlay />
      <ModalContent
        maxW={{ base: "100%", lg: "92vw" }}
        maxH="92vh"
        // Cmd+Enter reruns the script from anywhere in the studio, the
        // editor included; there's no form here for it to submit instead.
        onKeyDown={(e) => {
          // The editor handles the chord itself (and marks the event
          // handled); this catches it from the other fields.
          if (e.defaultPrevented) return
          if (isSubmitChord(e) && canRun) {
            e.preventDefault()
            e.stopPropagation()
            run()
          }
        }}
      >
        <ModalHeader>{edit ? "Edit figure" : "New figure"}</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={4}>
          <Text fontSize="sm" color="ui.dim" mb={4}>
            {edit
              ? `This is the script behind stage ${edit.stage}, run here in ` +
                "the browser. Saving commits the changes to that stage; the " +
                "figure on the project page updates on the next real run."
              : "Plot the data right here, no install needed. Saving " +
                "commits the script as a pipeline stage with a real " +
                "environment, so the figure is reproducible from then on."}
          </Text>
          <Grid
            templateColumns={{
              base: "1fr",
              lg: "minmax(0, 1fr) minmax(0, 1fr)",
            }}
            gap={6}
          >
            <GridItem minW={0}>
              <FormControl mb={3}>
                <Flex align="center" mb={1}>
                  <FormLabel fontSize="sm" mb={0} mr={1.5}>
                    Inputs
                  </FormLabel>
                  {/* Anything the script reads can be an input, not only a
                      declared dataset: another stage's output folder, a
                      config file, a results tree. */}
                  <PathPicker
                    ownerName={accountName}
                    projectName={projectName}
                    value=""
                    allowFolders
                    onChange={(path) => {
                      if (path && !datasetPaths.includes(path)) {
                        applyInputs([...datasetPaths, path])
                      }
                    }}
                    trigger={
                      <IconButton
                        aria-label="Add an input file or folder"
                        icon={<FaPlus fontSize="9px" />}
                        size="xs"
                        variant="primary"
                        height="16px"
                        minW="16px"
                      />
                    }
                  />
                </Flex>
                {datasetOptions.length ? (
                  <CheckboxGroup
                    value={datasetPaths}
                    onChange={(values) => {
                      // Keep the order of selection, so the first one
                      // picked stays the one the script calls `df`.
                      const next = values.map(String)
                      applyInputs([
                        ...datasetPaths.filter((p) => next.includes(p)),
                        ...next.filter((p) => !datasetPaths.includes(p)),
                      ])
                    }}
                  >
                    <Wrap spacing={4}>
                      {datasetOptions.map((p) => (
                        <WrapItem key={p} alignItems="center">
                          <Checkbox value={p} size="sm" colorScheme="teal">
                            <Code fontSize="xs">{p}</Code>
                          </Checkbox>
                          {isCsvPath(p) ? (
                            <DatasetPeek
                              accountName={accountName}
                              projectName={projectName}
                              path={p}
                            />
                          ) : null}
                        </WrapItem>
                      ))}
                    </Wrap>
                  </CheckboxGroup>
                ) : (
                  <Text fontSize="sm" color="ui.dim">
                    {datasetsQuery.isPending
                      ? "Loading datasets"
                      : "No datasets declared yet. Add one from the " +
                        "datasets page first."}
                  </Text>
                )}
                {preview?.columns.length ? (
                  <FormHelperText fontSize="xs">
                    {datasetPaths.length > 1
                      ? `df is ${primaryPath}; columns: `
                      : "Columns: "}
                    {preview.columns.join(", ")}
                  </FormHelperText>
                ) : dataQuery.isError ? (
                  <FormHelperText fontSize="xs" color="red.400">
                    {(dataQuery.error as Error).message}
                  </FormHelperText>
                ) : null}
                {dataQuery.data?.problems.length ? (
                  <FormHelperText fontSize="xs" color="red.400">
                    Some inputs didn't load:{" "}
                    {dataQuery.data.problems.join("; ")}
                  </FormHelperText>
                ) : null}
              </FormControl>
              <Box
                borderWidth={1}
                borderColor={borderColor}
                borderRadius="md"
                overflow="hidden"
                height={{ base: "340px", lg: "calc(92vh - 400px)" }}
                minH="340px"
              >
                {edit && scriptQuery.isError ? (
                  <Text p={3} fontSize="sm" color="red.400">
                    {(scriptQuery.error as Error).message}
                  </Text>
                ) : null}
                {code ? (
                  <CodeEditorPane
                    key={editorKey}
                    initialDoc={code}
                    path={scriptPath}
                    viewRef={viewRef}
                    onChange={(text) => {
                      setCode(text)
                      setCodeTouched(true)
                    }}
                    onModEnter={() => {
                      if (canRun) run()
                    }}
                  />
                ) : null}
              </Box>
              <HStack mt={3} spacing={3}>
                <Button
                  size="sm"
                  variant="primary"
                  onClick={run}
                  isLoading={running}
                  loadingText={status || "Running"}
                  isDisabled={!canRun}
                >
                  Run
                </Button>
                <Text fontSize="xs" color="ui.dim">
                  <Kbd>⌘</Kbd>+<Kbd>Enter</Kbd>
                </Text>
                <Checkbox
                  size="sm"
                  colorScheme="teal"
                  isChecked={autoRun}
                  onChange={(e) => toggleAutoRun(e.target.checked)}
                >
                  <Text fontSize="xs" color="ui.dim">
                    Auto-run
                  </Text>
                </Checkbox>
                <Text fontSize="xs" color="ui.dim">
                  {packages.length
                    ? `Uses ${packages.join(", ")}`
                    : "No packages detected"}
                  {runEnvName ? (
                    <>
                      . Runs in environment{" "}
                      <Link
                        cursor="pointer"
                        // Leaving unmounts the studio, so unsaved work gets
                        // the same confirmation as closing it would.
                        onClick={() => requestLeave(goToEnvironment)}
                      >
                        '{runEnvName}'
                      </Link>
                      .
                    </>
                  ) : environmentsQuery.isSuccess ? (
                    ". A Python environment will be created on save"
                  ) : (
                    ""
                  )}
                </Text>
                {outputLines > 0 ? (
                  <Button
                    size="xs"
                    variant="link"
                    ml="auto"
                    onClick={() => setShowOutput((v) => !v)}
                  >
                    {showOutput ? "Hide output" : "Show output"} ({outputLines}{" "}
                    {outputLines === 1 ? "line" : "lines"})
                  </Button>
                ) : null}
              </HStack>
              <Collapse in={showOutput && outputLines > 0} animateOpacity>
                <Code
                  display="block"
                  whiteSpace="pre-wrap"
                  fontSize="xs"
                  p={2}
                  mt={2}
                  maxH="160px"
                  overflowY="auto"
                >
                  {output}
                </Code>
              </Collapse>
            </GridItem>
            <GridItem minW={0}>
              <Box
                bg={previewBg}
                borderWidth={1}
                borderColor={borderColor}
                borderRadius="md"
                minH={{ base: "240px", lg: "calc(92vh - 520px)" }}
                display="flex"
                alignItems="center"
                justifyContent="center"
                p={2}
                mb={3}
              >
                {running ? (
                  <Flex direction="column" align="center" gap={2}>
                    <Spinner />
                    <Text fontSize="xs" color="ui.dim">
                      {status || "Running"}
                    </Text>
                  </Flex>
                ) : plotSpec ? (
                  // At the figure's own height (plotly's default is 450px),
                  // capped to the pane, the way the figures page draws it;
                  // a percentage height here would let the plot's default
                  // margins push it off center.
                  <Box
                    width="100%"
                    height={`${
                      typeof plotSpec.layout.height === "number"
                        ? plotSpec.layout.height
                        : 450
                    }px`}
                    maxH="100%"
                  >
                    <Suspense fallback={<Spinner />}>
                      <Plot
                        data={plotSpec.data as any}
                        layout={
                          {
                            ...plotSpec.layout,
                            autosize: true,
                            height: undefined,
                            width: undefined,
                          } as any
                        }
                        config={{ displayModeBar: false, responsive: true }}
                        style={{ width: "100%", height: "100%" }}
                        useResizeHandler
                        // Plotly measures its container on mount, before the
                        // pane has settled its size, and lays the plot out
                        // off center until something triggers a resize. A
                        // resize event on the next frame is that something.
                        onInitialized={() =>
                          requestAnimationFrame(() =>
                            window.dispatchEvent(new Event("resize")),
                          )
                        }
                      />
                    </Suspense>
                  </Box>
                ) : htmlDoc ? (
                  <iframe
                    title="Figure"
                    srcDoc={htmlDoc}
                    sandbox="allow-scripts"
                    style={{ width: "100%", height: "60vh", border: 0 }}
                  />
                ) : imageUrl ? (
                  result?.image?.type === "application/pdf" ? (
                    // The same renderer the figures page uses, rather than
                    // the browser's embed and its toolbar
                    // PdfCanvas centers its pages within the height it's
                    // given, so it gets the pane's inner height exactly: the
                    // pane's minimum less its padding. A stretched wrapper
                    // would leave the pages pinned to the top instead.
                    <Box width="100%">
                      <PdfCanvas
                        src={imageUrl}
                        width="100%"
                        height="calc(92vh - 536px)"
                      />
                    </Box>
                  ) : (
                    <Image
                      src={imageUrl}
                      alt={title || "Figure"}
                      maxH={{ base: "360px", lg: "calc(92vh - 540px)" }}
                      maxW="100%"
                    />
                  )
                ) : (
                  <Text fontSize="sm" color="ui.dim" textAlign="center">
                    The figure appears here after a run.
                  </Text>
                )}
              </Box>
              {result?.error ? (
                <Alert
                  status="error"
                  borderRadius="md"
                  mb={3}
                  fontSize="sm"
                  alignItems="flex-start"
                >
                  <AlertIcon />
                  {/* A Python traceback only reads with its indentation
                      intact, so it's shown as code rather than prose. */}
                  <AlertDescription
                    as="pre"
                    fontFamily="mono"
                    fontSize="xs"
                    whiteSpace="pre-wrap"
                    wordBreak="break-word"
                    maxH="200px"
                    overflowY="auto"
                    m={0}
                  >
                    {result.error}
                  </AlertDescription>
                </Alert>
              ) : null}
              <FormControl mb={3} isRequired>
                <FormLabel htmlFor="studio-title" fontSize="sm">
                  Title
                </FormLabel>
                <Input
                  id="studio-title"
                  size="sm"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  autoComplete="off"
                />
              </FormControl>
              <FormControl mb={3}>
                <FormLabel htmlFor="studio-description" fontSize="sm">
                  Description
                </FormLabel>
                <Input
                  id="studio-description"
                  size="sm"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What the figure shows"
                  autoComplete="off"
                />
              </FormControl>
              <FormControl isInvalid={!figurePath}>
                <FormLabel htmlFor="studio-path" fontSize="sm">
                  Figure path
                </FormLabel>
                <Input
                  id="studio-path"
                  size="sm"
                  value={figurePath}
                  isReadOnly
                  placeholder="No fig.savefig(...) call found in the script"
                  autoComplete="off"
                />
                <FormHelperText fontSize="xs">
                  Set by the <Code fontSize="xs">savefig</Code> call in the
                  script. Saved as stage{" "}
                  <Code fontSize="xs">
                    {edit?.stage ??
                      `plot-${slug(stem(figurePath || "figure"))}`}
                  </Code>{" "}
                  running <Code fontSize="xs">{scriptPath}</Code>.
                </FormHelperText>
              </FormControl>
            </GridItem>
          </Grid>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            onClick={() => saveMutation.mutate()}
            isLoading={saveMutation.isPending}
            isDisabled={!canSave}
            title={canSave ? undefined : "Run the script successfully first"}
          >
            Save to pipeline
          </Button>
          <Button onClick={requestClose}>Cancel</Button>
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
            <AlertDialogHeader fontSize="lg">
              Discard this figure?
            </AlertDialogHeader>
            <AlertDialogBody>
              {result?.image
                ? "The figure you made hasn't been saved to the pipeline. " +
                  "Leaving now drops it and the script."
                : "The script has edits that haven't been saved to the " +
                  "pipeline. Leaving now drops them."}
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button ref={keepEditingRef} onClick={discardDialog.onClose}>
                Keep editing
              </Button>
              <Button
                colorScheme="red"
                onClick={() => {
                  mixpanel.track("Discarded studio figure", {
                    had_figure: Boolean(result?.image),
                  })
                  discardDialog.onClose()
                  pendingLeave.current()
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

export default FigureStudio
