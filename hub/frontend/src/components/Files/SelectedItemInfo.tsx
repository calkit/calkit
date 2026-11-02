import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  HStack,
  Heading,
  Icon,
  IconButton,
  Link,
  Spinner,
  Text,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { FaCodeBranch, FaLock, FaTimesCircle, FaUpload } from "react-icons/fa"
import { MdEdit } from "react-icons/md"
import type { ContentsItem } from "../../client"
import { ProjectsService } from "../../client"
import useAuth from "../../hooks/useAuth"
import type { ArtifactKind } from "../Common/ArtifactCompareModal"
import EditFileInfo from "./EditFileInfo"
import UploadFile from "./UploadFile"

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
// As the Results page detects them
const RESULT_EXTS = new Set([
  ".json",
  ".csv",
  ".tsv",
  ".yaml",
  ".yml",
  ".toml",
  ".parquet",
  ".h5",
  ".hdf5",
  ".txt",
  ".html",
])
const RESULT_DIRS = new Set(["results", "result"])

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

export type FileKind = ArtifactKind | "result"

export function inferKindFromPath(path: string): FileKind | undefined {
  const lower = path.toLowerCase()
  const parts = lower.split("/")
  const ext = parts[parts.length - 1].includes(".")
    ? `.${parts[parts.length - 1].split(".").pop()!}`
    : ""

  // Notebooks: always by extension, never in hidden folders
  if (NOTEBOOK_EXTS.has(ext) && !parts.some((p) => p.startsWith(".")))
    return "notebook"

  // Check parent directory name for figures/publications first
  const parentDir = parts.length > 1 ? parts[parts.length - 2] : ""
  if (PUBLICATION_DIRS.has(parentDir) && PUBLICATION_EXTS.has(ext))
    return "publication"
  if (FIGURE_DIRS.has(parentDir) && FIGURE_EXTS.has(ext)) return "figure"
  if (
    RESULT_EXTS.has(ext) &&
    !parts.some((p) => p.startsWith(".")) &&
    (parts.slice(0, -1).some((p) => RESULT_DIRS.has(p)) ||
      parts[parts.length - 1].replace(/\.[^.]*$/, "") === "results")
  )
    return "result"

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
        owner_name: ownerName,
        project_name: projectName,
        fileLockPost: { path: item.path },
      }).then((response) => response.data),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "files"],
      }),
  })
  const deleteLockMutation = useMutation({
    mutationFn: () =>
      ProjectsService.deleteProjectFileLock({
        owner_name: ownerName,
        project_name: projectName,
        fileLockPost: { path: item.path },
      }).then((response) => response.data),
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
  // Provided (by the parent) only when this file can be edited in the app.
  // The parent decides which editor opens: a .tex source (or a LaTeX
  // publication) gets the LaTeX editor, anything else textual gets the plain
  // one. Either way it's one button, since it's one thing the user wants.
  onEditFile?: () => void
}

function SelectedItemInfo({
  selectedItem,
  ownerName,
  projectName,
  userHasWriteAccess,
  onOpenCompare,
  gitRef,
  onEditFile,
}: SelectedItemProps) {
  const fileInfoModal = useDisclosure()
  const uploadNewVersionModal = useDisclosure()

  const declaredKind = selectedItem.calkit_object?.kind as string | undefined
  const artifactKind: FileKind | undefined =
    (declaredKind as FileKind | undefined) ??
    (selectedItem.type === "file"
      ? inferKindFromPath(selectedItem.path)
      : undefined)
  // Shared with the figure viewer, which asks the same question
  const provenanceQuery = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "provenance",
      selectedItem.path,
      gitRef,
    ],
    queryFn: () =>
      ProjectsService.getProjectProvenance({
        owner_name: ownerName,
        project_name: projectName,
        path: selectedItem.path,
        ref: gitRef,
      }).then((response) => response.data),
    enabled: selectedItem.type === "file" || selectedItem.type === "dir",
    retry: false,
  })
  const provenance = provenanceQuery.data
  const stage = selectedItem.stage ?? provenance?.stage
  const exportApp = provenance?.stage_app
  const exportedFrom = exportApp ? provenance?.source : null
  const manualStep =
    provenance?.stage_kind === "manual-step" ? provenance.message : null
  // Only something that needs one, e.g., data, not code, lacks an origin
  const originMissing = Boolean(
    provenance?.gaps?.some((gap) => gap.path === selectedItem.path),
  )
  const pipelineTo = `/${ownerName}/${projectName}/pipeline`
  const filesTo = `/${ownerName}/${projectName}/files`
  // Where it's shown as what it is, if there's a page for that
  const artifactPage = (() => {
    const path = selectedItem.path
    if (declaredKind === "references item file") {
      const refsPath = selectedItem.calkit_object?.references_path
      return refsPath
        ? { page: "references", search: { path: String(refsPath) } }
        : null
    }
    // The results page lists what it detects, the rest only what's declared
    if (!declaredKind && artifactKind !== "result") return null
    const kind: string | undefined = artifactKind
    switch (kind) {
      case "figure":
      case "publication":
      case "notebook":
      case "result":
        return { page: `${kind}s`, search: { path } }
      case "references":
        return { page: "references", search: { path } }
      case "dataset":
        return { page: "datasets", search: { highlight: path } }
      default:
        return null
    }
  })()

  return (
    <Box w="100%" wordBreak="break-word" fontSize="sm">
      <Text>Name: {selectedItem.name}</Text>
      {selectedItem.type ? <Text>Type: {selectedItem.type}</Text> : ""}
      {selectedItem.size ? <Text>Size: {selectedItem.size}</Text> : ""}
      {selectedItem.storage ? <Text>Storage: {selectedItem.storage}</Text> : ""}
      {stage ? (
        <Text>
          Origin: stage{" "}
          <Link
            as={RouterLink}
            to={pipelineTo}
            search={{ stage, ref: gitRef } as any}
          >
            <Code>{stage}</Code>
          </Link>
          {exportedFrom ? (
            <>
              , exported with {exportApp} from{" "}
              <Link
                as={RouterLink}
                to={filesTo}
                search={{ path: exportedFrom, ref: gitRef } as any}
              >
                <Code>{exportedFrom}</Code>
              </Link>
            </>
          ) : null}
          {manualStep ? `, a manual step: ${manualStep}` : null}
        </Text>
      ) : provenanceQuery.isLoading ? (
        <Spinner size="xs" />
      ) : provenance?.origin ? (
        <Text>
          Origin:{" "}
          {provenance.origin_url ? (
            <Link href={provenance.origin_url} isExternal>
              {provenance.origin} <ExternalLinkIcon mb={0.5} />
            </Link>
          ) : (
            provenance.origin
          )}
          {provenance.origin_path ? (
            <>
              {" "}
              (recorded for{" "}
              <Link
                as={RouterLink}
                to={filesTo}
                search={{ path: provenance.origin_path, ref: gitRef } as any}
              >
                <Code>{provenance.origin_path}</Code>
              </Link>
              )
            </>
          ) : null}
        </Text>
      ) : originMissing ? (
        <Text>
          Origin:{" "}
          <Text as="span" color="red.500">
            Not defined
          </Text>
        </Text>
      ) : null}
      {provenance?.input_to_stages?.length ? (
        <Text>
          Input to:{" "}
          {provenance.input_to_stages.map((name, i) => (
            <span key={name}>
              {i > 0 ? ", " : ""}
              <Link
                as={RouterLink}
                to={pipelineTo}
                search={{ stage: name, ref: gitRef } as any}
              >
                <Code>{name}</Code>
              </Link>
            </span>
          ))}
        </Text>
      ) : null}
      {onEditFile ? (
        <Button
          size="sm"
          mt={2}
          onClick={onEditFile}
          isDisabled={Boolean(selectedItem.lock)}
        >
          <Icon as={MdEdit} mr={1} />
          Edit file
        </Button>
      ) : selectedItem.type === "file" &&
        selectedItem.in_repo &&
        userHasWriteAccess ? (
        // The in-app editor only handles text it knows how to open, so
        // anything else keeps the editor it has always had rather than
        // losing its only way to be edited.
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
        {artifactKind && artifactPage ? (
          <Link
            as={RouterLink}
            to={`/${ownerName}/${projectName}/${artifactPage.page}`}
            search={{ ...artifactPage.search, ref: gitRef } as any}
          >
            <Badge
              ml={1}
              bgColor={declaredKind ? "green.500" : "gray.400"}
              title={declaredKind ? undefined : "Auto-detected"}
              cursor="pointer"
            >
              {artifactKind}
            </Badge>
          </Link>
        ) : artifactKind ? (
          <Badge
            ml={1}
            bgColor={declaredKind ? "green.500" : "gray.400"}
            title={declaredKind ? undefined : "Auto-detected"}
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
    </Box>
  )
}

export default SelectedItemInfo
