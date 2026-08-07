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
  Tr,
} from "@chakra-ui/react"
import { ExternalLinkIcon } from "@chakra-ui/icons"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  useNavigate,
  Link as RouterLink,
} from "@tanstack/react-router"
import { z } from "zod"
import { useEffect, useState } from "react"
import { useDebounce } from "use-debounce"

import { capitalizeFirstLetter } from "../../lib/strings"
import { OrgsService } from "../../client"
import ClearableInput from "../../components/Common/ClearableInput"

const orgsSearchSchema = z.object({
  page: z.number().catch(1),
})

const PER_PAGE = 10

function getAllOrgsQueryOptions({
  page,
  searchFor,
}: { page: number; searchFor?: string }) {
  return {
    queryFn: () =>
      OrgsService.getOrgs({
        offset: (page - 1) * PER_PAGE,
        limit: PER_PAGE,
        searchFor: searchFor,
      }),
    queryKey: ["orgs-all", { page, searchFor }],
  }
}

export const Route = createFileRoute("/_layout/orgs")({
  component: OrgsPage,
})

function PublicOrgsTable() {
  const queryClient = useQueryClient()
  const { page } = orgsSearchSchema.parse(Route.useSearch())
  const navigate = useNavigate({ from: Route.fullPath })
  const setPage = (page: number) =>
    navigate({ search: (prev) => ({ ...prev, page }) })
  const [searchForText, setSearchForText] = useState("")
  const [searchFor] = useDebounce(searchForText, 400)

  const {
    data: orgs,
    isPending,
    isPlaceholderData,
  } = useQuery({
    ...getAllOrgsQueryOptions({ page, searchFor }),
    placeholderData: (prevData) => prevData,
  })

  const hasNextPage = !isPlaceholderData && orgs?.data.length === PER_PAGE
  const hasPreviousPage = page > 1

  useEffect(() => {
    if (hasNextPage) {
      queryClient.prefetchQuery(
        getAllOrgsQueryOptions({ page: page + 1, searchFor }),
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
              <Th>Name</Th>
              <Th>GitHub name</Th>
              <Th>Role</Th>
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(3).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {orgs?.data.map((org, index) => (
                <Tr key={index} opacity={isPlaceholderData ? 0.5 : 1}>
                  <Td>
                    <Link as={RouterLink} to={`/${org.name}`}>
                      {org.display_name}
                    </Link>
                  </Td>
                  <Td>
                    <Link
                      isExternal
                      href={`https://github.com/${org.github_name}`}
                    >
                      <ExternalLinkIcon mx="2px" />
                      {org.github_name}
                    </Link>
                  </Td>
                  <Td>{capitalizeFirstLetter(org.role)}</Td>
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

function OrgsPage() {
  return (
    <Container maxW={{ base: "90%", md: "60%" }} pb={10}>
      <Heading
        size="lg"
        textAlign={{ base: "center", md: "left" }}
        pt={12}
        mb={4}
      >
        Orgs
      </Heading>
      <PublicOrgsTable />
    </Container>
  )
}
