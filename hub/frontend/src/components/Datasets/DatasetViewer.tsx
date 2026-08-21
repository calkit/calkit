import {
  Box,
  Code,
  Flex,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import {
  type DatasetPublic,
  type Hdf5Listing,
  ProjectsService,
  type Table,
  type TableText,
} from "../../client"
import LoadingSpinner from "../Common/LoadingSpinner"
import Markdown from "../Common/Markdown"
import FileContent from "../Files/FileContent"
import TableView from "../Tables/TableView"

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

/**
 * The table behind a dataset, in the same viewer the tables page uses.
 *
 * The server turns CSV, TSV, parquet, or JSON lines into CSV text (capped
 * at a row count a browser can hold, and it says when it cut), and
 * TableView does the rest: search, sort, the gear menu for hiding columns,
 * and highlight links.
 */
function DatasetTable({
  ownerName,
  projectName,
  dataset,
}: {
  ownerName: string
  projectName: string
  dataset: DatasetPublic
}) {
  const csvQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "dataset-csv", dataset.path],
    queryFn: () =>
      ProjectsService.getProjectDatasetCsv({
        owner_name: ownerName,
        project_name: projectName,
        path: dataset.path,
      }).then((response) => response.data),
    retry: false,
    staleTime: 60_000,
  })
  if (csvQuery.isPending) return <LoadingSpinner height="60vh" />
  if (csvQuery.isError) {
    const err = csvQuery.error as any
    return (
      <Text color="red.400" fontSize="sm">
        {(err?.response?.data?.detail as string) ??
          err?.message ??
          "Could not read this file as a table."}
      </Text>
    )
  }
  const data = csvQuery.data
  // The content is CSV whatever the file was, so the parser is told so.
  const table: Table = {
    path: `${dataset.path}.csv`,
    title: dataset.title || dataset.path,
    description: dataset.description,
    stage: dataset.stage,
    content: data.content,
  }
  return (
    <Box>
      {data.truncated ? (
        <Text fontSize="xs" color="orange.400" mb={2}>
          The file has {data.n_rows.toLocaleString()} rows; the first 200,000
          are loaded here.
        </Text>
      ) : null}
      <TableView table={table} maxHeight="calc(92vh - 240px)" />
    </Box>
  )
}

/** One HDF5 dataset, fetched when its tab is first shown. */
function Hdf5DatasetTable({
  ownerName,
  projectName,
  path,
  hkey,
  title,
}: {
  ownerName: string
  projectName: string
  path: string
  hkey: string
  title: string
}) {
  const query = useQuery({
    queryKey: ["projects", ownerName, projectName, "dataset-hdf5", path, hkey],
    queryFn: () =>
      ProjectsService.getProjectDatasetHdf5({
        owner_name: ownerName,
        project_name: projectName,
        path,
        key: hkey,
      }).then((response) => response.data as TableText),
    retry: false,
    staleTime: 60_000,
  })
  if (query.isPending) return <LoadingSpinner height="50vh" />
  if (query.isError) {
    const err = query.error as any
    return (
      <Text color="red.400" fontSize="sm">
        {(err?.response?.data?.detail as string) ?? err?.message}
      </Text>
    )
  }
  const table: Table = {
    path: `${path}-${hkey.replace(/\//g, "-")}.csv`,
    title,
    content: query.data.content,
  }
  return (
    <Box>
      {query.data.truncated ? (
        <Text fontSize="xs" color="orange.400" mb={2}>
          {query.data.n_rows.toLocaleString()} rows; the first 200,000 are
          loaded here.
        </Text>
      ) : null}
      <TableView table={table} maxHeight="calc(92vh - 300px)" />
    </Box>
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
                  title={k.key}
                />
              </TabPanel>
            ))}
          </TabPanels>
        </Tabs>
      )}
    </Box>
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
            <FileContent item={item} />
          ) : (
            <Box fontSize="sm">
              <Text color={subtle}>
                {item?.type === "dir"
                  ? "This dataset is a folder."
                  : "No viewer for this file type."}{" "}
                Browse it on the{" "}
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
