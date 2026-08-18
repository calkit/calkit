import {
  Badge,
  Box,
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
import { FiGrid } from "react-icons/fi"
import { TiFlowMerge } from "react-icons/ti"

import type { Table } from "../../client"
import { decodeBase64Utf8 } from "../../lib/strings"
import { parseTable } from "../../lib/tables"
import Markdown from "../Common/Markdown"

// A card's worth of table. More than this is unreadable at thumbnail size,
// and the full grid is one click away.
const PREVIEW_ROWS = 5
const PREVIEW_COLUMNS = 6

interface TableThumbnailProps {
  table: Table
  onClick: () => void
}

/** Card showing a table's first rows, for the gallery. */
export default function TableThumbnail({
  table,
  onClick,
}: TableThumbnailProps) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const bg = useColorModeValue("white", "gray.800")
  const hoverBg = useColorModeValue("gray.50", "gray.700")
  const headBg = useColorModeValue("gray.50", "gray.700")
  const previewBg = useColorModeValue("white", "gray.800")
  // Only content already inlined by the API is previewed: a table big enough
  // to come back as a URL isn't worth a fetch per card.
  const parsed =
    table.content != null
      ? parseTable(table.path, decodeBase64Utf8(table.content))
      : null

  return (
    <Box
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="lg"
      overflow="hidden"
      bg={bg}
      cursor="pointer"
      _hover={{ bg: hoverBg, shadow: "md" }}
      onClick={onClick}
      transition="all 0.15s"
    >
      {/* Fixed height so cards line up whatever their table's shape, with the
          cut-off row fading out rather than being sliced through. */}
      <Box
        height="150px"
        overflow="hidden"
        position="relative"
        bg={previewBg}
        pointerEvents="none"
      >
        {parsed ? (
          <>
            <ChakraTable size="sm" variant="simple">
              <Thead bg={headBg}>
                <Tr>
                  {parsed.columns.slice(0, PREVIEW_COLUMNS).map((column, i) => (
                    <Th
                      // Column names repeat in plenty of real tables, so the
                      // position is what identifies one.
                      key={`${column}-${i}`}
                      whiteSpace="nowrap"
                      fontSize="2xs"
                    >
                      {column}
                    </Th>
                  ))}
                </Tr>
              </Thead>
              <Tbody>
                {parsed.rows.slice(0, PREVIEW_ROWS).map((row, rowIndex) => (
                  // Rows carry no id of their own, and identical rows are
                  // legitimate, so index is the only stable key here.
                  <Tr key={rowIndex}>
                    {row.slice(0, PREVIEW_COLUMNS).map((cell, cellIndex) => (
                      <Td
                        key={cellIndex}
                        whiteSpace="nowrap"
                        fontSize="2xs"
                        maxW="140px"
                        overflow="hidden"
                        textOverflow="ellipsis"
                      >
                        {cell}
                      </Td>
                    ))}
                  </Tr>
                ))}
              </Tbody>
            </ChakraTable>
            <Box
              position="absolute"
              bottom={0}
              left={0}
              right={0}
              height="40px"
              bgGradient={`linear(to-b, transparent, ${previewBg})`}
            />
          </>
        ) : (
          <Flex
            height="100%"
            align="center"
            justify="center"
            color="gray.400"
            fontSize="3xl"
          >
            <Icon as={FiGrid} />
          </Flex>
        )}
      </Box>
      <Box p={3} borderTopWidth={1} borderColor={borderColor}>
        <Box fontWeight="semibold" fontSize="sm">
          <Markdown inline noOfLines={1}>
            {table.title}
          </Markdown>
        </Box>
        {table.description ? (
          <Box fontSize="xs" color="gray.500" mt={0.5}>
            <Markdown inline noOfLines={2}>
              {table.description}
            </Markdown>
          </Box>
        ) : (
          <Text fontSize="xs" color="gray.500" mt={0.5} noOfLines={1}>
            {table.path}
          </Text>
        )}
        {/* Which stage produced this table, so its provenance is visible
            before opening it. The link to the stage lives in the modal,
            since the whole card is already one click target. */}
        <Flex align="center" gap={1} mt={1.5} fontSize="xs" color="gray.500">
          <Icon as={TiFlowMerge} flexShrink={0} />
          {table.stage ? (
            <>
              <Code fontSize="2xs" noOfLines={1}>
                {table.stage}
              </Code>
              {table.stage_status?.status === "stale" ? (
                <Badge colorScheme="orange" fontSize="2xs">
                  Stale
                </Badge>
              ) : null}
            </>
          ) : (
            <Text as="span">Not in pipeline</Text>
          )}
        </Flex>
      </Box>
    </Box>
  )
}
