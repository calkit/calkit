import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Badge,
  Box,
  Button,
  Container,
  Flex,
  Heading,
  Icon,
  Link,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router"
import { type ReactNode, useEffect, useRef, useState } from "react"
import { FaPlus } from "react-icons/fa"
import { useDebounce } from "use-debounce"
import { z } from "zod"

import { type UserPublic, UsersService } from "../../client"
import AddUser from "../../components/Admin/AddUser"
import ClearableInput from "../../components/Common/ClearableInput"
import FeedbackTable from "../../components/Admin/FeedbackTable"
import ActionsMenu from "../../components/Common/ActionsMenu"
import { isLoggedIn } from "../../hooks/useAuth"
import { pageWidthNoSidebar } from "../../lib/layout"
import { formatTimestamp } from "../../lib/strings"

const usersSearchSchema = z.object({
  page: z.number().catch(1),
  // In the URL so a search or an ordering can be linked to and survives
  // opening a user and coming back, the same as the page number already did.
  q: z.string().optional(),
  sort_by: z.enum(["created", "email", "full_name"]).catch("created"),
  desc: z.boolean().catch(true),
  add_user_open: z.boolean().optional(),
})

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  validateSearch: (search) => usersSearchSchema.parse(search),
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

const PER_PAGE = 5

type SortBy = "created" | "email" | "full_name"

function getUsersQueryOptions({
  page,
  searchFor,
  sortBy,
  descending,
}: {
  page: number
  searchFor?: string
  sortBy: SortBy
  descending: boolean
}) {
  return {
    queryFn: () =>
      UsersService.readUsers({
        skip: (page - 1) * PER_PAGE,
        limit: PER_PAGE,
        search_for: searchFor || undefined,
        sort_by: sortBy,
        descending,
      }).then((response) => response.data),
    queryKey: ["users", { page, searchFor, sortBy, descending }],
  }
}

/**
 * A column header that sorts on click and on Enter or Space.
 *
 * The header cell keeps its `aria-sort` so a screen reader announces the
 * ordering, and the button inside it is what takes focus, since a `th` with
 * an onClick is invisible to the keyboard.
 */
function SortableTh({
  width,
  active,
  descending,
  onToggle,
  children,
}: {
  width: string
  active: boolean
  descending: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <Th
      width={width}
      aria-sort={active ? (descending ? "descending" : "ascending") : "none"}
    >
      <Box
        as="button"
        type="button"
        onClick={onToggle}
        fontWeight="inherit"
        textTransform="inherit"
        letterSpacing="inherit"
        color="inherit"
        cursor="pointer"
      >
        {children}
        {active ? (descending ? " ↓" : " ↑") : ""}
      </Box>
    </Th>
  )
}

function UsersTable() {
  const queryClient = useQueryClient()
  const currentUser = queryClient.getQueryData<UserPublic>(["currentUser"])
  const {
    page,
    q,
    sort_by: sortBy,
    desc: descending,
    add_user_open: addUserOpen,
  } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const setPage = (page: number) =>
    navigate({ search: (prev) => ({ ...prev, page }) })
  // Typing stays local so every keystroke isn't a history entry; the URL
  // catches up once the input settles. The URL is still the source of
  // truth: a `q` that differs from what this component last pushed arrived
  // by Back or a link, and the input follows it rather than pushing its own
  // stale value back over the top, which would undo the Back.
  const [searchText, setSearchText] = useState(q ?? "")
  const [searchFor] = useDebounce(searchText, 400)
  const lastPushed = useRef(q ?? "")
  useEffect(() => {
    const fromUrl = q ?? ""
    if (fromUrl !== lastPushed.current) {
      lastPushed.current = fromUrl
      setSearchText(fromUrl)
    }
  }, [q])
  useEffect(() => {
    // Only once the debounce has caught up with the input: right after a
    // Back, the debounced value is still the search that was just left.
    if (searchFor !== searchText || searchFor === lastPushed.current) return
    lastPushed.current = searchFor
    navigate({
      search: (prev) => ({ ...prev, q: searchFor || undefined, page: 1 }),
    })
  }, [searchFor, searchText, navigate])
  // Clicking the column already sorted by flips the direction, which is
  // what a header that shows an arrow implies it will do.
  const toggleSort = (column: SortBy) => {
    navigate({
      search: (prev) => ({
        ...prev,
        sort_by: column,
        desc: column === sortBy ? !descending : true,
        page: 1,
      }),
    })
  }

  const {
    data: users,
    isPending,
    isPlaceholderData,
  } = useQuery({
    ...getUsersQueryOptions({ page, searchFor, sortBy, descending }),
    placeholderData: (prevData) => prevData,
  })

  const hasNextPage = !isPlaceholderData && users?.data.length === PER_PAGE
  const hasPreviousPage = page > 1

  useEffect(() => {
    if (hasNextPage) {
      queryClient.prefetchQuery(
        getUsersQueryOptions({
          page: page + 1,
          searchFor,
          sortBy,
          descending,
        }),
      )
    }
  }, [page, queryClient, hasNextPage, searchFor, sortBy, descending])

  return (
    <>
      <Flex py={4} gap={4} align="center">
        <Button
          variant="primary"
          gap={1}
          onClick={() =>
            navigate({ search: (prev) => ({ ...prev, add_user_open: true }) })
          }
        >
          <Icon as={FaPlus} /> Add user
        </Button>
        <AddUser
          isOpen={Boolean(addUserOpen)}
          onClose={() =>
            navigate({
              search: (prev) => ({ ...prev, add_user_open: undefined }),
            })
          }
        />
        <ClearableInput
          placeholder="Search by name, email, or GitHub username…"
          width="33%"
          value={searchText}
          onValueChange={setSearchText}
        />
        {users ? (
          <Text fontSize="sm" color="ui.dim" ml="auto" alignSelf="center">
            {users.count} {users.count === 1 ? "user" : "users"}
          </Text>
        ) : null}
      </Flex>
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <SortableTh
                width="18%"
                active={sortBy === "full_name"}
                descending={descending}
                onToggle={() => toggleSort("full_name")}
              >
                Full name
              </SortableTh>
              <Th width="16%">GitHub username</Th>
              <SortableTh
                width="30%"
                active={sortBy === "email"}
                descending={descending}
                onToggle={() => toggleSort("email")}
              >
                Email
              </SortableTh>
              <SortableTh
                width="16%"
                active={sortBy === "created"}
                descending={descending}
                onToggle={() => toggleSort("created")}
              >
                Signed up
              </SortableTh>
              <Th width="10%">Role</Th>
              <Th width="10%">Status</Th>
              <Th width="10%">Actions</Th>
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
              {users?.data.map((user) => (
                <Tr key={user.id}>
                  <Td
                    color={!user.full_name ? "ui.dim" : "inherit"}
                    isTruncated
                    maxWidth="150px"
                  >
                    {user.full_name || "N/A"}
                    {currentUser?.id === user.id && (
                      <Badge ml="1" colorScheme="teal">
                        You
                      </Badge>
                    )}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    {user.github_username ? (
                      <Link
                        href={`https://github.com/${user.github_username}`}
                        isExternal
                        variant="blue"
                      >
                        {user.github_username} <ExternalLinkIcon mb={0.5} />
                      </Link>
                    ) : (
                      <Text color="ui.dim">N/A</Text>
                    )}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    {user.email}
                  </Td>
                  <Td fontSize="sm" whiteSpace="nowrap">
                    {formatTimestamp(user.created)}
                  </Td>
                  <Td>{user.is_superuser ? "Superuser" : "User"}</Td>
                  <Td>
                    <Flex gap={2}>
                      <Box
                        w="2"
                        h="2"
                        borderRadius="50%"
                        bg={user.is_active ? "ui.success" : "ui.danger"}
                        alignSelf="center"
                      />
                      {user.is_active ? "Active" : "Inactive"}
                    </Flex>
                  </Td>
                  <Td>
                    <ActionsMenu
                      type="User"
                      value={user}
                      disabled={currentUser?.id === user.id}
                    />
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

function Admin() {
  return (
    <Container maxW={pageWidthNoSidebar}>
      <Heading size="lg" textAlign={{ base: "center", md: "left" }} pt={12}>
        User management
      </Heading>
      <UsersTable />
      <FeedbackTable />
    </Container>
  )
}
