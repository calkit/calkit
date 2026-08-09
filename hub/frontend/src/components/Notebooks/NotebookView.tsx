import { Alert, AlertIcon } from "@chakra-ui/react"

import { type Notebook } from "../../client"

interface NotebookViewProps {
  notebook: Notebook
}

function NotebookView({ notebook }: NotebookViewProps) {
  let contentView = <>Not set</>
  if (notebook.output_format === "html" && (notebook.content || notebook.url)) {
    contentView = (
      <embed
        height="100%"
        width="100%"
        type="text/html"
        src={
          notebook.url
            ? String(notebook.url)
            : `data:text/html;base64,${notebook.content}`
        }
        style={{ borderRadius: "0px" }}
      />
    )
  } else {
    contentView = (
      <Alert mt={2} status="warning" borderRadius="xl">
        <AlertIcon />
        Cannot render content, either because it is empty or an unrecognized
        file type.
      </Alert>
    )
  }
  return <>{contentView}</>
}

export default NotebookView
