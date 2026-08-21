import { ExternalLinkIcon } from "@chakra-ui/icons"
import { Button, Flex, HStack, Link, useDisclosure } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"

import { ProjectsService } from "../../client"
import useOnboardingFlags from "../../hooks/useOnboarding"
import { useProjectQuestions } from "../../hooks/useProject"
import { DISMISSED, buildProjectSteps } from "../../lib/onboarding"
import NewDataset from "../Datasets/NewDataset"
import FigureStudio from "../Figures/FigureStudio"
import ImportOverleaf from "../Publications/ImportOverleaf"
import NewPublication from "../Publications/NewPublication"
import CreateQuestion from "../Projects/CreateQuestion"
import ChecklistCard from "./ChecklistCard"
import CommandBlock from "./CommandBlock"

const VSCODE_EXT_URL =
  "https://marketplace.visualstudio.com/items?itemName=Calkit.calkit-vscode"
const CHROME_EXT_URL =
  "https://chromewebstore.google.com/detail/idhdomgapfolnpffanajdckdaojencal"
const JUPYTER_DOCS_URL = "https://docs.calkit.org/jupyterlab/"
const PIPELINE_DOCS_URL = "https://docs.calkit.org/pipeline/"

interface ProjectChecklistProps {
  accountName: string
  projectName: string
  projectId: string
}

/**
 * "What's left to do here", on the project home page.
 *
 * Shown only to people who can act on it. Every item is checked against the
 * project itself, so a project that was set up entirely from the CLI opens
 * with the list already done.
 */
const ProjectChecklist = ({
  accountName,
  projectName,
  projectId,
}: ProjectChecklistProps) => {
  const { projectFlags, setFlag } = useOnboardingFlags(projectId)
  const { questionsRequest } = useProjectQuestions(accountName, projectName)
  // Both of these read the project's repo, which the page has already had
  // cloned and cached for the README and showcase, so they're cheap here
  // and expensive nowhere else.
  const reproCheckQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "repro-check"],
    queryFn: () =>
      ProjectsService.getProjectReproCheck({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const pipelineQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "pipeline", undefined],
    queryFn: () =>
      ProjectsService.getProjectPipeline({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const newQuestionModal = useDisclosure()
  const newDatasetModal = useDisclosure()
  const enterDataModal = useDisclosure()
  const studioModal = useDisclosure()
  const newPubTemplateModal = useDisclosure()
  const overleafImportModal = useDisclosure()
  const steps = buildProjectSteps({
    questionCount: questionsRequest.data?.length ?? 0,
    reproCheck: reproCheckQuery.data,
    pipelineStatus: pipelineQuery.data?.status,
    stageStatuses: pipelineQuery.data?.stage_statuses as Record<
      string,
      { status?: string | null }
    >,
    flags: projectFlags,
  })
  // Waiting on the repo read would flash a list of unchecked boxes at
  // someone whose project is already in good shape, which is the worst
  // first impression this card can make. A read that failed outright says
  // nothing about the project either, so that's no reason to show one.
  if (reproCheckQuery.isPending || reproCheckQuery.isError) {
    return null
  }
  const actions: Record<string, React.ReactNode> = {
    question: (
      <>
        <Button size="xs" variant="primary" onClick={newQuestionModal.onOpen}>
          Add a question
        </Button>
        <CreateQuestion
          isOpen={newQuestionModal.isOpen}
          onClose={newQuestionModal.onClose}
        />
      </>
    ),
    dataset: (
      <>
        <HStack spacing={3}>
          <Button size="xs" variant="primary" onClick={enterDataModal.onOpen}>
            Type it in
          </Button>
          <Button size="xs" onClick={newDatasetModal.onOpen}>
            Upload or import
          </Button>
        </HStack>
        {/* Two instances rather than one with a changing default, so each
            opens on the source its button named. */}
        <NewDataset
          isOpen={enterDataModal.isOpen}
          onClose={enterDataModal.onClose}
          defaultSource="enter"
        />
        <NewDataset
          isOpen={newDatasetModal.isOpen}
          onClose={newDatasetModal.onClose}
        />
      </>
    ),
    figure: (
      <>
        <HStack spacing={3}>
          <Button
            size="xs"
            variant="primary"
            onClick={() => {
              mixpanel.track("Opened figure studio", { source: "checklist" })
              studioModal.onOpen()
            }}
          >
            New figure from data
          </Button>
          <Button
            size="xs"
            as={RouterLink}
            to={`/${accountName}/${projectName}/pipeline`}
          >
            Open the pipeline
          </Button>
          <Link
            fontSize="xs"
            variant="blue"
            href={PIPELINE_DOCS_URL}
            isExternal
          >
            Writing a stage <ExternalLinkIcon mb={0.5} />
          </Link>
        </HStack>
        {studioModal.isOpen ? (
          <FigureStudio
            isOpen={studioModal.isOpen}
            onClose={studioModal.onClose}
            ownerName={accountName}
            projectName={projectName}
          />
        ) : null}
      </>
    ),
    run: (
      <>
        <CommandBlock
          label="Install the CLI (macOS, Linux, or Git Bash)"
          command="curl -LsSf install.calkit.org | sh"
        />
        <CommandBlock
          label="Clone the project"
          command={`calkit clone ${accountName}/${projectName}`}
        />
        <CommandBlock
          label="Run it and push the results"
          command='calkit run -m "Run pipeline"'
        />
      </>
    ),
    publication: (
      <>
        <HStack spacing={3}>
          <Button
            size="xs"
            variant="primary"
            onClick={overleafImportModal.onOpen}
          >
            Link an Overleaf paper
          </Button>
          <Button size="xs" onClick={newPubTemplateModal.onOpen}>
            Start from a template
          </Button>
        </HStack>
        <NewPublication
          isOpen={newPubTemplateModal.isOpen}
          onClose={newPubTemplateModal.onClose}
          variant="template"
        />
        <ImportOverleaf
          isOpen={overleafImportModal.isOpen}
          onClose={overleafImportModal.onClose}
        />
      </>
    ),
    editor: (
      <Flex gap={4} wrap="wrap">
        <Link fontSize="xs" variant="blue" href={VSCODE_EXT_URL} isExternal>
          VS Code <ExternalLinkIcon mb={0.5} />
        </Link>
        <Link fontSize="xs" variant="blue" href={JUPYTER_DOCS_URL} isExternal>
          JupyterLab <ExternalLinkIcon mb={0.5} />
        </Link>
        <Link fontSize="xs" variant="blue" href={CHROME_EXT_URL} isExternal>
          Chrome <ExternalLinkIcon mb={0.5} />
        </Link>
      </Flex>
    ),
  }
  return (
    <ChecklistCard
      title="Project setup"
      intro={
        "Each step here is checked against the project itself, so anything " +
        "you do from the CLI ticks off on its own."
      }
      steps={steps}
      actions={actions}
      onMarkDone={setFlag}
      dismissed={projectFlags.includes(DISMISSED)}
      onDismissedChange={(dismissed) => setFlag(DISMISSED, dismissed)}
      doneMessage={
        "This project is reproducible end to end. Anyone can clone it and " +
        "get your results back."
      }
    />
  )
}

export default ProjectChecklist
