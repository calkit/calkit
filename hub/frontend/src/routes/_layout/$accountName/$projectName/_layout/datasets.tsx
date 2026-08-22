import { ExternalLinkIcon } from "@chakra-ui/icons"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import {
  Badge,
  Box,
  Button,
  Card,
  Code,
  Flex,
  Heading,
  Icon,
  Link,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  SimpleGrid,
  Text,
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
import BrowseDatasets from "../../../../../components/Datasets/BrowseDatasets"
import DatasetViewer from "../../../../../components/Datasets/DatasetViewer"
import Tooltip from "../../../../../components/Common/Tooltip"
import NewDataset from "../../../../../components/Datasets/NewDataset"
import FigureStudio from "../../../../../components/Figures/FigureStudio"
import useProject, { useProjectDatasets } from "../../../../../hooks/useProject"
import { useQuery } from "@tanstack/react-query"
import mixpanel from "mixpanel-browser"
import { z } from "zod"

import { ProjectsService } from "../../../../../client"
import TipBubble from "../../../../../components/Onboarding/TipBubble"

// Which "add a dataset" form is open lives in the URL, the same way the
// references page carries its own. Filling one in is several fields of
// work, so a refresh or a back button shouldn't throw it away, and a link
// can hand someone the right form already open.
interface ImportedFrom {
  project?: string | null
  path?: string | null
  git_rev?: string | null
  url?: string | null
  doi?: string | null
  git?: { repo_url: string; rev: string; path?: string | null } | null
  date?: string | null
}

interface Person {
  name?: string | null
  email?: string | null
  orcid?: string | null
  with_ai?: string | string[] | null
}

interface DatasetSourceProps {
  stage?: string | null
  importedFrom?: ImportedFrom | null
  collectedBy?: Person[] | null
  /** Where the stage link goes, when there is one. */
  pipelineTo?: string
}

const personLabel = (p: Person) =>
  p.name ?? p.email ?? p.orcid?.replace(/^https?:\/\/orcid\.org\//, "") ?? "?"

/**
 * Where a dataset came from, in one line.
 *
 * A dataset is produced by a stage, collected by someone, or imported from
 * somewhere, and a reader deciding whether to trust a figure needs to know
 * which. A dataset with none of the three is flagged, since that's the one
 * case where the answer is "nobody said".
 */
const DatasetSource = ({
  stage,
  importedFrom,
  collectedBy,
  pipelineTo,
}: DatasetSourceProps) => {
  if (stage) {
    return (
      <Text fontSize="sm">
        <strong>Source:</strong> produced by stage{" "}
        {pipelineTo ? (
          <Link as={RouterLink} to={pipelineTo} search={{ stage } as any}>
            <Code fontSize="xs">{stage}</Code>
          </Link>
        ) : (
          <Code fontSize="xs">{stage}</Code>
        )}
      </Text>
    )
  }
  if (importedFrom) {
    const date = importedFrom.date ? ` on ${importedFrom.date}` : ""
    if (importedFrom.doi) {
      // Entries written before the hub normalized DOIs may still carry a
      // doi.org prefix; show and link the bare identifier either way.
      const doi = importedFrom.doi
        .trim()
        .replace(/^(?:https?:\/\/)?(?:www\.|dx\.)?doi\.org\//i, "")
        .replace(/^doi:\s*/i, "")
      return (
        <Text fontSize="sm">
          <strong>Source:</strong> imported from DOI{" "}
          <Tooltip label={`https://doi.org/${doi}`}>
            <Link href={`https://doi.org/${doi}`} isExternal>
              {doi} <ExternalLinkIcon mb={0.5} />
            </Link>
          </Tooltip>
          {date}
        </Text>
      )
    }
    if (importedFrom.url) {
      // A download URL can run to hundreds of characters; the card shows
      // where it points and the tooltip holds the whole thing.
      let shown = importedFrom.url
      try {
        const u = new URL(importedFrom.url)
        shown = `${u.host}${u.pathname.length > 1 ? "/…/" : ""}${
          u.pathname.split("/").filter(Boolean).pop() ?? ""
        }`
      } catch {
        // Not a parseable URL; show it as is, truncated
      }
      return (
        <Text fontSize="sm" isTruncated>
          <strong>Source:</strong> downloaded from{" "}
          <Tooltip label={importedFrom.url}>
            <Link href={importedFrom.url} isExternal>
              {shown} <ExternalLinkIcon mb={0.5} />
            </Link>
          </Tooltip>
          {date}
        </Text>
      )
    }
    if (importedFrom.git) {
      const { repo_url, rev, path } = importedFrom.git
      const commitUrl = repo_url.includes("github.com")
        ? `${repo_url.replace(/\.git$/, "")}/tree/${rev}/${path ?? ""}`
        : repo_url
      const label = `${repo_url.replace(/^https?:\/\/(www\.)?/, "")}${
        path ? `/${path}` : ""
      }`
      return (
        <Text fontSize="sm" isTruncated>
          <strong>Source:</strong> from Git repo{" "}
          <Tooltip label={`${label} at ${rev}`}>
            <Link href={commitUrl} isExternal>
              {label} <ExternalLinkIcon mb={0.5} />
            </Link>
          </Tooltip>{" "}
          at <Code fontSize="xs">{rev.slice(0, 7)}</Code>
          {date}
        </Text>
      )
    }
    if (importedFrom.project) {
      const srcPath = importedFrom.path ?? ""
      const label = `${importedFrom.project}${srcPath ? `/${srcPath}` : ""}`
      return (
        <Text fontSize="sm" isTruncated>
          <strong>Source:</strong> imported from{" "}
          <Tooltip label={label}>
            {/* Straight to that dataset's viewer in its own project */}
            <Link
              as={RouterLink}
              to={`/${importedFrom.project}/datasets` as any}
              search={(srcPath ? { view: srcPath } : {}) as any}
            >
              {label}
            </Link>
          </Tooltip>
          {importedFrom.git_rev ? (
            <>
              {" "}
              at <Code fontSize="xs">{importedFrom.git_rev.slice(0, 7)}</Code>
            </>
          ) : null}
        </Text>
      )
    }
  }
  if (collectedBy?.length) {
    const names = collectedBy.map(personLabel).join(", ")
    const withAi = collectedBy.some((p) => p.with_ai)
    return (
      <Text fontSize="sm">
        <strong>Source:</strong> collected by {names}
        {withAi ? (
          <Text as="span" color="orange.400">
            {" "}
            (with generative AI)
          </Text>
        ) : null}
      </Text>
    )
  }
  return (
    <Text fontSize="sm" color="orange.400">
      <strong>Source:</strong> not recorded
    </Text>
  )
}

const datasetsSearchSchema = z.object({
  new_dataset_open: z.boolean().optional(),
  source: z
    .enum(["primary", "upload", "enter", "url", "doi", "git_repo"])
    .optional(),
  // Dataset the figure studio is open on, so the studio survives a refresh.
  studio: z.string().optional(),
  // The "find a dataset on Calkit" browser.
  browse: z.boolean().optional(),
  // The dataset open in the viewer, by path.
  view: z.string().optional(),
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
    new_dataset_open: newDatasetOpen,
    source,
    studio: studioDataset,
    browse: browseOpen,
    view: viewPath,
  } = Route.useSearch()
  const setViewPath = (path: string | undefined) =>
    navigate({ search: (prev) => ({ ...prev, view: path }) })
  const viewedDataset = datasets?.find((d) => d.path === viewPath) ?? null
  const setBrowseOpen = (open: boolean) =>
    navigate({ search: (prev) => ({ ...prev, browse: open || undefined }) })
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
  const openNewDataset = (
    nextSource: "primary" | "upload" | "enter" | "url" | "git_repo",
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
                <MenuItem onClick={() => openNewDataset("upload")}>
                  Upload data I collected myself
                </MenuItem>
                <MenuItem onClick={() => openNewDataset("enter")}>
                  Enter data by hand
                </MenuItem>
                <MenuItem onClick={() => openNewDataset("primary")}>
                  Label an existing file or folder
                </MenuItem>
                <MenuItem onClick={() => openNewDataset("url")}>
                  Import from a URL or DOI
                </MenuItem>
                <MenuItem onClick={() => openNewDataset("git_repo")}>
                  Fetch from a Git repo
                </MenuItem>
                <MenuItem onClick={() => setBrowseOpen(true)}>
                  Find a dataset on Calkit
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
              // "upload" is the primary source on its upload variant
              defaultSource={
                source === "upload" ? "primary" : source ?? "primary"
              }
              defaultPrimaryMode={source === "upload" ? "upload" : "existing"}
            />
            <BrowseDatasets
              isOpen={Boolean(browseOpen)}
              onClose={() => setBrowseOpen(false)}
            />
          </>
        ) : (
          ""
        )}
        {viewedDataset ? (
          <DatasetViewer
            isOpen
            onClose={() => setViewPath(undefined)}
            ownerName={accountName}
            projectName={projectName}
            dataset={viewedDataset}
          />
        ) : null}
        {userHasWriteAccess ? (
          <>
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
            {datasets?.map((dataset, datasetIndex) => (
              <Card key={dataset.path} p={6} variant="elevated">
                <Heading size="sm" mb={2}>
                  <Code p={1} maxW="100%">
                    {/* The card's heading opens the viewer; the viewer's
                        own header links to the file on the files page */}
                    <TipBubble
                      tip="view-dataset"
                      where="page"
                      when={datasetIndex === 0}
                    >
                      <Link
                        cursor="pointer"
                        onClick={() => setViewPath(dataset.path)}
                      >
                        {dataset.path}
                      </Link>
                    </TipBubble>
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
                  <Box sx={{ "& p": { my: 0 } }} mb={1}>
                    <strong>Description:</strong>{" "}
                    <Markdown inline>{dataset.description}</Markdown>
                  </Box>
                ) : (
                  ""
                )}
                <DatasetSource
                  stage={dataset.stage}
                  importedFrom={dataset.imported_from_info as any}
                  collectedBy={dataset.collected_by as any}
                  pipelineTo={`/${accountName}/${projectName}/pipeline`}
                />
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
