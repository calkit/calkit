/**
 * What a document shows on the page that came from the project: the values,
 * figures and generated blocks it took rather than copied, each with the
 * file behind it, the stage and script that produce it, the pages it lands
 * on, and whether the reader is looking at something the project still
 * produces.
 *
 * The other half of PublicationComponents, which lists the files the
 * publication's folder is made of. Both read provenance; this one reads it
 * off the page.
 */
import {
  Badge,
  Box,
  Code,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import {
  Link as RouterLink,
  getRouteApi,
  useNavigate,
} from "@tanstack/react-router"

import {
  type DocumentComponent,
  ProjectsService,
  type Publication,
} from "../../client"

const routeApi = getRouteApi(
  "/_layout/$accountName/$projectName/_layout/publications",
)

// Worst first, since that's what needs doing; then in the order a reader
// wants: what came from nowhere, then everything that is accounted for.
const STATUS_RANK: Record<DocumentComponent["status"], number> = {
  missing: 0,
  stale: 1,
  unknown: 2,
  ok: 3,
}

/**
 * Sort components for the table: by state as ranked above, then by the file
 * they came from, then by key, so one results file's values stay together.
 */
export function sortDocumentComponents(
  items: DocumentComponent[],
): DocumentComponent[] {
  const rank = (item: DocumentComponent) =>
    STATUS_RANK[item.status] ?? STATUS_RANK.unknown
  return [...items].sort(
    (a, b) =>
      rank(a) - rank(b) ||
      a.path.localeCompare(b.path) ||
      (a.key ?? "").localeCompare(b.key ?? ""),
  )
}

const STALE_EXPLANATIONS: Record<string, string> = {
  "stage-out-of-date": "its stage needs a rerun",
  "changed-since-build": "the project has moved on since this was built",
  "answer-stale": "the answer no longer matches its evidence",
}

/**
 * Why a component isn't current, in a reader's terms. Empty when it is, or
 * when nothing could be checked -- which is not the same as being fine and
 * is said separately.
 */
export function staleExplanation(item: DocumentComponent): string {
  return (item.stale_reasons ?? [])
    .map((reason) => STALE_EXPLANATIONS[reason] ?? reason)
    .join(", and ")
}

/** What a value reads as, for a table cell. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined) return ""
  return typeof value === "object" ? JSON.stringify(value) : String(value)
}

/** How to name a component to a reader: the file, and the key within it. */
export function componentLabel(item: DocumentComponent): string {
  return item.key ? `${item.path}:${item.key}` : item.path
}

/** "Pages 3, 7", or nothing for a component that reached no page. */
export function pagesText(pages: number[]): string {
  if (pages.length === 0) return ""
  return `${pages.length === 1 ? "Page" : "Pages"} ${pages.join(", ")}`
}

function StateCell({ item }: { item: DocumentComponent }) {
  if (item.status === "missing") {
    return (
      <>
        <Badge colorScheme="red">Missing</Badge>
        <Text fontSize="xs" color="gray.500">
          The project no longer has this file.
        </Text>
      </>
    )
  }
  if (item.status === "stale") {
    return (
      <>
        <Badge colorScheme="orange">Out of date</Badge>
        <Text fontSize="xs" color="gray.500">
          {staleExplanation(item)}
        </Text>
        {item.kind === "value" &&
        (item.stale_reasons ?? []).includes("changed-since-build") ? (
          <Text fontSize="xs" color="gray.500">
            Built with <Code fontSize="xs">{valueText(item.build_value)}</Code>,
            now <Code fontSize="xs">{valueText(item.current_value)}</Code>.
          </Text>
        ) : null}
      </>
    )
  }
  if (item.status === "unknown") {
    return (
      <>
        <Badge>Unchecked</Badge>
        <Text fontSize="xs" color="gray.500">
          Nothing here says whether this is current.
        </Text>
      </>
    )
  }
  return <Badge colorScheme="green">Current</Badge>
}

function OriginCell({ item }: { item: DocumentComponent }) {
  if (item.stage) {
    return (
      <>
        <Link
          as={RouterLink}
          to="../pipeline"
          search={{ stage: item.stage } as any}
        >
          <Code fontSize="xs" cursor="pointer">
            {item.stage}
          </Code>
        </Link>
        {item.script ? (
          <Text fontSize="xs" color="gray.500">
            <Link
              as={RouterLink}
              to="../files"
              search={{ path: item.script } as any}
            >
              {item.script}
            </Link>
          </Text>
        ) : null}
      </>
    )
  }
  if (item.provenance === "undeclared") {
    return (
      <>
        <Badge colorScheme="orange">No provenance</Badge>
        <Text fontSize="xs" color="gray.500">
          Nothing produces this and nobody has said where it came from.
        </Text>
      </>
    )
  }
  if (item.provenance === "project") {
    return (
      <Text fontSize="xs" color="gray.500">
        The project's own words
      </Text>
    )
  }
  return (
    <Badge colorScheme="blue">
      {item.provenance === "imported" ? "Imported" : "Attested"}
    </Badge>
  )
}

function ComponentsTable({ items }: { items: DocumentComponent[] }) {
  return (
    <Table size="sm" variant="simple">
      <Thead>
        <Tr>
          <Th>What</Th>
          <Th>From</Th>
          <Th>Where</Th>
          <Th>State</Th>
        </Tr>
      </Thead>
      <Tbody>
        {sortDocumentComponents(items).map((item) => (
          <Tr key={`${item.kind}-${item.path}-${item.key ?? ""}`}>
            <Td>
              <Badge mr={1}>{item.kind}</Badge>
              <Link
                as={RouterLink}
                to="../files"
                search={{ path: item.path } as any}
              >
                {componentLabel(item)}
              </Link>
              {item.kind === "value" &&
              item.current_value !== null &&
              item.current_value !== undefined ? (
                <Text fontSize="xs" color="gray.500">
                  {valueText(item.current_value)}
                </Text>
              ) : null}
            </Td>
            <Td>
              <OriginCell item={item} />
            </Td>
            <Td fontSize="xs" color="gray.500">
              {pagesText(item.pages ?? [])}
            </Td>
            <Td>
              <StateCell item={item} />
            </Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  )
}

export default function DocumentComponents({
  ownerName,
  projectName,
  publication,
  gitRef,
}: {
  ownerName: string
  projectName: string
  publication: Publication
  gitRef?: string
}) {
  const { page_components_open: open } = routeApi.useSearch()
  const navigate = useNavigate({
    from: "/$accountName/$projectName/publications",
  })
  const query = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "document-components",
      publication.path,
      gitRef,
    ],
    queryFn: () =>
      ProjectsService.getProjectDocumentComponents({
        owner_name: ownerName,
        project_name: projectName,
        path: publication.path,
        ref: gitRef,
      }).then((response) => response.data),
    enabled: Boolean(publication.path),
    retry: false,
  })
  const data = query.data
  const items = data?.items ?? []
  // A document built without provenance has no record, which is not a
  // problem to report -- there is simply nothing to say
  if (!data || !data.built || items.length === 0) return null
  const nItems = items.length
  const nStale = data.n_stale ?? 0
  const nUndeclared = data.n_undeclared ?? 0
  return (
    <Box fontSize="sm" mb={1} wordBreak="break-word">
      <Text as="span" fontWeight="semibold">
        On the page:
      </Text>{" "}
      <Link
        onClick={() =>
          navigate({
            search: (prev) => ({ ...prev, page_components_open: true }),
          })
        }
      >
        {nItems} from the project
      </Link>
      {nStale > 0 ? (
        <Badge colorScheme="orange" ml={1}>
          {nStale} out of date
        </Badge>
      ) : null}
      {nUndeclared > 0 ? (
        <Badge colorScheme="orange" ml={1}>
          {nUndeclared} with no provenance
        </Badge>
      ) : null}
      <Modal
        isOpen={Boolean(open)}
        onClose={() =>
          navigate({
            search: (prev) => ({ ...prev, page_components_open: undefined }),
          })
        }
        size="4xl"
        isCentered
      >
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>
            What <Code>{data.document}</Code> takes from the project
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <Text fontSize="sm" color="gray.500" mb={3}>
              Values, figures and generated blocks the document injects rather
              than copies. Out of date means either the stage that makes it
              needs a rerun, or the project has moved on since this document was
              built -- the second is fixed by rebuilding, the first is not.
            </Text>
            <ComponentsTable items={items} />
          </ModalBody>
        </ModalContent>
      </Modal>
    </Box>
  )
}
