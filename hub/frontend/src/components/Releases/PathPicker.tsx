import {
  Button,
  Code,
  Flex,
  Icon,
  IconButton,
  Input,
  InputGroup,
  InputRightElement,
  Popover,
  PopoverArrow,
  PopoverBody,
  PopoverContent,
  PopoverFooter,
  PopoverHeader,
  PopoverTrigger,
  Spinner,
  Text,
  useDisclosure,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import {
  FiChevronDown,
  FiChevronRight,
  FiFile,
  FiFolder,
  FiX,
} from "react-icons/fi"

import { ProjectsService } from "../../client"

interface PathPickerProps {
  ownerName: string
  projectName: string
  // Currently selected path; empty string means the whole project.
  value: string
  onChange: (path: string) => void
  // Whether a subfolder can be selected. Off by default: releasing a folder
  // implies zipping it (and DVC storage for internal releases), which the
  // backend doesn't do yet, so folders are browsable but not selectable.
  allowFolders?: boolean
}

// Parent directory of a path, e.g. "paper/figs/a.png" -> "paper/figs".
const dirname = (path: string) => {
  const i = path.lastIndexOf("/")
  return i === -1 ? "" : path.slice(0, i)
}

// Subsequence fuzzy score: returns null if every char of `query` doesn't
// appear in order in `target`, else a score that rewards contiguous runs,
// earlier matches, and matches in the file name over the directory.
const fuzzyScore = (query: string, target: string): number | null => {
  const q = query.toLowerCase()
  const t = target.toLowerCase()
  const nameStart = t.lastIndexOf("/") + 1
  let qi = 0
  let score = 0
  let prevIdx = -1
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] !== q[qi]) continue
    const contiguous = ti === prevIdx + 1
    score += 10 + (contiguous ? 8 : 0) + (ti >= nameStart ? 4 : 0) - ti * 0.05
    prevIdx = ti
    qi++
  }
  return qi === q.length ? score : null
}

const MAX_RESULTS = 50

// Browsable + searchable selector for a file or folder within the project
// tree. Type to fuzzy search across all paths, or browse the tree. An empty
// selection is the whole project.
const PathPicker = ({
  ownerName,
  projectName,
  value,
  onChange,
  allowFolders = false,
}: PathPickerProps) => {
  const { isOpen, onOpen, onClose } = useDisclosure()
  // Directory currently being browsed; opens at the parent of the selection.
  const [dir, setDir] = useState("")
  // Fuzzy search text; when non-empty, results replace the browse tree.
  const [query, setQuery] = useState("")
  const handleOpen = () => {
    setDir(dirname(value))
    setQuery("")
    onOpen()
  }
  const { data, isPending, isError } = useQuery({
    queryKey: ["projects", ownerName, projectName, "contents", dir],
    queryFn: () =>
      ProjectsService.getProjectContents({
        ownerName,
        projectName,
        path: dir || undefined,
      }),
    enabled: isOpen,
    retry: false,
  })
  // All file paths, loaded once per open, for fuzzy search.
  const pathsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "content-paths"],
    queryFn: () =>
      ProjectsService.getProjectContentPaths({ ownerName, projectName }),
    enabled: isOpen,
    retry: false,
  })
  const items = (data?.dir_items ?? []).slice().sort((a, b) => {
    if (a.type === b.type) return a.name.localeCompare(b.name)
    return a.type === "dir" ? -1 : 1
  })
  const segments = dir ? dir.split("/") : []
  const trimmedQuery = query.trim()
  const matches = useMemo(() => {
    if (!trimmedQuery) return []
    const scored: Array<[number, string]> = []
    for (const p of pathsQuery.data ?? []) {
      const s = fuzzyScore(trimmedQuery, p)
      if (s !== null) scored.push([s, p])
    }
    scored.sort((a, b) => b[0] - a[0])
    return scored.slice(0, MAX_RESULTS).map(([, p]) => p)
  }, [trimmedQuery, pathsQuery.data])
  const select = (path: string) => {
    onChange(path)
    onClose()
  }

  return (
    <Popover
      isOpen={isOpen}
      onOpen={handleOpen}
      onClose={onClose}
      placement="bottom-start"
      matchWidth
    >
      <PopoverTrigger>
        <Button
          variant="outline"
          w="full"
          justifyContent="space-between"
          rightIcon={<FiChevronDown />}
          fontWeight="normal"
        >
          {value ? (
            <Code bg="transparent" px={0}>
              {value}
            </Code>
          ) : (
            <Text color="gray.500">Whole project</Text>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent w="full">
        <PopoverArrow />
        <PopoverHeader>
          <InputGroup size="sm" mb={trimmedQuery ? 0 : 2}>
            <Input
              autoFocus
              placeholder="Search or type a path…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== "Enter" || !trimmedQuery) return
                e.preventDefault()
                select(matches[0] ?? trimmedQuery)
              }}
            />
            {query && (
              <InputRightElement>
                <IconButton
                  aria-label="Clear search"
                  icon={<FiX />}
                  size="xs"
                  variant="ghost"
                  onClick={() => setQuery("")}
                />
              </InputRightElement>
            )}
          </InputGroup>
          {!trimmedQuery && (
            <Flex align="center" wrap="wrap" fontSize="sm">
              <Button
                variant="link"
                size="sm"
                onClick={() => setDir("")}
                fontWeight={dir ? "normal" : "semibold"}
              >
                Project root
              </Button>
              {segments.map((seg, i) => (
                <Flex align="center" key={segments.slice(0, i + 1).join("/")}>
                  <Icon as={FiChevronRight} mx={1} color="gray.400" />
                  <Button
                    variant="link"
                    size="sm"
                    fontWeight={
                      i === segments.length - 1 ? "semibold" : "normal"
                    }
                    onClick={() => setDir(segments.slice(0, i + 1).join("/"))}
                  >
                    {seg}
                  </Button>
                </Flex>
              ))}
            </Flex>
          )}
        </PopoverHeader>
        <PopoverBody maxH="240px" overflowY="auto" px={0}>
          {trimmedQuery ? (
            <>
              {pathsQuery.isPending ? (
                <Flex justify="center" py={4}>
                  <Spinner size="sm" />
                </Flex>
              ) : pathsQuery.isError ? (
                <Text px={3} py={2} fontSize="sm" color="red.500">
                  Couldn't load the file list.
                </Text>
              ) : (
                matches.map((path) => (
                  <Flex
                    key={path}
                    align="center"
                    px={3}
                    py={1.5}
                    cursor="pointer"
                    _hover={{ bg: "gray.100", _dark: { bg: "gray.700" } }}
                    onClick={() => select(path)}
                  >
                    <Icon as={FiFile} mr={2} color="gray.400" />
                    <Text fontSize="sm" flex={1} noOfLines={1}>
                      {path}
                    </Text>
                  </Flex>
                ))
              )}
              {!pathsQuery.isPending &&
                !pathsQuery.isError &&
                !matches.includes(trimmedQuery) && (
                  <Flex
                    align="center"
                    px={3}
                    py={1.5}
                    cursor="pointer"
                    _hover={{ bg: "gray.100", _dark: { bg: "gray.700" } }}
                    onClick={() => select(trimmedQuery)}
                  >
                    <Icon as={FiFile} mr={2} color="gray.400" />
                    <Text fontSize="sm">
                      Use{" "}
                      <Code bg="transparent" px={0}>
                        {trimmedQuery}
                      </Code>
                    </Text>
                  </Flex>
                )}
            </>
          ) : isPending ? (
            <Flex justify="center" py={4}>
              <Spinner size="sm" />
            </Flex>
          ) : isError ? (
            <Text px={3} py={2} fontSize="sm" color="red.500">
              Couldn't load this folder.
            </Text>
          ) : items.length === 0 ? (
            <Text px={3} py={2} fontSize="sm" color="gray.500">
              Empty folder.
            </Text>
          ) : (
            items.map((item) => (
              <Flex
                key={item.path}
                align="center"
                px={3}
                py={1.5}
                cursor="pointer"
                _hover={{ bg: "gray.100", _dark: { bg: "gray.700" } }}
                onClick={() =>
                  item.type === "dir" ? setDir(item.path) : select(item.path)
                }
              >
                <Icon
                  as={item.type === "dir" ? FiFolder : FiFile}
                  mr={2}
                  color={item.type === "dir" ? "blue.400" : "gray.400"}
                />
                <Text fontSize="sm" flex={1} noOfLines={1}>
                  {item.name}
                </Text>
                {item.type === "dir" && (
                  <Icon as={FiChevronRight} color="gray.400" />
                )}
              </Flex>
            ))
          )}
        </PopoverBody>
        <PopoverFooter display="flex" gap={2}>
          <Button size="sm" variant="outline" onClick={() => select("")}>
            Whole project
          </Button>
          {allowFolders && (
            <Button
              size="sm"
              variant="primary"
              onClick={() => select(dir)}
              isDisabled={!dir}
            >
              Use this folder
            </Button>
          )}
        </PopoverFooter>
      </PopoverContent>
    </Popover>
  )
}

export default PathPicker
