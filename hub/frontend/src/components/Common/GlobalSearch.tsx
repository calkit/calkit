import {
  Box,
  Flex,
  Icon,
  IconButton,
  Input,
  InputGroup,
  InputLeftElement,
  InputRightElement,
  Spinner,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { CloseIcon } from "@chakra-ui/icons"
import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { FaSearch, FaFlask, FaUsers, FaDatabase } from "react-icons/fa"

import { MiscService, type SearchResults } from "../../client"

type SearchResultItem = SearchResults["results"][number]

const KIND_ICON = {
  project: FaFlask,
  org: FaUsers,
  dataset: FaDatabase,
}

const KIND_LABEL = {
  project: "Projects",
  org: "Orgs",
  dataset: "Datasets",
}

function useDebounce(value: string, delay: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export default function GlobalSearch() {
  const [query, setQuery] = useState("")
  const [isOpen, setIsOpen] = useState(false)
  const [highlightedIndex, setHighlightedIndex] = useState(0)
  const debouncedQuery = useDebounce(query, 300)
  const navigate = useNavigate()
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const itemRefs = useRef<(HTMLDivElement | null)[]>([])

  // Focus on "/" keypress (like GitHub), unless already in an input
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "/") return
      const tag = (e.target as HTMLElement).tagName
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        (e.target as HTMLElement).isContentEditable
      )
        return
      e.preventDefault()
      inputRef.current?.focus()
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [])

  const bg = useColorModeValue("white", "gray.800")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const hoverBg = useColorModeValue("gray.50", "gray.700")
  const labelColor = useColorModeValue("gray.500", "gray.400")
  const inputBg = useColorModeValue("white", "gray.700")

  const { data, isFetching, isSuccess } = useQuery({
    queryKey: ["global-search", debouncedQuery],
    queryFn: () => MiscService.globalSearch({ q: debouncedQuery }),
    enabled: debouncedQuery.length >= 2,
    staleTime: 30_000,
  })

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [])

  const results = data?.results ?? []
  const kinds: Array<"project" | "org" | "dataset"> = [
    "project",
    "org",
    "dataset",
  ]

  // Flat ordered list matching the rendered order (grouped by kind)
  const flatResults = kinds.flatMap((kind) =>
    results.filter((r) => r.kind === kind),
  )

  // Reset highlight to first item whenever results change
  useEffect(() => {
    setHighlightedIndex(0)
  }, [flatResults.length, debouncedQuery])

  const getPath = (item: SearchResultItem): string => {
    if (item.kind === "project") {
      return `/${item.owner_name}/${item.name}`
    }
    if (item.kind === "org") {
      return `/${item.name}`
    }
    // dataset: navigate to the project's datasets tab
    return `/${item.owner_name}/${item.project_name}/datasets`
  }

  const handleSelect = (item: SearchResultItem) => {
    setIsOpen(false)
    setQuery("")
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    navigate({ to: getPath(item) as any })
  }

  const showDropdown =
    isOpen && debouncedQuery.length >= 2 && (isFetching || isSuccess)

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setQuery("")
      setIsOpen(false)
      inputRef.current?.blur()
      return
    }
    if (!showDropdown) return
    if (e.key === "ArrowDown") {
      e.preventDefault()
      const next = Math.min(highlightedIndex + 1, flatResults.length - 1)
      setHighlightedIndex(next)
      itemRefs.current[next]?.scrollIntoView({ block: "nearest" })
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      const prev = Math.max(highlightedIndex - 1, 0)
      setHighlightedIndex(prev)
      itemRefs.current[prev]?.scrollIntoView({ block: "nearest" })
    } else if (e.key === "Enter") {
      e.preventDefault()
      const item = flatResults[highlightedIndex]
      if (item) handleSelect(item)
    }
  }

  return (
    <Box ref={containerRef} position="relative" w="220px">
      <InputGroup size="sm">
        <InputLeftElement pointerEvents="none">
          {isFetching ? (
            <Spinner size="xs" color="gray.400" />
          ) : (
            <Icon as={FaSearch} color="gray.400" fontSize="xs" />
          )}
        </InputLeftElement>
        <Input
          ref={inputRef}
          placeholder="Search…"
          value={query}
          bg={inputBg}
          borderColor={borderColor}
          onKeyDown={handleKeyDown}
          onChange={(e) => {
            setQuery(e.target.value)
            setIsOpen(true)
          }}
          onFocus={() => setIsOpen(true)}
          pr={query ? 8 : undefined}
        />
        {query && (
          <InputRightElement>
            <IconButton
              aria-label="Clear"
              icon={<CloseIcon boxSize="8px" />}
              size="xs"
              variant="ghost"
              onClick={() => {
                setQuery("")
                setIsOpen(false)
              }}
            />
          </InputRightElement>
        )}
      </InputGroup>

      {showDropdown && (
        <Box
          position="absolute"
          top="calc(100% + 4px)"
          left={0}
          right={0}
          bg={bg}
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="md"
          boxShadow="md"
          zIndex={2000}
          maxH="360px"
          overflowY="auto"
          minW="260px"
        >
          {results.length === 0 && !isFetching && (
            <Text p={3} fontSize="sm" color={labelColor}>
              No results found
            </Text>
          )}
          {(() => {
            let flatIdx = 0
            return kinds.map((kind) => {
              const group = results.filter((r) => r.kind === kind)
              if (group.length === 0) return null
              return (
                <Box key={kind}>
                  <Text
                    px={3}
                    pt={2}
                    pb={1}
                    fontSize="xs"
                    fontWeight="bold"
                    color={labelColor}
                    textTransform="uppercase"
                    letterSpacing="wide"
                  >
                    {KIND_LABEL[kind]}
                  </Text>
                  {group.map((item) => {
                    const idx = flatIdx++
                    const isHighlighted = idx === highlightedIndex
                    return (
                      <Flex
                        key={`${item.kind}-${item.owner_name}-${item.name}`}
                        ref={(el) => {
                          itemRefs.current[idx] = el
                        }}
                        px={3}
                        py={2}
                        cursor="pointer"
                        align="center"
                        gap={2}
                        bg={isHighlighted ? hoverBg : undefined}
                        _hover={{ bg: hoverBg }}
                        onMouseEnter={() => setHighlightedIndex(idx)}
                        onMouseDown={() => handleSelect(item)}
                      >
                        <Icon
                          as={KIND_ICON[item.kind]}
                          fontSize="sm"
                          color={labelColor}
                          flexShrink={0}
                        />
                        <Box minW={0}>
                          <Text fontSize="sm" fontWeight="medium" noOfLines={1}>
                            {item.kind === "project"
                              ? `${item.owner_name}/${item.name}`
                              : item.title ?? item.name}
                          </Text>
                          {item.kind === "project" && item.title && (
                            <Text
                              fontSize="xs"
                              color={labelColor}
                              noOfLines={1}
                            >
                              {item.title}
                            </Text>
                          )}
                          {item.kind === "dataset" && (
                            <Text
                              fontSize="xs"
                              color={labelColor}
                              noOfLines={1}
                            >
                              {item.owner_name}/{item.project_name} ·{" "}
                              {item.name}
                            </Text>
                          )}
                        </Box>
                      </Flex>
                    )
                  })}
                </Box>
              )
            })
          })()}
        </Box>
      )}
    </Box>
  )
}
