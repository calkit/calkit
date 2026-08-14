import { Box, Flex, Icon, Text, useColorModeValue } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link, getRouteApi, useSearch } from "@tanstack/react-router"
import axios from "axios"
import { FaLaptop } from "react-icons/fa"
import { FaCubes } from "react-icons/fa"
import {
  FiBookOpen,
  FiDatabase,
  FiFolder,
  FiGitBranch,
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
import type { IconType } from "react-icons"
import useAuth from "../../hooks/useAuth"

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
  const {
    isPending: localServerPending,
    error: localServerError,
    data: localServerData,
  } = useQuery({
    queryKey: ["local-server-sidebar", accountName, projectName],
    queryFn: () =>
      // The Calkit local server is usually not running. Fail fast so a
      // silently-dropped connection can't leave a request hanging; the
      // result only controls the sidebar "running locally" icon color.
      axios.get(
        `http://localhost:8866/projects/${accountName}/${projectName}`,
        { timeout: 2000 },
      ),
    retry: false,
  })
  const localMachineColor =
    localServerError || localServerPending || !localServerData
      ? "gray"
      : "ui.success"

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
