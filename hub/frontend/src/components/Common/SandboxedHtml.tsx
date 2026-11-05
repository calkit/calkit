import { Flex, Spinner, Text } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"

import { decodeBase64Utf8 } from "../../lib/strings"

interface SandboxedHtmlProps {
  title: string
  /** The page itself, when the caller already has it as text. */
  html?: string | null
  /** The page as base64, as the contents endpoints return it inline. */
  content?: string | null
  /** Where to read the page from when it isn't inline, e.g., a large file. */
  url?: string | null
  height?: string
}

/** Project HTML, embedded as untrusted content.
 *
 * Every page a project supplies (rendered notebooks, reports, decks, HTML
 * figures) goes through here so the policy lives in one place:
 *
 * - sandbox="allow-scripts allow-popups" without allow-same-origin, so the
 *   page runs in an opaque origin with no access to this page, its DOM or
 *   its storage, where the auth token is kept. Forms, dialogs and top-level
 *   navigation are blocked. Popups are allowed so links and a deck's speaker
 *   notes open, and inherit the same sandbox, since
 *   allow-popups-to-escape-sandbox is not granted.
 * - srcDoc rather than src, so the frame never holds a signed download URL
 *   its scripts could read from location and send elsewhere, and storage
 *   headers can't turn the frame into a download.
 * - Fetched without credentials or a referrer, so nothing identifying the
 *   viewer goes to a URL the project controls.
 */
function SandboxedHtml({
  title,
  html,
  content,
  url,
  height = "100%",
}: SandboxedHtmlProps) {
  const inline = html ?? (content ? decodeBase64Utf8(content) : null)
  const fetched = useQuery({
    queryKey: ["sandboxed-html", url],
    queryFn: async () => {
      const response = await fetch(String(url), {
        credentials: "omit",
        referrerPolicy: "no-referrer",
      })
      if (!response.ok) {
        throw new Error(`Could not load ${title}`)
      }
      return response.text()
    },
    enabled: inline == null && Boolean(url),
    retry: false,
  })
  const doc = inline ?? fetched.data
  if (doc == null) {
    return (
      <Flex height={height} align="center" justify="center" color="gray.500">
        {fetched.isError || !url ? (
          <Text fontSize="sm">Couldn't load {title}.</Text>
        ) : (
          <Spinner />
        )}
      </Flex>
    )
  }
  return (
    <iframe
      title={title}
      style={{ height, width: "100%", border: "none" }}
      sandbox="allow-scripts allow-popups"
      referrerPolicy="no-referrer"
      srcDoc={doc}
    />
  )
}

export default SandboxedHtml
