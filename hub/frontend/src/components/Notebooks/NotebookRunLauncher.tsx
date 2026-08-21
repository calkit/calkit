import { Box, Button, Text, useDisclosure } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import mixpanel from "mixpanel-browser"

import { ProjectsService } from "../../client"
import { declaredInputs, getStageDeps } from "../../lib/provenance"
import NotebookRunner from "./NotebookRunner"

/**
 * The "Run notebook" button, wherever a Jupyter notebook is shown.
 *
 * The stage's inputs come from the compiled pipeline so the runner can put
 * the files the notebook reads into place. A marimo notebook (a .py) is a
 * different runtime and isn't offered here yet.
 */
const NotebookRunLauncher = ({
  ownerName,
  projectName,
  path,
  stage,
  source,
  isOpen,
  onOpenChange,
}: {
  ownerName: string
  projectName: string
  path: string
  stage?: string | null
  /** Where the button lives, for telemetry. */
  source: string
  /** Controlled open state, when the page keeps it in the URL. */
  isOpen?: boolean
  onOpenChange?: (open: boolean) => void
}) => {
  const local = useDisclosure()
  const runner =
    isOpen !== undefined && onOpenChange
      ? {
          isOpen,
          onOpen: () => onOpenChange(true),
          onClose: () => onOpenChange(false),
        }
      : local
  const pipelineQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "pipeline", undefined],
    queryFn: () =>
      ProjectsService.getProjectPipeline({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: Boolean(stage),
    retry: false,
  })
  // The inputs the author declared in calkit.yaml, with other stages'
  // outputs expanded; dvc.yaml's deps also list what the CLI generates on
  // the fly (the cleaned notebook, environment locks), which isn't in the
  // repo to fetch.
  const stageQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "stage", stage],
    queryFn: () =>
      ProjectsService.getProjectPipelineStage({
        owner_name: ownerName,
        project_name: projectName,
        stage_name: stage!,
      }).then((response) => response.data),
    enabled: Boolean(stage),
    retry: false,
  })
  if (!path.toLowerCase().endsWith(".ipynb")) return null
  const dvcStages = pipelineQuery.data?.dvc_stages ?? {}
  const declared = declaredInputs(stageQuery.data?.yaml, dvcStages)
  const inputs = (
    declared.length
      ? declared
      : getStageDeps((stage ? dvcStages[stage] : undefined) as any).filter(
          (d) => !d.startsWith(".calkit/"),
        )
  ).filter((d) => d !== path)
  return (
    <Box mt={3} pt={3} borderTopWidth={1}>
      <Button
        size="sm"
        variant="primary"
        width="100%"
        onClick={() => {
          mixpanel.track("Opened notebook runner", { source })
          runner.onOpen()
        }}
      >
        Run notebook
      </Button>
      <Text fontSize="xs" color="ui.dim" mt={1}>
        Runs in your browser on a Python mirrored from the project's
        environment.
      </Text>
      {runner.isOpen ? (
        <NotebookRunner
          isOpen={runner.isOpen}
          onClose={runner.onClose}
          ownerName={ownerName}
          projectName={projectName}
          path={path}
          stage={stage}
          inputs={inputs}
        />
      ) : null}
    </Box>
  )
}

export default NotebookRunLauncher
