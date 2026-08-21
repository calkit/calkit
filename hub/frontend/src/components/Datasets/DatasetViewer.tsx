import {
  Box,
  Code,
  Flex,
  HStack,
  IconButton,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Tab,
  Table as ChakraTable,
  TableContainer,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useColorModeValue,
} from "@chakra-ui/react"
import { ChevronLeftIcon, ChevronRightIcon } from "@chakra-ui/icons"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { useState } from "react"
import {
  type DatasetPublic,
  type Hdf5Listing,
  ProjectsService,
  type Table,
  type TableText,
} from "../../client"
import LoadingSpinner from "../Common/LoadingSpinner"
import Markdown from "../Common/Markdown"
import { getLanguage } from "../Files/FileContent"
import TableView from "../Tables/TableView"
import SyntaxHighlighter from "react-syntax-highlighter"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"
import { decodeBase64Utf8 } from "../../lib/strings"

const TABLE_SUFFIXES = ["csv", "tsv", "parquet", "jsonl", "ndjson"]
const HDF5_SUFFIXES = ["h5", "hdf5", "hdf", "he5"]
const TEXT_SUFFIXES = [
  "json",
  "yaml",
  "yml",
  "toml",
  "txt",
  "md",
  "xml",
  "bib",
  "log",
  "ini",
  "cfg",
  "py",
  "r",
  "jl",
  "sh",
]

const suffixOf = (path: string) => path.toLowerCase().split(".").pop() ?? ""

const ROW_WINDOW = 1000
const COL_WINDOW = 100

interface WindowParams {
  row_offset: number
  row_limit: number
  col_offset: number
  col_limit: number
}

/**
 * One window of a table in the tables-page viewer, with controls to move
 * the window through the rows and the columns.
 *
 * The server cuts the table in both dimensions, since a file can be too
 * long (a million rows) or too wide (a 2D array with thousands of columns)
 * for a browser to hold or lay out; TableView then does search, sort, and
 * the gear menu within the window it's given.
 */
function TableWindow({
  queryKey,
  fetchWindow,
  parserPath,
  title,
}: {
  queryKey: unknown[]
  fetchWindow: (params: WindowParams) => Promise<TableText>
  parserPath: string
  title: string
}) {
  const subtle = useColorModeValue("gray.600", "gray.400")
  const [rowOffset, setRowOffset] = useState(0)
  const [colOffset, setColOffset] = useState(0)
  const params: WindowParams = {
    row_offset: rowOffset,
    row_limit: ROW_WINDOW,
    col_offset: colOffset,
    col_limit: COL_WINDOW,
  }
  const query = useQuery({
    queryKey: [...queryKey, params],
    queryFn: () => fetchWindow(params),
    retry: false,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  })
  if (query.isPending) return <LoadingSpinner height="50vh" />
  if (query.isError) {
    const err = query.error as any
    return (
      <Text color="red.400" fontSize="sm">
        {(err?.response?.data?.detail as string) ??
          err?.message ??
          "Could not read this file as a table."}
      </Text>
    )
  }
  const data = query.data
  const table: Table = {
    path: `${parserPath}.csv`,
    title,
    content: data.content,
  }
  const rowEnd = Math.min(data.n_rows, data.row_offset + data.row_limit)
  const colEnd = Math.min(data.n_cols, data.col_offset + data.col_limit)
  const pager = (
    label: string,
    start: number,
    end: number,
    total: number,
    step: number,
    setOffset: (n: number) => void,
  ) =>
    total > step ? (
      <HStack spacing={1} fontSize="xs" color={subtle}>
        <IconButton
          aria-label={`Previous ${label}`}
          icon={<ChevronLeftIcon />}
          size="xs"
          variant="ghost"
          isDisabled={start <= 0}
          onClick={() => setOffset(Math.max(0, start - step))}
        />
        <Text whiteSpace="nowrap">
          {label} {(start + 1).toLocaleString()}–{end.toLocaleString()} of{" "}
          {total.toLocaleString()}
        </Text>
        <IconButton
          aria-label={`Next ${label}`}
          icon={<ChevronRightIcon />}
          size="xs"
          variant="ghost"
          isDisabled={end >= total}
          onClick={() => setOffset(start + step)}
        />
      </HStack>
    ) : (
      <Text fontSize="xs" color={subtle} whiteSpace="nowrap">
        {total.toLocaleString()} {label}
      </Text>
    )
  return (
    <Box opacity={query.isFetching ? 0.7 : 1}>
      <Flex gap={4} mb={2} align="center" wrap="wrap">
        {pager(
          "rows",
          data.row_offset,
          rowEnd,
          data.n_rows,
          ROW_WINDOW,
          setRowOffset,
        )}
        {pager(
          "columns",
          data.col_offset,
          colEnd,
          data.n_cols,
          COL_WINDOW,
          setColOffset,
        )}
      </Flex>
      <TableView
        // A new window is a new table to the viewer
        key={`${data.row_offset}:${data.col_offset}`}
        table={table}
        maxHeight="calc(92vh - 300px)"
      />
    </Box>
  )
}

/** A CSV, TSV, parquet, or JSON-lines dataset, windowed by the server. */
function DatasetTable({
  ownerName,
  projectName,
  dataset,
}: {
  ownerName: string
  projectName: string
  dataset: DatasetPublic
}) {
  return (
    <TableWindow
      queryKey={[
        "projects",
        ownerName,
        projectName,
        "dataset-csv",
        dataset.path,
      ]}
      fetchWindow={(params) =>
        ProjectsService.getProjectDatasetCsv({
          owner_name: ownerName,
          project_name: projectName,
          path: dataset.path,
          ...params,
        }).then((response) => response.data)
      }
      parserPath={dataset.path}
      title={dataset.title || dataset.path}
    />
  )
}

/** One HDF5 dataset, fetched when its tab is first shown. */
function Hdf5DatasetTable({
  ownerName,
  projectName,
  path,
  hkey,
}: {
  ownerName: string
  projectName: string
  path: string
  hkey: string
}) {
  return (
    <TableWindow
      queryKey={[
        "projects",
        ownerName,
        projectName,
        "dataset-hdf5",
        path,
        hkey,
      ]}
      fetchWindow={(params) =>
        ProjectsService.getProjectDatasetHdf5({
          owner_name: ownerName,
          project_name: projectName,
          path,
          key: hkey,
          ...params,
        }).then((response) => response.data as TableText)
      }
      parserPath={`${path}-${hkey.replace(/\//g, "-")}`}
      title={hkey}
    />
  )
}

/**
 * An HDF5 file as tabs, one per dataset that can be shown as a table.
 *
 * Groups are structure, not data, so they're listed but not tabbed; a
 * dataset with more than two dimensions is listed with its shape so the
 * reader knows it's there, even though a table can't show it.
 */
function Hdf5Browser({
  ownerName,
  projectName,
  path,
}: {
  ownerName: string
  projectName: string
  path: string
}) {
  const subtle = useColorModeValue("gray.600", "gray.400")
  const listing = useQuery({
    queryKey: ["projects", ownerName, projectName, "dataset-hdf5", path],
    queryFn: () =>
      ProjectsService.getProjectDatasetHdf5({
        owner_name: ownerName,
        project_name: projectName,
        path,
      }).then((response) => response.data as Hdf5Listing),
    retry: false,
    staleTime: 60_000,
  })
  if (listing.isPending) return <LoadingSpinner height="60vh" />
  if (listing.isError) {
    const err = listing.error as any
    return (
      <Text color="red.400" fontSize="sm">
        {(err?.response?.data?.detail as string) ?? err?.message}
      </Text>
    )
  }
  const keys = listing.data.keys
  const tabular = keys.filter((k) => k.tabular)
  const other = keys.filter((k) => !k.tabular)
  return (
    <Box>
      {other.length ? (
        <Text fontSize="xs" color={subtle} mb={2}>
          Also in the file:{" "}
          {other.map((k, i) => (
            <Text as="span" key={k.key}>
              {i > 0 ? ", " : ""}
              <Code fontSize="xs">{k.key}</Code>
              {k.kind === "group"
                ? " (group)"
                : ` (${k.shape?.join("×")}, ${k.dtype})`}
            </Text>
          ))}
        </Text>
      ) : null}
      {tabular.length === 0 ? (
        <Text fontSize="sm" color={subtle}>
          No 1D or 2D datasets to show as a table.
        </Text>
      ) : (
        <Tabs isLazy variant="enclosed" size="sm">
          <TabList flexWrap="wrap">
            {tabular.map((k) => (
              <Tab key={k.key} title={`${k.shape?.join("×")} ${k.dtype}`}>
                {k.key}
              </Tab>
            ))}
          </TabList>
          <TabPanels>
            {tabular.map((k) => (
              <TabPanel key={k.key} px={0}>
                <Hdf5DatasetTable
                  ownerName={ownerName}
                  projectName={projectName}
                  path={path}
                  hkey={k.key}
                />
              </TabPanel>
            ))}
          </TabPanels>
        </Tabs>
      )}
    </Box>
  )
}

/**
 * A text-like file in a box sized to its content, capped to the dialog.
 *
 * FileContent's panes are sized for the files page (the full viewport), so
 * a one-line JSON file would get a tall empty block in a dialog.
 */
function TextFile({ item }: { item: any }) {
  const text = item?.content ? decodeBase64Utf8(String(item.content)) : ""
  const name = String(item?.name ?? item?.path ?? "")
  if (name.toLowerCase().endsWith(".md")) {
    return (
      <Box maxH="70vh" overflowY="auto">
        <Markdown>{text}</Markdown>
      </Box>
    )
  }
  return (
    <Box maxH="70vh" overflowY="auto" borderRadius="md" fontSize="sm">
      <SyntaxHighlighter
        language={getLanguage(name)}
        style={atomOneDark}
        customStyle={{ margin: 0, borderRadius: "8px" }}
      >
        {text}
      </SyntaxHighlighter>
    </Box>
  )
}

const formatSize = (size: number | null | undefined) => {
  if (size == null) return ""
  if (size < 1024) return `${size} B`
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`
  return `${(size / 1024 ** 3).toFixed(2)} GB`
}

/**
 * A folder dataset as a table of what's in it.
 *
 * A dataset is often a directory of files (one per run, per case, per
 * sensor), and the question "what's in it?" shouldn't need a trip to the
 * files page. Folders sort first; each name goes to the file itself.
 */
function FolderListing({
  ownerName,
  projectName,
  item,
}: {
  ownerName: string
  projectName: string
  item: any
}) {
  const headBg = useColorModeValue("gray.50", "gray.700")
  const entries = [...((item?.dir_items ?? []) as any[])].sort((a, b) => {
    const da = a.type === "dir" ? 0 : 1
    const db = b.type === "dir" ? 0 : 1
    return da - db || String(a.name).localeCompare(String(b.name))
  })
  const filesTo = `/${ownerName}/${projectName}/files`
  if (!entries.length) {
    return (
      <Text fontSize="sm" color="ui.dim">
        This folder is empty, or its contents haven't been pushed yet.
      </Text>
    )
  }
  return (
    <TableContainer
      borderWidth={1}
      borderRadius="md"
      maxH="70vh"
      overflowY="auto"
    >
      <ChakraTable size="sm" variant="simple">
        <Thead position="sticky" top={0} bg={headBg} zIndex={1}>
          <Tr>
            <Th>Name</Th>
            <Th>Type</Th>
            <Th isNumeric>Size</Th>
            <Th>Storage</Th>
          </Tr>
        </Thead>
        <Tbody>
          {entries.map((e) => (
            <Tr key={e.path}>
              <Td>
                <Link
                  as={RouterLink}
                  to={filesTo as any}
                  search={{ path: e.path } as any}
                >
                  {e.type === "dir" ? `${e.name}/` : e.name}
                </Link>
              </Td>
              <Td color="ui.dim">
                {e.type === "dir"
                  ? "folder"
                  : (String(e.name).split(".").pop() ?? "").toLowerCase()}
              </Td>
              <Td isNumeric fontFamily="mono" fontSize="xs">
                {formatSize(e.size)}
              </Td>
              <Td color="ui.dim">{e.storage ?? (e.in_repo ? "git" : "")}</Td>
            </Tr>
          ))}
        </Tbody>
      </ChakraTable>
    </TableContainer>
  )
}

interface DatasetViewerProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  dataset: DatasetPublic
}

/**
 * A dataset opened from its card: a paged table for tabular files, the
 * file itself for text, and the facts plus a download for anything else.
 */
const DatasetViewer = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  dataset,
}: DatasetViewerProps) => {
  const subtle = useColorModeValue("gray.600", "gray.400")
  const suffix = suffixOf(dataset.path)
  const isTable = TABLE_SUFFIXES.includes(suffix)
  const isHdf5 = HDF5_SUFFIXES.includes(suffix)
  const isText = !isTable && !isHdf5 && TEXT_SUFFIXES.includes(suffix)
  // Only non-table files are fetched whole; a table is paged by the server.
  const contentsQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "contents", dataset.path],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: ownerName,
        project_name: projectName,
        path: dataset.path,
      }).then((response) => response.data),
    enabled: isOpen && !isTable && !isHdf5,
    retry: false,
  })
  const item = contentsQuery.data as any
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={isTable || isHdf5 ? "6xl" : "4xl"}
      scrollBehavior="inside"
      isCentered
    >
      <ModalOverlay />
      {/* Big enough for a wide table, still a dialog over the page */}
      {/* A fixed height for tables, so searching and filtering change the
          rows, not the size of the dialog */}
      <ModalContent
        maxW={isTable || isHdf5 ? { base: "100%", lg: "92vw" } : undefined}
        h={isTable || isHdf5 ? "92vh" : undefined}
        maxH="92vh"
      >
        <ModalHeader pb={1}>
          <Text noOfLines={1}>
            <Markdown inline>{dataset.title || dataset.path}</Markdown>
          </Text>
          <Flex
            gap={3}
            fontSize="xs"
            color={subtle}
            fontWeight="normal"
            wrap="wrap"
          >
            <Link
              as={RouterLink}
              to={`/${ownerName}/${projectName}/files` as any}
              search={{ path: dataset.path } as any}
            >
              {dataset.path}
            </Link>
            {dataset.stage ? (
              <Text as="span">
                Stage:{" "}
                <Link
                  as={RouterLink}
                  to={`/${ownerName}/${projectName}/pipeline` as any}
                  search={{ stage: dataset.stage } as any}
                >
                  <Code fontSize="xs">{dataset.stage}</Code>
                </Link>
              </Text>
            ) : null}
            {item?.url ? (
              <Link href={String(item.url)} isExternal download>
                Download
              </Link>
            ) : null}
          </Flex>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pt={2} pb={6}>
          {dataset.description ? (
            <Box fontSize="sm" color={subtle} mb={3} sx={{ "& p": { my: 0 } }}>
              <Markdown inline>{dataset.description}</Markdown>
            </Box>
          ) : null}
          {isTable ? (
            <DatasetTable
              ownerName={ownerName}
              projectName={projectName}
              dataset={dataset}
            />
          ) : isHdf5 ? (
            <Hdf5Browser
              ownerName={ownerName}
              projectName={projectName}
              path={dataset.path}
            />
          ) : contentsQuery.isPending ? (
            <LoadingSpinner height="200px" />
          ) : contentsQuery.isError ? (
            <Text fontSize="sm" color="red.400">
              Couldn't load this file. It may not be pushed to storage yet.
            </Text>
          ) : isText && item ? (
            <TextFile item={item} />
          ) : item?.type === "dir" ? (
            <FolderListing
              ownerName={ownerName}
              projectName={projectName}
              item={item}
            />
          ) : (
            <Box fontSize="sm">
              <Text color={subtle}>
                No viewer for this file type. Browse it on the{" "}
                <Link
                  as={RouterLink}
                  to={`/${ownerName}/${projectName}/files` as any}
                  search={{ path: dataset.path } as any}
                >
                  files page
                </Link>
                {item?.url ? (
                  <>
                    {" "}
                    or{" "}
                    <Link href={String(item.url)} isExternal download>
                      download it
                    </Link>
                  </>
                ) : null}
                .
              </Text>
              {item?.size ? (
                <Text color={subtle} mt={1}>
                  {(item.size / 1e6).toFixed(2)} MB
                </Text>
              ) : null}
            </Box>
          )}
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default DatasetViewer
