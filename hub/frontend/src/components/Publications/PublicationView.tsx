import { Alert, AlertIcon, Image } from "@chakra-ui/react"
import type { ReactNode } from "react"

import type { Publication } from "../../client"
import PdfDocumentViewer from "../Common/PdfDocumentViewer"

interface PubViewProps {
  publication: Publication
  // Optional element rendered in the PDF viewer toolbar, e.g. an "Edit LaTeX"
  // button. Only shown for PDF publications (the only type with a toolbar).
  toolbarAction?: ReactNode
}

function PublicationView({ publication, toolbarAction }: PubViewProps) {
  let contentView = <>Not set</>
  if (
    publication.path.endsWith(".pdf") &&
    (publication.content || publication.url)
  ) {
    contentView = (
      <PdfDocumentViewer
        url={
          publication.content
            ? `data:application/pdf;base64,${publication.content}`
            : String(publication.url)
        }
        source="showcase"
        defaultScale="page-width"
        toolbarAction={toolbarAction}
      />
    )
  } else if (
    publication.path.endsWith(".html") &&
    (publication.content || publication.url)
  ) {
    contentView = (
      // Sandboxed so an embedded deck (e.g. reveal.js) can't read or navigate
      // the host page. allow-same-origin and allow-top-navigation are both
      // omitted so the content runs in an opaque origin and can't reach the
      // parent (it also can't pollute the surrounding modal's history).
      <iframe
        title={publication.title || publication.path}
        style={{ height: "100%", width: "100%", border: "none" }}
        sandbox="allow-scripts allow-popups"
        src={
          publication.url
            ? String(publication.url)
            : `data:text/html;base64,${publication.content}`
        }
      />
    )
  } else if (
    publication.path.endsWith(".png") &&
    (publication.content || publication.url)
  ) {
    contentView = (
      <Image
        alt={publication.title}
        src={
          publication.content
            ? `data:image/png;base64,${publication.content}`
            : String(publication.url)
        }
      />
    )
  } else {
    contentView = (
      <Alert mt={2} status="warning" borderRadius="xl">
        <AlertIcon />
        No content found. Perhaps the publication hasn't been built and pushed
        yet?
      </Alert>
    )
  }
  return <>{contentView}</>
}

export default PublicationView
