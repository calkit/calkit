import { Image } from "@chakra-ui/react"
import type { ReactNode } from "react"

import SandboxedHtml from "../Common/SandboxedHtml"
import type { Publication } from "../../client"
import NotBuiltAlert from "../Common/NotBuiltAlert"
import PdfDocumentViewer from "../Common/PdfDocumentViewer"

interface PubViewProps {
  publication: Publication
  // Optional element rendered in the PDF viewer toolbar, e.g. an "Edit LaTeX"
  // button. Shown for PDF publications (the only type with a toolbar) and in
  // the no-content fallback, so an unbuilt publication can still be edited.
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
      <SandboxedHtml
        title={publication.title || publication.path}
        content={publication.content}
        url={publication.url}
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
      <NotBuiltAlert
        kind="publication"
        stage={publication.stage}
        path={publication.path}
        action={toolbarAction}
      />
    )
  }
  return <>{contentView}</>
}

export default PublicationView
