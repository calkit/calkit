import type { ComponentType, ElementType } from "react"

import { Button, Flex, Icon, useDisclosure } from "@chakra-ui/react"
import { FaPlus } from "react-icons/fa"

interface NavbarProps {
  type: string
  addModalAs: ComponentType | ElementType
  verb?: string
  isOpen?: boolean
  onOpen?: () => void
  onClose?: () => void
}

const Navbar = ({
  type,
  addModalAs,
  verb,
  isOpen,
  onOpen,
  onClose,
}: NavbarProps) => {
  const addModal = useDisclosure()
  const open = isOpen ?? addModal.isOpen
  const handleOpen = onOpen ?? addModal.onOpen
  const handleClose = onClose ?? addModal.onClose
  const AddModal = addModalAs
  return (
    <>
      <Flex py={4} gap={4}>
        <Button
          variant="primary"
          gap={1}
          fontSize={{ base: "sm", md: "inherit" }}
          onClick={handleOpen}
        >
          <Icon as={FaPlus} /> {verb ? verb : "Add"} {type}
        </Button>
        <AddModal isOpen={open} onClose={handleClose} />
      </Flex>
    </>
  )
}

export default Navbar
