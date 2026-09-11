import {
  Box,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
} from "@chakra-ui/react"

import type { ReferenceEntry } from "../../client"

interface FileViewProps {
  isOpen: boolean
  onClose: () => void
  entry?: ReferenceEntry
}

const FileViewModal = ({ isOpen, onClose, entry }: FileViewProps) => {
  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={{ base: "xl", md: "xxl" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>{entry?.file_path}</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6} px={20}>
            <Box height="80vh">
              <embed src={String(entry?.url)} width="100%" height="100%" />
            </Box>
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  )
}

export default FileViewModal
