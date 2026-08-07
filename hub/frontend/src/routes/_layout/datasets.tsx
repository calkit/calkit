import {
  Button,
  Container,
  Flex,
  Heading,
  Link,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Th,
  Thead,
  Text,
  Tr,
} from "@chakra-ui/react"
import Tooltip from "../../components/Common/Tooltip"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  useNavigate,
  Link as RouterLink,
} from "@tanstack/react-router"
import { z } from "zod"
import { useEffect, useState } from "react"
import { useDebounce } from "use-debounce"

import { pageWidthNoSidebar } from "../../lib/layout"
import { DatasetsService } from "../../client"
import ClearableInput from "../../components/Common/ClearableInput"

const datasetsSearchSchema = z.object({
  page: z.number().catch(1),
})

const PER_PAGE = 10

function getAllDatasetsQueryOptions({
  page,
  searchFor,
}: { page: number; searchFor?: string }) {
  return {
    queryFn: () =>
      DatasetsService.getDatasets({
        offset: (page - 1) * PER_PAGE,
        limit: PER_PAGE,
        searchFor: searchFor,
      }),
    queryKey: ["datasets-all", { page, searchFor }],
  }
}

export const Route = createFileRoute("/_layout/datasets")({
  component: PublicDatasets,
})

function PublicDatasetsTable() {
  const queryClient = useQueryClient()
  const { page } = datasetsSearchSchema.parse(Route.useSearch())
  const navigate = useNavigate({ from: Route.fullPath })
  const setPage = (page: number) =>
    navigate({ search: (prev) => ({ ...prev, page }) })
  const [searchForText, setSearchForText] = useState("")
  const [searchFor] = useDebounce(searchForText, 400)

  const {
    data: datasets,
    isPending,
    isPlaceholderData,
  } = useQuery({
    ...getAllDatasetsQueryOptions({ page, searchFor }),
    placeholderData: (prevData) => prevData,
  })

  const hasNextPage = !isPlaceholderData && datasets?.data.length === PER_PAGE
  const hasPreviousPage = page > 1

  useEffect(() => {
    if (hasNextPage) {
      queryClient.prefetchQuery(
        getAllDatasetsQueryOptions({ page: page + 1, searchFor }),
      )
    }
  }, [page, queryClient, hasNextPage, searchFor])

  return (
    <>
      <ClearableInput
        mb={4}
        placeholder="Search..."
        width="33%"
        value={searchForText ?? ""}
        onValueChange={setSearchForText}
      />
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th>Owner</Th>
              <Th>Project</Th>
              <Th>Path</Th>
              <Th>Title</Th>
              <Th>Description</Th>
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(4).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {datasets?.data.map((dataset, index) => (
                <Tr key={index} opacity={isPlaceholderData ? 0.5 : 1}>
                  <Td isTruncated maxWidth="80px">
                    {dataset.project.owner_account_display_name}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    <Link
                      as={RouterLink}
                      to={`/${dataset.project.owner_account_name}/${dataset.project.name}/datasets`}
                    >
                      <Tooltip label={dataset.project.title}>
                        <Text isTruncated>{dataset.project.title}</Text>
                      </Tooltip>
                    </Link>
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    <Link
                      as={RouterLink}
                      to={`/${dataset.project.owner_account_name}/${dataset.project.name}/datasets`}
                    >
                      <Tooltip label={dataset.path}>
                        <Text isTruncated>{dataset.path}</Text>
                      </Tooltip>
                    </Link>
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    <Link
                      as={RouterLink}
                      to={`/${dataset.project.owner_account_name}/${dataset.project.name}/datasets`}
                    >
                      {dataset.title}
                    </Link>
                  </Td>
                  <Td
                    color={!dataset.description ? "ui.dim" : "inherit"}
                    isTruncated
                    maxWidth="250px"
                  >
                    {dataset.description ? (
                      <Tooltip label={dataset.description}>
                        <Text isTruncated>{dataset.description}</Text>
                      </Tooltip>
                    ) : (
                      "N/A"
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          )}
        </Table>
      </TableContainer>
      <Flex
        gap={4}
        alignItems="center"
        mt={4}
        direction="row"
        justifyContent="flex-end"
      >
        <Button onClick={() => setPage(page - 1)} isDisabled={!hasPreviousPage}>
          Previous
        </Button>
        <span>Page {page}</span>
        <Button isDisabled={!hasNextPage} onClick={() => setPage(page + 1)}>
          Next
        </Button>
      </Flex>
    </>
  )
}

function PublicDatasets() {
  return (
    <Container maxW={pageWidthNoSidebar} pb={10}>
      <Heading
        size="lg"
        textAlign={{ base: "center", md: "left" }}
        pt={12}
        mb={4}
      >
        Browse all datasets
      </Heading>
      <PublicDatasetsTable />
    </Container>
  )
}
