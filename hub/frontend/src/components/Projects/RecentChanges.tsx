import {
  Badge,
  Box,
  Flex,
  Heading,
  Icon,
  Link,
  Skeleton,
  Text,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { useEffect, useMemo } from "react"
import type { IconType } from "react-icons"
import {
  FiCheckSquare,
  FiFolder,
  FiGitBranch,
  FiMessageSquare,
  FiTag,
  FiUsers,
} from "react-icons/fi"

import { type ProjectActivityItem, ProjectsService } from "../../client"

const LAST_SEEN_PREFIX = "last_seen_activity:"

// The same icons the sidebar uses for the page each kind of item links to
const KIND_ICONS: Record<ProjectActivityItem["kind"], IconType> = {
  commit: FiGitBranch,
  "dvc-push": FiFolder,
  collaborator: FiUsers,
  todo: FiCheckSquare,
  comment: FiMessageSquare,
  release: FiTag,
}

const KIND_LABELS: Record<ProjectActivityItem["kind"], string> = {
  commit: "Commit",
  "dvc-push": "Data push",
  collaborator: "Collaborator",
  todo: "To-do",
  comment: "Comment",
  release: "Release",
}

/** "3 hours ago", without pulling in a date library for one label. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000)
  // Largest unit that fits, rounded, so two years minus a leap day still
  // reads as two years rather than one.
  const units: [number, string][] = [
    [31557600, "year"],
    [2629800, "month"],
    [604800, "week"],
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
  ]
  for (const [size, label] of units) {
    if (seconds >= size) {
      const n = Math.round(seconds / size)
      return `${n} ${label}${n === 1 ? "" : "s"} ago`
    }
  }
  return "just now"
}

/**
 * How many of the listed items happened after the one this browser last
 * saw. Unknown (first visit, or the item has dropped out of the window)
 * counts as none, since "everything is new" on a first visit is noise
 * rather than news.
 */
export function countNewItems(
  items: { id: string }[],
  lastSeen: string | null,
): number {
  if (!lastSeen) return 0
  const index = items.findIndex((item) => item.id === lastSeen)
  return index === -1 ? 0 : index
}

/**
 * Split an activity link like `history?commit=abc` into the route path and
 * its search params, since the router wants them separately.
 */
export function splitActivityLink(link: string): {
  path: string
  search: Record<string, string>
} {
  const [path, query] = link.split("?", 2)
  const search: Record<string, string> = {}
  if (query) {
    for (const [key, value] of new URLSearchParams(query)) {
      search[key] = value
    }
  }
  return { path, search }
}

interface RecentChangesProps {
  accountName: string
  projectName: string
  limit?: number
}

/**
 * The last few things that happened, with a count of what's new since the
 * last visit.
 *
 * A project moves between sessions: a collaborator pushed, a pipeline run
 * landed from the CLI, a paper edit synced from Overleaf, a release was
 * cut. This is the "what changed while I was away" a returning user would
 * otherwise go looking for; the History page has the full commit list and
 * the diffs.
 */
const RecentChanges = ({
  accountName,
  projectName,
  limit = 5,
}: RecentChangesProps) => {
  const storageKey = `${LAST_SEEN_PREFIX}${accountName}/${projectName}`
  const activityQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "activity", limit],
    queryFn: () =>
      ProjectsService.getProjectActivity({
        owner_name: accountName,
        project_name: projectName,
        limit,
      }).then((response) => response.data),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const items = activityQuery.data ?? []
  // Read once per load rather than on every render, so the badge holds
  // still while the effect below records the newest item as seen.
  const lastSeen = useMemo(() => {
    try {
      return localStorage.getItem(storageKey)
    } catch {
      return null
    }
  }, [storageKey])
  const newCount = countNewItems(items, lastSeen)
  useEffect(() => {
    if (!items.length) return
    try {
      localStorage.setItem(storageKey, items[0].id)
    } catch {
      // Storage unavailable; the badge just won't appear next time.
    }
  }, [items, storageKey])
  if (activityQuery.isError) return null
  const projectTo = `/${accountName}/${projectName}`
  return (
    <Box>
      <Flex align="center" gap={2} mb={2} wrap="wrap">
        <Heading size="md">Recent changes</Heading>
        {newCount > 0 ? (
          <Badge colorScheme="teal" borderRadius="full" px={2}>
            {newCount} new
          </Badge>
        ) : null}
      </Flex>
      {activityQuery.isPending ? (
        <>
          <Skeleton height="14px" mb={2} />
          <Skeleton height="14px" mb={2} />
          <Skeleton height="14px" />
        </>
      ) : items.length === 0 ? (
        <Text fontSize="sm" color="ui.dim">
          Nothing yet.
        </Text>
      ) : (
        <>
          {items.map((item, index) => {
            const isNew = index < newCount
            const target = item.link ? splitActivityLink(item.link) : null
            return (
              <Flex
                key={item.id}
                py={1.5}
                gap={2}
                align="flex-start"
                borderBottomWidth={index < items.length - 1 ? 1 : 0}
                fontSize="sm"
              >
                <Icon
                  as={KIND_ICONS[item.kind]}
                  color="ui.dim"
                  boxSize={3.5}
                  mt={1}
                  flexShrink={0}
                  title={KIND_LABELS[item.kind]}
                  aria-label={KIND_LABELS[item.kind]}
                />
                <Box minW={0}>
                  {target ? (
                    <Link
                      as={RouterLink}
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      to={`${projectTo}/${target.path}` as any}
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      search={target.search as any}
                      display="block"
                      noOfLines={1}
                      fontWeight={isNew ? "semibold" : "normal"}
                      title={item.title}
                    >
                      {item.title}
                    </Link>
                  ) : (
                    <Text
                      noOfLines={1}
                      fontWeight={isNew ? "semibold" : "normal"}
                      title={item.title}
                    >
                      {item.title}
                    </Text>
                  )}
                  <Text color="ui.dim" fontSize="xs">
                    {KIND_LABELS[item.kind]}
                    {item.actor ? ` by ${item.actor}` : ""},{" "}
                    {timeAgo(item.timestamp)}
                  </Text>
                </Box>
              </Flex>
            )
          })}
          <Link
            as={RouterLink}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            to={`${projectTo}/history` as any}
            fontSize="sm"
            display="inline-block"
            mt={2}
          >
            View all changes →
          </Link>
        </>
      )}
    </Box>
  )
}

export default RecentChanges
