import {
  Badge,
  Box,
  Code,
  Flex,
  Heading,
  Link,
  Skeleton,
  Text,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { useEffect, useMemo } from "react"

import { ProjectsService } from "../../client"

interface Commit {
  hash: string
  short_hash: string
  message: string
  summary?: string
  author: string
  timestamp: string
}

const LAST_SEEN_PREFIX = "last_seen_commit:"

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
 * How many of the listed commits landed after the one this browser last
 * saw. Unknown (first visit, or history rewritten) counts as none, since
 * "everything is new" on a first visit is noise rather than news.
 */
export function countNewCommits(
  commits: { hash: string }[],
  lastSeen: string | null,
): number {
  if (!lastSeen) return 0
  const index = commits.findIndex((c) => c.hash === lastSeen)
  return index === -1 ? 0 : index
}

interface RecentChangesProps {
  accountName: string
  projectName: string
  limit?: number
}

/**
 * The last few commits, with a count of what's new since the last visit.
 *
 * A project moves between sessions: a collaborator pushed, a pipeline run
 * landed from the CLI, a paper edit synced from Overleaf. This is the
 * "what changed while I was away" a returning user would otherwise go
 * looking for; the History page has the full list and the diffs.
 */
const RecentChanges = ({
  accountName,
  projectName,
  limit = 5,
}: RecentChangesProps) => {
  const storageKey = `${LAST_SEEN_PREFIX}${accountName}/${projectName}`
  const historyQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "history", limit],
    queryFn: () =>
      ProjectsService.getProjectHistory({
        owner_name: accountName,
        project_name: projectName,
        limit,
      }).then((response) => response.data as unknown as Commit[]),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const commits = historyQuery.data ?? []
  // Read once per load rather than on every render, so the badge holds
  // still while the effect below records the newest hash as seen.
  const lastSeen = useMemo(() => {
    try {
      return localStorage.getItem(storageKey)
    } catch {
      return null
    }
  }, [storageKey])
  const newCount = countNewCommits(commits, lastSeen)
  useEffect(() => {
    if (!commits.length) return
    try {
      localStorage.setItem(storageKey, commits[0].hash)
    } catch {
      // Storage unavailable; the badge just won't appear next time.
    }
  }, [commits, storageKey])
  if (historyQuery.isError) return null
  const historyTo = `/${accountName}/${projectName}/history`
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
      {historyQuery.isPending ? (
        <>
          <Skeleton height="14px" mb={2} />
          <Skeleton height="14px" mb={2} />
          <Skeleton height="14px" />
        </>
      ) : commits.length === 0 ? (
        <Text fontSize="sm" color="ui.dim">
          No commits yet.
        </Text>
      ) : (
        <>
          {commits.map((commit, index) => {
            const summary = commit.summary ?? commit.message.split("\n")[0]
            const isNew = index < newCount
            return (
              <Box
                key={commit.hash}
                py={1.5}
                borderBottomWidth={index < commits.length - 1 ? 1 : 0}
                fontSize="sm"
              >
                <Link
                  as={RouterLink}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  to={historyTo as any}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  search={{ commit: commit.hash } as any}
                  display="block"
                  noOfLines={1}
                  fontWeight={isNew ? "semibold" : "normal"}
                  title={summary}
                >
                  {summary}
                </Link>
                <Text color="ui.dim" fontSize="xs">
                  <Code fontSize="xs" mr={1}>
                    {commit.short_hash}
                  </Code>
                  {commit.author}, {timeAgo(commit.timestamp)}
                </Text>
              </Box>
            )
          })}
          <Link
            as={RouterLink}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            to={historyTo as any}
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
