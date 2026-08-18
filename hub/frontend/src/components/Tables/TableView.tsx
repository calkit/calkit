import {
  Box,
  Button,
  Table as ChakraTable,
  Code,
  Flex,
  Icon,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useRef, useState } from "react"
import { FaLink, FaSort, FaSortDown, FaSortUp } from "react-icons/fa"
import { useDebounce } from "use-debounce"

import type { Table } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { decodeBase64Utf8 } from "../../lib/strings"
import {
  type HighlightRange,
  filterRows,
  firstHighlightedRow,
  formatHighlight,
  indexRows,
  isCellHighlighted,
  isNumericColumn,
  parseHighlight,
  parseTable,
  sortRows,
} from "../../lib/tables"
import ClearableInput from "../Common/ClearableInput"
import LoadingSpinner from "../Common/LoadingSpinner"

// Rendering every row of a large table locks the page up for seconds, and
// nobody reads past the first screenful anyway -- searching and sorting are
// how you get to a specific row, and both run over the full set.
const MAX_RENDERED_ROWS = 500

interface TableViewProps {
  table: Table
  maxHeight?: string
  // Highlight spec from the URL (see `parseHighlight`), so a link can point
  // at the cells being talked about.
  highlight?: string
  onHighlightChange?: (spec: string | undefined) => void
}

/** A project table, rendered as a searchable, sortable grid. */
export default function TableView({
  table,
  maxHeight = "70vh",
  highlight,
  onHighlightChange,
}: TableViewProps) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const headBg = useColorModeValue("gray.50", "gray.700")
  const stripeBg = useColorModeValue("gray.50", "whiteAlpha.50")
  // Distinct from the stripe, since a wide table is read by scrolling
  // sideways and the highlight is what keeps your place in the row.
  const rowHoverBg = useColorModeValue("blue.50", "whiteAlpha.200")
  const cellHighlightBg = useColorModeValue("yellow.200", "yellow.700")
  const numberColor = useColorModeValue("gray.400", "gray.500")
  const showToast = useCustomToast()
  const [search, setSearch] = useState("")
  // Filtering runs over every cell in the table, so it's debounced: doing
  // that per keystroke on a big one is visibly slow.
  const [debouncedSearch] = useDebounce(search, 250)
  const [sort, setSort] = useState<{
    index: number
    direction: "asc" | "desc"
  } | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const highlightRef = useRef<HTMLTableCellElement>(null)
  // The cell a shift-click extends from, i.e. the last one clicked on its
  // own. Dragging a rectangle out was tried and behaved badly against the
  // browser's own text selection, so extending is shift-click only.
  const anchorRef = useRef<{ row: number; column: number } | null>(null)
  // A table too big to inline comes back as a storage URL instead of
  // content, so fetch the text ourselves in that case.
  const urlQuery = useQuery({
    queryKey: ["table-content", table.url],
    queryFn: () => fetch(String(table.url)).then((response) => response.text()),
    enabled: !table.content && !!table.url,
  })
  const text = table.content
    ? decodeBase64Utf8(table.content)
    : urlQuery.data ?? null
  const parsed = useMemo(
    () => (text === null ? null : parseTable(table.path, text)),
    [text, table.path],
  )
  const allRows = useMemo(
    () => (parsed ? indexRows(parsed.rows) : []),
    [parsed],
  )
  const numericColumns = useMemo(
    () =>
      parsed ? parsed.columns.map((_, i) => isNumericColumn(allRows, i)) : [],
    [parsed, allRows],
  )
  // Filter before sorting so the sort only orders what's on screen, and do
  // both over every row rather than the rendered slice.
  const rows = useMemo(() => {
    const matched = filterRows(allRows, debouncedSearch)
    return sort ? sortRows(matched, sort.index, sort.direction) : matched
  }, [allRows, debouncedSearch, sort])
  const ranges: HighlightRange[] = useMemo(
    () => parseHighlight(highlight),
    [highlight],
  )
  // Where the first highlighted row ended up after filtering and sorting, so
  // a shared link can render and scroll to it wherever that is.
  const highlightRow = firstHighlightedRow(ranges)
  const highlightPosition =
    highlightRow === null
      ? -1
      : rows.findIndex((row) => row.index === highlightRow)
  const renderLimit =
    highlightPosition >= MAX_RENDERED_ROWS
      ? highlightPosition + 20
      : MAX_RENDERED_ROWS
  // Scroll once per highlight rather than on every click that builds one up,
  // which would yank the table around under the cursor.
  const scrolledFor = useRef<string | null>(null)
  useEffect(() => {
    const container = scrollRef.current
    const cell = highlightRef.current
    if (!container || !cell || !highlight) return
    if (scrolledFor.current === highlight) return
    scrolledFor.current = highlight
    // Centered by hand rather than with scrollIntoView, which would scroll
    // the modal and the page behind this container too.
    container.scrollTop = Math.max(
      0,
      cell.offsetTop - container.clientHeight / 2,
    )
    container.scrollLeft = Math.max(
      0,
      cell.offsetLeft - container.clientWidth / 2,
    )
  }, [highlight])
  if (text === null) {
    if (!table.content && !table.url) {
      // Nothing to read: a DVC-tracked table whose data was never pushed.
      return (
        <Text color="gray.500">
          This table's content isn't available in project storage.
        </Text>
      )
    }
    return urlQuery.isError ? (
      <Text color="gray.500">Failed to load this table's content.</Text>
    ) : (
      <LoadingSpinner height="200px" />
    )
  }
  if (!parsed) {
    // Nothing tabular in the file: show what's actually there rather than an
    // empty grid claiming the table has no rows.
    return (
      <Box
        borderWidth={1}
        borderColor={borderColor}
        borderRadius="md"
        p={3}
        overflow="auto"
        maxHeight={maxHeight}
      >
        <Code
          display="block"
          whiteSpace="pre"
          bg="transparent"
          fontSize="xs"
          p={0}
        >
          {text}
        </Code>
      </Box>
    )
  }
  const toggleSort = (index: number) =>
    setSort((prev) => {
      if (prev?.index !== index) return { index, direction: "asc" }
      // Third click on the same column drops back to the file's own order,
      // which is often meaningful (a table is usually written sorted).
      return prev.direction === "asc" ? { index, direction: "desc" } : null
    })
  // Clicking a cell highlights it, shift-clicking another covers the block
  // between them, and a row number highlights the whole row. All of it goes
  // through the URL, so what you're looking at is what a copied link shows.
  const selectCell = (row: number, column: number | null, extend: boolean) => {
    if (!onHighlightChange) return
    const anchor = anchorRef.current
    if (extend && anchor && column !== null) {
      // Shift-clicking a cell also drags a text selection across the rows in
      // between, which reads as an accident next to the highlight.
      window.getSelection()?.removeAllRanges()
      onHighlightChange(
        formatHighlight([
          {
            rowStart: Math.min(anchor.row, row),
            rowEnd: Math.max(anchor.row, row),
            colStart: Math.min(anchor.column, column),
            colEnd: Math.max(anchor.column, column),
          },
        ]),
      )
      return
    }
    const spec = formatHighlight([
      column === null
        ? { rowStart: row, rowEnd: row }
        : { rowStart: row, rowEnd: row, colStart: column, colEnd: column },
    ])
    // Clicking what's already highlighted clears it, so there's a way back to
    // the plain table without hunting for the button.
    if (spec === highlight) {
      anchorRef.current = null
      onHighlightChange(undefined)
      return
    }
    anchorRef.current = column === null ? null : { row, column }
    onHighlightChange(spec)
  }
  const copyLink = () => {
    navigator.clipboard
      .writeText(window.location.href)
      .then(() => showToast("Copied", "Link to these cells copied.", "success"))
      .catch(() =>
        showToast(
          "Couldn't copy",
          "Copy the URL from the address bar.",
          "error",
        ),
      )
  }
  const shown = rows.slice(0, renderLimit)
  // The first highlighted cell in render order is the one scrolled to; ref
  // that one and leave the rest alone.
  let highlightSeen = false

  return (
    <Box>
      <Flex align="center" gap={3} mb={2} wrap="wrap">
        <ClearableInput
          placeholder="Search rows…"
          size="sm"
          maxW="220px"
          value={search}
          onValueChange={setSearch}
        />
        <Text fontSize="sm" color="gray.500">
          {debouncedSearch
            ? `${rows.length} of ${parsed.rows.length} rows`
            : `${parsed.rows.length} rows × ${parsed.columns.length} columns`}
        </Text>
        {ranges.length > 0 ? (
          <Flex align="center" gap={1}>
            <Button
              size="xs"
              variant="ghost"
              leftIcon={<FaLink />}
              onClick={copyLink}
            >
              Copy link to highlight
            </Button>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => {
                anchorRef.current = null
                onHighlightChange?.(undefined)
              }}
            >
              Clear
            </Button>
          </Flex>
        ) : onHighlightChange ? (
          <Text fontSize="xs" color="gray.500">
            Click a cell to highlight it; shift-click for a block.
          </Text>
        ) : null}
      </Flex>
      <Box
        ref={scrollRef}
        borderWidth={1}
        borderColor={borderColor}
        borderRadius="md"
        overflow="auto"
        maxHeight={maxHeight}
        position="relative"
      >
        <ChakraTable size="sm" variant="simple">
          <Thead position="sticky" top={0} zIndex={1} bg={headBg}>
            <Tr>
              <Th bg={headBg} px={2} color={numberColor}>
                #
              </Th>
              {parsed.columns.map((column, i) => (
                <Th
                  // Column names repeat in plenty of real tables, so the
                  // position is what identifies one.
                  key={`${column}-${i}`}
                  onClick={() => toggleSort(i)}
                  cursor="pointer"
                  userSelect="none"
                  whiteSpace="nowrap"
                  isNumeric={numericColumns[i]}
                  bg={headBg}
                  _hover={{ color: "blue.500" }}
                  title={`Sort by ${column || `column ${i + 1}`}`}
                >
                  {column}
                  <Icon
                    as={
                      sort?.index !== i
                        ? FaSort
                        : sort.direction === "asc"
                          ? FaSortUp
                          : FaSortDown
                    }
                    ml={1}
                    fontSize="2xs"
                    opacity={sort?.index === i ? 1 : 0.35}
                    verticalAlign="middle"
                  />
                </Th>
              ))}
            </Tr>
          </Thead>
          <Tbody>
            {shown.map((row, rowIndex) => (
              <Tr
                key={row.index}
                bg={rowIndex % 2 ? stripeBg : undefined}
                _hover={{ bg: rowHoverBg }}
              >
                <Td
                  px={2}
                  color={numberColor}
                  fontSize="xs"
                  userSelect="none"
                  cursor={onHighlightChange ? "pointer" : undefined}
                  onClick={() => selectCell(row.index, null, false)}
                  title="Highlight this row"
                >
                  {row.index}
                </Td>
                {row.cells.map((cell, cellIndex) => {
                  const isHighlighted = isCellHighlighted(
                    ranges,
                    row.index,
                    cellIndex + 1,
                  )
                  const isScrollTarget = isHighlighted && !highlightSeen
                  if (isScrollTarget) highlightSeen = true
                  return (
                    <Td
                      key={cellIndex}
                      ref={isScrollTarget ? highlightRef : undefined}
                      isNumeric={numericColumns[cellIndex]}
                      // Tabular figures so digits line up column-wise, which
                      // is most of what makes a numeric table readable.
                      sx={
                        numericColumns[cellIndex]
                          ? { fontVariantNumeric: "tabular-nums" }
                          : undefined
                      }
                      whiteSpace="pre-wrap"
                      // A single long text column would otherwise take the
                      // whole width and push the numbers off screen; capped,
                      // it wraps instead.
                      maxW="400px"
                      bg={isHighlighted ? cellHighlightBg : undefined}
                      cursor={onHighlightChange ? "pointer" : undefined}
                      onClick={(e) =>
                        selectCell(row.index, cellIndex + 1, e.shiftKey)
                      }
                    >
                      {cell}
                    </Td>
                  )
                })}
              </Tr>
            ))}
          </Tbody>
        </ChakraTable>
        {rows.length === 0 ? (
          <Flex align="center" justify="center" py={6} color="gray.500">
            <Text fontSize="sm">No rows match "{debouncedSearch}"</Text>
          </Flex>
        ) : null}
      </Box>
      {rows.length > renderLimit ? (
        <Text fontSize="xs" color="gray.500" mt={2}>
          Showing the first {renderLimit} of {rows.length} matching rows. Search
          or sort to bring others into view.
        </Text>
      ) : null}
    </Box>
  )
}
