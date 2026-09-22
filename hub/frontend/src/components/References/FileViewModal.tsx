import {
  Box,
  Image,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Text,
} from "@chakra-ui/react"

import type { ReferenceEntry } from "../../client"
import PdfDocumentViewer from "../Common/PdfDocumentViewer"
import SandboxedHtml from "../Common/SandboxedHtml"

interface FileViewProps {
  isOpen: boolean
  onClose: () => void
  entry?: ReferenceEntry
}

// An attachment is rendered by type, never handed to the browser to embed
// as-is: an HTML snapshot, or HTML served under another extension, would
// otherwise run unsandboxed and could navigate this tab.
function Attachment({ path, url }: { path: string; url: string }) {
  const lower = path.toLowerCase()
  if (lower.endsWith(".pdf")) {
    return <PdfDocumentViewer url={url} source="reference" />
  }
  if (lower.endsWith(".html") || lower.endsWith(".htm")) {
    return <SandboxedHtml title={path} url={url} />
  }
  if (/\.(png|jpe?g|gif|webp)$/.test(lower)) {
    return <Image src={url} alt={path} maxH="100%" mx="auto" />
  }
  return (
    <Text fontSize="sm">
      This attachment can't be previewed.{" "}
      <Link href={url} isExternal color="blue.500">
        Open it
      </Link>
    </Text>
  )
}

const FileViewModal = ({ isOpen, onClose, entry }: FileViewProps) => {
  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={{ base: "xl", md: "xxl" }}
        isCentered
        motionPreset="none"
      >
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>{entry?.file_path}</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6} px={20}>
            <Box height="80vh">
              {entry?.url ? (
                <Attachment path={entry.file_path ?? ""} url={entry.url} />
              ) : (
                <Text fontSize="sm" color="gray.500">
                  No file is attached.
                </Text>
              )}
            </Box>
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  )
}

export default FileViewModal
