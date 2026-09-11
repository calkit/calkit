import { AddIcon, CloseIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  HStack,
  IconButton,
  Input,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useColorModeValue,
} from "@chakra-ui/react"
import type { ClipboardEvent } from "react"

import { type Table as TableData, parseDelimited } from "../../lib/csv"

interface DataEntryGridProps {
  value: TableData
  onChange: (value: TableData) => void
  maxRows?: number
}

/**
 * A small spreadsheet for data that gets typed in rather than downloaded.
 *
 * Measurements read off an instrument, counts tallied by hand, a table
 * copied out of a paper: the kind of data that otherwise lands in a
 * spreadsheet nobody can find later. Pasting a block from a spreadsheet
 * fills the grid from the focused cell, so an existing sheet moves over in
 * one keystroke.
 */
const DataEntryGrid = ({
  value,
  onChange,
  maxRows = 500,
}: DataEntryGridProps) => {
  const headerBg = useColorModeValue("gray.50", "gray.700")
  const { columns, rows } = value
  const setCell = (r: number, c: number, text: string) => {
    const next = rows.map((row) => [...row])
    next[r][c] = text
    onChange({ columns, rows: next })
  }
  const setColumn = (c: number, name: string) => {
    const next = [...columns]
    next[c] = name
    onChange({ columns: next, rows })
  }
  const addRow = () => {
    if (rows.length >= maxRows) return
    onChange({ columns, rows: [...rows, columns.map(() => "")] })
  }
  const addColumn = () => {
    onChange({
      columns: [...columns, `col${columns.length + 1}`],
      rows: rows.map((row) => [...row, ""]),
    })
  }
  const removeRow = (r: number) =>
    onChange({ columns, rows: rows.filter((_, i) => i !== r) })
  const removeColumn = (c: number) => {
    if (columns.length <= 1) return
    onChange({
      columns: columns.filter((_, i) => i !== c),
      rows: rows.map((row) => row.filter((_, i) => i !== c)),
    })
  }
  // A multi-cell paste lands as a block starting at the focused cell,
  // growing the grid as needed, which is what a spreadsheet would do.
  const onPaste = (e: ClipboardEvent, r: number, c: number) => {
    const text = e.clipboardData.getData("text/plain")
    const block = parseDelimited(text)
    if (block.length <= 1 && (block[0]?.length ?? 0) <= 1) return
    e.preventDefault()
    const width = Math.max(...block.map((row) => row.length))
    const nextColumns = [...columns]
    while (nextColumns.length < c + width) {
      nextColumns.push(`col${nextColumns.length + 1}`)
    }
    const nextRows = rows.map((row) => [
      ...row,
      ...new Array(Math.max(0, nextColumns.length - row.length)).fill(""),
    ])
    block.forEach((pasted, dr) => {
      if (r + dr >= maxRows) return
      while (nextRows.length <= r + dr) {
        nextRows.push(nextColumns.map(() => ""))
      }
      pasted.forEach((cell, dc) => {
        nextRows[r + dr][c + dc] = cell
      })
    })
    onChange({ columns: nextColumns, rows: nextRows })
  }
  return (
    <Box>
      <TableContainer
        borderWidth={1}
        borderRadius="md"
        maxH="320px"
        overflowY="auto"
      >
        <Table size="sm" variant="simple">
          <Thead position="sticky" top={0} bg={headerBg} zIndex={1}>
            <Tr>
              <Th width="32px" px={1} />
              {columns.map((name, c) => (
                <Th key={c} px={1} py={1} minW="120px">
                  <HStack spacing={1}>
                    <Input
                      size="xs"
                      variant="unstyled"
                      fontWeight="semibold"
                      value={name}
                      onChange={(e) => setColumn(c, e.target.value)}
                      aria-label={`Column ${c + 1} name`}
                      autoComplete="off"
                    />
                    <IconButton
                      aria-label={`Remove column ${name}`}
                      icon={<CloseIcon boxSize={2} />}
                      size="xs"
                      variant="ghost"
                      onClick={() => removeColumn(c)}
                      isDisabled={columns.length <= 1}
                    />
                  </HStack>
                </Th>
              ))}
            </Tr>
          </Thead>
          <Tbody>
            {rows.map((row, r) => (
              <Tr key={r}>
                <Td px={1} py={0}>
                  <IconButton
                    aria-label={`Remove row ${r + 1}`}
                    icon={<CloseIcon boxSize={2} />}
                    size="xs"
                    variant="ghost"
                    onClick={() => removeRow(r)}
                  />
                </Td>
                {columns.map((_, c) => (
                  <Td key={c} px={1} py={0}>
                    <Input
                      size="sm"
                      variant="flushed"
                      value={row[c] ?? ""}
                      onChange={(e) => setCell(r, c, e.target.value)}
                      onPaste={(e) => onPaste(e, r, c)}
                      onKeyDown={(e) => {
                        // Enter on the last row starts a new one, so typing
                        // a column of numbers never needs the mouse.
                        if (e.key === "Enter" && r === rows.length - 1) {
                          e.preventDefault()
                          addRow()
                        }
                      }}
                      aria-label={`${columns[c]} row ${r + 1}`}
                      autoComplete="off"
                    />
                  </Td>
                ))}
              </Tr>
            ))}
          </Tbody>
        </Table>
      </TableContainer>
      <HStack mt={2} spacing={2}>
        <Button
          size="xs"
          leftIcon={<AddIcon boxSize={2} />}
          onClick={addRow}
          isDisabled={rows.length >= maxRows}
        >
          Row
        </Button>
        <Button
          size="xs"
          leftIcon={<AddIcon boxSize={2} />}
          onClick={addColumn}
        >
          Column
        </Button>
        <Text fontSize="xs" color="ui.dim">
          {rows.length} {rows.length === 1 ? "row" : "rows"}. Paste from a
          spreadsheet to fill many cells at once.
        </Text>
      </HStack>
    </Box>
  )
}

export default DataEntryGrid
