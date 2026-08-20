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
import { useEffect } from "react"
import { FaGithub, FaPlus } from "react-icons/fa"
import { FiHelpCircle } from "react-icons/fi"

import { useQuery } from "@tanstack/react-query"

import { MiscService } from "../../client"
import useAuth from "../../hooks/useAuth"
import NewOrg from "../Orgs/NewOrg"
import NewProject from "../Projects/NewProject"
import UserMenu from "./UserMenu"
import GlobalSearch from "./GlobalSearch"
import HelpFeedback from "./HelpFeedback"
import NotificationBell from "./NotificationBell"

// "Docs" leaves the app entirely rather than going to a page that only
// links onward to the documentation site, which is where that content is
// actually maintained.
const NAV_LINKS: { label: string; to?: string; href?: string }[] = [
  { label: "Orgs", to: "/orgs" },
  { label: "Projects", to: "/projects" },
  { label: "Datasets", to: "/datasets" },
  { label: "Docs", href: "https://docs.calkit.org" },
]

/**
 * Which hub this is, next to the repo it's built from.
 *
 * Self-hosted instances make "which Calkit is this" a real question, and
 * the answer belongs where the project it comes from is already named.
 * Nothing is shown until the hub answers, since a version that renders as
 * a gap and then appears would shift the toolbar under the cursor.
 */
const HubVersion = () => {
  const { data } = useQuery({
    queryKey: ["hub-version"],
    queryFn: () => MiscService.getHubVersion().then((res) => res.data),
    // It cannot change without a deployment, which serves a new page
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  })
  const version = data?.version
  if (!version || version === "unknown") {
    return null
  }
  return (
    <Text fontSize="xs" color="gray.500" title="Hub version">
      hub/v{version}
    </Text>
  )
}

const NavLink = ({
  label,
  to,
  href,
}: { label: string; to?: string; href?: string }) => {
  const hoverBg = useColorModeValue("gray.200", "gray.700")
  const linkProps = href
    ? { as: "a" as const, href, target: "_blank", rel: "noopener noreferrer" }
    : { as: RouterLink, to }
  return (
    <Box
      {...(linkProps as any)}
      px={2}
      py={1}
      rounded={"md"}
      _hover={{ textDecoration: "none", bg: hoverBg }}
    >
      {label}
    </Box>
  )
}

export default function Topbar() {
  const { isOpen, onOpen, onClose } = useDisclosure()
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const { user } = useAuth()
  // The new-project button goes to the wizard now; this modal is still here
  // for the "use as template" form, which sends the user off to connect
  // GitHub and comes back with ?newProject=1 to be reopened.
  const newProjectModal = useDisclosure()
  const newOrgModal = useDisclosure()
  const helpModal = useDisclosure()
  // Reopen whichever creation modal sent the user off to connect GitHub,
  // and drop the marker so a refresh doesn't reopen it again
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const toReopen = params.get("newProject")
      ? newProjectModal
      : params.get("newOrg")
        ? newOrgModal
        : null
    if (toReopen) {
      params.delete("newProject")
      params.delete("newOrg")
      const query = params.toString()
      window.history.replaceState(
        {},
        "",
        window.location.pathname + (query ? `?${query}` : ""),
      )
      toReopen.onOpen()
    }
  }, [])
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
              {NAV_LINKS.map((link) => (
                <NavLink key={link.label} {...link} />
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
              as={RouterLink}
              to="/new"
            >
              <Icon as={FaPlus} mr={1} />
              New project
            </Button>
            {user ? (
              <>
                <Button
                  aria-label="help"
                  size="sm"
                  onClick={helpModal.onOpen}
                  leftIcon={<Icon as={FiHelpCircle} />}
                >
                  Help
                </Button>
                <HelpFeedback
                  isOpen={helpModal.isOpen}
                  onClose={helpModal.onClose}
                />
              </>
            ) : null}
            <NewProject
              onClose={newProjectModal.onClose}
              isOpen={newProjectModal.isOpen}
            />
            <Link
              isExternal
              href="https://github.com/calkit/calkit"
              aria-label="View GitHub repo."
            >
              <Flex alignItems={"center"} pt={0.5} pb={0.5} mr={-0.5}>
                <Icon fontSize="2xl" mr={1}>
                  <FaGithub />
                </Icon>
                <Text fontSize="xs">calkit/calkit</Text>
              </Flex>
            </Link>
            <HubVersion />
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
              {NAV_LINKS.map((link) => (
                <NavLink key={link.label} {...link} />
              ))}
            </Stack>
          </Box>
        ) : null}
      </Box>
    </>
  )
}
