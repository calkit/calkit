import { CloseIcon, HamburgerIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Flex,
  HStack,
  Icon,
  IconButton,
  Image,
  Link,
  Stack,
  Text,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { Link as RouterLink, useNavigate } from "@tanstack/react-router"
import { FaGithub, FaPlus } from "react-icons/fa"

import useAuth from "../../hooks/useAuth"
import NewOrg from "../Orgs/NewOrg"
import NewProject from "../Projects/NewProject"
import UserMenu from "./UserMenu"
import GlobalSearch from "./GlobalSearch"
import NotificationBell from "./NotificationBell"

interface Props {
  children: React.ReactNode
}

const Links = ["Orgs", "Projects", "Datasets", "Learn"]

const getPath = (link: React.ReactNode) => {
  const linkString = link?.toString()
  return `/${linkString?.toLowerCase()}`
}

const NavLink = (props: Props) => {
  const { children } = props

  return (
    <Box
      as={RouterLink}
      px={2}
      py={1}
      rounded={"md"}
      _hover={{
        textDecoration: "none",
        bg: useColorModeValue("gray.200", "gray.700"),
      }}
      to={getPath(children)}
    >
      {children}
    </Box>
  )
}

export default function Topbar() {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const { user } = useAuth()
  const newProjectModal = useDisclosure()
  const newOrgModal = useDisclosure()
  const navigate = useNavigate()
  const goToLoginWithRedirect = () => {
    const href =
      typeof window !== "undefined"
        ? `${window.location.pathname}${window.location.search}${window.location.hash}`
        : "/"
    localStorage.setItem("post_login_redirect", href)
    navigate({ to: "/login" })
  }

  return (
    <>
      <Box
        bg={secBgColor}
        px={4}
        position={"sticky"}
        top={0}
        h={16}
        zIndex={1000}
      >
        <Flex h={16} alignItems={"center"} justifyContent={"space-between"}>
          <IconButton
            size={"md"}
            icon={isOpen ? <CloseIcon /> : <HamburgerIcon />}
            aria-label={"Open Menu"}
            display={{ md: "none" }}
            onClick={isOpen ? onClose : onOpen}
          />
          <HStack spacing={8} alignItems={"center"}>
            <Box px={8}>
              <Link as={RouterLink} to="/">
                <Image
                  width={"80px"}
                  src="/assets/images/calkit.svg"
                  alt="Calkit logo"
                />
              </Link>
            </Box>
            <HStack
              as={"nav"}
              spacing={4}
              display={{ base: "none", md: "flex" }}
            >
              {Links.map((link) => (
                <NavLink key={link}>{link}</NavLink>
              ))}
            </HStack>
          </HStack>
          <Flex alignItems={"center"} gap={2}>
            <GlobalSearch />
            <Button
              aria-label="new-org"
              size="sm"
              onClick={user ? newOrgModal.onOpen : goToLoginWithRedirect}
            >
              <Icon as={FaPlus} mr={1} />
              New org
            </Button>
            <NewOrg onClose={newOrgModal.onClose} isOpen={newOrgModal.isOpen} />
            <Button
              aria-label="new-project"
              size="sm"
              onClick={user ? newProjectModal.onOpen : goToLoginWithRedirect}
            >
              <Icon as={FaPlus} mr={1} />
              New project
            </Button>
            <NewProject
              onClose={newProjectModal.onClose}
              isOpen={newProjectModal.isOpen}
            />
            <Link
              isExternal
              href="https://github.com/calkit/calkit-cloud"
              aria-label="View GitHub repo."
            >
              <Flex alignItems={"center"} pt={0.5} pb={0.5}>
                <Icon fontSize="2xl" mr={1}>
                  <FaGithub />
                </Icon>
                <Text fontSize="xs">calkit/calkit-cloud</Text>
              </Flex>
            </Link>
            {user && <NotificationBell />}
            {user ? (
              <UserMenu />
            ) : (
              <Link
                as={RouterLink}
                to={"/login"}
                onClick={(event) => {
                  event.preventDefault()
                  goToLoginWithRedirect()
                }}
              >
                <Button variant="primary">Sign in</Button>
              </Link>
            )}
          </Flex>
        </Flex>
        {isOpen ? (
          <Box pb={4} display={{ md: "none" }}>
            <Stack as={"nav"} spacing={4}>
              {Links.map((link) => (
                <NavLink key={link}>{link}</NavLink>
              ))}
            </Stack>
          </Box>
        ) : null}
      </Box>
    </>
  )
}
