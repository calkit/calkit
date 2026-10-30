/**
 * Modal for viewing an artifact with version comparison support.
 *
 * Shows the artifact content alongside a version history panel. Users can
 * select two commits to compare side-by-side.
 */
import {
  Badge,
  Box,
  Button,
  ButtonGroup,
  Code,
  Divider,
  Flex,
  Heading,
  Icon,
  IconButton,
  Input,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Radio,
  RadioGroup,
  Spinner,
  Stack,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  VStack,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { Suspense, lazy, useEffect, useRef, useState } from "react"
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued"
import { useForm } from "react-hook-form"
import {
  FaChevronLeft,
  FaChevronRight,
  FaCodeBranch,
  FaLink,
} from "react-icons/fa"
import { useDebounce } from "use-debounce"
import SandboxedHtml from "./SandboxedHtml"
import Tooltip from "./Tooltip"

import {
  type ContentsItem,
  type Figure,
  type GitRef,
  type Notebook,
  ProjectsService,
  type Publication,
  type StageFromScript,
} from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import useProject from "../../hooks/useProject"
import { httpStatus } from "../../lib/api"
import { handleError } from "../../lib/errors"
import {
  canBeCreatedByPerson,
  declaredInputs,
  matchDepsToDatasets,
} from "../../lib/provenance"
import {
  IMPORTED_FROM_DEFAULTS,
  type ImportSource,
  ImportedFromFields,
  type ImportedFromForm,
  buildImportedFrom,
} from "../Datasets/NewDataset"
import FigureEditLauncher from "../Figures/FigureEditLauncher"
import FigureView from "../Figures/FigureView"
import {
  AttestationFields,
  type AttestationForm,
  creatorFromUser,
} from "../Figures/UploadFigure"
import FileContent from "../Files/FileContent"
import PathPicker from "../Releases/PathPicker"
import SharedCommentsPanel, {
  projectCommentToPanelComment,
} from "./CommentsPanel"
import InputsRow, { type InputLink } from "./InputsRow"
import Markdown from "./Markdown"
import PdfCanvas from "./PdfCanvas"
import PdfDocumentViewer from "./PdfDocumentViewer"
const IpynbRenderer = lazy(() =>
  import("react-ipynb-renderer").then(async (m) => {
    await import("react-ipynb-renderer/dist/styles/monokai.css")
    return { default: m.IpynbRenderer }
  }),
)

/** "file" covers auto-detected types not explicitly declared in calkit.yaml. */
export type ArtifactKind = "figure" | "publication" | "notebook" | "file"

/** How two versions of a publication are compared. */
export type CompareView = "side-by-side" | "latex-diff"

interface CommitHistory {
  hash: string
  short_hash: string
  message: string
  author: string
  author_email: string
  timestamp: string
  committed_date: number
  parent_hashes: string[]
  summary: string
}

interface ArtifactCompareModalProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  path: string
  kind: ArtifactKind
  initialRef?: string
  initialRef2?: string
  initialArtifact?: Figure | Publication | Notebook | ContentsItem
  onRefsChange?: (ref1: string | undefined, ref2: string | undefined) => void
  onPrev?: () => void
  onNext?: () => void
  /** Whether the figure editor is open, when the page keeps it in the URL. */
  editOpen?: boolean
  onEditOpenChange?: (open: boolean) => void
  /** Unset opens on the LaTeX diff when there is one, else side by side. */
  compareView?: CompareView
  onCompareViewChange?: (view: CompareView) => void
}

/** Render the artifact content for a given kind/data. */
function ArtifactContent({
  kind,
  path,
  data,
  missing,
  atRef,
}: {
  kind: ArtifactKind
  path: string
  data: Figure | Publication | Notebook | ContentsItem | undefined
  /** Whether the hub said there's nothing at this path. */
  missing?: boolean
  /** The version shown, when it isn't the current one. */
  atRef?: string
}) {
  if (!data && missing)
    return (
      <Text color="gray.500">
        This {kind} does not exist{atRef ? " at this version" : ""}.
      </Text>
    )
  if (!data) return <Text color="gray.500">Not available at this version.</Text>

  if (kind === "file") {
    const item = data as ContentsItem
    if (!item.content && !item.url)
      return <Text color="gray.500">No content found for this version.</Text>
    return <FileContent item={item} />
  }

  if (kind === "figure") {
    const fig = data as Figure
    if (!fig.content && !fig.url) {
      return <Text color="gray.500">No content found for this version.</Text>
    }
    if (path.endsWith(".pdf")) {
      const src = fig.content
        ? `data:application/pdf;base64,${fig.content}`
        : String(fig.url)
      return <PdfCanvas src={src} height="100%" />
    }
    return (
      <Box height="100%" width="100%">
        <FigureView figure={fig} fillHeight />
      </Box>
    )
  }

  if (kind === "publication") {
    const pub = data as Publication
    if (!pub.url)
      return <Text color="gray.500">No URL for this publication.</Text>
    if (path.endsWith(".pdf") || pub.url?.includes(".pdf")) {
      return (
        <Box height="75vh" width="100%">
          <PdfDocumentViewer url={pub.url} source="compare" />
        </Box>
      )
    }
    return (
      <Link href={pub.url} isExternal color="blue.500">
        Open publication
      </Link>
    )
  }

  if (kind === "notebook") {
    const nb = data as Notebook
    if (!nb.url && !nb.content)
      return <Text color="gray.500">No content for this version.</Text>
    if (nb.content && nb.output_format === "notebook") {
      try {
        const json = JSON.parse(atob(nb.content))
        return (
          <Box height="75vh" overflowY="auto">
            <Suspense fallback={<Spinner />}>
              <IpynbRenderer ipynb={json} syntaxTheme="atomDark" />
            </Suspense>
          </Box>
        )
      } catch {
        // fall through
      }
    }
    if (nb.content && nb.output_format === "html") {
      return (
        <Box height="75vh" width="100%">
          <SandboxedHtml title="notebook" content={nb.content} />
        </Box>
      )
    }
    if (nb.url) {
      return (
        <Box height="75vh" width="100%">
          <SandboxedHtml title="notebook" url={nb.url} />
        </Box>
      )
    }
    return <Text color="gray.500">Cannot render this notebook.</Text>
  }

  return null
}

function useArtifactAtRef(
  ownerName: string,
  projectName: string,
  path: string,
  kind: ArtifactKind,
  ref: string | undefined,
  enabled: boolean,
) {
  return useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      kind,
      path,
      ref,
      "compare-modal",
    ],
    queryFn: async () => {
      if (kind === "file") {
        return ProjectsService.getProjectContents({
          owner_name: ownerName,
          project_name: projectName,
          path,
          ref,
        }).then((response) => response.data)
      }
      if (kind === "figure") {
        // Fetch just this figure. Listing every figure to pick one out meant
        // downloading and base64-encoding the whole project's figures on each
        // ref, which is what made this modal take minutes to open.
        try {
          return await ProjectsService.getProjectFigure({
            owner_name: ownerName,
            project_name: projectName,
            figure_path: path,
            ref,
          }).then((response) => response.data)
        } catch (err) {
          // A 404 is the one expected outcome: the path isn't a figure at
          // this ref, so show it as a plain file instead. Anything else
          // (auth, 5xx, network) is a real failure and has to surface --
          // swallowing it would silently hand back the wrong shape.
          if (httpStatus(err) !== 404) throw err
          return ProjectsService.getProjectContents({
            owner_name: ownerName,
            project_name: projectName,
            path,
            ref,
          }).then((response) => response.data)
        }
      }
      if (kind === "publication") {
        const pubs = await ProjectsService.getProjectPublications({
          owner_name: ownerName,
          project_name: projectName,
          ref,
        }).then((response) => response.data)
        const found = pubs.find((p) => p.path === path)
        if (found) return found
        return ProjectsService.getProjectContents({
          owner_name: ownerName,
          project_name: projectName,
          path,
          ref,
        }).then((response) => response.data)
      }
      if (kind === "notebook") {
        const nbs = await ProjectsService.getProjectNotebooks({
          owner_name: ownerName,
          project_name: projectName,
          ref,
        }).then((response) => response.data)
        const found = nbs.find((n) => n.path === path)
        if (found) return found
        return ProjectsService.getProjectContents({
          owner_name: ownerName,
          project_name: projectName,
          path,
          ref,
        }).then((response) => response.data)
      }
    },
    enabled,
    retry: false,
  })
}

/** Info panel for a figure, mirroring the publications page layout. */
function FigureInfo({
  figure,
  ownerName,
  projectName,
  gitRef,
  editOpen,
  onEditOpenChange,
}: {
  figure: Figure
  ownerName: string
  projectName: string
  gitRef?: string
  editOpen?: boolean
  onEditOpenChange?: (open: boolean) => void
}) {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  // Typed as plain string so the router's typed `to` prop accepts them.
  const filesTo: string = `/${ownerName}/${projectName}/files`
  const pipelineTo: string = `/${ownerName}/${projectName}/pipeline`
  const datasetsTo: string = `/${ownerName}/${projectName}/datasets`
  // What the figure was made from: its stage's concrete inputs in dvc.yaml,
  // matched against the project's declared datasets.
  const pipelineQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "pipeline", undefined],
    queryFn: () =>
      ProjectsService.getProjectPipeline({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: Boolean(figure.stage),
    retry: false,
  })
  const datasetsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "datasets"],
    queryFn: () =>
      ProjectsService.getProjectDatasets({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: Boolean(figure.stage),
    retry: false,
  })
  // The stage as declared in calkit.yaml: its inputs are the data the
  // author named, whereas dvc.yaml's deps also carry environment locks
  const stageQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "stage", figure.stage],
    queryFn: () =>
      ProjectsService.getProjectPipelineStage({
        owner_name: ownerName,
        project_name: projectName,
        stage_name: figure.stage!,
      }).then((response) => response.data),
    enabled: Boolean(figure.stage),
    retry: false,
  })
  // Where it came from when no stage makes it, e.g., an import or a person
  const provenanceQuery = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "provenance",
      figure.path,
      gitRef,
    ],
    queryFn: () =>
      ProjectsService.getProjectProvenance({
        owner_name: ownerName,
        project_name: projectName,
        path: figure.path,
        ref: gitRef,
      }).then((response) => response.data),
    enabled: !figure.stage,
    retry: false,
  })
  const origin = provenanceQuery.data?.origin
  const originUrl = provenanceQuery.data?.origin_url
  // A figure calkit.yaml doesn't declare can still have a stage that makes it
  const stage = figure.stage ?? provenanceQuery.data?.stage
  const stageKind = provenanceQuery.data?.stage_kind
  const exportedFrom =
    stageKind === "manual" || stageKind === "export"
      ? provenanceQuery.data?.source
      : null
  const dataLinks: InputLink[] = []
  if (figure.stage && pipelineQuery.data && datasetsQuery.data) {
    const deps = declaredInputs(
      stageQuery.data?.yaml,
      pipelineQuery.data.dvc_stages,
      pipelineQuery.data.calkit_yaml,
    )
    if (figure.dataset && !deps.includes(figure.dataset))
      deps.push(figure.dataset)
    const inputs = matchDepsToDatasets(deps, datasetsQuery.data)
    for (const { dataset } of inputs.declared) {
      dataLinks.push({
        key: dataset.path,
        to: datasetsTo,
        label: dataset.title || dataset.path,
        tooltipPath: dataset.title ? dataset.path : undefined,
        code: !dataset.title,
      })
    }
    for (const path of inputs.other) {
      dataLinks.push({
        key: path,
        to: filesTo,
        search: { path, ref: gitRef },
        label: path,
        code: true,
      })
    }
  }
  return (
    <Box bg={secBgColor} borderRadius="lg" p={3} mb={3} h="fit-content">
      <Heading size="sm" mb={2}>
        Info
      </Heading>
      {figure.title && (
        <Flex fontSize="sm" mb={1} wrap="wrap" align="baseline">
          <Text as="span" fontWeight="semibold" mr={1}>
            Title:
          </Text>
          <Box flex={1} minW={0} color="gray.500" sx={{ "& p": { my: 0 } }}>
            <Markdown inline>{figure.title}</Markdown>
          </Box>
        </Flex>
      )}
      {figure.description && (
        <Box fontSize="sm" mb={1}>
          <Text as="span" fontWeight="semibold">
            Description:
          </Text>{" "}
          <Box
            as="span"
            display="inline"
            color="gray.500"
            sx={{ "& p": { my: 0 } }}
          >
            <Markdown inline>{figure.description}</Markdown>
          </Box>
        </Box>
      )}
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Path:
        </Text>{" "}
        <Link
          as={RouterLink}
          to={filesTo}
          search={{ path: figure.path, ref: gitRef } as any}
        >
          {figure.path}
        </Link>
      </Text>
      <Text fontSize="sm" mb={1}>
        <Text as="span" fontWeight="semibold">
          Origin:
        </Text>{" "}
        {stage ? (
          <>
            Stage{" "}
            <Link
              as={RouterLink}
              to={pipelineTo}
              search={{ stage, ref: gitRef } as any}
            >
              <Code fontSize="xs" cursor="pointer">
                {stage}
              </Code>
            </Link>
            {exportedFrom ? (
              <>
                , exported {stageKind === "manual" ? "by hand " : ""}from{" "}
                <Link
                  as={RouterLink}
                  to={filesTo}
                  search={{ path: exportedFrom, ref: gitRef } as any}
                >
                  <Code fontSize="xs" cursor="pointer">
                    {exportedFrom}
                  </Code>
                </Link>
              </>
            ) : null}
          </>
        ) : provenanceQuery.isPending ? (
          <Spinner size="xs" />
        ) : origin && originUrl ? (
          <Link href={originUrl} isExternal>
            {origin}
          </Link>
        ) : origin ? (
          <Text as="span">{origin}</Text>
        ) : (
          <Text as="span" color="red.500">
            Not defined
          </Text>
        )}
      </Text>
      {!stage && provenanceQuery.isSuccess && !origin ? (
        <DefineFigureOrigin
          ownerName={ownerName}
          projectName={projectName}
          path={figure.path}
        />
      ) : null}
      <InputsRow label="Data" items={dataLinks} />
      {/* Back into the code that made it, when there is some: last, after
          the facts, and set off from them */}
      <FigureEditLauncher
        ownerName={ownerName}
        projectName={projectName}
        figure={figure}
        isOpen={editOpen}
        onOpenChange={onEditOpenChange}
      />
    </Box>
  )
}

type OriginMode = "script" | "notebook" | "imported" | "exported" | "created"

/** Define where a figure came from, when nothing does yet. */
function DefineFigureOrigin({
  ownerName,
  projectName,
  path,
}: {
  ownerName: string
  projectName: string
  path: string
}) {
  const { userHasWriteAccess } = useProject(ownerName, projectName)
  const [mode, setMode] = useState<OriginMode | null>(null)
  const queryClient = useQueryClient()
  if (!userHasWriteAccess) return null
  const modes: [OriginMode, string][] = [
    ["script", "Script"],
    ["notebook", "Notebook"],
    ["imported", "Imported"],
  ]
  // Something exported, e.g., a PNG, comes from a file a person made
  if (!canBeCreatedByPerson(path)) modes.push(["exported", "Exported"])
  if (canBeCreatedByPerson(path)) modes.push(["created", "Created"])
  const onDone = () => {
    setMode(null)
    queryClient.invalidateQueries({
      queryKey: ["projects", ownerName, projectName],
    })
  }
  return (
    <Box mb={2}>
      <Flex gap={1} align="center" wrap="wrap">
        <Text fontSize="xs" color="gray.500" mr={1}>
          Define origin:
        </Text>
        {modes.map(([value, label]) => (
          <Button
            key={value}
            size="xs"
            variant={mode === value ? "primary" : "outline"}
            onClick={() => setMode(mode === value ? null : value)}
          >
            {label}
          </Button>
        ))}
      </Flex>
      {mode === "script" || mode === "notebook" ? (
        <StageFromScriptForm
          key={mode}
          ownerName={ownerName}
          projectName={projectName}
          shows={path}
          kind={mode}
          onDone={onDone}
        />
      ) : mode === "exported" ? (
        <ManualExportForm
          ownerName={ownerName}
          projectName={projectName}
          path={path}
          onDone={onDone}
        />
      ) : mode ? (
        <RecordOriginForm
          key={mode}
          ownerName={ownerName}
          projectName={projectName}
          path={path}
          how={mode}
          onDone={onDone}
        />
      ) : null}
    </Box>
  )
}

/**
 * Record that a file is exported by hand from one someone made, e.g., a
 * PNG from a Photoshop file, so the pipeline asks for a new export
 * whenever that file changes.
 */
function ManualExportForm({
  ownerName,
  projectName,
  path,
  onDone,
}: {
  ownerName: string
  projectName: string
  path: string
  onDone: () => void
}) {
  const showToast = useCustomToast()
  const [sourcePath, setSourcePath] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [app, setApp] = useState("")
  // Kept out of the paper's folder, which may sync to Overleaf
  const source = sourcePath || (file ? `figures/src/${file.name}` : "")
  // An app that exports it as the pipeline runs, as the hub decides
  const exporter = source.toLowerCase().endsWith(".svg")
    ? "Inkscape"
    : source.toLowerCase().endsWith(".xcf")
      ? "GIMP"
      : null
  const saveMutation = useMutation({
    mutationFn: async () => {
      const content = file
        ? await new Promise<string>((resolve, reject) => {
            const reader = new FileReader()
            reader.onload = () =>
              resolve(String(reader.result).replace(/^data:[^,]*,/, ""))
            reader.onerror = () => reject(reader.error)
            reader.readAsDataURL(file)
          })
        : null
      return ProjectsService.postProjectStageExport({
        owner_name: ownerName,
        project_name: projectName,
        stageExportPost: {
          path,
          source_path: source,
          content,
          app: app.trim() || null,
        },
      }).then((response) => response.data)
    },
    onSuccess: (data) => {
      showToast("Origin defined", data.message, "success")
      onDone()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  return (
    <Box mt={2} fontSize="sm">
      <Text mb={1}>
        The file <Code fontSize="xs">{path}</Code> is exported from
      </Text>
      <Flex gap={2} align="center" wrap="wrap" mb={2}>
        <PathPicker
          ownerName={ownerName}
          projectName={projectName}
          value={sourcePath}
          onChange={setSourcePath}
        />
        <Input
          type="file"
          size="sm"
          p={1}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </Flex>
      <Input
        size="sm"
        mb={2}
        placeholder="App it's exported with, e.g., Photoshop (optional)"
        value={app}
        onChange={(e) => setApp(e.target.value)}
      />
      {exporter ? (
        <Text fontSize="xs" color="gray.500" mb={2}>
          {exporter} exports it whenever the pipeline runs.
        </Text>
      ) : null}
      {source && !canBeCreatedByPerson(source) ? (
        <Text fontSize="xs" color="red.500" mb={2}>
          {source} is exported from something itself; choose the file it's made
          from.
        </Text>
      ) : null}
      <Button
        size="xs"
        variant="primary"
        isDisabled={!source || !canBeCreatedByPerson(source)}
        isLoading={saveMutation.isPending}
        onClick={() => saveMutation.mutate()}
      >
        Add the export step
      </Button>
    </Box>
  )
}

/** Make the stage that produces a file from the script that writes it. */
function StageFromScriptForm({
  ownerName,
  projectName,
  shows,
  kind,
  onDone,
}: {
  ownerName: string
  projectName: string
  shows: string
  kind: "script" | "notebook"
  onDone: () => void
}) {
  const showToast = useCustomToast()
  const [scriptPath, setScriptPath] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [detected, setDetected] = useState<StageFromScript | null>(null)
  const [produces, setProduces] = useState<string | undefined>()
  const exts =
    kind === "notebook" ? [".ipynb"] : [".py", ".r", ".jl", ".m", ".sh"]
  const post = async (save: boolean) => {
    const content = file
      ? await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () =>
            resolve(String(reader.result).replace(/^data:[^,]*,/, ""))
          reader.onerror = () => reject(reader.error)
          reader.readAsDataURL(file)
        })
      : null
    return ProjectsService.postProjectStageFromScript({
      owner_name: ownerName,
      project_name: projectName,
      stageFromScriptPost: {
        // An upload goes where it's named, or with others of its kind
        script_path: scriptPath || (file ? `${kind}s/${file.name}` : ""),
        content,
        shows,
        produces: save ? produces : null,
        save,
      },
    }).then((response) => response.data)
  }
  const readMutation = useMutation({
    mutationFn: () => post(false),
    onSuccess: (data) => {
      setDetected(data)
      setProduces(data.produces ?? data.outputs?.[0])
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const saveMutation = useMutation({
    mutationFn: () => post(true),
    onSuccess: (data) => {
      showToast(
        "Origin defined",
        `Added stage ${data.stage_name}. It hasn't run yet; run it with calkit run --save.`,
        "success",
      )
      onDone()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  return (
    <Box mt={2} fontSize="sm">
      <Text mb={1}>
        The {kind} that makes <Code fontSize="xs">{shows}</Code>
      </Text>
      <Flex gap={2} align="center" wrap="wrap" mb={2}>
        <PathPicker
          ownerName={ownerName}
          projectName={projectName}
          value={scriptPath}
          onChange={(value) => {
            setScriptPath(value)
            setDetected(null)
          }}
        />
        <Input
          type="file"
          size="sm"
          p={1}
          accept={exts.join(",")}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null)
            setDetected(null)
          }}
        />
      </Flex>
      <Button
        size="xs"
        isDisabled={!scriptPath && !file}
        isLoading={readMutation.isPending}
        onClick={() => readMutation.mutate()}
      >
        Read the {kind}
      </Button>
      {detected ? (
        <Box mt={2}>
          <Text>
            Stage <Code fontSize="xs">{detected.stage_name}</Code> runs in{" "}
            {detected.environment}
            {detected.environment_is_new ? " (a new environment)" : ""}
          </Text>
          {detected.inputs?.length ? (
            <Text color="gray.500">Reads {detected.inputs.join(", ")}</Text>
          ) : null}
          {detected.missing_inputs?.length ? (
            <Text color="orange.400">
              Not in the project yet: {detected.missing_inputs.join(", ")}
            </Text>
          ) : null}
          {detected.outputs?.length ? (
            <RadioGroup value={produces} onChange={setProduces} mt={1}>
              <Text color="gray.500">
                Which output is <Code fontSize="xs">{shows}</Code>?
              </Text>
              <Stack spacing={0}>
                {detected.outputs.map((output) => (
                  <Radio key={output} value={output} size="sm">
                    <Code fontSize="xs">{output}</Code>
                  </Radio>
                ))}
              </Stack>
            </RadioGroup>
          ) : (
            <Text color="gray.500">
              Calkit didn't find anything the {kind} writes.
            </Text>
          )}
          <Button
            size="xs"
            variant="primary"
            mt={2}
            isDisabled={!produces}
            isLoading={saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            Add to the pipeline
          </Button>
        </Box>
      ) : null}
    </Box>
  )
}

interface RecordOriginValues extends AttestationForm, ImportedFromForm {}

/** Record that a file was imported, or made by the signed-in user. */
function RecordOriginForm({
  ownerName,
  projectName,
  path,
  how,
  onDone,
}: {
  ownerName: string
  projectName: string
  path: string
  how: "imported" | "created"
  onDone: () => void
}) {
  const showToast = useCustomToast()
  const { user } = useAuth()
  const [source, setSource] = useState<ImportSource>("url")
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RecordOriginValues>({
    mode: "onBlur",
    defaultValues: { created_with_ai: "", ...IMPORTED_FROM_DEFAULTS },
  })
  const mutation = useMutation({
    mutationFn: (data: RecordOriginValues) =>
      ProjectsService.postProjectMisc({
        owner_name: ownerName,
        project_name: projectName,
        miscArtifactPost: {
          path,
          message: `Record where ${path} came from`,
          ...(how === "created"
            ? { created_by: [creatorFromUser(user, data.created_with_ai)] }
            : { imported_from: buildImportedFrom(source, data) }),
        },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Origin defined", `${path} is now accounted for.`, "success")
      onDone()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  return (
    <Box
      as="form"
      autoComplete="off"
      mt={2}
      onSubmit={handleSubmit((data) => mutation.mutateAsync(data))}
    >
      {how === "created" ? (
        <AttestationFields
          register={register}
          user={user}
          subject="This figure"
          mt={0}
        />
      ) : (
        <>
          <RadioGroup
            value={source}
            onChange={(value) => setSource(value as ImportSource)}
            mb={2}
          >
            <Stack direction="row" spacing={3}>
              <Radio value="url" size="sm">
                Website
              </Radio>
              <Radio value="doi" size="sm">
                DOI
              </Radio>
              <Radio value="git_repo" size="sm">
                Git repo
              </Radio>
            </Stack>
          </RadioGroup>
          <ImportedFromFields
            source={source}
            register={register}
            errors={errors}
          />
        </>
      )}
      <Button
        size="xs"
        variant="primary"
        type="submit"
        mt={2}
        isLoading={isSubmitting || mutation.isPending}
      >
        Save
      </Button>
    </Box>
  )
}

function FigureComments({
  ownerName,
  projectName,
  path,
  gitRef,
  fetchEnabled = true,
}: {
  ownerName: string
  projectName: string
  path: string
  gitRef?: string | undefined
  /** False while the carousel is still settling; see `pathSettled`. */
  fetchEnabled?: boolean
}) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [showResolved, setShowResolved] = useState(false)
  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: [
        "projects",
        ownerName,
        projectName,
        "comments",
        "figure",
        path,
      ],
    })
    queryClient.invalidateQueries({
      queryKey: ["projects", ownerName, projectName, "figures"],
    })
  }
  const commentsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "comments", "figure", path],
    queryFn: () =>
      ProjectsService.getProjectComments({
        owner_name: ownerName,
        project_name: projectName,
        artifact_type: "figure",
        artifact_path: path,
      }).then((response) => response.data),
    enabled: fetchEnabled,
  })
  const postMutation = useMutation({
    mutationFn: (vars: { body: string; createIssue: boolean }) =>
      ProjectsService.postProjectComment({
        owner_name: ownerName,
        project_name: projectName,
        projectCommentPost: {
          artifact_path: path,
          artifact_type: "figure",
          comment: vars.body,
          create_github_issue: vars.createIssue,
          git_ref: gitRef ?? null,
        },
      }).then((response) => response.data),
    onSuccess: invalidate,
  })
  const replyMutation = useMutation({
    mutationFn: (vars: { commentId: string; body: string }) =>
      ProjectsService.postProjectCommentReply({
        owner_name: ownerName,
        project_name: projectName,
        comment_id: vars.commentId,
        commentReply: { body: vars.body },
      }).then((response) => response.data),
    onSuccess: invalidate,
  })
  const resolveMutation = useMutation({
    mutationFn: (vars: { commentId: string; resolved: boolean }) =>
      ProjectsService.patchProjectComment({
        owner_name: ownerName,
        project_name: projectName,
        comment_id: vars.commentId,
        projectCommentPatch: { resolved: vars.resolved },
      }).then((response) => response.data),
    onSuccess: invalidate,
  })
  const comments = commentsQuery.data ?? []
  return (
    <SharedCommentsPanel
      comments={comments.map(projectCommentToPanelComment)}
      isLoading={commentsQuery.isPending}
      canComment={!!user}
      canResolve={!!user}
      showResolved={showResolved}
      onShowResolvedChange={setShowResolved}
      showCreateIssueCheckbox
      onPostComment={(body, opts) =>
        postMutation.mutateAsync({ body, createIssue: opts.createIssue })
      }
      postingComment={postMutation.isPending}
      onPostReply={(parentId, body) =>
        replyMutation.mutateAsync({ commentId: parentId, body })
      }
      postingReplyForId={
        replyMutation.isPending
          ? replyMutation.variables?.commentId ?? null
          : null
      }
      onResolve={(id, resolved) =>
        resolveMutation.mutate({ commentId: id, resolved })
      }
      resolvingId={
        resolveMutation.isPending
          ? resolveMutation.variables?.commentId ?? null
          : null
      }
    />
  )
}

export function ArtifactCompareModal({
  isOpen,
  onClose,
  ownerName,
  projectName,
  path,
  kind,
  initialRef,
  initialRef2,
  initialArtifact,
  onRefsChange,
  onPrev,
  onNext,
  editOpen,
  onEditOpenChange,
  compareView,
  onCompareViewChange,
}: ArtifactCompareModalProps) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const hoverBg = useColorModeValue("gray.50", "gray.700")
  const selectedBg = useColorModeValue("blue.50", "blue.900")

  const [ref1, setRef1] = useState<string | undefined>(initialRef)
  const [ref2, setRef2] = useState<string | undefined>(initialRef2)
  const [branchesEnabled, setBranchesEnabled] = useState(false)

  useEffect(() => {
    setRef1(initialRef)
    setRef2(initialRef2)
  }, [initialRef, initialRef2])

  useEffect(() => {
    onRefsChange?.(ref1, ref2)
  }, [ref1, ref2])

  // Read the handlers through a ref so the listener is attached once. Keying
  // the effect on them instead re-registers whenever the parent hands over
  // new closures, which it does on every render while the carousel rolls onto
  // the next page -- and because effects run after paint, a key pressed in
  // that gap reaches the previous, now-stale handler and does nothing. That
  // is precisely when someone flipping quickly is pressing.
  const navHandlers = useRef({ onPrev, onNext })
  navHandlers.current = { onPrev, onNext }
  useEffect(() => {
    if (!isOpen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return
      // The comment box lives in this modal, so arrows have to stay with the
      // field being typed in rather than paging the carousel underneath it.
      const el = e.target as HTMLElement | null
      if (
        el?.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(el?.tagName ?? "") ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey
      ) {
        return
      }
      if (e.key === "ArrowLeft") navHandlers.current.onPrev?.()
      else navHandlers.current.onNext?.()
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [isOpen])

  // Comments and file history are the slow panels here, and arrowing through
  // the carousel changes `path` on every keypress. Hold their fetches until
  // the path stops moving, so a run of presses costs one request for the
  // figure you land on instead of one per figure you pass through. The keys
  // still use the live `path`, so anything already cached (a figure you've
  // been to before) renders immediately rather than waiting out the delay,
  // and no panel ever shows another figure's data.
  const [settledPath] = useDebounce(path, 300)
  const pathSettled = settledPath === path
  const artifactStorage = (initialArtifact as { storage?: string } | undefined)
    ?.storage as "git" | "dvc" | "dvc-zip" | undefined
  const historyQuery = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "file-history",
      path,
      artifactStorage,
    ],
    queryFn: async () =>
      (await ProjectsService.getProjectFileHistory({
        owner_name: ownerName,
        project_name: projectName,
        path,
        limit: 50,
        storage: artifactStorage ?? null,
      }).then((response) => response.data)) as unknown as CommitHistory[],
    enabled: isOpen && pathSettled,
    staleTime: 5 * 60 * 1000,
  })

  // For publication/notebook, fetching without a ref loads ALL items just to
  // find one--skip that when we already have initialArtifact. For "file" and
  // "figure" the fetch is a direct single-item call, so it's cheap.
  // When there is no initialArtifact (e.g. opened from the files page), also
  // enable the query without a ref so the current version is shown on open.
  // A figure the listing carried as a thumbnail has no full-size bytes and,
  // when it lives in Git rather than object storage, no URL either -- so
  // there is nothing to show at full size without asking for it. Treat that
  // the same as having been opened with no artifact at all.
  const initialIsDisplayable = Boolean(
    initialArtifact &&
      ((initialArtifact as { content?: string | null }).content ||
        (initialArtifact as { url?: string | null }).url),
  )
  const artifact1Enabled =
    kind === "file" || !initialIsDisplayable ? isOpen : isOpen && Boolean(ref1)
  const artifact1Query = useArtifactAtRef(
    ownerName,
    projectName,
    path,
    kind,
    ref1,
    artifact1Enabled,
  )
  const artifact2Query = useArtifactAtRef(
    ownerName,
    projectName,
    path,
    kind,
    ref2,
    isOpen && Boolean(ref2),
  )

  // For figure/publication/notebook: when no ref is selected, use the pre-loaded
  // artifact from the parent so we don't fetch all items. For file, artifact1Query
  // always runs so use its data directly. When there is no initialArtifact (e.g.
  // opened from the files page), fall through to artifact1Query so the current
  // version is displayed.
  const displayData1 =
    kind === "file" || ref1 || !initialIsDisplayable
      ? artifact1Query.data
      : initialArtifact
  const isPending1 =
    kind === "file" || ref1 || !initialIsDisplayable
      ? artifact1Query.isPending
      : false
  const missing1 =
    Boolean(kind === "file" || ref1 || !initialIsDisplayable) &&
    httpStatus(artifact1Query.error) === 404
  const missing2 = httpStatus(artifact2Query.error) === 404

  const isComparing = Boolean(ref2)
  // LaTeX diffs are kept with the publication at each version, so the two
  // being compared are where to look for one between them
  const pub1 = displayData1 as Publication | undefined
  const pub2 = artifact2Query.data as Publication | undefined
  const hasLatexDiffs =
    kind === "publication" &&
    isComparing &&
    Boolean(pub1?.latex_diffs?.length || pub2?.latex_diffs?.length)
  const refsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "refs"],
    queryFn: () =>
      ProjectsService.searchProjectRefs({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    // Also needed to resolve a diff's branch or tag to a commit
    enabled: isOpen && (branchesEnabled || hasLatexDiffs),
    staleTime: 5 * 60 * 1000,
  })
  const branches = (refsQuery.data ?? []).filter(
    (r: GitRef) => r.kind === "branch",
  )
  // Whether a ref as a diff declares it names the selected version, going
  // through commits since the two are rarely written the same way.
  // Relative refs like HEAD~1 can't be resolved here, and a branch resolves
  // to where it is now, not where it was when the diff was built.
  const refMatches = (spec: string, selected: string) => {
    if (spec === selected) return true
    const selectedHash =
      historyQuery.data?.find((c) => c.short_hash === selected)?.hash ??
      refsQuery.data?.find((r) => r.name === selected)?.hash
    if (!selectedHash) return false
    if (/^[0-9a-f]{4,40}$/i.test(spec))
      return selectedHash.startsWith(spec.toLowerCase())
    return refsQuery.data?.find((r) => r.name === spec)?.hash === selectedHash
  }
  // A diff kept at a version compares its from ref against that version
  // unless it names a to ref
  const findLatexDiff = (
    pub: Publication | undefined,
    fromRef: string,
    atRef: string,
  ) =>
    pub?.latex_diffs?.find(
      (d) =>
        (d.url || d.content) &&
        refMatches(d.from_ref, fromRef) &&
        (!d.to_ref || d.to_ref === "HEAD" || refMatches(d.to_ref, atRef)),
    )
  // Either order, since A can be the newer version
  const latexDiff =
    hasLatexDiffs && ref1 && ref2
      ? findLatexDiff(pub2, ref1, ref2) ?? findLatexDiff(pub1, ref2, ref1)
      : undefined
  const showLatexDiff = Boolean(latexDiff) && compareView !== "side-by-side"

  // Figure metadata (title/description/stage) for the info panel, sourced from
  // the figure at the displayed ref, falling back to the one we opened with.
  const figureInfo =
    kind === "figure"
      ? (displayData1 as Figure | undefined) ??
        (initialArtifact as Figure | undefined)
      : undefined

  const getShareUrl = () => {
    const url = new URL(window.location.href)
    if (ref1) url.searchParams.set("base_ref", ref1)
    else url.searchParams.delete("base_ref")
    if (ref2) url.searchParams.set("compare_ref", ref2)
    else url.searchParams.delete("compare_ref")
    return url.toString()
  }

  const copyShareUrl = () => {
    navigator.clipboard.writeText(getShareUrl())
  }

  const handleCommitClick = (commit: CommitHistory) => {
    // First click sets ref1, second click sets ref2, third resets
    if (!ref1 || ref1 === commit.short_hash) {
      setRef1(commit.short_hash)
      setRef2(undefined)
    } else if (!ref2) {
      setRef2(commit.short_hash)
    } else {
      setRef1(commit.short_hash)
      setRef2(undefined)
    }
  }

  const clearComparison = () => {
    setRef1(undefined)
    setRef2(undefined)
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="6xl"
      scrollBehavior="inside"
      isCentered
      motionPreset="none"
    >
      <ModalOverlay />
      <ModalContent maxW="95vw" maxH="95vh">
        <ModalHeader pr={12}>
          <Flex align="center" gap={2}>
            <Text noOfLines={1} flex={1}>
              {path}
            </Text>
            {isComparing && (
              <Tooltip label="Copy shareable link">
                <IconButton
                  aria-label="Copy share link"
                  icon={<FaLink />}
                  size="sm"
                  variant="ghost"
                  onClick={copyShareUrl}
                />
              </Tooltip>
            )}
          </Flex>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={4}>
          <Flex gap={4} height="80vh">
            {/* Version history sidebar */}
            <Box
              w="200px"
              flexShrink={0}
              borderRightWidth={1}
              borderColor={borderColor}
              pr={3}
              overflowY="auto"
            >
              {(ref1 || ref2) && (
                <Button
                  size="xs"
                  variant="ghost"
                  mb={2}
                  onClick={clearComparison}
                >
                  Clear selection
                </Button>
              )}
              {ref1 && !ref2 && (
                <Text fontSize="xs" color="gray.500" mb={2}>
                  Click another version to compare
                </Text>
              )}
              <Tabs
                size="sm"
                variant="enclosed"
                onChange={(i) => {
                  if (i === 1) setBranchesEnabled(true)
                }}
              >
                <TabList>
                  <Tab fontSize="xs">Commits</Tab>
                  <Tab fontSize="xs">Branches</Tab>
                </TabList>
                <TabPanels>
                  <TabPanel px={0} pb={0}>
                    {historyQuery.isPending ? (
                      <Flex justify="center" py={2}>
                        <Spinner size="sm" color="ui.main" />
                      </Flex>
                    ) : (historyQuery.data?.length ?? 0) === 0 ? (
                      <Text fontSize="xs" color="gray.500">
                        No version history found.
                      </Text>
                    ) : (
                      <VStack align="stretch" spacing={1}>
                        {historyQuery.data?.map((commit) => {
                          const isRef1 = commit.short_hash === ref1
                          const isRef2 = commit.short_hash === ref2
                          return (
                            <Box
                              key={commit.hash}
                              p={2}
                              borderRadius="md"
                              cursor="pointer"
                              bg={isRef1 || isRef2 ? selectedBg : undefined}
                              _hover={{
                                bg: isRef1 || isRef2 ? selectedBg : hoverBg,
                              }}
                              onClick={() => handleCommitClick(commit)}
                              borderWidth={isRef1 || isRef2 ? 1 : 0}
                              borderColor="blue.300"
                            >
                              <Flex align="center" gap={1} mb={0.5}>
                                <Code fontSize="xs">{commit.short_hash}</Code>
                                {isRef1 && (
                                  <Badge colorScheme="blue" fontSize="xs">
                                    A
                                  </Badge>
                                )}
                                {isRef2 && (
                                  <Badge colorScheme="purple" fontSize="xs">
                                    B
                                  </Badge>
                                )}
                              </Flex>
                              <Text fontSize="xs" noOfLines={1}>
                                {commit.summary}
                              </Text>
                              <Text fontSize="xs" color="gray.500">
                                {new Date(
                                  commit.timestamp,
                                ).toLocaleDateString()}
                              </Text>
                            </Box>
                          )
                        })}
                      </VStack>
                    )}
                  </TabPanel>
                  <TabPanel px={0} pb={0}>
                    {refsQuery.isPending ? (
                      <Flex justify="center" py={2}>
                        <Spinner size="sm" color="ui.main" />
                      </Flex>
                    ) : branches.length === 0 ? (
                      <Text fontSize="xs" color="gray.500">
                        No branches found.
                      </Text>
                    ) : (
                      <VStack align="stretch" spacing={1}>
                        {branches.map((branch: GitRef) => {
                          const isRef1 = branch.name === ref1
                          const isRef2 = branch.name === ref2
                          return (
                            <Box
                              key={branch.name}
                              p={2}
                              borderRadius="md"
                              cursor="pointer"
                              bg={isRef1 || isRef2 ? selectedBg : undefined}
                              _hover={{
                                bg: isRef1 || isRef2 ? selectedBg : hoverBg,
                              }}
                              onClick={() => {
                                if (!ref1 || ref1 === branch.name) {
                                  setRef1(branch.name)
                                  setRef2(undefined)
                                } else if (!ref2) {
                                  setRef2(branch.name)
                                } else {
                                  setRef1(branch.name)
                                  setRef2(undefined)
                                }
                              }}
                              borderWidth={isRef1 || isRef2 ? 1 : 0}
                              borderColor="blue.300"
                            >
                              <Flex align="center" gap={1}>
                                <Icon
                                  as={FaCodeBranch}
                                  fontSize="xs"
                                  color="gray.400"
                                  flexShrink={0}
                                />
                                <Text fontSize="xs" noOfLines={1} flex={1}>
                                  {branch.name}
                                </Text>
                                {isRef1 && (
                                  <Badge colorScheme="blue" fontSize="xs">
                                    A
                                  </Badge>
                                )}
                                {isRef2 && (
                                  <Badge colorScheme="purple" fontSize="xs">
                                    B
                                  </Badge>
                                )}
                                {branch.is_default && (
                                  <Badge colorScheme="green" fontSize="xs">
                                    default
                                  </Badge>
                                )}
                              </Flex>
                            </Box>
                          )
                        })}
                      </VStack>
                    )}
                  </TabPanel>
                </TabPanels>
              </Tabs>
            </Box>

            {/* Artifact content area */}
            <Box
              flex={1}
              minW={0}
              minH={0}
              display="flex"
              flexDirection="column"
            >
              {isComparing && latexDiff && onCompareViewChange && (
                <ButtonGroup
                  size="xs"
                  isAttached
                  variant="outline"
                  mb={2}
                  flexShrink={0}
                >
                  <Button
                    onClick={() => onCompareViewChange("side-by-side")}
                    isActive={!showLatexDiff}
                  >
                    Side by side
                  </Button>
                  <Button
                    onClick={() => onCompareViewChange("latex-diff")}
                    isActive={showLatexDiff}
                  >
                    LaTeX diff
                  </Button>
                </ButtonGroup>
              )}
              {isComparing ? (
                <Box
                  flex={1}
                  minH={0}
                  overflow={kind === "figure" ? "hidden" : "auto"}
                >
                  {showLatexDiff && latexDiff ? (
                    <Box height="75vh" width="100%">
                      <PdfDocumentViewer
                        url={
                          latexDiff.content
                            ? `data:application/pdf;base64,${latexDiff.content}`
                            : String(latexDiff.url)
                        }
                        source="compare"
                      />
                    </Box>
                  ) : kind === "file" && displayData1 && artifact2Query.data ? (
                    (() => {
                      const decode = (
                        d: Figure | Publication | Notebook | ContentsItem,
                      ) => {
                        const item = d as ContentsItem
                        if (item.content) return atob(item.content)
                        return ""
                      }
                      return (
                        <ReactDiffViewer
                          oldValue={decode(displayData1!)}
                          newValue={decode(artifact2Query.data)}
                          leftTitle={
                            <Flex align="center" gap={1}>
                              <Badge colorScheme="blue">A</Badge>
                              <Code fontSize="xs">{ref1}</Code>
                            </Flex>
                          }
                          rightTitle={
                            <Flex align="center" gap={1}>
                              <Badge colorScheme="purple">B</Badge>
                              <Code fontSize="xs">{ref2}</Code>
                            </Flex>
                          }
                          compareMethod={DiffMethod.WORDS}
                          useDarkTheme
                          styles={{
                            variables: {
                              dark: { gutterBackground: "#1a202c" },
                            },
                          }}
                        />
                      )
                    })()
                  ) : (
                    <Flex gap={4} align="flex-start" height="100%">
                      <Box flex={1} minH={0}>
                        <Flex align="center" gap={2} mb={2}>
                          <Badge colorScheme="blue">A</Badge>
                          <Code fontSize="sm">{ref1}</Code>
                        </Flex>
                        {isPending1 ? (
                          <Spinner color="ui.main" />
                        ) : (
                          <ArtifactContent
                            kind={kind}
                            path={path}
                            data={displayData1}
                            missing={missing1}
                            atRef={ref1}
                          />
                        )}
                      </Box>
                      <Divider orientation="vertical" />
                      <Box flex={1} minH={0}>
                        <Flex align="center" gap={2} mb={2}>
                          <Badge colorScheme="purple">B</Badge>
                          <Code fontSize="sm">{ref2}</Code>
                        </Flex>
                        {artifact2Query.isPending ? (
                          <Spinner color="ui.main" />
                        ) : (
                          <ArtifactContent
                            kind={kind}
                            path={path}
                            data={artifact2Query.data}
                            missing={missing2}
                            atRef={ref2}
                          />
                        )}
                      </Box>
                    </Flex>
                  )}
                </Box>
              ) : (
                <>
                  {ref1 && (
                    <Flex align="center" gap={2} mb={2} flexShrink={0}>
                      <Badge colorScheme="blue">A</Badge>
                      <Code fontSize="sm">{ref1}</Code>
                      <Text fontSize="xs" color="gray.500">
                        (click another version on the left to compare)
                      </Text>
                    </Flex>
                  )}
                  <Flex flex={1} minH={0} align="stretch" gap={1}>
                    {/* Left arrow */}
                    <Flex
                      w="28px"
                      flexShrink={0}
                      align="center"
                      justify="center"
                      ml={-2}
                    >
                      {onPrev && (
                        <IconButton
                          aria-label="Previous"
                          icon={<FaChevronLeft />}
                          size="sm"
                          variant="ghost"
                          onClick={onPrev}
                        />
                      )}
                    </Flex>
                    {/* Content */}
                    <Box
                      flex={1}
                      minH={0}
                      overflow={kind === "figure" ? "hidden" : "auto"}
                    >
                      {isPending1 ? (
                        <Flex justify="center" align="center" height="200px">
                          <Spinner color="ui.main" />
                        </Flex>
                      ) : (
                        <ArtifactContent
                          kind={kind}
                          path={path}
                          data={displayData1}
                          missing={missing1}
                          atRef={ref1}
                        />
                      )}
                    </Box>
                    {/* Right arrow */}
                    <Flex
                      w="28px"
                      flexShrink={0}
                      align="center"
                      justify="center"
                      mr={-2}
                    >
                      {onNext && (
                        <IconButton
                          aria-label="Next"
                          icon={<FaChevronRight />}
                          size="sm"
                          variant="ghost"
                          onClick={onNext}
                        />
                      )}
                    </Flex>
                  </Flex>
                </>
              )}
            </Box>

            {/* Figure comments panel */}
            {kind === "figure" && (
              <Box
                w="300px"
                flexShrink={0}
                borderLeftWidth={1}
                borderColor={borderColor}
                pl={3}
                overflowY="auto"
              >
                {figureInfo && (
                  <FigureInfo
                    figure={figureInfo}
                    ownerName={ownerName}
                    projectName={projectName}
                    gitRef={ref1}
                    editOpen={editOpen}
                    onEditOpenChange={onEditOpenChange}
                  />
                )}
                <FigureComments
                  ownerName={ownerName}
                  projectName={projectName}
                  path={path}
                  gitRef={ref1}
                  fetchEnabled={pathSettled}
                />
              </Box>
            )}
          </Flex>
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}
