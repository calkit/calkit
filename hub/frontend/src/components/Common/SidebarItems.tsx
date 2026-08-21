import { Box, Flex, Icon, Text, useColorModeValue } from "@chakra-ui/react"
import { Link, getRouteApi, useSearch } from "@tanstack/react-router"
import type { IconType } from "react-icons"
import { FaLaptop } from "react-icons/fa"
import { FaCubes } from "react-icons/fa"
import {
  FiBookOpen,
  FiDatabase,
  FiFolder,
  FiGitBranch,
  FiGrid,
  FiHardDrive,
  FiHome,
  FiImage,
  FiMonitor,
  FiTag,
  FiUsers,
} from "react-icons/fi"
import { IoLibraryOutline } from "react-icons/io5"
import { MdOutlineDashboard } from "react-icons/md"
import { SiJupyter } from "react-icons/si"
import { TiFlowMerge } from "react-icons/ti"
import useAuth from "../../hooks/useAuth"
import { useLocalServer } from "../../hooks/useOnboarding"

export interface ProjectNavItem {
  icon: IconType
  title: string
  path: string
  // Hidden from the sidebar and command palette when logged out.
  requiresLogin?: boolean
}

// The project's navigable sections, shared with the Cmd+K command palette.
export const projectNavItems: ProjectNavItem[] = [
  { icon: FiHome, title: "Project home", path: "" },
  { icon: MdOutlineDashboard, title: "Apps", path: "/apps" },
  { icon: TiFlowMerge, title: "Pipeline", path: "/pipeline" },
  { icon: FaCubes, title: "Environments", path: "/environments" },
  { icon: FiDatabase, title: "Datasets", path: "/datasets" },
  { icon: FiImage, title: "Figures", path: "/figures" },
  { icon: FiGrid, title: "Tables", path: "/tables" },
  { icon: FiBookOpen, title: "Publications", path: "/publications" },
  { icon: FiMonitor, title: "Presentations", path: "/presentations" },
  { icon: SiJupyter, title: "Notebooks", path: "/notebooks" },
  { icon: FiGitBranch, title: "History", path: "/history" },
  { icon: FiTag, title: "Releases", path: "/releases" },
  { icon: FiHardDrive, title: "Software", path: "/software" },
  {
    icon: FiUsers,
    title: "Collaborators",
    path: "/collaborators",
    requiresLogin: true,
  },
  { icon: IoLibraryOutline, title: "References", path: "/references" },
  { icon: FiFolder, title: "All files", path: "/files" },
  {
    icon: FaLaptop,
    title: "Local machine",
    path: "/local",
    requiresLogin: true,
  },
]

interface SidebarItemsProps {
  onClose?: () => void
  basePath: string
}

const SidebarItems = ({ onClose, basePath }: SidebarItemsProps) => {
  const textColor = useColorModeValue("ui.main", "ui.light")
  const bgActive = useColorModeValue("#E2E8F0", "#4A5568")
  const finalItems = projectNavItems
  const { user } = useAuth()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const currentRef: string | undefined = layoutSearch?.ref
  // Only controls the "running locally" icon color; the hook shares its
  // query with the onboarding checklist so the page asks localhost once.
  const { projectConnected } = useLocalServer(accountName, projectName)
  const localMachineColor = projectConnected ? "ui.success" : "gray"

  const listItems = finalItems.map(({ icon, title, path, requiresLogin }) => {
    if (requiresLogin && !user) {
      return null
    }

    return (
      <Flex
        key={title}
        as={Link}
        to={basePath + path}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        search={currentRef ? ({ ref: currentRef } as any) : undefined}
        w="100%"
        p={2}
        activeOptions={{ exact: true, includeSearch: false }}
        activeProps={{
          style: {
            background: bgActive,
            borderRadius: "12px",
          },
        }}
        color={textColor}
        onClick={onClose}
      >
        <Icon
          as={icon}
          color={title === "Local machine" ? localMachineColor : "default"}
          alignSelf="center"
        />
        <Text ml={2}>{title}</Text>
      </Flex>
    )
  })

  return (
    <>
      <Box>{listItems}</Box>
    </>
  )
}

export default SidebarItems
