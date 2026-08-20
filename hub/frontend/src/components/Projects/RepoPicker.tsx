import {
  Box,
  Input,
  List,
  ListItem,
  Spinner,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useState } from "react"

export interface GitHubRepo {
  full_name: string
  private?: boolean
  description?: string | null
}

/**
 * Rank repos against what's been typed, subsequence-style.
 *
 * Typing "navwake" should find "navier-wake-analysis": people remember
 * fragments of a repo name, not its exact spelling, and a substring match
 * makes them get the gaps right. Matches earlier in the name and closer
 * together score higher, so the obvious candidate lands at the top.
 *
 * Exported for its unit tests, which is where the ranking is pinned down.
 */
export function scoreRepo(name: string, query: string): number | null {
  const target = name.toLowerCase()
  const q = query.toLowerCase().replace(/\s+/g, "")
  if (!q) return 0
  let score = 0
  let index = -1
  for (const char of q) {
    const next = target.indexOf(char, index + 1)
    if (next === -1) return null
    // A jump means characters the user didn't type; the further the jump,
    // the weaker the match. Consecutive characters cost nothing.
    score += next - index - 1
    index = next
  }
  // Prefer matches that start earlier, so "wake" ranks wake-study above
  // turbine-wake when both match.
  return score + target.indexOf(q[0])
}

export function filterRepos(
  repos: GitHubRepo[],
  query: string,
  limit = 8,
): GitHubRepo[] {
  const scored: { repo: GitHubRepo; score: number }[] = []
  for (const repo of repos) {
    const score = scoreRepo(repo.full_name, query)
    if (score !== null) {
      scored.push({ repo, score })
    }
  }
  scored.sort((a, b) => a.score - b.score)
  return scored.slice(0, limit).map((s) => s.repo)
}

interface RepoPickerProps {
  repos: GitHubRepo[]
  isLoading?: boolean
  onSelect: (repo: GitHubRepo) => void
}

/**
 * Type-to-filter list of the user's GitHub repos.
 *
 * A plain select is unusable past a few dozen repos, which is most people
 * with an account of any age.
 */
const RepoPicker = ({ repos, isLoading, onSelect }: RepoPickerProps) => {
  const [query, setQuery] = useState("")
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const listBg = useColorModeValue("white", "gray.700")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const hoverBg = useColorModeValue("gray.100", "gray.600")
  const matches = filterRepos(repos, query)
  const choose = (repo: GitHubRepo) => {
    setQuery(repo.full_name)
    setOpen(false)
    onSelect(repo)
  }
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || !matches.length) return
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setHighlighted((h) => (h + 1) % matches.length)
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setHighlighted((h) => (h - 1 + matches.length) % matches.length)
    } else if (e.key === "Enter") {
      // The picker is inside a form, so Enter must not submit it while a
      // suggestion is being chosen.
      e.preventDefault()
      choose(matches[Math.min(highlighted, matches.length - 1)])
    } else if (e.key === "Escape") {
      setOpen(false)
    }
  }
  return (
    <Box position="relative">
      <Input
        id="existing_repo"
        value={query}
        placeholder={isLoading ? "Loading your repos…" : "Start typing…"}
        autoComplete="off"
        onChange={(e) => {
          setQuery(e.target.value)
          setHighlighted(0)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        // Deferred so a click on a suggestion lands before the list closes.
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {isLoading ? (
        <Spinner
          size="sm"
          position="absolute"
          right={3}
          top="50%"
          transform="translateY(-50%)"
        />
      ) : null}
      {open && matches.length > 0 ? (
        <List
          position="absolute"
          zIndex={10}
          mt={1}
          width="100%"
          bg={listBg}
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="md"
          boxShadow="md"
          maxH="240px"
          overflowY="auto"
        >
          {matches.map((repo, index) => (
            <ListItem
              key={repo.full_name}
              px={3}
              py={2}
              cursor="pointer"
              bg={index === highlighted ? hoverBg : undefined}
              _hover={{ bg: hoverBg }}
              onMouseEnter={() => setHighlighted(index)}
              onMouseDown={(e) => {
                // mousedown, not click: blur would close the list first.
                e.preventDefault()
                choose(repo)
              }}
            >
              <Text fontSize="sm">
                {repo.full_name}
                {repo.private ? (
                  <Text as="span" color="ui.dim" fontSize="xs" ml={2}>
                    private
                  </Text>
                ) : null}
              </Text>
            </ListItem>
          ))}
        </List>
      ) : null}
    </Box>
  )
}

export default RepoPicker
