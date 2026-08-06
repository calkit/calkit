import {
  Box,
  Button,
  Flex,
  Input,
  Spinner,
  Tag,
  TagLabel,
  Text,
  VStack,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { useDebounce } from "use-debounce"
import { useEffect, useRef, useState } from "react"
import { ProjectsService, type GitRef } from "../../client"

interface RefPickerProps {
  ownerName: string
  projectName: string
  value: string | undefined
  onChange: (ref: string | undefined) => void
  placeholder?: string
  disabled?: boolean
}

export function RefPicker({
  ownerName,
  projectName,
  value,
  onChange,
  placeholder = "Search refs (branches, tags, commits)...",
  disabled = false,
}: RefPickerProps) {
  const [searchInput, setSearchInput] = useState("")
  const [debouncedSearch] = useDebounce(searchInput, 300)
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const dropdownBg = useColorModeValue("white", "gray.800")
  const dropdownBorder = useColorModeValue("gray.200", "gray.600")
  const hoverBg = useColorModeValue("gray.100", "gray.700")
  const selectedBg = useColorModeValue("gray.50", "gray.700")
  const messageColor = useColorModeValue("gray.600", "gray.400")

  const { data: refs = [], isPending } = useQuery({
    queryKey: ["search_refs", ownerName, projectName, debouncedSearch],
    queryFn: () =>
      ProjectsService.searchProjectRefs({
        ownerName,
        projectName,
        q: debouncedSearch || undefined,
      }),
    staleTime: 1000 * 60 * 5, // 5 minutes
  })

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false)
      }
    }

    document.addEventListener("mousedown", handleClickOutside)
    return () => {
      document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [])

  const handleSelectRef = (ref: GitRef) => {
    onChange(ref.name)
    setSearchInput("")
    setIsOpen(false)
  }

  const handleClear = () => {
    onChange(undefined)
    setSearchInput("")
    setIsOpen(false)
  }

  const selectedRef = refs.find((r) => r.name === value)

  return (
    <Box ref={containerRef} position="relative">
      <Flex gap={2} alignItems="flex-start">
        <VStack align="stretch" flex={1} gap={1}>
          <Input
            placeholder={placeholder}
            value={searchInput || value || ""}
            onChange={(e) => {
              setSearchInput(e.target.value)
              setIsOpen(true)
            }}
            onFocus={() => setIsOpen(true)}
            disabled={disabled}
            size="sm"
            autoComplete="off"
          />

          {isOpen && (
            <Box
              position="absolute"
              top="100%"
              left={0}
              right={0}
              mt={1}
              bg={dropdownBg}
              border="1px solid"
              borderColor={dropdownBorder}
              borderRadius="md"
              boxShadow="md"
              maxH="300px"
              overflowY="auto"
              zIndex={10}
            >
              {isPending ? (
                <Flex justify="center" align="center" h="100px">
                  <Spinner size="sm" />
                </Flex>
              ) : refs.length === 0 ? (
                <Text p={2} fontSize="sm" color="gray.500">
                  No refs found
                </Text>
              ) : (
                <VStack align="stretch" spacing={0}>
                  {refs.map((ref) => (
                    <Box
                      key={`${ref.kind}-${ref.name}`}
                      p={2}
                      cursor="pointer"
                      _hover={{ bg: hoverBg }}
                      borderBottomWidth={1}
                      borderBottomColor={dropdownBorder}
                      onClick={() => handleSelectRef(ref)}
                    >
                      <Flex justify="space-between" align="flex-start" gap={2}>
                        <VStack align="flex-start" spacing={0} flex={1}>
                          <Flex gap={2} align="center">
                            <Text fontWeight="bold" fontSize="sm">
                              {ref.name}
                            </Text>
                            <Tag size="sm" variant="subtle">
                              <TagLabel>{ref.kind}</TagLabel>
                            </Tag>
                          </Flex>
                          {ref.message && (
                            <Text
                              fontSize="xs"
                              color={messageColor}
                              noOfLines={1}
                            >
                              {ref.message}
                            </Text>
                          )}
                          <Text fontSize="xs" color="gray.500">
                            {ref.author && `${ref.author} • `}
                            {ref.timestamp
                              ? new Date(ref.timestamp).toLocaleDateString()
                              : "unknown date"}
                          </Text>
                        </VStack>
                      </Flex>
                    </Box>
                  ))}
                </VStack>
              )}
            </Box>
          )}
        </VStack>

        {value && (
          <Button
            size="sm"
            variant="ghost"
            onClick={handleClear}
            disabled={disabled}
            mt={0.5}
          >
            ✕
          </Button>
        )}
      </Flex>

      {selectedRef && value && (
        <Box mt={2} p={2} bg={selectedBg} borderRadius="md" fontSize="xs">
          <Tag size="sm" mr={1}>
            <TagLabel>{selectedRef.kind}</TagLabel>
          </Tag>
          {selectedRef.message && (
            <Text mt={1} color={messageColor} noOfLines={2}>
              {selectedRef.message}
            </Text>
          )}
          {(selectedRef.author || selectedRef.timestamp) && (
            <Text mt={1} color="gray.500" fontSize="xs">
              {selectedRef.author && `by ${selectedRef.author}`}
              {selectedRef.author && selectedRef.timestamp && " • "}
              {selectedRef.timestamp &&
                new Date(selectedRef.timestamp).toLocaleDateString()}
            </Text>
          )}
        </Box>
      )}
    </Box>
  )
}
