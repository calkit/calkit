import { Box, Button, useDisclosure } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { load as yamlLoad } from "js-yaml"
import mixpanel from "mixpanel-browser"

import { type Figure, ProjectsService } from "../../client"
import useProject from "../../hooks/useProject"
import { declaredInputs } from "../../lib/provenance"
import NotebookRunLauncher from "../Notebooks/NotebookRunLauncher"
import TipBubble from "../Onboarding/TipBubble"
import FigureStudio, { type StudioEdit } from "./FigureStudio"

interface StageInfo {
  kind?: string
  script_path?: string
  notebook_path?: string
  environment?: string | null
  inputs?: (string | { from_stage_outputs?: string; path?: string })[]
}

/**
 * A way back into the code that made a figure, from the figure itself.
 *
 * A script stage opens in the figure editor with its script and data, and
 * saving there updates the stage. A notebook stage opens in the notebook
 * runner, on the same in-browser Python, with the stage's inputs in place.
 */
const FigureEditLauncher = ({
  ownerName,
  projectName,
  figure,
  isOpen,
  onOpenChange,
}: {
  ownerName: string
  projectName: string
  figure: Figure
  /** Controlled open state, for a page that keeps it in the URL. */
  isOpen?: boolean
  onOpenChange?: (open: boolean) => void
}) => {
  const { userHasWriteAccess } = useProject(ownerName, projectName)
  const local = useDisclosure()
  const studio = {
    isOpen: isOpen ?? local.isOpen,
    onOpen: () => (onOpenChange ? onOpenChange(true) : local.onOpen()),
    onClose: () => (onOpenChange ? onOpenChange(false) : local.onClose()),
  }
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
  // The stage's concrete inputs, from dvc.yaml, since calkit.yaml may name
  // them indirectly as another stage's outputs.
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
  if (!figure.stage) return null
  // The slot is held from the start so the panel doesn't jump when the
  // stage arrives; the studio reads the script's own read_csv calls, so it
  // doesn't need the pipeline to have loaded before it opens.
  if (!stageQuery.data) {
    if (stageQuery.isError || !userHasWriteAccess) return null
    return (
      <Box mt={3} pt={3} borderTopWidth={1}>
        <Button size="sm" width="100%" isLoading loadingText="Edit" />
      </Box>
    )
  }
  let stage: StageInfo = {}
  try {
    stage = (yamlLoad(stageQuery.data.yaml) as StageInfo) ?? {}
  } catch {
    return null
  }
  // What the script reads, of any kind (a CSV, an HDF5 file, another
  // stage's output folder): the stage's inputs as declared in calkit.yaml,
  // with `from_stage_outputs` resolved through the other stage's declared
  // outputs and any iteration expanded.
  const inputs = declaredInputs(
    stageQuery.data.yaml,
    pipelineQuery.data?.dvc_stages as Record<string, unknown> | undefined,
    pipelineQuery.data?.calkit_yaml,
  )
  if (stage.kind === "python-script" && stage.script_path) {
    if (!userHasWriteAccess) return null
    const edit: StudioEdit = {
      stage: figure.stage,
      scriptPath: stage.script_path,
      figurePath: figure.path,
      datasetPaths: inputs,
      environment: stage.environment ?? null,
      title: figure.title,
      description: figure.description,
    }
    return (
      <Box mt={3} pt={3} borderTopWidth={1}>
        <TipBubble tip="edit-figure" where="page" display="block">
          <Button
            size="sm"
            variant="primary"
            width="100%"
            onClick={() => {
              mixpanel.track("Opened figure studio", {
                source: "figure-detail",
                editing: true,
              })
              studio.onOpen()
            }}
          >
            Edit figure
          </Button>
        </TipBubble>
        {studio.isOpen ? (
          <FigureStudio
            isOpen={studio.isOpen}
            onClose={studio.onClose}
            ownerName={ownerName}
            projectName={projectName}
            edit={edit}
          />
        ) : null}
      </Box>
    )
  }
  if (stage.kind === "jupyter-notebook" && stage.notebook_path) {
    if (!userHasWriteAccess) return null
    return (
      <NotebookRunLauncher
        ownerName={ownerName}
        projectName={projectName}
        path={stage.notebook_path}
        stage={figure.stage}
        source="figure-detail"
      />
    )
  }
  return null
}

export default FigureEditLauncher
