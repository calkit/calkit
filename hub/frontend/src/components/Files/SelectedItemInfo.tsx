import {
  Badge,
  Box,
  Button,
  Flex,
  Text,
  Icon,
  Heading,
  useDisclosure,
  IconButton,
  HStack,
  Link,
  Code,
} from "@chakra-ui/react"
import { FaTimesCircle, FaUpload, FaLock, FaCodeBranch } from "react-icons/fa"
import { MdEdit } from "react-icons/md"
import { ExternalLinkIcon } from "@chakra-ui/icons"
import { Link as RouterLink } from "@tanstack/react-router"
import { type ContentsItem } from "../../client"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import EditFileInfo from "./EditFileInfo"
import useAuth from "../../hooks/useAuth"
import UploadFile from "./UploadFile"
import { ProjectsService } from "../../client"
import { type ArtifactKind } from "../Common/ArtifactCompareModal"

const FIGURE_EXTS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".svg",
  ".gif",
  ".json",
  ".html",
])
const PUBLICATION_EXTS = new Set([".pdf", ".html"])
const NOTEBOOK_EXTS = new Set([".ipynb"])

// Path segments that hint at figure or publication directories
const FIGURE_DIRS = new Set([
  "figures",
  "figure",
  "figs",
  "fig",
  "plots",
  "images",
])
const PUBLICATION_DIRS = new Set([
  "paper",
  "papers",
  "publications",
  "publication",
  "pub",
  "pubs",
  "manuscript",
  "article",
])

export function inferKindFromPath(path: string): ArtifactKind | undefined {
  const lower = path.toLowerCase()
  const parts = lower.split("/")
  const ext = parts[parts.length - 1].includes(".")
    ? "." + parts[parts.length - 1].split(".").pop()!
    : ""

  // Notebooks: always by extension, never in hidden folders
  if (NOTEBOOK_EXTS.has(ext) && !parts.some((p) => p.startsWith(".")))
    return "notebook"

  // Check parent directory name for figures/publications first
  const parentDir = parts.length > 1 ? parts[parts.length - 2] : ""
  if (PUBLICATION_DIRS.has(parentDir) && PUBLICATION_EXTS.has(ext))
    return "publication"
  if (FIGURE_DIRS.has(parentDir) && FIGURE_EXTS.has(ext)) return "figure"

  // Fall back to extension only; exclude .json since it's too ambiguous (configs, etc.)
  if (FIGURE_EXTS.has(ext) && ext !== ".json") return "figure"
  if (ext === ".pdf") return "figure"

  return undefined
}

interface FileLockProps {
  item: ContentsItem
  ownerName: string
  projectName: string
}

function FileLock({ item, ownerName, projectName }: FileLockProps) {
  const { user: currentUser } = useAuth()
  const queryClient = useQueryClient()
  const createLockMutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectFileLock({
        ownerName,
        projectName,
        requestBody: { path: item.path },
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "files"],
      }),
  })
  const deleteLockMutation = useMutation({
    mutationFn: () =>
      ProjectsService.deleteProjectFileLock({
        ownerName,
        projectName,
        requestBody: { path: item.path },
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "files"],
      }),
  })

  if (!item.lock) {
    if (item.type === "file") {
      return (
        <Flex mt={2}>
          <Button
            size="sm"
            aria-label="Lock file"
            onClick={() => createLockMutation.mutate()}
            isLoading={createLockMutation.isPending}
          >
            <Icon mr={1} as={FaLock} /> Lock file for editing
          </Button>
        </Flex>
      )
    }
    return <></>
  }
  return (
    <Flex color="yellow.500" align="center" mt={2} py={2}>
      <Icon as={FaLock} mr={1} height={"13px"} />
      <Text fontWeight="bold">Locked by {item.lock.user_github_username}</Text>
      {item.lock.user_github_username === currentUser?.github_username ? (
        <>
          <IconButton
            aria-label="Clear file lock"
            icon={<FaTimesCircle />}
            height={"12px"}
            size={"20px"}
            borderRadius={3}
            bg="none"
            ml={1}
            color={"yellow.500"}
            onClick={() => deleteLockMutation.mutate()}
            isLoading={deleteLockMutation.isPending}
          />
        </>
      ) : (
        ""
      )}
    </Flex>
  )
}

interface SelectedItemProps {
  selectedItem: ContentsItem
  ownerName: string
  projectName: string
  userHasWriteAccess: boolean
  onOpenCompare?: () => void
  gitRef?: string
  // Provided (by the parent) only when this file can be opened in the in-browser
  // LaTeX editor — e.g. a .tex source or a LaTeX publication.
  onEditLatex?: () => void
}

function SelectedItemInfo({
  selectedItem,
  ownerName,
  projectName,
  userHasWriteAccess,
  onOpenCompare,
  gitRef,
  onEditLatex,
}: SelectedItemProps) {
  const fileInfoModal = useDisclosure()
  const uploadNewVersionModal = useDisclosure()

  const artifactKind: ArtifactKind | undefined =
    (selectedItem.calkit_object?.kind as ArtifactKind | undefined) ??
    (selectedItem.type === "file"
      ? inferKindFromPath(selectedItem.path)
      : undefined)

  return (
    <Box w="100%" wordBreak="break-word" fontSize="sm">
      <Text>Name: {selectedItem.name}</Text>
      {selectedItem.type ? <Text>Type: {selectedItem.type}</Text> : ""}
      {selectedItem.size ? <Text>Size: {selectedItem.size}</Text> : ""}
      {selectedItem.storage ? <Text>Storage: {selectedItem.storage}</Text> : ""}
      {selectedItem.stage ? (
        <Text>
          Pipeline stage:{" "}
          <Link
            as={RouterLink}
            to={`/${ownerName}/${projectName}/pipeline`}
            search={{ stage: selectedItem.stage, ref: gitRef } as any}
          >
            <Code>{selectedItem.stage}</Code>
          </Link>
        </Text>
      ) : (
        ""
      )}
      {onEditLatex ? (
        <Button size="sm" mt={2} onClick={onEditLatex}>
          <Icon as={MdEdit} mr={1} />
          Edit LaTeX
        </Button>
      ) : (
        ""
      )}
      {userHasWriteAccess ? (
        <FileLock
          item={selectedItem}
          ownerName={ownerName}
          projectName={projectName}
        />
      ) : (
        ""
      )}
      {selectedItem.type === "file" &&
      selectedItem.in_repo &&
      userHasWriteAccess ? (
        <>
          <Button
            size="sm"
            mt={2}
            onClick={uploadNewVersionModal.onOpen}
            isDisabled={Boolean(selectedItem.lock)}
          >
            <Icon as={FaUpload} mr={1} />
            Upload new version
          </Button>
          <UploadFile
            onClose={uploadNewVersionModal.onClose}
            isOpen={uploadNewVersionModal.isOpen}
            path={selectedItem.path}
          />
        </>
      ) : (
        ""
      )}
      {selectedItem.type === "file" ? (
        <Button mt={2} onClick={onOpenCompare} size="sm">
          <Icon as={FaCodeBranch} mr={1} />
          Browse history
        </Button>
      ) : null}
      {selectedItem.type === "file" &&
      selectedItem.in_repo &&
      userHasWriteAccess ? (
        <Link
          href={`https://github.dev/${ownerName}/${projectName}/blob/main/${selectedItem.path}`}
          isExternal
        >
          <Button size="sm" mt={2}>
            <Icon mr={1} as={MdEdit} />
            Edit on GitHub.dev <Icon ml={1} as={ExternalLinkIcon} />
          </Button>
        </Link>
      ) : (
        ""
      )}
      <HStack alignContent={"center"} mt={4} mb={1} gap={1}>
        <Heading size={"sm"}>Artifact info</Heading>
        {userHasWriteAccess ? (
          <>
            <IconButton
              aria-label="Change artifact info"
              icon={<MdEdit />}
              height={"19px"}
              size={"22px"}
              width={"18px"}
              borderRadius={3}
              fontSize="15px"
              onClick={fileInfoModal.onOpen}
            />
            <EditFileInfo
              isOpen={fileInfoModal.isOpen}
              onClose={fileInfoModal.onClose}
              item={selectedItem}
            />
          </>
        ) : (
          ""
        )}
      </HStack>
      <Text>
        Type:
        {artifactKind ? (
          <Badge
            ml={1}
            bgColor={
              selectedItem.calkit_object?.kind ? "green.500" : "gray.400"
            }
            title={
              selectedItem.calkit_object?.kind ? undefined : "Auto-detected"
            }
          >
            {artifactKind}
          </Badge>
        ) : (
          <Badge ml={1} bgColor="gray">
            None
          </Badge>
        )}
      </Text>
      {selectedItem.calkit_object?.name ? (
        <Text mt={1}>Name: {String(selectedItem.calkit_object.name)}</Text>
      ) : (
        ""
      )}
      {selectedItem.calkit_object?.title ? (
        <Text mt={1}>Title: {String(selectedItem.calkit_object.title)}</Text>
      ) : (
        ""
      )}
      {selectedItem.calkit_object?.description ? (
        <Text mt={1}>
          Description: {String(selectedItem.calkit_object.description)}
        </Text>
      ) : (
        ""
      )}
      {!selectedItem.stage && selectedItem.calkit_object?.stage ? (
        <Text mt={1}>
          Pipeline stage:{" "}
          <Code>{String(selectedItem.calkit_object.stage)}</Code>
        </Text>
      ) : (
        ""
      )}
    </Box>
  )
}

export default SelectedItemInfo
