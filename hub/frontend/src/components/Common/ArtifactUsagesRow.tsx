/**
 * Where an artifact ends up in the project's papers.
 *
 * The reverse of a document's components: given a figure or a results file,
 * which documents typeset it and on which pages, so a change to a result
 * shows what it touches before it is made.
 */
import { Box, Link, Text } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"

import { type ArtifactUsage, ProjectsService } from "../../client"

/**
 * How one usage reads: the document, the key it appears under when the
 * artifact is a results file, and the pages it lands on.
 */
export function usageLabel(usage: ArtifactUsage): string {
  const pages = usage.pages ?? []
  const where =
    pages.length === 0
      ? ""
      : ` (${pages.length === 1 ? "p." : "pp."} ${pages.join(", ")})`
  return usage.key
    ? `${usage.document}: ${usage.key}${where}`
    : `${usage.document}${where}`
}

/**
 * Merge the usages of one artifact into one line per document, since a
 * results file cited under several keys is still one paper to go and look
 * at. Pages are pooled and ordered.
 */
export function usagesByDocument(
  usages: ArtifactUsage[],
): { document: string; keys: string[]; pages: number[] }[] {
  const byDocument = new Map<
    string,
    { document: string; keys: string[]; pages: number[] }
  >()
  for (const usage of usages) {
    const entry = byDocument.get(usage.document) ?? {
      document: usage.document,
      keys: [],
      pages: [],
    }
    if (usage.key && !entry.keys.includes(usage.key)) entry.keys.push(usage.key)
    for (const page of usage.pages ?? [])
      if (!entry.pages.includes(page)) entry.pages.push(page)
    byDocument.set(usage.document, entry)
  }
  return [...byDocument.values()]
    .map((entry) => ({
      ...entry,
      keys: [...entry.keys].sort(),
      pages: [...entry.pages].sort((a, b) => a - b),
    }))
    .sort((a, b) => a.document.localeCompare(b.document))
}

/** "pp. 3, 7", or nothing when the record names no page. */
export function pagesSuffix(pages: number[]): string {
  if (pages.length === 0) return ""
  return `${pages.length === 1 ? "p." : "pp."} ${pages.join(", ")}`
}

export default function ArtifactUsagesRow({
  ownerName,
  projectName,
  path,
  gitRef,
  publicationsTo = "../publications",
}: {
  ownerName: string
  projectName: string
  path: string
  gitRef?: string
  /** Route to the publications page, relative to where this is rendered. */
  publicationsTo?: string
}) {
  const query = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "artifact-usages",
      path,
      gitRef,
    ],
    queryFn: () =>
      ProjectsService.getProjectArtifactUsages({
        owner_name: ownerName,
        project_name: projectName,
        path,
        ref: gitRef,
      }).then((response) => response.data),
    enabled: Boolean(path),
    retry: false,
  })
  const usages = usagesByDocument(query.data?.items ?? [])
  // A project whose papers were never built with provenance on has no
  // record to read, and that is not a fact worth a row of its own
  if (usages.length === 0) return null
  return (
    <Box fontSize="sm" mb={1} wordBreak="break-word">
      <Text as="span" fontWeight="semibold">
        Used in:
      </Text>{" "}
      {usages.map((usage, index) => (
        <Text as="span" key={usage.document}>
          {index > 0 ? ", " : ""}
          <Link
            as={RouterLink}
            to={publicationsTo}
            search={{ path: usage.document, ref: gitRef } as any}
          >
            {usage.document}
          </Link>
          {usage.pages.length > 0 ? (
            <Text as="span" color="gray.500">
              {" "}
              {pagesSuffix(usage.pages)}
            </Text>
          ) : null}
        </Text>
      ))}
    </Box>
  )
}
