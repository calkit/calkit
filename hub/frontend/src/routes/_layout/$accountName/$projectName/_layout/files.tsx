import {
  Box,
  Flex,
  Heading,
  Icon,
  IconButton,
  Tag,
  TagCloseButton,
  TagLabel,
  Text,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { AiOutlinePython } from "react-icons/ai"
import { BsFiletypeYml } from "react-icons/bs"
import {
  FaDocker,
  FaHistory,
  FaList,
  FaRegFileImage,
  FaRegFolderOpen,
  FaSync,
} from "react-icons/fa"
import { FaLock, FaMarkdown, FaPlus } from "react-icons/fa6"
import { FiDatabase, FiFile, FiFolder } from "react-icons/fi"
import { SiAnaconda, SiJupyter } from "react-icons/si"
import { z } from "zod"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Tooltip from "../../../../../components/Common/Tooltip"

import { type ContentsItem, ProjectsService } from "../../../../../client"
import {
  ArtifactCompareModal,
  type ArtifactKind,
} from "../../../../../components/Common/ArtifactCompareModal"
import PageMenu from "../../../../../components/Common/PageMenu"
import FileContent from "../../../../../components/Files/FileContent"
import FileEditorModal, {
  isEditableText,
} from "../../../../../components/Files/FileEditorModal"
import SelectedItemInfo, {
  inferKindFromPath,
} from "../../../../../components/Files/SelectedItemInfo"
import UploadFile from "../../../../../components/Files/UploadFile"
import LatexEditor from "../../../../../components/Publications/LatexEditor"
import useProject from "../../../../../hooks/useProject"

const fileSearchSchema = z.object({
  path: z.string().catch(""),
  ref: z.string().optional(),
  compare_open: z.boolean().optional(),
  base_ref: z.string().optional(),
  compare_ref: z.string().optional(),
  editor_open: z.boolean().optional(),
  file_editor_open: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/files",
)({
  component: Files,
  validateSearch: (search) => fileSearchSchema.parse(search),
})

function sortByTypeAndName(a: ContentsItem, b: ContentsItem) {
  if (a.type === "dir" && b.type === "dir") {
    if (a.name < b.name) {
      return -1
    }
  } else if (a.type === "dir" && b.type === "file") {
    return -1
  } else if (a.type === "file" && b.type === "file") {
    if (a.name < b.name) {
      return -1
    }
  }
  return 0
}

interface ItemProps {
  item: ContentsItem
  level?: number
  selectedPath: string
  setSelectedPath: (path: string) => void
}

// A component to render an individual item in the list of contents
// If a directory, expand to show files when clicked
// If a file, get content and display to the right in a viewer
function Item({ item, level, selectedPath, setSelectedPath }: ItemProps) {
  const bgActive = useColorModeValue("#E2E8F0", "#4A5568")
  const navigate = useNavigate({ from: Route.fullPath })
  const indent = level ? level : 0
  const [isExpanded, setIsExpanded] = useState(
    pathShouldBeExpanded(item.path, selectedPath),
  )
  const { accountName, projectName } = Route.useParams()
  const { ref } = Route.useSearch()
  const { data } = useQuery({
    queryKey: ["projects", accountName, projectName, "files", item.path, ref],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: accountName,
        project_name: projectName,
        path: item.path,
        ref,
      }).then((response) => response.data),
    enabled: isExpanded,
  })

  // Determine if a given path should be expanded based on whether or not it is
  // a parent directory of the selected path
  function pathShouldBeExpanded(path: string, selectedPath: string) {
    if (path === selectedPath) {
      return true
    }
    const parentTokens = path.split("/").filter((i) => i.length)
    const childTokens = selectedPath.split("/").filter((i) => i.length)
    return parentTokens.every((t, i) => childTokens[i] === t)
  }

  // Helper function to get the appropriate icon based on item type
  const getIcon = (item: ContentsItem, isExpanded = false) => {
    if (item.calkit_object) {
      if (item.calkit_object.kind === "dataset" && item.type !== "dir") {
        return FiDatabase
      }
      if (item.calkit_object.kind === "figure") {
        return FaRegFileImage
      }
      if (item.calkit_object.kind === "references") {
        return FaList
      }
    }
    if (item.type === "dir" && !isExpanded) {
      return FiFolder
    }
    if (item.type === "dir" && isExpanded) {
      return FaRegFolderOpen
    }
    if (item.name.endsWith(".png")) {
      return FaRegFileImage
    }
    if (item.name.endsWith(".py")) {
      return AiOutlinePython
    }
    if (item.name.endsWith(".ipynb")) {
      return SiJupyter
    }
    if (item.name.endsWith(".md")) {
      return FaMarkdown
    }
    if (item.name.endsWith("yaml") || item.name === "dvc.lock") {
      return BsFiletypeYml
    }
    if (item.name === "environment.yml") {
      return SiAnaconda
    }
    if (item.name === "Dockerfile") {
      return FaDocker
    }
    return FiFile
  }

  const handleClick = () => {
    setIsExpanded(!isExpanded)
    setSelectedPath(item.path)
    navigate({
      search: (prev) => ({
        ...prev,
        path: item.path,
      }),
    })
  }

  if (Array.isArray(data)) {
    data.sort(sortByTypeAndName)
  }

  const itemIsSelected = item.path === selectedPath

  return (
    <>
      <Tooltip label={item.path} placement="right">
        <Flex
          cursor="pointer"
          onClick={handleClick}
          ml={indent * 4}
          bg={itemIsSelected ? bgActive : ""}
          borderRadius="md"
          px="2px"
        >
          <Icon
            as={getIcon(item, isExpanded)}
            alignSelf="center"
            mr={1}
            color={item.calkit_object ? "green.500" : "default"}
          />
          <Text
            isTruncated
            noOfLines={1}
            whiteSpace="nowrap"
            overflow="hidden"
            textOverflow="ellipsis"
            display="inline-block"
            maxW="100%"
          >
            {item.name}
          </Text>
          {item.lock ? (
            <Icon
              as={FaLock}
              ml={0.1}
              color={"yellow.500"}
              alignSelf="center"
              height={"12px"}
            />
          ) : (
            ""
          )}
        </Flex>
      </Tooltip>
      {isExpanded && item.type === "dir" ? (
        <Box>
          {data?.dir_items?.map((subItem: ContentsItem) => (
            <Item
              key={subItem.name}
              item={subItem}
              level={indent + 1}
              selectedPath={selectedPath}
              setSelectedPath={setSelectedPath}
            />
          ))}
        </Box>
      ) : (
        ""
      )}
    </>
  )
}

function Files() {
  const { accountName, projectName } = Route.useParams()
  const {
    path,
    ref,
    compare_open,
    base_ref,
    compare_ref,
    editor_open,
    file_editor_open,
  } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const {
    isPending: filesPending,
    data: files,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ["projects", accountName, projectName, "files", ref],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })
  const [selectedPath, setSelectedPath] = useState<string>(path)
  // Keep selectedPath in sync when the URL `path` param changes (e.g., back/forward)
  useEffect(() => {
    setSelectedPath(path)
  }, [path])
  const selectedItemQuery = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "files",
      selectedPath,
      ref,
    ],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: accountName,
        project_name: projectName,
        path: selectedPath,
        ref,
      }).then((response) => response.data),
    enabled: selectedPath !== undefined,
  })
  // Pre-fetch all ancestor directories so tree expansion doesn't waterfall.
  // Using prefetchQuery (fire-and-forget) avoids extra re-renders that
  // useQueries subscriptions would cause.
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!selectedPath) return
    const segments = selectedPath.split("/").slice(0, -1)
    segments.forEach((_, i, arr) => {
      const ancestorPath = arr.slice(0, i + 1).join("/")
      queryClient.prefetchQuery({
        queryKey: [
          "projects",
          accountName,
          projectName,
          "files",
          ancestorPath,
          ref,
        ],
        queryFn: () =>
          ProjectsService.getProjectContents({
            owner_name: accountName,
            project_name: projectName,
            path: ancestorPath,
            ref,
          }).then((response) => response.data),
      })
    })
  }, [selectedPath, accountName, projectName, ref])
  const fileUploadModal = useDisclosure()
  if (Array.isArray(files?.dir_items)) {
    files.dir_items.sort(sortByTypeAndName)
  }
  const refresh = () => {
    refetch()
    selectedItemQuery.refetch()
  }

  const clearRef = () => {
    navigate({ search: (prev) => ({ ...prev, ref: undefined }) })
  }

  const openCompare = () =>
    navigate({
      search: (prev) => ({ ...prev, compare_open: true }),
    })

  const closeCompare = () =>
    navigate({
      search: (prev) => ({
        ...prev,
        compare_open: undefined,
        base_ref: undefined,
        compare_ref: undefined,
      }),
    })

  const selectedItem = selectedItemQuery.data
  const artifactKind: ArtifactKind | undefined =
    selectedItem?.type === "file"
      ? (selectedItem.calkit_object?.kind as ArtifactKind | undefined) ??
        inferKindFromPath(selectedItem.path)
      : undefined
  // The in-browser LaTeX editor can open a .tex source directly, or a LaTeX
  // publication (whose source we derive as <name>.tex, matching the
  // publications page). deps help load figures from outside the paper dir.
  // Only a PDF publication gets that treatment: an .html or .md one has no
  // .tex behind it, and deriving one would open the LaTeX editor on a file
  // that doesn't exist instead of editing the publication itself.
  const latexTexPath: string | undefined =
    selectedItem?.type === "file"
      ? selectedItem.path.endsWith(".tex")
        ? selectedItem.path
        : artifactKind === "publication" && selectedItem.path.endsWith(".pdf")
          ? selectedItem.path.replace(/\.pdf$/, ".tex")
          : undefined
      : undefined
  // No pipeline deps here (that lives on the Publication object, not a file
  // listing) — the editor falls back to loading the .tex's own directory.
  const openEditor = () =>
    navigate({ search: (prev) => ({ ...prev, editor_open: true }) })
  const closeEditor = () =>
    navigate({ search: (prev) => ({ ...prev, editor_open: undefined }) })
  // Anything textual and in the repo can be edited in the app. DVC-tracked
  // files live outside Git, so committing one here wouldn't update the pointer
  // the project actually reads.
  const editableFilePath: string | undefined =
    selectedItem?.type === "file" &&
    selectedItem.in_repo &&
    isEditableText(selectedItem.path)
      ? selectedItem.path
      : undefined
  // One "Edit file" button, whichever editor it opens: a .tex source (and a
  // LaTeX publication, whose source we derive) gets the LaTeX editor with its
  // preview, everything else textual gets the plain one.
  const canEdit = Boolean(
    (latexTexPath || editableFilePath) && userHasWriteAccess && !ref,
  )
  const openFileEditor = () =>
    navigate({ search: (prev) => ({ ...prev, file_editor_open: true }) })
  const closeFileEditor = () =>
    navigate({ search: (prev) => ({ ...prev, file_editor_open: undefined }) })

  return (
    <>
      {filesPending || isRefetching ? (
        <LoadingSpinner />
      ) : (
        <Flex height={"100%"} overflowX="hidden">
          <PageMenu>
            <Flex align="center" gap={1} mb={2} wrap="wrap">
              <Heading size="md">All files</Heading>
              {userHasWriteAccess && !ref ? (
                <IconButton
                  variant="primary"
                  height="25px"
                  fontSize="sm"
                  onClick={fileUploadModal.onOpen}
                  icon={<FaPlus />}
                  aria-label="upload"
                />
              ) : null}
              <IconButton
                aria-label="refresh"
                height="25px"
                icon={<FaSync />}
                onClick={refresh}
              />
            </Flex>

            {/* Version badge when a ref is active */}
            {ref && (
              <Box mb={3}>
                <Tag size="sm" colorScheme="blue" borderRadius="full">
                  <Icon as={FaHistory} mr={1} fontSize="10px" />
                  <TagLabel fontSize="xs" maxW="120px" isTruncated>
                    {ref}
                  </TagLabel>
                  <TagCloseButton onClick={clearRef} />
                </Tag>
              </Box>
            )}
            <UploadFile
              isOpen={fileUploadModal.isOpen}
              onClose={fileUploadModal.onClose}
            />
            {Array.isArray(files?.dir_items)
              ? files.dir_items?.map((file) => (
                  <Item
                    key={file.name}
                    item={file}
                    selectedPath={selectedPath}
                    setSelectedPath={setSelectedPath}
                  />
                ))
              : ""}
          </PageMenu>
          <Flex flex={1} minW={0} gap={6} align="flex-start">
            <Box flex={1} minW={0} minH={0} overflowY="auto" overflowX="auto">
              {selectedPath !== undefined && selectedItemQuery.isPending ? (
                <LoadingSpinner />
              ) : selectedItemQuery?.data?.content ||
                selectedItemQuery?.data?.url ? (
                <FileContent item={selectedItemQuery.data!} />
              ) : null}
            </Box>
            <Box
              w="280px"
              flexShrink={0}
              px={3}
              py={2}
              borderRadius="lg"
              bg={useColorModeValue("ui.secondary", "ui.darkSlate")}
              h="fit-content"
              overflow="hidden"
            >
              <Heading size="md" mb={2}>
                Info
              </Heading>
              {selectedPath !== undefined && selectedItemQuery.isPending ? (
                ""
              ) : (
                <>
                  {selectedItemQuery?.data && selectedPath !== undefined ? (
                    <SelectedItemInfo
                      selectedItem={selectedItemQuery.data}
                      ownerName={accountName}
                      projectName={projectName}
                      userHasWriteAccess={userHasWriteAccess}
                      onOpenCompare={openCompare}
                      gitRef={ref}
                      onEditFile={
                        canEdit
                          ? latexTexPath
                            ? openEditor
                            : openFileEditor
                          : undefined
                      }
                    />
                  ) : (
                    ""
                  )}
                </>
              )}
            </Box>
          </Flex>
        </Flex>
      )}

      {selectedItem?.type === "file" && (
        <ArtifactCompareModal
          isOpen={Boolean(compare_open)}
          onClose={closeCompare}
          ownerName={accountName}
          projectName={projectName}
          path={selectedItem.path}
          kind={artifactKind ?? "file"}
          initialRef={base_ref}
          initialRef2={compare_ref}
          onRefsChange={(r1, r2) =>
            navigate({
              search: (prev) => ({
                ...prev,
                base_ref: r1,
                compare_ref: r2,
              }),
            })
          }
        />
      )}

      {file_editor_open && editableFilePath && (
        <FileEditorModal
          isOpen={Boolean(file_editor_open)}
          onClose={closeFileEditor}
          ownerName={accountName}
          projectName={projectName}
          path={editableFilePath}
        />
      )}

      {editor_open && latexTexPath && (
        <LatexEditor
          isOpen={Boolean(editor_open)}
          onClose={closeEditor}
          ownerName={accountName}
          projectName={projectName}
          texPath={latexTexPath}
        />
      )}
    </>
  )
}
