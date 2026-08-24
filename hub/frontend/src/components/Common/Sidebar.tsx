import {
  Box,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerOverlay,
  Flex,
  IconButton,
  Image,
  Text,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { FiLogOut, FiMenu } from "react-icons/fi"

import Logo from "/assets/images/kdot.svg"
import useAuth from "../../hooks/useAuth"
import SidebarItems from "./SidebarItems"

interface SidebarProps {
  basePath: string
}

const Sidebar = ({ basePath }: SidebarProps) => {
  const bgColor = useColorModeValue("ui.light", "ui.dark")
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const { isOpen, onOpen, onClose } = useDisclosure()
  const { logout } = useAuth()

  const handleLogout = async () => {
    logout()
  }

  return (
    <>
      {/* Mobile */}
      <IconButton
        onClick={onOpen}
        display={{ base: "flex", md: "none" }}
        aria-label="Open Menu"
        position="absolute"
        fontSize="20px"
        m={4}
        icon={<FiMenu />}
      />
      <Drawer isOpen={isOpen} placement="left" onClose={onClose}>
        <DrawerOverlay />
        <DrawerContent maxW="250px">
          <DrawerCloseButton />
          <DrawerBody py={8}>
            <Flex flexDir="column" justify="space-between">
              <Box>
                <Image src={Logo} alt="logo" p={6} />
                <SidebarItems onClose={onClose} basePath={basePath} />
                <Flex
                  as="button"
                  onClick={handleLogout}
                  p={2}
                  color="ui.danger"
                  fontWeight="bold"
                  alignItems="center"
                >
                  <FiLogOut />
                  <Text ml={2}>Log out</Text>
                </Flex>
              </Box>
            </Flex>
          </DrawerBody>
        </DrawerContent>
      </Drawer>
      {/* Desktop */}
      <Box
        bg={bgColor}
        h="calc(100vh - 64px)"
        position="sticky"
        left="0"
        top={16}
        display={{ base: "none", md: "flex" }}
      >
        <Flex flexDir="column" justify="space-between" bg={secBgColor} p={4}>
          <Box minW="150px" mt={2}>
            <SidebarItems basePath={basePath} />
          </Box>
        </Flex>
      </Box>
    </>
  )
}

export default Sidebar
