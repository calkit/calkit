import {
  Badge,
  Box,
  Code,
  Flex,
  Heading,
  Icon,
  Link,
  Text,
  Tooltip,
  useColorModeValue,
} from "@chakra-ui/react"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
  useSearch,
} from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { FiBarChart2 } from "react-icons/fi"
import { TiFlowMerge } from "react-icons/ti"
import { z } from "zod"

import type { Provenance, Result } from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import {
  useProjectProvenance,
  useProjectResults,
} from "../../../../../hooks/useProject"

const resultsSearchSchema = z.object({
  ref: z.string().optional(),
  // The results file open, and the value in it a link points at, e.g.,
  // from a paper's \ckvalue
  path: z.string().optional(),
  key: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/results",
)({
  component: Results,
  validateSearch: (search) => resultsSearchSchema.parse(search),
})

/** A value as it reads in a row, short enough to scan. */
function valueText(value: unknown): string {
  if (typeof value === "string") return value
  return JSON.stringify(value)
}

/**
 * A results file as a tree, each value clickable to point a link at it.
 *
 * Keys are joined with dots, which is how a paper's \ckvalue and a
 * question's evidence name them, so the key in the URL is the one to copy.
 */
function ValueTree({
  value,
  prefix,
  selected,
  onSelect,
  depth = 0,
}: {
  value: unknown
  prefix: string
  selected?: string
  onSelect: (key: string) => void
  depth?: number
}) {
  const highlight = useColorModeValue("yellow.100", "yellow.800")
  const keyColor = useColorModeValue("gray.600", "gray.400")
  const selectedRef = useRef<HTMLDivElement | null>(null)
  // Brought into view once, when a link opens the page on a value
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "center" })
  }, [])
  if (value === null || typeof value !== "object") {
    return null
  }
  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index), item] as const)
    : Object.entries(value as Record<string, unknown>)
  return (
    <Box pl={depth ? 4 : 0}>
      {entries.map(([name, item]) => {
        const key = prefix ? `${prefix}.${name}` : name
        const isSelected = key === selected
        const nested = item !== null && typeof item === "object"
        return (
          <Box key={key}>
            <Flex
              ref={isSelected ? selectedRef : undefined}
              as="button"
              type="button"
              w="100%"
              textAlign="left"
              gap={2}
              px={1}
              borderRadius="sm"
              fontFamily="mono"
              fontSize="sm"
              bg={isSelected ? highlight : undefined}
              _hover={{ textDecoration: "underline" }}
              onClick={() => onSelect(key)}
            >
              <Text as="span" color={keyColor} flexShrink={0}>
                {name}
              </Text>
              {nested ? null : (
                <Text as="span" noOfLines={1}>
                  {valueText(item)}
                </Text>
              )}
            </Flex>
            {nested ? (
              <ValueTree
                value={item}
                prefix={key}
                selected={selected}
                onSelect={onSelect}
                depth={depth + 1}
              />
            ) : null}
          </Box>
        )
      })}
    </Box>
  )
}

/** The stage behind a path, what to edit, what it reads, and whether it's
 * out of date. */
function ProvenanceCard({
  provenance,
  accountName,
  projectName,
  gitRef,
}: {
  provenance: Provenance
  accountName: string
  projectName: string
  gitRef?: string
}) {
  const subtle = useColorModeValue("gray.600", "gray.400")
  const fileLink = (path: string) => (
    <Link
      as={RouterLink}
      to={`/${accountName}/${projectName}/files`}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      search={{ path, ref: gitRef } as any}
    >
      <Code fontSize="xs">{path}</Code>
    </Link>
  )
  // A copy, e.g., a figure put beside a paper, is described by the original
  const copied = provenance.copied_from ? (
    <Text fontSize="sm" color={subtle}>
      Copied from {fileLink(provenance.copied_from)}
      {provenance.copy_stage ? ` by ${provenance.copy_stage}` : ""}
    </Text>
  ) : null
  // What calkit.yaml records for something no stage makes
  const origin = provenance.origin ? (
    <Text fontSize="sm">
      {provenance.origin_url ? (
        <Link href={provenance.origin_url} isExternal>
          {provenance.origin}
        </Link>
      ) : (
        provenance.origin
      )}
      {provenance.origin_path ? (
        <Text as="span" color={subtle}>
          {" "}
          (recorded for {fileLink(provenance.origin_path)})
        </Text>
      ) : null}
    </Text>
  ) : null
  // Data behind it, however far back, that nothing records the origin of
  const gaps = provenance.gaps?.length ? (
    <Box mt={1} fontSize="sm" color="orange.400">
      {provenance.gaps.map((gap) => {
        const via = (gap.steps ?? []).flatMap((step) =>
          step.stage ? [step.stage] : [],
        )
        return (
          <Text key={gap.path}>
            Nothing records where {fileLink(gap.path)} came from
            {via.length ? ` (via ${via.join(", ")})` : ""}.
          </Text>
        )
      })}
      <Text color={subtle}>
        Record it in calkit.yaml with imported_from or created_by, or add the
        stage that makes it.
      </Text>
    </Box>
  ) : null
  if (!provenance.stage) {
    return (
      <Box>
        {copied}
        {origin ?? (
          <Text fontSize="sm" color={subtle}>
            No pipeline stage produces this file.
          </Text>
        )}
        {gaps}
      </Box>
    )
  }
  return (
    <Box fontSize="sm">
      {copied}
      <Flex align="center" gap={2} wrap="wrap">
        <Icon as={TiFlowMerge} />
        <Link
          as={RouterLink}
          to={`/${accountName}/${projectName}/pipeline`}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          search={{ stage: provenance.stage, ref: gitRef } as any}
        >
          <Code fontSize="xs">{provenance.stage}</Code>
        </Link>
        {provenance.stage_kind ? (
          <Text as="span" color={subtle}>
            {provenance.stage_kind}
          </Text>
        ) : null}
        {provenance.stale_reason ? (
          <Tooltip
            label={
              provenance.stale_reason === "frozen"
                ? "Frozen, and its inputs or outputs have moved since it ran"
                : "Its inputs or code changed since it last ran"
            }
          >
            <Badge colorScheme="orange" fontSize="2xs">
              {provenance.stale_reason === "frozen" ? "Frozen" : "Stale"}
            </Badge>
          </Tooltip>
        ) : provenance.stage_status?.status === "up-to-date" ? (
          <Badge colorScheme="green" fontSize="2xs">
            Up to date
          </Badge>
        ) : null}
      </Flex>
      {provenance.source ? (
        <Text mt={1}>Edit {fileLink(provenance.source)} to change it.</Text>
      ) : provenance.command ? (
        <Text mt={1}>
          Made by <Code fontSize="xs">{provenance.command}</Code>
        </Text>
      ) : null}
      {provenance.inputs?.length ? (
        <Box mt={1}>
          <Text color={subtle}>Reads</Text>
          <Flex gap={2} wrap="wrap">
            {provenance.inputs.map((input) => (
              <Box key={input}>{fileLink(input)}</Box>
            ))}
          </Flex>
        </Box>
      ) : null}
      {gaps}
    </Box>
  )
}

function Results() {
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const { path: selectedPath, key } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const subtle = useColorModeValue("gray.600", "gray.400")
  const { resultsRequest } = useProjectResults(accountName, projectName, ref)
  // The whole file, to browse, and the value a link points at, with what
  // produced it
  const { provenanceRequest: fileRequest } = useProjectProvenance(
    accountName,
    projectName,
    selectedPath,
    undefined,
    ref,
  )
  const { provenanceRequest: valueRequest } = useProjectProvenance(
    accountName,
    projectName,
    key ? selectedPath : undefined,
    key,
    ref,
  )
  // Several results can be keys into one file, which is listed once
  const files: Result[] = []
  for (const result of resultsRequest.data ?? []) {
    if (!files.some((file) => file.path === result.path)) {
      files.push(result)
    }
  }
  if (resultsRequest.isPending) {
    return <LoadingSpinner height="100vh" />
  }
  return (
    <Box>
      <Heading size="md" mb={4}>
        Results
      </Heading>
      {files.length === 0 ? (
        <NoArtifactFound
          icon={FiBarChart2}
          title="No results found"
          hint={
            <>
              Declare one in <Code>calkit.yaml</Code>, or write a JSON, YAML, or
              TOML file to a <Code>results</Code> directory.
            </>
          }
          docsUrl="https://docs.calkit.org/calkit-yaml/"
        />
      ) : (
        <Flex gap={4} align="start" direction={{ base: "column", lg: "row" }}>
          <Box w={{ base: "100%", lg: "30%" }} flexShrink={0}>
            {files.map((file) => (
              <Box
                key={file.path}
                as="button"
                type="button"
                w="100%"
                textAlign="left"
                px={3}
                py={2}
                mb={2}
                borderRadius="md"
                bg={file.path === selectedPath ? secBgColor : undefined}
                _hover={{ bg: secBgColor }}
                onClick={() =>
                  navigate({
                    search: (prev) => ({
                      ...prev,
                      path: file.path,
                      key: undefined,
                    }),
                  })
                }
              >
                <Text fontWeight="semibold" noOfLines={1}>
                  {file.title}
                </Text>
                <Flex align="center" gap={2} fontSize="xs" color={subtle}>
                  <Text as="span" noOfLines={1}>
                    {file.path}
                  </Text>
                  {file.stage_status?.status === "stale" ? (
                    <Badge colorScheme="orange" fontSize="2xs">
                      Stale
                    </Badge>
                  ) : null}
                </Flex>
              </Box>
            ))}
          </Box>
          <Box flex="1" minW={0}>
            {!selectedPath ? (
              <Text color={subtle}>Pick a results file to browse it.</Text>
            ) : fileRequest.isPending ? (
              <LoadingSpinner />
            ) : fileRequest.data ? (
              <Box>
                <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
                  <Code fontSize="sm">{selectedPath}</Code>
                  {key ? (
                    <Box mt={2}>
                      <Text fontSize="sm" color={subtle}>
                        {key}
                      </Text>
                      <Text fontSize="2xl" fontWeight="semibold">
                        {valueRequest.isPending
                          ? "…"
                          : valueRequest.data?.value_error ??
                            valueText(valueRequest.data?.value)}
                      </Text>
                    </Box>
                  ) : null}
                  <Box mt={3}>
                    <ProvenanceCard
                      provenance={fileRequest.data}
                      accountName={accountName}
                      projectName={projectName}
                      gitRef={ref}
                    />
                  </Box>
                </Box>
                {fileRequest.data.value_error ? (
                  <Text color={subtle}>{fileRequest.data.value_error}</Text>
                ) : (
                  <ValueTree
                    value={fileRequest.data.value}
                    prefix=""
                    selected={key}
                    onSelect={(selected) =>
                      navigate({
                        search: (prev) => ({ ...prev, key: selected }),
                        replace: true,
                      })
                    }
                  />
                )}
              </Box>
            ) : (
              <Text color={subtle}>Couldn't read {selectedPath}.</Text>
            )}
          </Box>
        </Flex>
      )}
    </Box>
  )
}
