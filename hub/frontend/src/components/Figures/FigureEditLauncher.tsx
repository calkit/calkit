import { Box, Button, useDisclosure } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { load as yamlLoad } from "js-yaml"
import mixpanel from "mixpanel-browser"

import { type Figure, ProjectsService } from "../../client"
import useProject from "../../hooks/useProject"
import NotebookRunLauncher from "../Notebooks/NotebookRunLauncher"
import FigureStudio, { type StudioEdit } from "./FigureStudio"

interface StageInfo {
  kind?: string
  script_path?: string
  notebook_path?: string
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
}: {
  ownerName: string
  projectName: string
  figure: Figure
}) => {
  const { userHasWriteAccess } = useProject(ownerName, projectName)
  const studio = useDisclosure()
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
  const dvcStage = pipelineQuery.data?.dvc_stages?.[figure.stage] as
    | { deps?: string[] | null }
    | undefined
  // Inputs from both places they can be declared: concrete deps in
  // dvc.yaml, and plain paths in the stage's own inputs list.
  const declared = (stage.inputs ?? []).flatMap((i) =>
    typeof i === "string" ? [i] : i.path ? [i.path] : [],
  )
  const csvDeps = [...new Set([...(dvcStage?.deps ?? []), ...declared])].filter(
    (d) => d.toLowerCase().endsWith(".csv"),
  )
  if (stage.kind === "python-script" && stage.script_path) {
    if (!userHasWriteAccess) return null
    const edit: StudioEdit = {
      stage: figure.stage,
      scriptPath: stage.script_path,
      figurePath: figure.path,
      datasetPaths: csvDeps,
      title: figure.title,
      description: figure.description,
    }
    return (
      <Box mt={3} pt={3} borderTopWidth={1}>
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
