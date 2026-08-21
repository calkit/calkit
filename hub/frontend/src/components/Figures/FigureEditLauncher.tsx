import { ExternalLinkIcon } from "@chakra-ui/icons"
import { Box, Button, Text, useDisclosure } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { load as yamlLoad } from "js-yaml"
import mixpanel from "mixpanel-browser"

import { type Figure, ProjectsService } from "../../client"
import useProject from "../../hooks/useProject"
import Tooltip from "../Common/Tooltip"
import FigureStudio, { type StudioEdit } from "./FigureStudio"

/** The JupyterLite site notebooks open in; `fromURL` loads one by URL. */
const JUPYTERLITE_URL = "https://jupyterlite.github.io/demo/lab/index.html"

interface StageInfo {
  kind?: string
  script_path?: string
  notebook_path?: string
  inputs?: (string | { from_stage_outputs?: string; path?: string })[]
}

/**
 * A way back into the code that made a figure, from the figure itself.
 *
 * A script stage opens in the figure studio with its script and data, and
 * saving there updates the stage. A notebook stage can't run in the studio,
 * so it opens in JupyterLite instead, which is a best-effort stand-in: the
 * notebook loads from the public repo, but its data files and the exact
 * environment don't come with it.
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
  const { projectRequest, userHasWriteAccess } = useProject(
    ownerName,
    projectName,
  )
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
  if (!figure.stage || !stageQuery.data) return null
  let stage: StageInfo = {}
  try {
    stage = (yamlLoad(stageQuery.data.yaml) as StageInfo) ?? {}
  } catch {
    return null
  }
  const dvcStage = pipelineQuery.data?.dvc_stages?.[figure.stage] as
    | { deps?: string[] | null }
    | undefined
  const csvDeps = (dvcStage?.deps ?? []).filter((d) =>
    d.toLowerCase().endsWith(".csv"),
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
          Edit in figure studio
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
    const repoUrl = projectRequest.data?.git_repo_url ?? ""
    const isPublic = Boolean(projectRequest.data?.is_public)
    const match = repoUrl.match(/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?$/)
    const rawUrl = match
      ? `https://raw.githubusercontent.com/${match[1]}/${match[2]}/HEAD/${stage.notebook_path}`
      : null
    const liteUrl = rawUrl
      ? `${JUPYTERLITE_URL}?fromURL=${encodeURIComponent(rawUrl)}`
      : null
    const disabledReason = !liteUrl
      ? "The repo isn't on GitHub"
      : !isPublic
        ? "JupyterLite can only fetch notebooks from a public repo"
        : null
    return (
      <Box mt={3} pt={3} borderTopWidth={1}>
        <Tooltip label={disabledReason ?? ""} isDisabled={!disabledReason}>
          <Button
            size="sm"
            width="100%"
            as={disabledReason ? undefined : "a"}
            href={disabledReason ? undefined : liteUrl ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
            isDisabled={Boolean(disabledReason)}
            rightIcon={<ExternalLinkIcon />}
            onClick={() =>
              mixpanel.track("Opened notebook in JupyterLite", {
                source: "figure-detail",
              })
            }
          >
            Open notebook in JupyterLite
          </Button>
        </Tooltip>
        <Text fontSize="xs" color="ui.dim" mt={1}>
          Experimental: the notebook loads, its data files don't.
        </Text>
      </Box>
    )
  }
  return null
}

export default FigureEditLauncher
