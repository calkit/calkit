import {
  Box,
  Button,
  Table as ChakraTable,
  Code,
  Flex,
  Icon,
  IconButton,
  Menu,
  MenuButton,
  MenuDivider,
  MenuItem,
  MenuItemOption,
  MenuList,
  MenuOptionGroup,
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
import { FiSettings } from "react-icons/fi"
import { useDebounce } from "use-debounce"

import type { Table } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { decodeBase64Utf8 } from "../../lib/strings"
import {
  type HighlightRange,
  filterRows,
  firstHighlightedRow,
  formatHiddenColumns,
  formatHighlight,
  formatSort,
  indexRows,
  isCellHighlighted,
  isNumericColumn,
  parseHiddenColumns,
  parseHighlight,
  parseSort,
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
  // Search, sort and hidden columns come from the URL too, for the same
  // reason: what you're looking at is what a copied link shows. Each falls
  // back to local state when its callback isn't given.
  search?: string
  onSearchChange?: (value: string | undefined) => void
  sort?: string
  onSortChange?: (spec: string | undefined) => void
  hiddenColumns?: string
  onHiddenColumnsChange?: (spec: string | undefined) => void
}

/** A project table, rendered as a searchable, sortable grid. */
export default function TableView({
  table,
  maxHeight = "70vh",
  highlight,
  onHighlightChange,
  search: searchParam,
  onSearchChange,
  sort: sortParam,
  onSortChange,
  hiddenColumns: hiddenColumnsParam,
  onHiddenColumnsChange,
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
  // The box stays local while typing; the URL catches up with the debounce,
  // so a keystroke doesn't push a history entry or re-render the route.
  const [search, setSearch] = useState(searchParam ?? "")
  // Filtering runs over every cell in the table, so it's debounced: doing
  // that per keystroke on a big one is visibly slow.
  const [debouncedSearch] = useDebounce(search, 250)
  useEffect(() => {
    if (!onSearchChange) return
    if ((searchParam ?? "") === debouncedSearch) return
    onSearchChange(debouncedSearch || undefined)
  }, [debouncedSearch, searchParam, onSearchChange])
  const [localSort, setLocalSort] = useState<string | undefined>(undefined)
  const sortSpec = onSortChange ? sortParam : localSort
  const setSortSpec = onSortChange ?? setLocalSort
  const sort = useMemo(() => parseSort(sortSpec), [sortSpec])
  const [localHidden, setLocalHidden] = useState<string | undefined>(undefined)
  const hiddenSpec = onHiddenColumnsChange ? hiddenColumnsParam : localHidden
  const setHiddenSpec = onHiddenColumnsChange ?? setLocalHidden
  // 1-based column numbers, matching what highlight specs use.
  const hidden = useMemo(() => parseHiddenColumns(hiddenSpec), [hiddenSpec])
  const hiddenSet = useMemo(() => new Set(hidden), [hidden])
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
    queryFn: () =>
      fetch(String(table.url)).then((response) => {
        // Without this an error page's body would be parsed as the table.
        if (!response.ok) {
          throw new Error(`Fetching table content failed: ${response.status}`)
        }
        return response.text()
      }),
    // Checked against null rather than for truthiness: an empty file has
    // empty content, which is present, not missing.
    enabled: table.content == null && !!table.url,
  })
  const text =
    table.content != null
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
  // 0-based indexes of the columns still on screen, kept in file order.
  const visibleColumns = useMemo(
    () =>
      (parsed?.columns ?? [])
        .map((_, i) => i)
        .filter((i) => !hiddenSet.has(i + 1)),
    [parsed, hiddenSet],
  )
  // Filter before sorting so the sort only orders what's on screen, and do
  // both over every row rather than the rendered slice.
  const rows = useMemo(() => {
    const matched = filterRows(allRows, debouncedSearch, visibleColumns)
    return sort ? sortRows(matched, sort.column - 1, sort.direction) : matched
  }, [allRows, debouncedSearch, sort, visibleColumns])
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
    if (table.content == null && !table.url) {
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
  const toggleSort = (index: number) => {
    const column = index + 1
    if (sort?.column !== column) {
      setSortSpec(formatSort({ column, direction: "asc" }))
      return
    }
    // Third click on the same column drops back to the file's own order,
    // which is often meaningful (a table is usually written sorted).
    setSortSpec(
      sort.direction === "asc"
        ? formatSort({ column, direction: "desc" })
        : undefined,
    )
  }
  // Hiding the sorted column would leave the rows in an order with nothing
  // on screen explaining it, so the sort goes with it.
  const setHiddenColumns = (columns: number[]) => {
    // Hiding every column would leave an empty grid with no obvious way back,
    // so the last visible one stays.
    if (columns.length >= parsed.columns.length) return
    setHiddenSpec(formatHiddenColumns(columns))
    if (sort && columns.includes(sort.column)) setSortSpec(undefined)
  }
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
            : `${parsed.rows.length} rows × ${visibleColumns.length} columns`}
          {hidden.length > 0 ? ` (${hidden.length} hidden)` : ""}
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
        <Menu closeOnSelect={false}>
          <MenuButton
            as={IconButton}
            aria-label="Column settings"
            title="Show or hide columns"
            icon={<FiSettings />}
            size="sm"
            variant="ghost"
            ml="auto"
          />
          <MenuList maxHeight="60vh" overflowY="auto" zIndex={2}>
            <MenuOptionGroup
              title="Columns"
              type="checkbox"
              // Chakra hands back the values that are still checked, i.e. the
              // visible columns, so hiding is what's left over.
              value={visibleColumns.map((i) => String(i + 1))}
              onChange={(value) => {
                const shown = new Set(
                  (Array.isArray(value) ? value : [value]).map(Number),
                )
                setHiddenColumns(
                  parsed.columns
                    .map((_, i) => i + 1)
                    .filter((column) => !shown.has(column)),
                )
              }}
            >
              {parsed.columns.map((column, i) => (
                <MenuItemOption
                  key={`${column}-${i}`}
                  value={String(i + 1)}
                  fontSize="sm"
                >
                  {column || `Column ${i + 1}`}
                </MenuItemOption>
              ))}
            </MenuOptionGroup>
            {hidden.length > 0 ? (
              <>
                <MenuDivider />
                <MenuItem fontSize="sm" onClick={() => setHiddenColumns([])}>
                  Show all columns
                </MenuItem>
              </>
            ) : null}
          </MenuList>
        </Menu>
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
              {visibleColumns.map((i) => {
                const column = parsed.columns[i]
                return (
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
                        sort?.column !== i + 1
                          ? FaSort
                          : sort.direction === "asc"
                            ? FaSortUp
                            : FaSortDown
                      }
                      ml={1}
                      fontSize="2xs"
                      opacity={sort?.column === i + 1 ? 1 : 0.35}
                      verticalAlign="middle"
                    />
                  </Th>
                )
              })}
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
                {visibleColumns.map((cellIndex) => {
                  const cell = row.cells[cellIndex] ?? ""
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
