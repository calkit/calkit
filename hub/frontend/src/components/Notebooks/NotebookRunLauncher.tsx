import { Box, Button, Text, useDisclosure } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import mixpanel from "mixpanel-browser"

import { ProjectsService } from "../../client"
import { load as yamlLoad } from "js-yaml"

import { browserRunnable } from "../../lib/notebook"
import FeatureVoteButton from "../Common/FeatureVoteButton"
import { declaredInputs } from "../../lib/provenance"
import NotebookRunner from "./NotebookRunner"

/**
 * The "Run notebook" button, wherever a Jupyter notebook is shown.
 *
 * The stage's inputs come from calkit.yaml so the runner can put the
 * files the notebook reads into place. A marimo notebook (a .py) is a
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
  // The stage's environment decides whether the browser can run this at
  // all: the kernel here is Python, so a Julia or R notebook isn't offered
  const environmentsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "environments"],
    queryFn: () =>
      ProjectsService.getProjectEnvironments({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: Boolean(stage),
  })
  if (!path.toLowerCase().endsWith(".ipynb")) return null
  let envName: string | undefined
  try {
    envName = (yamlLoad(stageQuery.data?.yaml ?? "") as any)?.environment
  } catch {
    envName = undefined
  }
  const envKind = environmentsQuery.data?.find((e) => e.name === envName)?.kind
  const runnable = browserRunnable(stageQuery.data?.yaml, envKind)
  if (!runnable.ok) {
    return (
      <Box mt={3} pt={3} borderTopWidth={1}>
        <Text fontSize="xs" color="ui.dim" mb={2}>
          {runnable.reason} Running it from here on your own machine is
          something we're weighing.
        </Text>
        <FeatureVoteButton
          feature="local-workspace-compute"
          size="xs"
          showCount={false}
        />
      </Box>
    )
  }
  const dvcStages = pipelineQuery.data?.dvc_stages ?? {}
  const calkitYaml = pipelineQuery.data?.calkit_yaml
  // calkit.yaml is the source of what the notebook reads; the compiled
  // pipeline only helps resolve a stage calkit.yaml doesn't describe.
  const inputs = declaredInputs(
    stageQuery.data?.yaml,
    dvcStages,
    calkitYaml,
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
