import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Badge,
  Box,
  Code,
  Container,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  Flex,
  Heading,
  Icon,
  IconButton,
  Input,
  Link,
  Menu,
  MenuButton,
  MenuDivider,
  MenuItem,
  MenuList,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Portal,
  Spinner,
  Text,
  VStack,
  useDisclosure,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import {
  Outlet,
  createFileRoute,
  notFound,
  useNavigate,
} from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import { useEffect, useState } from "react"
import { BsThreeDots } from "react-icons/bs"
import { FaCodeBranch } from "react-icons/fa"
import { FaGithub, FaQuestion, FaRegClone } from "react-icons/fa"
import { LuCopyPlus } from "react-icons/lu"
import { MdEdit } from "react-icons/md"
import { z } from "zod"

import {
  type GitRef,
  type ProjectPublic,
  ProjectsService,
} from "../../../../client"
import LoadingSpinner from "../../../../components/Common/LoadingSpinner"
import ProjectCommandPalette from "../../../../components/Common/ProjectCommandPalette"
import Sidebar from "../../../../components/Common/Sidebar"
import CloneProject from "../../../../components/Projects/CloneProject"
import EditProject from "../../../../components/Projects/EditProject"
import HelpContent from "../../../../components/Projects/HelpContent"
import MakeProjectPublic from "../../../../components/Projects/MakeProjectPublic"
import NewProject from "../../../../components/Projects/NewProject"
import ProjectStatus from "../../../../components/Projects/ProjectStatus"
import useAuth from "../../../../hooks/useAuth"
import useProject from "../../../../hooks/useProject"
import { isAuthenticationError } from "../../../../lib/auth"

interface CommitHistory {
  hash: string
  short_hash: string
  message: string
  author: string
  author_email: string
  timestamp: string
  committed_date: number
  parent_hashes: string[]
  summary: string
}

const layoutSearchSchema = z.object({
  ref: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout",
)({
  component: ProjectLayout,
  validateSearch: (search) => layoutSearchSchema.parse(search),
})

function SwitchVersionModal({
  isOpen,
  onClose,
  branches,
  currentRef,
  defaultBranchName,
  onSetRef,
  accountName,
  projectName,
}: {
  isOpen: boolean
  onClose: () => void
  branches: GitRef[]
  currentRef: string | undefined
  defaultBranchName: string | undefined
  onSetRef: (ref: string | undefined) => void
  accountName: string
  projectName: string
}) {
  const [query, setQuery] = useState("")

  const commitsQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "git-history-all"],
    queryFn: async () =>
      (await ProjectsService.getProjectHistory({
        owner_name: accountName,
        project_name: projectName,
        limit: 100,
      }).then((response) => response.data)) as unknown as CommitHistory[],
    enabled: isOpen,
  })

  const filteredBranches = branches.filter((r) =>
    r.name.toLowerCase().includes(query.toLowerCase()),
  )
  const filteredCommits = (commitsQuery.data ?? []).filter(
    (c: CommitHistory) =>
      c.summary.toLowerCase().includes(query.toLowerCase()) ||
      c.short_hash.toLowerCase().includes(query.toLowerCase()),
  )

  const handleSelect = (ref: string, isDefault?: boolean) => {
    onSetRef(isDefault ? undefined : ref)
    onClose()
    setQuery("")
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => {
        onClose()
        setQuery("")
      }}
      size="md"
    >
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Switch version</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={4}>
          <Input
            placeholder="Search branches or commits…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            mb={3}
            autoFocus
          />
          <VStack align="stretch" spacing={1} maxH="60vh" overflowY="auto">
            {filteredBranches.length > 0 && (
              <>
                <Text
                  fontSize="xs"
                  color="gray.500"
                  fontWeight="semibold"
                  px={2}
                  pt={1}
                >
                  Branches
                </Text>
                {filteredBranches.map((r) => (
                  <Box
                    key={r.name}
                    px={2}
                    py={1}
                    borderRadius="md"
                    cursor="pointer"
                    fontWeight={
                      (currentRef ?? defaultBranchName) === r.name
                        ? "semibold"
                        : "normal"
                    }
                    _hover={{ bg: "gray.100", _dark: { bg: "gray.700" } }}
                    onClick={() => handleSelect(r.name, r.is_default)}
                  >
                    <Flex align="center" gap={2}>
                      <Icon as={FaCodeBranch} fontSize="xs" color="gray.400" />
                      <Text fontSize="sm">{r.name}</Text>
                      {r.is_default && (
                        <Badge colorScheme="green" fontSize="xs">
                          default
                        </Badge>
                      )}
                    </Flex>
                  </Box>
                ))}
              </>
            )}
            {filteredCommits.length > 0 && (
              <>
                <Text
                  fontSize="xs"
                  color="gray.500"
                  fontWeight="semibold"
                  px={2}
                  pt={2}
                >
                  Commits
                </Text>
                {filteredCommits.map((c: CommitHistory) => (
                  <Box
                    key={c.hash}
                    px={2}
                    py={1}
                    borderRadius="md"
                    cursor="pointer"
                    fontWeight={
                      currentRef === c.short_hash ? "semibold" : "normal"
                    }
                    _hover={{ bg: "gray.100", _dark: { bg: "gray.700" } }}
                    onClick={() => handleSelect(c.short_hash)}
                  >
                    <Flex align="center" gap={2}>
                      <Code fontSize="xs" flexShrink={0}>
                        {c.short_hash}
                      </Code>
                      <Text fontSize="sm" noOfLines={1}>
                        {c.summary}
                      </Text>
                    </Flex>
                    <Text fontSize="xs" color="gray.500" pl={7}>
                      {new Date(c.timestamp).toLocaleDateString()}
                    </Text>
                  </Box>
                ))}
                {commitsQuery.isPending && (
                  <Flex justify="center" py={2}>
                    <Spinner size="sm" color="ui.main" />
                  </Flex>
                )}
              </>
            )}
            {filteredBranches.length === 0 &&
              filteredCommits.length === 0 &&
              !commitsQuery.isPending && (
                <Text fontSize="sm" color="gray.500" px={2}>
                  No results
                </Text>
              )}
          </VStack>
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

interface ProjectMenuProps {
  project: ProjectPublic
  userHasWriteAccess: boolean
  branches: GitRef[]
  currentRef: string | undefined
  defaultBranchName: string | undefined
  onSetRef: (ref: string | undefined) => void
  accountName: string
  projectName: string
}

function ProjectMenu({
  project,
  userHasWriteAccess,
  branches,
  currentRef,
  defaultBranchName,
  onSetRef,
  accountName,
  projectName,
}: ProjectMenuProps) {
  const { user } = useAuth()
  const editProjectModal = useDisclosure()
  const newProjectModal = useDisclosure()
  const cloneProjectModal = useDisclosure()
  const switchVersionModal = useDisclosure()

  return (
    <>
      <Menu>
        <MenuButton as={IconButton} icon={<BsThreeDots />} size="xs" mr={1} />
        <Portal>
          <MenuList zIndex="popover">
            <MenuItem
              icon={<MdEdit fontSize={18} />}
              onClick={editProjectModal.onOpen}
              isDisabled={!userHasWriteAccess}
            >
              Edit title or description
            </MenuItem>
            <MenuItem
              icon={<LuCopyPlus fontSize={18} />}
              onClick={newProjectModal.onOpen}
              isDisabled={!user}
            >
              Use this project as a template
            </MenuItem>
            <MenuItem
              icon={<FaRegClone fontSize={18} />}
              onClick={cloneProjectModal.onOpen}
            >
              Clone to local machine
            </MenuItem>
            <MenuDivider />
            <MenuItem
              icon={<FaCodeBranch fontSize={16} />}
              onClick={switchVersionModal.onOpen}
            >
              Switch version
            </MenuItem>
          </MenuList>
        </Portal>
      </Menu>
      <EditProject
        project={project}
        isOpen={editProjectModal.isOpen}
        onClose={editProjectModal.onClose}
      />
      <NewProject
        isOpen={newProjectModal.isOpen}
        onClose={newProjectModal.onClose}
        defaultTemplate={`${project.owner_account_name}/${project.name}`}
      />
      <CloneProject
        project={project}
        isOpen={cloneProjectModal.isOpen}
        onClose={cloneProjectModal.onClose}
      />
      <SwitchVersionModal
        isOpen={switchVersionModal.isOpen}
        onClose={switchVersionModal.onClose}
        branches={branches}
        currentRef={currentRef}
        defaultBranchName={defaultBranchName}
        onSetRef={onSetRef}
        accountName={accountName}
        projectName={projectName}
      />
    </>
  )
}

function ProjectLayout() {
  const { accountName, projectName } = Route.useParams()
  const { ref: currentRef } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { projectRequest, userHasWriteAccess } = useProject(
    accountName,
    projectName,
  )
  const isPending = projectRequest.isPending
  const error = projectRequest.error
  const project = projectRequest.data
  // A session/token 403 (an expired token that briefly slipped through) is not
  // a missing project — don't render NotFound for it; the auth layer refreshes
  // or logs out. Only a real 404 or a genuine permission denial is NotFound.
  if (
    error?.message === "Not Found" ||
    (error?.message === "Forbidden" && !isAuthenticationError(error))
  ) {
    throw notFound()
  }
  // Redirect to canonical casing if URL doesn't match the stored names
  useEffect(() => {
    if (!project) return
    const canonicalOwner = project.owner_account_name
    const canonicalProject = project.name
    if (accountName !== canonicalOwner || projectName !== canonicalProject) {
      navigate({
        params: { accountName: canonicalOwner, projectName: canonicalProject },
        search: (s: any) => s,
        replace: true,
      })
    }
  }, [project, accountName, projectName, navigate])
  const helpDrawer = useDisclosure()
  const refsQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "refs"],
    queryFn: () =>
      ProjectsService.searchProjectRefs({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: !isPending,
  })
  const branches = (refsQuery.data ?? []).filter(
    (r: GitRef) => r.kind === "branch",
  )
  const defaultBranch = branches.find((r: GitRef) => r.is_default)

  const setRef = (newRef: string | undefined) => {
    navigate({ search: (prev) => ({ ...prev, ref: newRef }) })
  }

  const titleSize = "lg"
  const onClickHelp = () => {
    // Record which page's help was opened (home, releases, pipeline, …) so we
    // can see which concepts users look up.
    const lastSeg = location.pathname.split("/").filter(Boolean).pop()
    const helpPage = !lastSeg || lastSeg === projectName ? "home" : lastSeg
    mixpanel.track("Clicked project help button", { page: helpPage })
    helpDrawer.onOpen()
  }
  const projectStatusModal = useDisclosure()
  const projectPublicModal = useDisclosure()

  return (
    <>
      {isPending ? (
        <LoadingSpinner height="100vh" />
      ) : (
        <Flex>
          <ProjectCommandPalette />
          <Sidebar basePath={`/${accountName}/${projectName}`} />
          <Container
            maxW="full"
            mx={6}
            height="calc(100vh - 64px)"
            overflow="hidden"
            display="flex"
            flexDirection="column"
            px={0}
          >
            <Container
              maxW="100%"
              alignContent="center"
              alignItems="center"
              mt={5}
              mb={4}
              display="flex"
              flexWrap="wrap"
              px={0}
              flexShrink={0}
            >
              <Box maxW="100%" mr={2}>
                <Heading size={titleSize}>{project?.title}</Heading>
              </Box>
              {currentRef && currentRef !== defaultBranch?.name && (
                <Box mr={2} pb={0.5} alignSelf="center">
                  <Code
                    fontSize="xs"
                    cursor="pointer"
                    title="Click to reset to default branch"
                    onClick={() => setRef(undefined)}
                    px={2}
                    py={0.5}
                    borderRadius="md"
                    colorScheme="orange"
                  >
                    {currentRef} ✕
                  </Code>
                </Box>
              )}
              {/* Public/private badge */}
              <Box mr={2} pb={0.5}>
                <Badge
                  color={project?.is_public ? "green.500" : "yellow.500"}
                  onClick={() => {
                    !project?.is_public ? projectPublicModal.onOpen() : null
                  }}
                  cursor={!project?.is_public ? "pointer" : "default"}
                >
                  {project?.is_public ? "Public" : "Private"}
                </Badge>
                {project && !project?.is_public ? (
                  <MakeProjectPublic
                    project={project}
                    isOpen={projectPublicModal.isOpen}
                    onClose={projectPublicModal.onClose}
                  />
                ) : (
                  ""
                )}
              </Box>
              {/* Status badge */}
              <Box mr={2} pb={0.5}>
                <Link>
                  <Badge
                    color={
                      project?.status === "in-progress"
                        ? "green.500"
                        : project?.status === "completed"
                          ? "blue.500"
                          : "gray.500"
                    }
                    onClick={projectStatusModal.onOpen}
                  >
                    {project?.status
                      ? project.status.replaceAll("-", " ")
                      : "no status"}
                  </Badge>
                </Link>
                {project ? (
                  <ProjectStatus
                    project={project}
                    isOpen={projectStatusModal.isOpen}
                    onClose={projectStatusModal.onClose}
                  />
                ) : (
                  ""
                )}
              </Box>
              {/* GitHub link */}
              {project?.git_repo_url ? (
                <Box mr={2}>
                  <Link href={project?.git_repo_url} isExternal>
                    <Flex alignItems="center">
                      <Icon as={FaGithub} pt={0.5} />
                      <Icon as={ExternalLinkIcon} />
                    </Flex>
                  </Link>
                </Box>
              ) : (
                ""
              )}
              <Box mr={2}>
                <Flex>
                  {project ? (
                    <ProjectMenu
                      project={project}
                      userHasWriteAccess={userHasWriteAccess}
                      branches={branches}
                      currentRef={currentRef}
                      defaultBranchName={defaultBranch?.name}
                      onSetRef={setRef}
                      accountName={accountName}
                      projectName={projectName}
                    />
                  ) : (
                    ""
                  )}
                  <IconButton
                    isRound
                    aria-label="Open help"
                    size={"xs"}
                    onClick={onClickHelp}
                    icon={<FaQuestion />}
                  />
                </Flex>
              </Box>
              <Box>
                {project?.description ? (
                  <Text fontSize="small">→ {project.description}</Text>
                ) : (
                  ""
                )}
              </Box>
            </Container>
            <Box flex={1} overflowY="auto" minH={0}>
              <Outlet />
            </Box>
          </Container>
          <Drawer
            isOpen={helpDrawer.isOpen}
            onClose={helpDrawer.onClose}
            placement="right"
            size="sm"
          >
            <DrawerOverlay />
            <DrawerContent>
              <DrawerCloseButton />
              <DrawerHeader>Help</DrawerHeader>
              <DrawerBody>
                <HelpContent userHasWriteAccess={userHasWriteAccess} />
              </DrawerBody>
            </DrawerContent>
          </Drawer>
        </Flex>
      )}
    </>
  )
}
