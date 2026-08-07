import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  HStack,
  Heading,
  Icon,
  IconButton,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useDisclosure,
  useToast,
} from "@chakra-ui/react"
import Tooltip from "../Common/Tooltip"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { useState } from "react"
import {
  FaCheck,
  FaGithub,
  FaPlus,
  FaSort,
  FaSortDown,
  FaSortUp,
  FaTrash,
} from "react-icons/fa"
import { FiExternalLink, FiShare2 } from "react-icons/fi"

import { type ReleaseListItem, ReleasesService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import {
  formatReleaseDate,
  releaseLocation,
  releasePagePath,
} from "../../lib/releases"
import LoadingSpinner from "../Common/LoadingSpinner"
import NewRelease from "./NewRelease"
import ShareDialog from "./ShareDialog"
import {
  DEFAULT_RELEASE_SORT,
  type ReleaseSort,
  type SortKey,
} from "./releaseSort"

// Columns that read most naturally as descending on first click.
const DESC_FIRST: Set<SortKey> = new Set(["date", "views", "comments"])

const sortValue = (r: ReleaseListItem, key: SortKey): string | number => {
  switch (key) {
    case "name":
      return r.name.toLowerCase()
    case "path":
      return (r.path && r.path !== "." ? r.path : "").toLowerCase()
    case "version":
      return (r.git_ref ?? r.git_rev_abbrev ?? "").toLowerCase()
    case "date":
      return r.date ? new Date(r.date).getTime() || 0 : 0
    case "views":
      return r.view_count ?? -1
    case "comments":
      return r.comment_count ?? -1
  }
}

interface ReleasesTableProps {
  ownerName: string
  projectName: string
  userHasWriteAccess: boolean
  // Controlled sort state so it can be persisted (e.g., in URL params).
  sort?: ReleaseSort
  onSortChange?: (sort: ReleaseSort) => void
  // Case-insensitive substring filter across name/path/title/publisher.
  filter?: string
  // Controlled "New release" modal open state, so it can live in URL params.
  newReleaseOpen?: boolean
  onNewReleaseOpenChange?: (open: boolean) => void
}

const ReleasesTable = ({
  ownerName,
  projectName,
  userHasWriteAccess,
  sort: sortProp,
  onSortChange,
  filter,
  newReleaseOpen,
  onNewReleaseOpenChange,
}: ReleasesTableProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  // Used directly (not via useCustomToast) so the result can link to GitHub.
  const toast = useToast()
  // Falls back to internal disclosure when used uncontrolled.
  const newReleaseModal = useDisclosure()
  const newReleaseIsOpen = newReleaseOpen ?? newReleaseModal.isOpen
  const openNewRelease = () =>
    onNewReleaseOpenChange
      ? onNewReleaseOpenChange(true)
      : newReleaseModal.onOpen()
  const closeNewRelease = () =>
    onNewReleaseOpenChange
      ? onNewReleaseOpenChange(false)
      : newReleaseModal.onClose()
  const confirmDelete = useDisclosure()
  const shareModal = useDisclosure()
  const [toDelete, setToDelete] = useState<ReleaseListItem | null>(null)
  // The cloud release whose share links are being managed.
  const [active, setActive] = useState<ReleaseListItem | null>(null)
  const openShare = (r: ReleaseListItem) => {
    setActive(r)
    shareModal.onOpen()
  }
  // Fall back to internal state when used uncontrolled.
  const [sortState, setSortState] = useState<ReleaseSort>(DEFAULT_RELEASE_SORT)
  const sort = sortProp ?? sortState
  const toggleSort = (key: SortKey) => {
    const next: ReleaseSort =
      sort.key === key
        ? { key, dir: sort.dir === "asc" ? "desc" : "asc" }
        : { key, dir: DESC_FIRST.has(key) ? "desc" : "asc" }
    if (onSortChange) {
      onSortChange(next)
    } else {
      setSortState(next)
    }
  }

  const releasesQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "releases", undefined],
    queryFn: () =>
      ReleasesService.getProjectReleases({ ownerName, projectName }),
  })
  const deleteMutation = useMutation({
    mutationFn: (name: string) =>
      ReleasesService.deleteProjectRelease({
        ownerName,
        projectName,
        releaseName: name,
      }),
    onSuccess: () => {
      showToast("Success", "Release deleted.", "success")
      confirmDelete.onClose()
      setToDelete(null)
    },
    onError: (err: ApiError) => handleError(err, showToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "releases"],
      })
    },
  })
  const importMutation = useMutation({
    mutationFn: () =>
      ReleasesService.importGithubReleases({ ownerName, projectName }),
    onSuccess: (msg) => {
      showToast("Success", msg.message, "success")
    },
    onError: (err: ApiError) => handleError(err, showToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "releases"],
      })
    },
  })
  const githubMutation = useMutation({
    mutationFn: (releaseName: string) =>
      ReleasesService.createReleaseGithubRelease({
        ownerName,
        projectName,
        releaseName,
      }),
    onSuccess: (data) => {
      toast({
        title: data.created
          ? "Released to GitHub"
          : "GitHub release already exists",
        description: (
          <Link href={data.url} isExternal textDecoration="underline">
            View the release on GitHub
          </Link>
        ),
        status: "success",
        isClosable: true,
        position: "bottom-right",
      })
    },
    onError: (err: ApiError) => handleError(err, showToast),
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "releases"],
      })
    },
  })
  const filterLower = (filter ?? "").trim().toLowerCase()
  const releases = (releasesQuery.data ?? []).filter(
    (r) =>
      !filterLower ||
      `${r.name} ${r.path ?? ""} ${r.publisher ?? ""}`
        .toLowerCase()
        .includes(filterLower),
  )
  const sortedReleases = [...releases].sort((a, b) => {
    const av = sortValue(a, sort.key)
    const bv = sortValue(b, sort.key)
    let cmp: number
    if (typeof av === "number" && typeof bv === "number") {
      cmp = av - bv
    } else {
      cmp = String(av).localeCompare(String(bv))
    }
    return sort.dir === "asc" ? cmp : -cmp
  })

  const SortableTh = ({
    label,
    sortKey,
    isNumeric,
  }: {
    label: string
    sortKey: SortKey
    isNumeric?: boolean
  }) => {
    const active = sort.key === sortKey
    const icon = !active ? FaSort : sort.dir === "asc" ? FaSortUp : FaSortDown
    return (
      <Th
        isNumeric={isNumeric}
        cursor="pointer"
        userSelect="none"
        onClick={() => toggleSort(sortKey)}
        _hover={{ color: "blue.500" }}
      >
        <HStack
          spacing={1}
          display="inline-flex"
          justify={isNumeric ? "flex-end" : "flex-start"}
        >
          <Text as="span">{label}</Text>
          <Icon
            as={icon}
            fontSize="2xs"
            color={active ? "blue.500" : "gray.400"}
          />
        </HStack>
      </Th>
    )
  }

  return (
    <Box>
      <Flex align="center" mb={4}>
        <Heading size="md">Releases</Heading>
        {userHasWriteAccess && (
          <>
            <Button
              variant="primary"
              size="sm"
              ml={4}
              leftIcon={<Icon as={FaPlus} />}
              onClick={openNewRelease}
            >
              New release
            </Button>
            <Button
              size="sm"
              ml={2}
              leftIcon={<Icon as={FaGithub} />}
              onClick={() => importMutation.mutate()}
              isLoading={importMutation.isPending}
            >
              Import from GitHub
            </Button>
          </>
        )}
      </Flex>
      {releasesQuery.isPending ? (
        <LoadingSpinner height="200px" />
      ) : releasesQuery.isError ? (
        <Flex align="center" justify="center" h="160px" color="red.500">
          <Text>Failed to load releases. Try refreshing.</Text>
        </Flex>
      ) : releases.length === 0 ? (
        <Flex align="center" justify="center" h="160px" color="gray.500">
          <Text>
            No releases yet.
            {userHasWriteAccess
              ? " Create one to share a versioned artifact for review."
              : ""}
          </Text>
        </Flex>
      ) : (
        <Box overflowX="auto">
          <Table size="sm">
            <Thead>
              <Tr>
                <SortableTh label="Name" sortKey="name" />
                <SortableTh label="Path" sortKey="path" />
                <SortableTh label="Version" sortKey="version" />
                <SortableTh label="Date" sortKey="date" />
                <SortableTh label="Views" sortKey="views" isNumeric />
                <SortableTh label="Comments" sortKey="comments" isNumeric />
                <Th>Location</Th>
                <Th>GitHub</Th>
                {userHasWriteAccess && <Th />}
              </Tr>
            </Thead>
            <Tbody>
              {sortedReleases.map((r) => (
                <Tr key={`${r.source}-${r.name}`}>
                  <Td fontWeight="semibold">
                    <Link
                      as={RouterLink}
                      to={
                        releasePagePath(ownerName, projectName, r.name) as any
                      }
                      color="blue.500"
                    >
                      {r.name}
                    </Link>
                  </Td>
                  <Td>
                    <Link
                      as={RouterLink}
                      to={
                        releasePagePath(ownerName, projectName, r.name) as any
                      }
                      color="blue.500"
                    >
                      <Text noOfLines={1} maxW="180px">
                        {r.path || "."}
                      </Text>
                    </Link>
                  </Td>
                  <Td>
                    <Code fontSize="xs">
                      {r.git_ref ?? r.git_rev_abbrev ?? "—"}
                    </Code>
                  </Td>
                  <Td whiteSpace="nowrap">{formatReleaseDate(r.date)}</Td>
                  <Td isNumeric>{r.view_count != null ? r.view_count : "—"}</Td>
                  <Td isNumeric>
                    {r.comment_count != null ? r.comment_count : "—"}
                  </Td>
                  <Td>
                    {(() => {
                      const dest = releaseLocation(r)
                      if (dest.internal)
                        return (
                          <Tooltip label="Hosted on Calkit for review">
                            <Badge colorScheme="blue" fontSize="xs">
                              Internal
                            </Badge>
                          </Tooltip>
                        )
                      return (
                        <HStack spacing={1}>
                          <Badge colorScheme="purple" fontSize="xs">
                            {dest.label}
                          </Badge>
                          {dest.href && (
                            <Link
                              href={dest.href}
                              isExternal
                              color="blue.500"
                              fontSize="sm"
                              display="inline-flex"
                              alignItems="center"
                              gap={1}
                            >
                              {r.doi ?? "Link"}
                              <Icon as={FiExternalLink} />
                            </Link>
                          )}
                        </HStack>
                      )
                    })()}
                  </Td>
                  <Td>
                    {(() => {
                      const githubUrl =
                        r.github_release_url ??
                        (r.publisher === "github" ? r.url : null)
                      if (githubUrl)
                        return (
                          <Tooltip label="View release on GitHub">
                            <Link
                              href={githubUrl}
                              isExternal
                              color="green.500"
                              display="inline-flex"
                              alignItems="center"
                              gap={1}
                            >
                              <Icon as={FaCheck} />
                              <Icon as={FiExternalLink} />
                            </Link>
                          </Tooltip>
                        )
                      if (r.source === "cloud" && userHasWriteAccess)
                        return (
                          <Tooltip label="Release to GitHub">
                            <IconButton
                              aria-label="Release to GitHub"
                              icon={<FaGithub />}
                              size="xs"
                              variant="ghost"
                              isLoading={
                                githubMutation.isPending &&
                                githubMutation.variables === r.name
                              }
                              onClick={() => githubMutation.mutate(r.name)}
                            />
                          </Tooltip>
                        )
                      return (
                        <Text color="gray.400" fontSize="sm">
                          —
                        </Text>
                      )
                    })()}
                  </Td>
                  {userHasWriteAccess && (
                    <Td>
                      {r.source === "cloud" && (
                        <HStack spacing={0} justify="flex-end">
                          <Tooltip
                            label={
                              r.share_count
                                ? `Share (${r.share_count} active)`
                                : "Share"
                            }
                          >
                            <IconButton
                              aria-label="Share release"
                              icon={<FiShare2 />}
                              size="xs"
                              variant="ghost"
                              onClick={() => openShare(r)}
                            />
                          </Tooltip>
                          <Tooltip label="Delete">
                            <IconButton
                              aria-label="Delete release"
                              icon={<FaTrash />}
                              size="xs"
                              variant="ghost"
                              colorScheme="red"
                              onClick={() => {
                                setToDelete(r)
                                confirmDelete.onOpen()
                              }}
                            />
                          </Tooltip>
                        </HStack>
                      )}
                    </Td>
                  )}
                </Tr>
              ))}
            </Tbody>
          </Table>
        </Box>
      )}
      <NewRelease
        isOpen={newReleaseIsOpen}
        onClose={closeNewRelease}
        ownerName={ownerName}
        projectName={projectName}
      />
      <Modal
        isOpen={confirmDelete.isOpen}
        onClose={confirmDelete.onClose}
        isCentered
        size={{ base: "sm", md: "md" }}
      >
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Delete release</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            Delete release <Code>{toDelete?.name}</Code>? Its share links and
            comments are removed, and it's dropped from <Code>calkit.yaml</Code>
            . This cannot be undone.
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="danger"
              isLoading={deleteMutation.isPending}
              onClick={() => toDelete && deleteMutation.mutate(toDelete.name)}
            >
              Delete
            </Button>
            <Button onClick={confirmDelete.onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      {active && (
        <ShareDialog
          isOpen={shareModal.isOpen}
          onClose={shareModal.onClose}
          ownerName={ownerName}
          projectName={projectName}
          releaseName={active.name}
        />
      )}
    </Box>
  )
}

export default ReleasesTable
