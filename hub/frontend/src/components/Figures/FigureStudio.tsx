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
import { ExternalLinkIcon, InfoOutlineIcon } from "@chakra-ui/icons"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink, useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import type { EditorView } from "codemirror"
import mixpanel from "mixpanel-browser"
import { useEffect, useMemo, useRef, useState } from "react"

import {
  type Environment,
  ProjectsService,
  type StudioFigure,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { isSubmitChord } from "../../hooks/useSubmitOnCmdEnter"
import { numericColumns, previewCsv } from "../../lib/csv"
import { handleError } from "../../lib/errors"
import {
  type RunResult,
  packagesFromImports,
  preloadPackages,
  runFigureScript,
} from "../../lib/pyodide"
import CodeEditorPane from "../Common/CodeEditorPane"

const MAX_DATA_BYTES = 20 * 1024 * 1024

// Kinds a Python script can run in, most preferred first. Mirrors the
// backend's choice, so what the studio shows is what the stage gets.
const PYTHON_ENV_KINDS = ["uv", "uv-venv", "pixi", "conda", "venv"]

/** The project's Python environment the stage would run in, if any. */
export function pickPythonEnv(envs: Environment[]): Environment | null {
  for (const kind of PYTHON_ENV_KINDS) {
    const match = envs.find((e) => e.kind === kind)
    if (match) return match
  }
  return null
}

/**
 * Package names declared in an environment's spec file.
 *
 * Good enough to mirror the environment in the browser: one name per line
 * for requirements files, quoted entries for pyproject and pixi, dashed
 * entries for conda. Version pins and extras are dropped, since Pyodide
 * ships one version of each.
 */
export function envPackages(env: Environment | null): string[] {
  const text = env?.file_content ?? ""
  const names = new Set<string>()
  // YAML specs (conda) list channels and dependencies as sibling lists;
  // only the dependencies are packages.
  let section = ""
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    if (!line || line.startsWith("#") || line.startsWith("[")) continue
    if (/^[A-Za-z_-]+:\s*$/.test(line)) {
      section = line.slice(0, -1)
      continue
    }
    if (line.startsWith("-") && section && section !== "dependencies") continue
    const match = line.match(
      /^(?:-\s*)?["']?([A-Za-z0-9][A-Za-z0-9._-]*)["']?\s*(?:[<>=!~\[;, ]|$)/,
    )
    if (!match) continue
    const name = match[1].toLowerCase()
    if (
      ["python", "pip", "name", "version", "channels", "dependencies"].includes(
        name,
      )
    ) {
      continue
    }
    names.add(name)
  }
  return [...names]
}

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

/**
 * The path the script saves its figure to, read from the last savefig call.
 *
 * The script is the source of truth for where the figure lands, since that
 * is what the stage will run; the form only reflects it.
 */
export function savefigPath(code: string): string | null {
  const matches = [
    ...code.matchAll(/\.savefig\(\s*(?:fname\s*=\s*)?[rf]?(["'])([^"'\n]+)\1/g),
  ]
  const last = matches.at(-1)
  return last ? last[2] : null
}

const stem = (path: string) =>
  (path.split("/").pop() ?? path).replace(/\.[^.]+$/, "")

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "figure"

const isLoadLine = (line: string) => /^\s*df\d*\s*=\s*pd\.read_csv\(/.test(line)

const loadLines = (paths: string[]) =>
  paths.map(
    (path, i) =>
      `${i === 0 ? "df" : `df${i + 1}`} = pd.read_csv(${JSON.stringify(path)})`,
  )

/**
 * The script with its `df = pd.read_csv(...)` lines replaced for a new
 * dataset selection, everything else left as the user wrote it.
 *
 * The new lines go where the old ones were; a script with none yet gets
 * them after its imports.
 */
export function withDatasetLines(code: string, paths: string[]): string {
  const lines = code.split("\n")
  const first = lines.findIndex(isLoadLine)
  const kept = lines.filter((line) => !isLoadLine(line))
  const fresh = loadLines(paths)
  if (first !== -1) {
    kept.splice(first, 0, ...fresh)
    return kept.join("\n")
  }
  let lastImport = -1
  kept.forEach((line, i) => {
    if (/^\s*(import|from)\s/.test(line)) lastImport = i
  })
  kept.splice(lastImport + 1, 0, "", ...fresh)
  return kept.join("\n")
}

/** A plotting script for the chosen datasets, as the starting point to edit. */
export function defaultScript({
  datasetPaths,
  figurePath,
  x,
  y,
}: {
  datasetPaths: string[]
  figurePath: string
  x?: string
  y?: string
}): string {
  const [first] = datasetPaths
  const lines = ["import matplotlib.pyplot as plt", "import pandas as pd", ""]
  // The first dataset is `df`; the rest count up from df2.
  lines.push(...loadLines(datasetPaths))
  lines.push("", "fig, ax = plt.subplots(figsize=(5, 3.5))")
  if (first && x && y) {
    lines.push(
      `ax.plot(df[${JSON.stringify(x)}], df[${JSON.stringify(y)}], "o")`,
      `ax.set_xlabel(${JSON.stringify(x)})`,
      `ax.set_ylabel(${JSON.stringify(y)})`,
    )
  } else if (first) {
    lines.push(
      "# Pick the columns to plot; df.columns lists them.",
      "df.plot(ax=ax)",
    )
  } else {
    lines.push("# Choose a dataset above, or load one here.")
  }
  lines.push(
    "fig.tight_layout()",
    `fig.savefig(${JSON.stringify(figurePath)}, dpi=150)`,
    "",
  )
  return lines.join("\n")
}

/** An existing script stage to edit, rather than a new figure to make. */
export interface StudioEdit {
  stage: string
  scriptPath: string
  figurePath: string
  datasetPaths: string[]
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
  const [showOutput, setShowOutput] = useState(false)
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
  const csvDatasets = useMemo(
    () =>
      (datasetsQuery.data ?? [])
        .map((d) => d.path)
        .filter((p) => p.toLowerCase().endsWith(".csv")),
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
  // The first CSV is the default, which on a template project is the data
  // its own pipeline plots.
  useEffect(() => {
    if (!datasetPaths.length && csvDatasets.length) {
      setDatasetPaths([initialDataset ?? csvDatasets[0]])
    }
  }, [csvDatasets, datasetPaths.length, initialDataset])
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
    }
  }, [scriptQuery.data, code])
  // Every chosen file is fetched up front and written into the in-browser
  // filesystem at its repo path, so the script reads them exactly as it
  // will in the pipeline.
  const dataQuery = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "studio-data",
      [...datasetPaths].sort(),
    ],
    queryFn: async () => {
      const entries = await Promise.all(
        datasetPaths.map(
          async (path) =>
            [
              path,
              await fetchFileText(accountName, projectName, path),
            ] as const,
        ),
      )
      return Object.fromEntries(entries) as Record<string, string>
    },
    enabled: isOpen && datasetPaths.length > 0,
    retry: false,
    staleTime: 60_000,
  })
  const preview = useMemo(() => {
    const text = dataQuery.data?.[primaryPath]
    return text ? previewCsv(text) : null
  }, [dataQuery.data, primaryPath])
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
    }
  }, [primaryPath, datasetPaths, preview, codeTouched])
  useEffect(() => {
    if (!result?.image) {
      setImageUrl(null)
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
  const canRun = Boolean(dataQuery.data && figurePath && code.trim())
  const run = async () => {
    if (!dataQuery.data || !figurePath || running) return
    setRunning(true)
    setResult(null)
    const started = performance.now()
    if (envPackageNames.length) {
      setStatus(`Loading ${pythonEnv?.name} packages`)
      await preloadPackages(envPackageNames)
    }
    const res = await runFigureScript({
      code,
      files: Object.entries(dataQuery.data).map(([path, data]) => ({
        path,
        data,
      })),
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
          environment: pythonEnv?.name ?? null,
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
  const requestClose = () => {
    if (hasUnsavedWork && !saveMutation.isSuccess) {
      discardDialog.onOpen()
      return
    }
    onClose()
  }
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
        <ModalHeader>
          {edit ? `Figure studio: ${edit.stage}` : "Figure studio"}
        </ModalHeader>
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
                <FormLabel fontSize="sm">Data</FormLabel>
                {csvDatasets.length ? (
                  <CheckboxGroup
                    value={datasetPaths}
                    onChange={(values) => {
                      // Keep the order of selection, so the first one
                      // picked stays the one the script calls `df`.
                      const next = values.map(String)
                      const ordered = [
                        ...datasetPaths.filter((p) => next.includes(p)),
                        ...next.filter((p) => !datasetPaths.includes(p)),
                      ]
                      setDatasetPaths(ordered)
                      setResult(null)
                      // An edited script keeps its edits and only has its
                      // loading lines swapped, written through the editor
                      // so undo history and cursor survive. An untouched
                      // one is regenerated wholesale by the effect above.
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
                    }}
                  >
                    <Wrap spacing={4}>
                      {csvDatasets.map((p) => (
                        <WrapItem key={p} alignItems="center">
                          <Checkbox value={p} size="sm" colorScheme="teal">
                            <Code fontSize="xs">{p}</Code>
                          </Checkbox>
                          <DatasetPeek
                            accountName={accountName}
                            projectName={projectName}
                            path={p}
                          />
                        </WrapItem>
                      ))}
                    </Wrap>
                  </CheckboxGroup>
                ) : (
                  <Text fontSize="sm" color="ui.dim">
                    {datasetsQuery.isPending
                      ? "Loading datasets"
                      : "No CSV datasets declared yet. Add one from the " +
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
                <Text fontSize="xs" color="ui.dim">
                  {packages.length
                    ? `Uses ${packages.join(", ")}`
                    : "No packages detected"}
                  {pythonEnv ? (
                    <>
                      . Runs in environment{" "}
                      <Link
                        as={RouterLink}
                        // eslint-disable-next-line @typescript-eslint/no-explicit-any
                        to={
                          `/${accountName}/${projectName}/environments` as any
                        }
                        search={{ name: pythonEnv.name } as any}
                        variant="blue"
                        // A new tab, since navigating this one would unmount
                        // the studio and whatever is drafted in it.
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        '{pythonEnv.name}' <ExternalLinkIcon mb={0.5} />
                      </Link>
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
                ) : imageUrl ? (
                  result?.image?.type === "application/pdf" ? (
                    <embed
                      src={imageUrl}
                      type="application/pdf"
                      width="100%"
                      height="60vh"
                    />
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
                  "Closing now drops it and the script."
                : "The script has edits that haven't been saved to the " +
                  "pipeline. Closing now drops them."}
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

export default FigureStudio
