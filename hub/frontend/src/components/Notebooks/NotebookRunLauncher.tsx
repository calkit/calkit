import { Box, Button, Text, useDisclosure } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import mixpanel from "mixpanel-browser"

import { ProjectsService } from "../../client"
import { getStageDeps } from "../../lib/provenance"
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
}: {
  ownerName: string
  projectName: string
  path: string
  stage?: string | null
  /** Where the button lives, for telemetry. */
  source: string
}) => {
  const runner = useDisclosure()
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
  if (!path.toLowerCase().endsWith(".ipynb")) return null
  const dvcStage = stage ? pipelineQuery.data?.dvc_stages?.[stage] : undefined
  const inputs = getStageDeps(dvcStage as any).filter((d) => d !== path)
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
