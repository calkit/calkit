import {
  Badge,
  Box,
  Flex,
  Heading,
  Icon,
  IconButton,
  Link,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Spinner,
  Text,
  useClipboard,
  useDisclosure,
} from "@chakra-ui/react"
import Tooltip from "../Common/Tooltip"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { useState } from "react"
import { FaPlus, FaTag } from "react-icons/fa"
import { FiExternalLink, FiLink, FiShare2 } from "react-icons/fi"

import { ReleasesService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { releaseLocation, releasePagePath } from "../../lib/releases"
import NewRelease from "./NewRelease"
import ShareDialog from "./ShareDialog"

interface ArtifactReleasesPanelProps {
  ownerName: string
  projectName: string
  path: string
  userHasWriteAccess: boolean
  // Calkit artifact kind for the "new release" shortcut (e.g. "publication",
  // "presentation"); also used in the button label.
  kind?: string
}

/**
 * Compact list of releases that point at a specific artifact path, with a
 * shortcut to create a new one. Each release name links to its release page.
 * Rendered inside a publication/presentation info panel.
 */
const ArtifactReleasesPanel = ({
  ownerName,
  projectName,
  path,
  userHasWriteAccess,
  kind = "publication",
}: ArtifactReleasesPanelProps) => {
  const newReleaseModal = useDisclosure()
  const shareModal = useDisclosure()
  // The release name to share, plus whether the New Release flow was opened to
  // share its result (vs. just creating a release).
  const [shareName, setShareName] = useState<string | null>(null)
  const [shareAfterCreate, setShareAfterCreate] = useState(false)
  // Shares its cache with the History page's releases table/badges.
  const releasesQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "releases", undefined],
    queryFn: () =>
      ReleasesService.getProjectReleases({ ownerName, projectName }),
  })
  // Only releases that specifically target this artifact's path -- not
  // whole-project releases, which would otherwise flood every artifact's panel
  // (e.g. after importing many project releases from GitHub).
  const matching = (releasesQuery.data ?? []).filter((r) => r.path === path)
  // Only cloud (Calkit-hosted) releases can be shared via a link; external ones
  // live on a third-party venue.
  const shareable = matching.filter((r) => r.source === "cloud")
  const openShare = (name: string) => {
    setShareName(name)
    shareModal.onOpen()
  }
  const showToast = useCustomToast()
  // A direct link to this artifact's page, so sharing doesn't require a
  // release. It opens the project shell, so it's only useful to project members
  // (vs. a release's no-signup share link).
  const kindRoute = kind === "presentation" ? "presentations" : "publications"
  const artifactUrl = `${window.location.origin}/${ownerName}/${projectName}/${kindRoute}?path=${encodeURIComponent(path)}`
  const { onCopy: onCopyArtifact } = useClipboard(artifactUrl)
  const copyArtifactLink = () => {
    onCopyArtifact()
    showToast(
      "Link copied",
      `A link to this ${kind} was copied. Project members can open it.`,
      "success",
    )
  }
  const createReleaseToShare = () => {
    setShareAfterCreate(true)
    newReleaseModal.onOpen()
  }
  const closeNewRelease = () => {
    newReleaseModal.onClose()
    setShareAfterCreate(false)
  }

  return (
    <Box>
      <Flex align="center" mb={1}>
        <Heading size="sm">Releases</Heading>
        {userHasWriteAccess && (
          <>
            <Tooltip label={`Create release of this ${kind}`}>
              <IconButton
                aria-label="Create release"
                icon={<FaPlus />}
                size="xs"
                variant="primary"
                ml={2}
                onClick={newReleaseModal.onOpen}
              />
            </Tooltip>
            <Menu>
              <Tooltip label={`Share this ${kind}`}>
                <MenuButton
                  as={IconButton}
                  aria-label="Share"
                  icon={<FiShare2 />}
                  size="xs"
                  variant="ghost"
                  ml={1}
                />
              </Tooltip>
              <MenuList>
                {shareable.length > 0 && (
                  <MenuItem
                    icon={<FiShare2 />}
                    onClick={() => openShare(shareable[0].name)}
                  >
                    Share release {shareable[0].name}
                  </MenuItem>
                )}
                <MenuItem icon={<FiLink />} onClick={copyArtifactLink}>
                  Copy link to this {kind}
                </MenuItem>
                <MenuItem icon={<FaPlus />} onClick={createReleaseToShare}>
                  Create a release to share a version
                </MenuItem>
              </MenuList>
            </Menu>
          </>
        )}
      </Flex>
      {releasesQuery.isPending ? (
        <Spinner size="sm" color="ui.main" />
      ) : releasesQuery.isError ? (
        <Text fontSize="sm" color="red.500">
          Failed to load releases.
        </Text>
      ) : matching.length === 0 ? (
        <Text fontSize="sm" color="gray.500">
          None yet
        </Text>
      ) : (
        matching.map((r) => (
          <Flex key={`${r.source}-${r.name}`} align="center" gap={1} mb={0.5}>
            <Icon as={FaTag} fontSize="xs" color="gray.400" flexShrink={0} />
            <Link
              as={RouterLink}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              to={releasePagePath(ownerName, projectName, r.name) as any}
              fontSize="sm"
              color="blue.500"
              flex={1}
              noOfLines={1}
            >
              {r.name}
            </Link>
            {(() => {
              // Show where it was released to -- "Calkit" (hosted for review)
              // or the external venue (Zenodo, arXiv, …) -- not public/private.
              const dest = releaseLocation(r)
              return (
                <>
                  <Badge
                    colorScheme={dest.internal ? "blue" : "purple"}
                    fontSize="xs"
                    flexShrink={0}
                  >
                    {dest.label}
                  </Badge>
                  {dest.href && (
                    <Link
                      href={dest.href}
                      isExternal
                      flexShrink={0}
                      display="inline-flex"
                      alignItems="center"
                      color="blue.500"
                    >
                      <Icon as={FiExternalLink} />
                    </Link>
                  )}
                </>
              )
            })()}
            {userHasWriteAccess && r.source === "cloud" && (
              <Tooltip label="Share">
                <IconButton
                  aria-label="Share release"
                  icon={<FiShare2 />}
                  size="xs"
                  variant="ghost"
                  flexShrink={0}
                  onClick={() => openShare(r.name)}
                />
              </Tooltip>
            )}
          </Flex>
        ))
      )}
      <NewRelease
        isOpen={newReleaseModal.isOpen}
        onClose={closeNewRelease}
        ownerName={ownerName}
        projectName={projectName}
        defaultPath={path}
        kind={kind}
        onCreated={
          shareAfterCreate ? (release) => openShare(release.name) : undefined
        }
      />
      {shareName && (
        <ShareDialog
          isOpen={shareModal.isOpen}
          onClose={shareModal.onClose}
          ownerName={ownerName}
          projectName={projectName}
          releaseName={shareName}
        />
      )}
    </Box>
  )
}

export default ArtifactReleasesPanel
