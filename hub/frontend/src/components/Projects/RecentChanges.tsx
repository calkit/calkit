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
  gitRepoUrl?: string | null
  limit?: number
}

/**
 * The last few commits, with a count of what's new since the last visit.
 *
 * A project moves between sessions: a collaborator pushed, a pipeline run
 * landed from the CLI, a paper edit synced from Overleaf. This is the
 * "what changed while I was away" a returning user otherwise reconstructs
 * from the GitHub commit list.
 */
const RecentChanges = ({
  accountName,
  projectName,
  gitRepoUrl,
  limit = 6,
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
  return (
    <Box>
      <Flex align="center" gap={2} mb={2}>
        <Heading size="md">Recent changes</Heading>
        {newCount > 0 ? (
          <Badge colorScheme="teal" borderRadius="full" px={2}>
            {newCount} since your last visit
          </Badge>
        ) : null}
      </Flex>
      {historyQuery.isPending ? (
        <>
          <Skeleton height="16px" mb={2} />
          <Skeleton height="16px" mb={2} />
          <Skeleton height="16px" />
        </>
      ) : commits.length === 0 ? (
        <Text fontSize="sm" color="ui.dim">
          No commits yet.
        </Text>
      ) : (
        commits.map((commit, index) => {
          const summary = commit.summary ?? commit.message.split("\n")[0]
          const isNew = index < newCount
          return (
            <Flex
              key={commit.hash}
              gap={3}
              py={1.5}
              borderBottomWidth={index < commits.length - 1 ? 1 : 0}
              fontSize="sm"
              align="baseline"
            >
              {gitRepoUrl ? (
                <Link
                  href={`${gitRepoUrl}/commit/${commit.hash}`}
                  isExternal
                  flexShrink={0}
                >
                  <Code fontSize="xs">{commit.short_hash}</Code>
                </Link>
              ) : (
                <Code fontSize="xs" flexShrink={0}>
                  {commit.short_hash}
                </Code>
              )}
              <Text
                flex={1}
                noOfLines={1}
                fontWeight={isNew ? "semibold" : "normal"}
              >
                {summary}
              </Text>
              <Text color="ui.dim" fontSize="xs" flexShrink={0}>
                {commit.author}, {timeAgo(commit.timestamp)}
              </Text>
            </Flex>
          )
        })
      )}
    </Box>
  )
}

export default RecentChanges
