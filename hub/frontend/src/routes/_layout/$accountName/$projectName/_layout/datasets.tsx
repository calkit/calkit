import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import {
  Box,
  Heading,
  Flex,
  Text,
  Code,
  Badge,
  SimpleGrid,
  Card,
  Menu,
  MenuButton,
  Icon,
  MenuList,
  MenuItem,
  Button,
  Link,
} from "@chakra-ui/react"
import {
  createFileRoute,
  Link as RouterLink,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import { FaPlus } from "react-icons/fa"
import { FiDatabase } from "react-icons/fi"

import Markdown from "../../../../../components/Common/Markdown"
import NewDataset from "../../../../../components/Datasets/NewDataset"
import FigureStudio from "../../../../../components/Figures/FigureStudio"
import UploadDataset from "../../../../../components/Datasets/UploadDataset"
import useProject, { useProjectDatasets } from "../../../../../hooks/useProject"
import { useQuery } from "@tanstack/react-query"
import mixpanel from "mixpanel-browser"
import { z } from "zod"

import { ProjectsService } from "../../../../../client"

// Which "add a dataset" form is open lives in the URL, the same way the
// references page carries its own. Filling one in is several fields of
// work, so a refresh or a back button shouldn't throw it away, and a link
// can hand someone the right form already open.
const datasetsSearchSchema = z.object({
  upload_open: z.boolean().optional(),
  new_dataset_open: z.boolean().optional(),
  source: z.enum(["primary", "enter", "url", "doi", "git_repo"]).optional(),
  // Dataset the figure studio is open on, so the studio survives a refresh.
  studio: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/datasets",
)({
  component: ProjectData,
  validateSearch: (search) => datasetsSearchSchema.parse(search),
})

function ProjectDataView() {
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const { datasetsRequest } = useProjectDatasets(accountName, projectName, ref)
  const { isPending: dataPending, data: datasets } = datasetsRequest
  const {
    upload_open: uploadOpen,
    new_dataset_open: newDatasetOpen,
    source,
    studio: studioDataset,
  } = Route.useSearch()
  const setStudioDataset = (path: string | undefined) =>
    navigate({ search: (prev) => ({ ...prev, studio: path }) })
  // Which figures each dataset feeds: a figure's stage lists its concrete
  // inputs in dvc.yaml, so a dataset path (or a file under a dataset
  // folder) among those deps ties the two together.
  const figuresQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "figures"],
    queryFn: () =>
      ProjectsService.getProjectFigures({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
  })
  const pipelineQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "pipeline", undefined],
    queryFn: () =>
      ProjectsService.getProjectPipeline({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
  })
  const figuresUsing = (datasetPath: string) =>
    (figuresQuery.data?.items ?? []).filter((figure) => {
      if (!figure.stage) return false
      const stage = pipelineQuery.data?.dvc_stages?.[figure.stage] as
        | { deps?: string[] | null }
        | undefined
      return (stage?.deps ?? []).some(
        (dep) => dep === datasetPath || dep.startsWith(`${datasetPath}/`),
      )
    })
  const navigate = useNavigate({ from: Route.fullPath })
  const openUpload = () =>
    navigate({ search: (prev) => ({ ...prev, upload_open: true }) })
  const openNewDataset = (
    nextSource: "primary" | "enter" | "url" | "git_repo",
  ) =>
    navigate({
      search: (prev) => ({
        ...prev,
        new_dataset_open: true,
        source: nextSource,
      }),
    })
  const closeAll = () =>
    navigate({
      search: (prev) => ({
        ...prev,
        upload_open: undefined,
        new_dataset_open: undefined,
        source: undefined,
      }),
    })

  return (
    <>
      <Flex align="center" mb={2}>
        <Heading size="md">Datasets</Heading>
        {userHasWriteAccess ? (
          <>
            <Menu>
              <MenuButton
                as={Button}
                variant="primary"
                height={"25px"}
                width={"9px"}
                px={1}
                ml={2}
              >
                <Icon as={FaPlus} fontSize="xs" />
              </MenuButton>
              <MenuList>
                <MenuItem onClick={() => openNewDataset("enter")}>
                  Enter data by hand
                </MenuItem>
                <MenuItem onClick={openUpload}>Upload new dataset</MenuItem>
                <MenuItem onClick={() => openNewDataset("primary")}>
                  Label an existing file or folder
                </MenuItem>
                <MenuItem onClick={() => openNewDataset("url")}>
                  Import from a URL or DOI
                </MenuItem>
                <MenuItem onClick={() => openNewDataset("git_repo")}>
                  Fetch from a Git repo
                </MenuItem>
              </MenuList>
            </Menu>
            {/* Keyed on the source so switching between menu entries
                remounts the form rather than leaving the previous one's
                fields behind. */}
            <NewDataset
              key={source ?? "primary"}
              onClose={closeAll}
              isOpen={Boolean(newDatasetOpen)}
              defaultSource={source ?? "primary"}
            />
            <UploadDataset onClose={closeAll} isOpen={Boolean(uploadOpen)} />
            {studioDataset ? (
              <FigureStudio
                isOpen
                onClose={() => setStudioDataset(undefined)}
                ownerName={accountName}
                projectName={projectName}
                initialDataset={studioDataset}
              />
            ) : null}
          </>
        ) : (
          ""
        )}
      </Flex>
      {dataPending ? (
        <LoadingSpinner height="100vh" />
      ) : (
        <Box>
          {!datasets || datasets.length === 0 ? (
            // Passed as a string rather than JSX text: a dash in a text node
            // picks up the surrounding line breaks as spaces, and an entity
            // isn't decoded here.
            <NoArtifactFound
              icon={FiDatabase}
              title="No datasets found"
              hint={
                "Declaring one records where the data came from\u2014" +
                "collected here, downloaded, from a DOI, or from a Git " +
                "repo\u2014which is what lets a figure be traced back to it."
              }
              docsUrl="https://docs.calkit.org/datasets/"
            />
          ) : null}
          <SimpleGrid columns={[3, null, 4]} gap={6}>
            {datasets?.map((dataset) => (
              <Card key={dataset.path} p={6} variant="elevated">
                <Heading size="sm" mb={2}>
                  <Code p={1} maxW="100%">
                    <Link
                      as={RouterLink}
                      to={"../files"}
                      search={{ path: dataset.path } as any}
                    >
                      {dataset.path}
                    </Link>
                    {dataset.imported_from ? (
                      <Badge ml={1} bgColor="green.500">
                        imported
                      </Badge>
                    ) : (
                      ""
                    )}
                  </Code>
                </Heading>
                {dataset.title ? (
                  <Text mb={1}>
                    <strong>Title:</strong> {dataset.title}
                  </Text>
                ) : (
                  ""
                )}
                {dataset.description ? (
                  <Box sx={{ "& p": { my: 0 } }}>
                    <strong>Description:</strong>{" "}
                    <Markdown inline>{dataset.description}</Markdown>
                  </Box>
                ) : (
                  ""
                )}
                {(() => {
                  const used = figuresUsing(dataset.path)
                  const isCsv = dataset.path.toLowerCase().endsWith(".csv")
                  return (
                    <Flex mt={3} gap={3} align="center" wrap="wrap">
                      {used.length > 0 ? (
                        <Link
                          as={RouterLink}
                          to={"../figures"}
                          search={{ path: used[0].path } as any}
                          fontSize="sm"
                        >
                          Used in {used.length}{" "}
                          {used.length === 1 ? "figure" : "figures"} →
                        </Link>
                      ) : pipelineQuery.isSuccess ? (
                        <Text fontSize="sm" color="ui.dim">
                          Not plotted yet
                        </Text>
                      ) : null}
                      {userHasWriteAccess && isCsv && !ref ? (
                        <Button
                          size="xs"
                          variant="primary"
                          onClick={() => {
                            mixpanel.track("Opened figure studio", {
                              source: "dataset-card",
                            })
                            setStudioDataset(dataset.path)
                          }}
                        >
                          New figure
                        </Button>
                      ) : null}
                    </Flex>
                  )
                })()}
              </Card>
            ))}
          </SimpleGrid>
        </Box>
      )}
    </>
  )
}

function ProjectData() {
  return <ProjectDataView />
}
