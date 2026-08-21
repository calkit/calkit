import {
  Alert,
  AlertDescription,
  AlertIcon,
  Box,
  Button,
  Code,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  Grid,
  GridItem,
  HStack,
  Image,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  Spinner,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import type { EditorView } from "codemirror"
import mixpanel from "mixpanel-browser"
import { useEffect, useMemo, useRef, useState } from "react"

import { ProjectsService, type StudioFigure } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { numericColumns, previewCsv } from "../../lib/csv"
import { handleError } from "../../lib/errors"
import {
  type RunResult,
  packagesFromImports,
  runFigureScript,
} from "../../lib/pyodide"
import CodeEditorPane from "../Common/CodeEditorPane"

const MAX_DATA_BYTES = 20 * 1024 * 1024

/** A plotting script for a dataset, as the starting point to edit. */
export function defaultScript({
  datasetPath,
  figurePath,
  x,
  y,
}: {
  datasetPath: string
  figurePath: string
  x?: string
  y?: string
}): string {
  const lines = [
    "import matplotlib.pyplot as plt",
    "import pandas as pd",
    "",
    `df = pd.read_csv(${JSON.stringify(datasetPath)})`,
    "",
    "fig, ax = plt.subplots(figsize=(5, 3.5))",
  ]
  if (x && y) {
    lines.push(
      `ax.plot(df[${JSON.stringify(x)}], df[${JSON.stringify(y)}], "o")`,
      `ax.set_xlabel(${JSON.stringify(x)})`,
      `ax.set_ylabel(${JSON.stringify(y)})`,
    )
  } else {
    lines.push(
      "# Pick the columns to plot; df.columns lists them.",
      "df.plot(ax=ax)",
    )
  }
  lines.push(
    "fig.tight_layout()",
    `fig.savefig(${JSON.stringify(figurePath)}, dpi=150)`,
    "",
  )
  return lines.join("\n")
}

const stem = (path: string) =>
  (path.split("/").pop() ?? path).replace(/\.[^.]+$/, "")

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "figure"

interface FigureStudioProps {
  isOpen: boolean
  onClose: () => void
  /** Supplied when rendered outside the project route. */
  ownerName?: string
  projectName?: string
  /** Dataset to open on; the first CSV dataset otherwise. */
  initialDataset?: string
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
  const [datasetPath, setDatasetPath] = useState(initialDataset ?? "")
  const [figurePath, setFigurePath] = useState("")
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [code, setCode] = useState("")
  const [codeTouched, setCodeTouched] = useState(false)
  const [editorKey, setEditorKey] = useState(0)
  const [status, setStatus] = useState("")
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunResult | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const viewRef = useRef<EditorView | null>(null)
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
  // The first CSV is the default, which on a template project is the data
  // its own pipeline plots.
  useEffect(() => {
    if (!datasetPath && csvDatasets.length) {
      setDatasetPath(initialDataset ?? csvDatasets[0])
    }
  }, [csvDatasets, datasetPath, initialDataset])
  const dataQuery = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "studio-data",
      datasetPath,
    ],
    queryFn: async () => {
      const item = await ProjectsService.getProjectContents({
        owner_name: accountName,
        project_name: projectName,
        path: datasetPath,
      }).then((response) => response.data as any)
      if (item?.size && item.size > MAX_DATA_BYTES) {
        throw new Error("That file is too large to load in the browser.")
      }
      if (item?.content) {
        return atob(item.content)
      }
      if (item?.url) {
        const resp = await fetch(String(item.url))
        if (!resp.ok) throw new Error("Could not fetch the data file.")
        return resp.text()
      }
      throw new Error("No content available for that path.")
    },
    enabled: isOpen && Boolean(datasetPath),
    retry: false,
    staleTime: 60_000,
  })
  const preview = useMemo(
    () => (dataQuery.data ? previewCsv(dataQuery.data) : null),
    [dataQuery.data],
  )
  // Defaults follow the dataset until the user has edited something.
  useEffect(() => {
    if (!datasetPath) return
    const numeric = preview ? numericColumns(preview.columns, preview.rows) : []
    const [x, y] = numeric.length >= 2 ? numeric : [undefined, undefined]
    const nextFigure = `figures/${slug(stem(datasetPath))}${
      y ? `-${slug(y)}` : ""
    }.png`
    setFigurePath((current) => current || nextFigure)
    setTitle(
      (current) => current || (x && y ? `${y} vs. ${x}` : stem(datasetPath)),
    )
    if (!codeTouched) {
      setCode(defaultScript({ datasetPath, figurePath: nextFigure, x, y }))
      setEditorKey((k) => k + 1)
    }
  }, [datasetPath, preview, codeTouched])
  useEffect(() => {
    if (!result?.image) {
      setImageUrl(null)
      return
    }
    const url = URL.createObjectURL(result.image)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [result])
  const scriptPath = `scripts/plot-${slug(stem(figurePath || "figure"))}.py`
  const packages = useMemo(() => packagesFromImports(code), [code])
  const run = async () => {
    if (!dataQuery.data || !figurePath) return
    setRunning(true)
    setResult(null)
    const started = performance.now()
    const res = await runFigureScript({
      code,
      files: [{ path: datasetPath, data: dataQuery.data }],
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
          inputs: [datasetPath],
          packages,
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
  const canRun = Boolean(dataQuery.data && figurePath && code.trim())
  const canSave = Boolean(
    result?.image && !result.error && title.trim() && figurePath,
  )
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="6xl"
      scrollBehavior="inside"
      isCentered
    >
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Figure studio</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={4}>
          <Text fontSize="sm" color="ui.dim" mb={4}>
            Plot the data right here, no install needed. Saving commits the
            script as a pipeline stage with a real environment, so the figure is
            reproducible from then on.
          </Text>
          <Grid
            templateColumns={{
              base: "1fr",
              lg: "minmax(0, 3fr) minmax(0, 2fr)",
            }}
            gap={5}
          >
            <GridItem minW={0}>
              <FormControl mb={3}>
                <FormLabel htmlFor="studio-dataset" fontSize="sm">
                  Data
                </FormLabel>
                <HStack>
                  <Select
                    id="studio-dataset"
                    size="sm"
                    value={csvDatasets.includes(datasetPath) ? datasetPath : ""}
                    onChange={(e) => {
                      setDatasetPath(e.target.value)
                      setFigurePath("")
                      setTitle("")
                      setResult(null)
                    }}
                    placeholder={
                      csvDatasets.length
                        ? "Choose a dataset"
                        : "No CSV datasets"
                    }
                    maxW="60%"
                  >
                    {csvDatasets.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </Select>
                  <Input
                    size="sm"
                    value={datasetPath}
                    onChange={(e) => setDatasetPath(e.target.value)}
                    placeholder="or a path to a CSV in the repo"
                    autoComplete="off"
                  />
                </HStack>
                {preview?.columns.length ? (
                  <FormHelperText fontSize="xs">
                    Columns: {preview.columns.join(", ")}
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
                height="340px"
              >
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
                  {packages.length
                    ? `Uses ${packages.join(", ")}`
                    : "No packages detected"}
                </Text>
              </HStack>
            </GridItem>
            <GridItem minW={0}>
              <Box
                bg={previewBg}
                borderWidth={1}
                borderColor={borderColor}
                borderRadius="md"
                minH="240px"
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
                      height="300px"
                    />
                  ) : (
                    <Image
                      src={imageUrl}
                      alt={title || "Figure"}
                      maxH="360px"
                    />
                  )
                ) : (
                  <Text fontSize="sm" color="ui.dim" textAlign="center">
                    The figure appears here after a run.
                  </Text>
                )}
              </Box>
              {result?.error ? (
                <Alert status="error" borderRadius="md" mb={3} fontSize="sm">
                  <AlertIcon />
                  <AlertDescription whiteSpace="pre-wrap">
                    {result.error}
                  </AlertDescription>
                </Alert>
              ) : null}
              {result?.stdout ? (
                <Code
                  display="block"
                  whiteSpace="pre-wrap"
                  fontSize="xs"
                  p={2}
                  mb={3}
                  maxH="100px"
                  overflowY="auto"
                >
                  {result.stdout}
                </Code>
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
              <FormControl>
                <FormLabel htmlFor="studio-path" fontSize="sm">
                  Figure path
                </FormLabel>
                <Input
                  id="studio-path"
                  size="sm"
                  value={figurePath}
                  onChange={(e) => setFigurePath(e.target.value)}
                  autoComplete="off"
                />
                <FormHelperText fontSize="xs">
                  The script should save to this path. Saved as stage{" "}
                  <Code fontSize="xs">
                    plot-{slug(stem(figurePath || "figure"))}
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
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default FigureStudio
