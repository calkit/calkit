import {
  Box,
  Button,
  Code,
  Flex,
  Heading,
  IconButton,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  SimpleGrid,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { FaChevronLeft, FaChevronRight } from "react-icons/fa"
import { FiDownload, FiGrid } from "react-icons/fi"
import { z } from "zod"

import type { Table } from "../../../../../client"
import ClearableInput from "../../../../../components/Common/ClearableInput"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import Markdown from "../../../../../components/Common/Markdown"
import TableThumbnail from "../../../../../components/Tables/TableThumbnail"
import TableView from "../../../../../components/Tables/TableView"
import { useProjectTables } from "../../../../../hooks/useProject"

const tablesSearchSchema = z.object({
  ref: z.string().optional(),
  path: z.string().optional(),
  q: z.string().optional(),
  // Cells to highlight in the open table, e.g. "r3c2" or "r2-4c1-3", so a
  // link can point at the numbers being discussed.
  highlight: z.string().optional(),
  // How the open table is being read: rows searched for `tq`, sorted by
  // `sort` ("2:desc"), with the columns in `hide` ("3,5-6") left out. All
  // three ride in the URL so a link reproduces the view, not just the file.
  tq: z.string().optional(),
  sort: z.string().optional(),
  hide: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/tables",
)({
  component: Tables,
  validateSearch: (search) => tablesSearchSchema.parse(search),
})

/** Full-screen view of one table, with room for its columns. */
function TableModal({
  table,
  gitRef,
  highlight,
  onHighlightChange,
  search,
  onSearchChange,
  sort,
  onSortChange,
  hide,
  onHiddenColumnsChange,
  onClose,
  onPrev,
  onNext,
}: {
  table: Table
  gitRef?: string
  highlight?: string
  onHighlightChange: (spec: string | undefined) => void
  search?: string
  onSearchChange: (value: string | undefined) => void
  sort?: string
  onSortChange: (spec: string | undefined) => void
  hide?: string
  onHiddenColumnsChange: (spec: string | undefined) => void
  onClose: () => void
  onPrev?: () => void
  onNext?: () => void
}) {
  const subtleColor = useColorModeValue("gray.600", "gray.400")
  // Left/right step through the gallery without closing the modal, the way
  // the figure carousel does.
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (
        el?.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(el?.tagName ?? "") ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey
      ) {
        return
      }
      if (e.key === "ArrowLeft" && onPrev) {
        e.preventDefault()
        onPrev()
      } else if (e.key === "ArrowRight" && onNext) {
        e.preventDefault()
        onNext()
      }
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [onPrev, onNext])

  return (
    <Modal
      isOpen
      onClose={onClose}
      size="6xl"
      scrollBehavior="inside"
      isCentered
    >
      <ModalOverlay />
      {/* Wide enough for a table's columns, still a dialog over the page,
          and a fixed height so filtering changes the rows, not the box */}
      <ModalContent maxW={{ base: "100%", lg: "92vw" }} h="92vh" maxH="92vh">
        <ModalHeader pb={1}>
          <Flex align="center" gap={2}>
            <IconButton
              aria-label="Previous table"
              icon={<FaChevronLeft />}
              size="sm"
              variant="ghost"
              isDisabled={!onPrev}
              onClick={onPrev}
            />
            <IconButton
              aria-label="Next table"
              icon={<FaChevronRight />}
              size="sm"
              variant="ghost"
              isDisabled={!onNext}
              onClick={onNext}
            />
            <Box minW={0}>
              <Heading size="md">
                <Markdown inline>{table.title}</Markdown>
              </Heading>
              <Flex align="center" gap={3} fontSize="xs" color={subtleColor}>
                <Link
                  as={RouterLink}
                  to="../files"
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  search={{ path: table.path, ref: gitRef } as any}
                >
                  {table.path}
                </Link>
                {table.stage ? (
                  // Linked to the pipeline so the stage that produced these
                  // numbers -- and what went into it -- is one click away.
                  <Text as="span">
                    Stage:{" "}
                    <Link
                      as={RouterLink}
                      to="../pipeline"
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      search={{ stage: table.stage, ref: gitRef } as any}
                    >
                      <Code fontSize="xs" cursor="pointer">
                        {table.stage}
                      </Code>
                    </Link>
                  </Text>
                ) : (
                  <Text as="span" color="red.500">
                    Not in pipeline
                  </Text>
                )}
                {table.url ? (
                  <Button
                    as="a"
                    href={String(table.url)}
                    download
                    target="_blank"
                    rel="noopener noreferrer"
                    size="xs"
                    variant="ghost"
                    leftIcon={<FiDownload />}
                  >
                    Download
                  </Button>
                ) : null}
              </Flex>
            </Box>
          </Flex>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pt={0} pb={6}>
          {table.description ? (
            <Box fontSize="sm" color={subtleColor} mb={2}>
              <Markdown>{table.description}</Markdown>
            </Box>
          ) : null}
          <TableView
            // Remount per table so the search box picks up the new table's
            // query rather than keeping the one being left behind.
            key={table.path}
            table={table}
            maxHeight="calc(92vh - 260px)"
            highlight={highlight}
            onHighlightChange={onHighlightChange}
            search={search}
            onSearchChange={onSearchChange}
            sort={sort}
            onSortChange={onSortChange}
            hiddenColumns={hide}
            onHiddenColumnsChange={onHiddenColumnsChange}
          />
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

function Tables() {
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const { path: selectedPath, q, highlight, tq, sort, hide } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { tablesRequest } = useProjectTables(accountName, projectName, ref)
  // Seeded from the URL so a shared link opens on the same results, then kept
  // local while typing and mirrored back below.
  const [search, setSearch] = useState(q ?? "")
  useEffect(() => {
    if ((q ?? "") === search) return
    navigate({
      search: (prev) => ({ ...prev, q: search || undefined }),
      replace: true,
    })
  }, [search, q, navigate])
  const tables = tablesRequest.data ?? []
  // The whole listing is already here, so filtering it is local. It covers
  // the description too, which is often where a table says what it's for.
  const needle = search.trim().toLowerCase()
  const matched = needle
    ? tables.filter(
        (table) =>
          table.path.toLowerCase().includes(needle) ||
          table.title.toLowerCase().includes(needle) ||
          (table.description ?? "").toLowerCase().includes(needle),
      )
    : tables
  // A highlight belongs to the table it was made in, so opening another one
  // drops it rather than pointing at unrelated cells.
  // Search, sort and hidden columns mean something only in the table they
  // were set in, so they're dropped alongside the highlight.
  const perTable = {
    highlight: undefined,
    tq: undefined,
    sort: undefined,
    hide: undefined,
  }
  const openTable = (path: string) =>
    navigate({ search: (prev) => ({ ...prev, path, ...perTable }) })
  const closeTable = () =>
    navigate({ search: (prev) => ({ ...prev, path: undefined, ...perTable }) })
  const setHighlight = (spec: string | undefined) =>
    navigate({
      search: (prev) => ({ ...prev, highlight: spec }),
      replace: true,
    })
  // Replaced rather than pushed: reading a table is a lot of small
  // adjustments, and each one shouldn't need its own press of Back.
  const setTableSearchParam =
    (key: "tq" | "sort" | "hide") => (value: string | undefined) =>
      navigate({
        search: (prev) => ({ ...prev, [key]: value || undefined }),
        replace: true,
      })
  // Stepping moves through what's on screen, so a filtered gallery steps
  // through its matches rather than the tables it just hid.
  const selectedIndex = matched.findIndex((t) => t.path === selectedPath)
  const selectedTable = selectedIndex >= 0 ? matched[selectedIndex] : undefined

  if (tablesRequest.isPending) {
    return <LoadingSpinner height="100vh" />
  }

  return (
    <Box>
      <Flex align="center" mb={4} gap={2} wrap="wrap">
        <Heading size="md">Tables</Heading>
        <ClearableInput
          placeholder="Search tables…"
          size="sm"
          maxW="220px"
          value={search}
          onValueChange={setSearch}
        />
        {matched.length > 0 ? (
          <Text fontSize="sm" color="gray.500" ml="auto">
            {matched.length} of {tables.length}
          </Text>
        ) : null}
      </Flex>
      {matched.length === 0 ? (
        <NoArtifactFound
          icon={FiGrid}
          title={needle ? `No tables match "${search}"` : "No tables found"}
          hint={
            needle ? undefined : (
              <>
                Declare one in <Code>calkit.yaml</Code>, or add a CSV to a{" "}
                <Code>tables</Code> or <Code>results</Code> directory.
              </>
            )
          }
          docsUrl={needle ? undefined : "https://docs.calkit.org/calkit-yaml/"}
        />
      ) : (
        <SimpleGrid columns={{ base: 1, md: 2, xl: 3 }} spacing={4}>
          {matched.map((table) => (
            <TableThumbnail
              key={table.path}
              table={table}
              onClick={() => openTable(table.path)}
            />
          ))}
        </SimpleGrid>
      )}
      {selectedTable ? (
        <TableModal
          table={selectedTable}
          gitRef={ref}
          highlight={highlight}
          onHighlightChange={setHighlight}
          search={tq}
          onSearchChange={setTableSearchParam("tq")}
          sort={sort}
          onSortChange={setTableSearchParam("sort")}
          hide={hide}
          onHiddenColumnsChange={setTableSearchParam("hide")}
          onClose={closeTable}
          onPrev={
            selectedIndex > 0
              ? () => openTable(matched[selectedIndex - 1].path)
              : undefined
          }
          onNext={
            selectedIndex < matched.length - 1
              ? () => openTable(matched[selectedIndex + 1].path)
              : undefined
          }
        />
      ) : null}
    </Box>
  )
}
