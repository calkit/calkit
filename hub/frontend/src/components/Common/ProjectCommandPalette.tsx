import {
  Flex,
  Icon,
  Input,
  Kbd,
  Modal,
  ModalBody,
  ModalContent,
  ModalOverlay,
  Text,
  VStack,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { getRouteApi, useNavigate, useSearch } from "@tanstack/react-router"
import { useEffect, useMemo, useRef, useState } from "react"

import useAuth from "../../hooks/useAuth"
import { projectNavItems } from "./SidebarItems"

// A Cmd/Ctrl+K command palette for jumping between a project's sections by
// keyboard, mounted once in the project layout so it's available everywhere.
const ProjectCommandPalette = () => {
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const currentRef: string | undefined = layoutSearch?.ref
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [query, setQuery] = useState("")
  const [activeIndex, setActiveIndex] = useState(0)
  const bgActive = useColorModeValue("blue.50", "blue.900")
  const activeColor = useColorModeValue("blue.700", "blue.200")

  // Cmd/Ctrl+K toggles the palette from anywhere in the project.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        if (isOpen) {
          onClose()
        } else {
          onOpen()
        }
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [isOpen, onOpen, onClose])

  // Reset the query and selection each time it opens.
  useEffect(() => {
    if (isOpen) {
      setQuery("")
      setActiveIndex(0)
    }
  }, [isOpen])

  // Mirror the sidebar: don't surface sections the user can't reach when logged
  // out.
  const availableItems = useMemo(
    () => projectNavItems.filter((item) => user || !item.requiresLogin),
    [user],
  )
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return availableItems
    return availableItems.filter((item) => item.title.toLowerCase().includes(q))
  }, [query, availableItems])

  const listRef = useRef<HTMLDivElement>(null)
  // Keep the highlighted item in view as the selection moves.
  useEffect(() => {
    const el = listRef.current?.children[activeIndex] as HTMLElement | undefined
    el?.scrollIntoView({ block: "nearest" })
  }, [activeIndex])

  const go = (path: string) => {
    onClose()
    navigate({
      to: `/${accountName}/${projectName}${path}`,
      // Preserve the selected git ref, like the sidebar does.
      search: currentRef ? ({ ref: currentRef } as never) : undefined,
    })
  }

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter") {
      e.preventDefault()
      const item = filtered[activeIndex]
      if (item) go(item.path)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="lg">
      <ModalOverlay />
      <ModalContent>
        <ModalBody p={0}>
          <Input
            placeholder="Jump to a section…"
            variant="unstyled"
            px={4}
            py={3}
            borderBottomWidth={1}
            borderRadius={0}
            value={query}
            autoFocus
            onChange={(e) => {
              setQuery(e.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={onInputKeyDown}
            autoComplete="off"
            data-form-type="other"
            data-lpignore="true"
          />
          <VStack
            ref={listRef}
            align="stretch"
            spacing={0}
            maxH="320px"
            overflowY="auto"
            py={2}
          >
            {filtered.length === 0 ? (
              <Text px={4} py={2} fontSize="sm" color="gray.500">
                No sections match.
              </Text>
            ) : (
              filtered.map((item, i) => (
                <Flex
                  key={item.title}
                  px={4}
                  py={2}
                  align="center"
                  cursor="pointer"
                  bg={i === activeIndex ? bgActive : undefined}
                  color={i === activeIndex ? activeColor : undefined}
                  fontWeight={i === activeIndex ? "semibold" : "normal"}
                  onMouseEnter={() => setActiveIndex(i)}
                  onClick={() => go(item.path)}
                >
                  <Icon as={item.icon} mr={3} />
                  <Text fontSize="sm">{item.title}</Text>
                </Flex>
              ))
            )}
          </VStack>
          <Flex
            px={4}
            py={2}
            borderTopWidth={1}
            gap={3}
            fontSize="xs"
            color="gray.500"
          >
            <Text>
              <Kbd>↑</Kbd> <Kbd>↓</Kbd> to navigate
            </Text>
            <Text>
              <Kbd>↵</Kbd> to open
            </Text>
            <Text>
              <Kbd>esc</Kbd> to close
            </Text>
          </Flex>
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default ProjectCommandPalette
