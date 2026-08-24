import {
  Code,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Box,
} from "@chakra-ui/react"
import SyntaxHighlighter from "react-syntax-highlighter"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"

import { Environment } from "../../client"

interface ViewEnvProps {
  environment: Environment
  isOpen: boolean
  onClose: () => void
}

const ViewEnvironment = ({ environment, isOpen, onClose }: ViewEnvProps) => {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="2xl"
      isCentered
      scrollBehavior="inside"
    >
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>
          View environment: <Code fontSize="md">{environment.name}</Code>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <Box borderRadius="md" overflow="hidden" fontSize="sm">
            <SyntaxHighlighter
              language="yaml"
              style={atomOneDark}
              customStyle={{
                margin: 0,
                borderRadius: "8px",
                maxHeight: "70vh",
              }}
              showLineNumbers={false}
            >
              {environment.file_content ?? ""}
            </SyntaxHighlighter>
          </Box>
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default ViewEnvironment
