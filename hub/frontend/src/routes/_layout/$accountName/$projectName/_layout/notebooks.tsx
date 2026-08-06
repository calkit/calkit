import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import {
  Text,
  Flex,
  Box,
  useColorModeValue,
  Heading,
  Icon,
  Code,
  HStack,
  Button,
} from "@chakra-ui/react"
import Tooltip from "../../../../../components/Common/Tooltip"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useNavigate } from "@tanstack/react-router"
import { lazy, Suspense } from "react"
import { SiJupyter } from "react-icons/si"
import { FaCodeBranch } from "react-icons/fa"
import { z } from "zod"

const IpynbRenderer = lazy(() =>
  import("react-ipynb-renderer").then(async (m) => {
    await import("react-ipynb-renderer/dist/styles/monokai.css")
    return { default: m.IpynbRenderer }
  }),
)

import { ProjectsService, type Notebook } from "../../../../../client"
import PageMenu from "../../../../../components/Common/PageMenu"
import { ArtifactCompareModal } from "../../../../../components/Common/ArtifactCompareModal"

const notebookSearchSchema = z.object({
  ref: z.string().optional(),
  path: z.string().optional(),
  compare_open: z.boolean().optional(),
  base_ref: z.string().optional(),
  compare_ref: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/notebooks",
)({
  component: Notebooks,
  validateSearch: (search) => notebookSearchSchema.parse(search),
})

function NotebookView({ notebook }: { notebook: Notebook }) {
  if (notebook.output_format === "notebook" && notebook.content) {
    try {
      const json = JSON.parse(atob(notebook.content))
      return (
        <Box
          overflowY="auto"
          overflowX="hidden"
          borderRadius="lg"
          sx={{
            ".ipynb-renderer-root": { borderRadius: "var(--chakra-radii-lg)" },
            ".ipynb-renderer-root #notebook-container": {
              width: "100%",
              marginLeft: 0,
              marginRight: 0,
            },
            ".ipynb-renderer-root pre, .ipynb-renderer-root .CodeMirror": {
              fontSize: "13px !important",
              lineHeight: "1.5 !important",
            },
          }}
        >
          <Suspense fallback={<LoadingSpinner />}>
            <IpynbRenderer ipynb={json} syntaxTheme="atomDark" />
          </Suspense>
        </Box>
      )
    } catch {
      // fall through to other renderers
    }
  }
  if (notebook.output_format === "html" && notebook.content) {
    return (
      <embed
        height="100%"
        width="100%"
        type="text/html"
        src={`data:text/html;base64,${notebook.content}`}
      />
    )
  }
  if (notebook.url) {
    return (
      <iframe
        height="100%"
        width="100%"
        title="notebook"
        src={notebook.url}
        style={{ border: "none" }}
      />
    )
  }
  return (
    <Flex align="center" justify="center" height="300px" color="gray.500">
      <Text>
        No rendered output found. Run the notebook and commit the HTML output to
        view it here.
      </Text>
    </Flex>
  )
}

function NotebookInfo({
  notebook,
  onOpenCompare,
}: {
  notebook: Notebook
  onOpenCompare: () => void
}) {
  const bg = useColorModeValue("ui.secondary", "ui.darkSlate")

  return (
    <Box bg={bg} borderRadius="lg" p={3} h="fit-content">
      <Heading size="sm" mb={2}>
        Info
      </Heading>
      <Text fontSize="sm" mb={1}>
        <Text as="span">Title:</Text>{" "}
        <Text as="span" color="gray.500">
          {notebook.title ?? ""}
        </Text>
      </Text>
      <Text fontSize="sm" mb={1}>
        <Text as="span">Description:</Text>{" "}
        <Text as="span" color="gray.500">
          {notebook.description ?? ""}
        </Text>
      </Text>
      <Text fontSize="sm" mb={1}>
        <Text as="span">Path:</Text> <Code fontSize="xs">{notebook.path}</Code>
      </Text>
      <Text fontSize="sm" mb={1}>
        <Text as="span">Pipeline stage:</Text>{" "}
        {notebook.stage ? (
          <Code fontSize="xs">{notebook.stage}</Code>
        ) : (
          <Text as="span" color="red.500">
            Not in pipeline
          </Text>
        )}
      </Text>
      <Button mt={2} size="sm" onClick={onOpenCompare}>
        <Icon as={FaCodeBranch} mr={1} />
        Browse history
      </Button>
    </Box>
  )
}

function Notebooks() {
  const { accountName, projectName } = Route.useParams()
  const {
    ref,
    path: selectedPath,
    compare_open,
    base_ref,
    compare_ref,
  } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const setSelectedPath = (p: string) =>
    navigate({ search: (prev) => ({ ...prev, path: p }) })

  const openCompare = (notebookPath: string) =>
    navigate({
      search: (prev) => ({
        ...prev,
        path: notebookPath,
        compare_open: true,
      }),
    })

  const closeCompare = () =>
    navigate({
      search: (prev) => ({
        ...prev,
        compare_open: undefined,
        base_ref: undefined,
        compare_ref: undefined,
      }),
    })

  const { isPending, data: notebooks } = useQuery({
    queryKey: ["projects", accountName, projectName, "notebooks", ref],
    queryFn: () =>
      ProjectsService.getProjectNotebooks({
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
  })

  const selectedNotebook =
    notebooks?.find((n) => n.path === selectedPath) ?? notebooks?.[0]

  return (
    <>
      {isPending ? (
        <LoadingSpinner />
      ) : (
        <Flex height="100%" gap={0}>
          {/* Left: list */}
          <PageMenu>
            <Heading size="md" mb={2}>
              Notebooks
            </Heading>
            {!notebooks || notebooks.length === 0 ? (
              <Text fontSize="sm" color="gray.500">
                No notebooks found
              </Text>
            ) : (
              notebooks.map((nb) => {
                const isSelected = nb.path === selectedNotebook?.path
                return (
                  <Tooltip
                    key={nb.path}
                    label={nb.title ?? nb.path}
                    placement="right"
                  >
                    <HStack
                      px={1}
                      py={0.5}
                      borderRadius="md"
                      cursor="pointer"
                      fontWeight={isSelected ? "semibold" : "normal"}
                      _hover={{ color: "blue.500" }}
                      onClick={() => setSelectedPath(nb.path ?? "")}
                      spacing={1}
                    >
                      <Icon as={SiJupyter} flexShrink={0} color="orange.400" />
                      <Text fontSize="sm" noOfLines={1}>
                        {nb.title ?? nb.path}
                      </Text>
                    </HStack>
                  </Tooltip>
                )
              })
            )}
          </PageMenu>
          {/* Center: viewer */}
          <Box flex={1} minW={0} mr={6}>
            {selectedNotebook ? (
              <>
                <Box
                  height="82vh"
                  borderRadius="lg"
                  overflowX="hidden"
                  overflowY="auto"
                >
                  <NotebookView notebook={selectedNotebook} />
                </Box>
              </>
            ) : (
              <Flex
                align="center"
                justify="center"
                height="300px"
                color="gray.500"
                direction="column"
                gap={3}
              >
                <Icon as={SiJupyter} fontSize="4xl" color="orange.300" />
                <Text>No notebooks found</Text>
              </Flex>
            )}
          </Box>
          {/* Right: info */}
          {selectedNotebook && (
            <Box w="240px" flexShrink={0}>
              <NotebookInfo
                notebook={selectedNotebook}
                onOpenCompare={() => openCompare(selectedNotebook.path ?? "")}
              />
              <ArtifactCompareModal
                isOpen={Boolean(compare_open)}
                onClose={closeCompare}
                ownerName={accountName}
                projectName={projectName}
                path={selectedNotebook.path ?? ""}
                kind="notebook"
                initialRef={base_ref}
                initialRef2={compare_ref}
                initialArtifact={selectedNotebook}
                onRefsChange={(r1, r2) =>
                  navigate({
                    search: (prev) => ({
                      ...prev,
                      base_ref: r1,
                      compare_ref: r2,
                    }),
                  })
                }
              />
            </Box>
          )}
        </Flex>
      )}
    </>
  )
}
