import {
  Code,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Text,
  Link,
} from "@chakra-ui/react"

import { type ProjectPublic } from "../../client"

interface CloneProjectProps {
  project: ProjectPublic
  isOpen: boolean
  onClose: () => void
}

const CloneProject = ({ project, isOpen, onClose }: CloneProjectProps) => {
  return (
    <>
      <Modal isOpen={isOpen} onClose={onClose} size="xl" isCentered>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Clone project</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6} maxW="100%">
            <Text mb={4}>
              To clone the project to your local machine, first ensure you have
              the{" "}
              <Link
                target="_blank"
                variant="blue"
                href="https://github.com/calkit/calkit?tab=readme-ov-file#installation"
              >
                Calkit CLI installed
              </Link>
              , then execute:
            </Text>
            <Code whiteSpace="pre" overflow="auto" p={2} width="100%">
              calkit clone {project.owner_account_name}/{project.name}
            </Code>
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  )
}

export default CloneProject
