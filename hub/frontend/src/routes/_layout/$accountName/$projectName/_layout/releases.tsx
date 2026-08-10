import {
  Box,
  IconButton,
  Input,
  InputGroup,
  InputRightElement,
} from "@chakra-ui/react"
import { CloseIcon } from "@chakra-ui/icons"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"
import { z } from "zod"

import ReleasesTable from "../../../../../components/Releases/ReleasesTable"
import {
  DEFAULT_RELEASE_SORT,
  type ReleaseSort,
} from "../../../../../components/Releases/releaseSort"
import useProject from "../../../../../hooks/useProject"

const SORT_KEYS = [
  "name",
  "path",
  "version",
  "date",
  "views",
  "comments",
] as const

const releasesSearchSchema = z.object({
  // Table sort, persisted in the URL so it survives navigation/refresh.
  sort: z.enum(SORT_KEYS).optional(),
  dir: z.enum(["asc", "desc"]).optional(),
  // New release modal open state, so a link can reopen it.
  new_release: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/releases",
)({
  component: Releases,
  validateSearch: (search) => releasesSearchSchema.parse(search),
})

function Releases() {
  const { accountName, projectName } = Route.useParams()
  const navigate = Route.useNavigate()
  const search = Route.useSearch()
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const [query, setQuery] = useState("")
  const sort: ReleaseSort = {
    key: search.sort ?? DEFAULT_RELEASE_SORT.key,
    dir: search.dir ?? DEFAULT_RELEASE_SORT.dir,
  }
  const setSort = (s: ReleaseSort) => {
    const isDefault =
      s.key === DEFAULT_RELEASE_SORT.key && s.dir === DEFAULT_RELEASE_SORT.dir
    navigate({
      search: (prev) => ({
        ...prev,
        sort: isDefault ? undefined : s.key,
        dir: isDefault ? undefined : s.dir,
      }),
    })
  }
  return (
    <Box p={4} maxH="100%" overflowY="auto" w="100%">
      <InputGroup maxW="container.sm" mb={4}>
        <Input
          placeholder="Search releases…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoComplete="off"
          pr={query ? 8 : undefined}
        />
        {query && (
          <InputRightElement>
            <IconButton
              aria-label="Clear search"
              icon={<CloseIcon boxSize="8px" />}
              size="xs"
              variant="ghost"
              onClick={() => setQuery("")}
            />
          </InputRightElement>
        )}
      </InputGroup>
      <ReleasesTable
        ownerName={accountName}
        projectName={projectName}
        userHasWriteAccess={userHasWriteAccess}
        sort={sort}
        onSortChange={setSort}
        filter={query}
        newReleaseOpen={Boolean(search.new_release)}
        onNewReleaseOpenChange={(open) =>
          navigate({
            search: (prev) => ({ ...prev, new_release: open || undefined }),
          })
        }
      />
    </Box>
  )
}
