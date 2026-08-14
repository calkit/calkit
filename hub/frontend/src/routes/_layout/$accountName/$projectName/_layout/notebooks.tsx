import {
  Box,
  Button,
  Code,
  Flex,
  HStack,
  Heading,
  Icon,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useNavigate } from "@tanstack/react-router"
import { FaCodeBranch } from "react-icons/fa"
import { SiJupyter } from "react-icons/si"
import { z } from "zod"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Tooltip from "../../../../../components/Common/Tooltip"

import { type Notebook, ProjectsService } from "../../../../../client"
import { ArtifactCompareModal } from "../../../../../components/Common/ArtifactCompareModal"
import PageMenu from "../../../../../components/Common/PageMenu"
import NotebookView from "../../../../../components/Notebooks/NotebookView"

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
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
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
