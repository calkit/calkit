import { CloseIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormErrorMessage,
  FormLabel,
  IconButton,
  Input,
  InputGroup,
  InputRightElement,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Radio,
  RadioGroup,
  Select,
  Stack,
  Text,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { ProjectsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import LoadingSpinner from "../Common/LoadingSpinner"

interface ImportFromZoteroModalProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
}

// Either link a whole existing Zotero collection, or check off a subset of its
// items, which the backend copies into a new collection dedicated to this
// project.
type Mode = "collection" | "items"

const ImportFromZoteroModal = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
}: ImportFromZoteroModalProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [library, setLibrary] = useState<string>("")
  const [collectionKey, setCollectionKey] = useState<string>("")
  const [mode, setMode] = useState<Mode>("collection")
  const [search, setSearch] = useState<string>("")
  const [bibPath, setBibPath] = useState<string>("references.bib")
  const [checkedItems, setCheckedItems] = useState<Record<string, boolean>>({})
  const librariesQuery = useQuery({
    queryFn: () =>
      ProjectsService.getProjectZoteroLibraries({ ownerName, projectName }),
    queryKey: ["projects", ownerName, projectName, "zotero", "libraries"],
    enabled: isOpen,
  })
  const [libraryType, libraryId] = library ? library.split(":") : ["", ""]
  const collectionsQuery = useQuery({
    queryFn: () =>
      ProjectsService.getProjectZoteroCollections({
        ownerName,
        projectName,
        libraryType: libraryType as "user" | "group",
        libraryId,
      }),
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "zotero",
      "collections",
      library,
    ],
    enabled: isOpen && Boolean(library),
  })
  const itemsQuery = useQuery({
    queryFn: () =>
      ProjectsService.getProjectZoteroItems({
        ownerName,
        projectName,
        libraryType: libraryType as "user" | "group",
        libraryId,
        collectionKey: collectionKey || undefined,
        q: search || undefined,
      }),
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "zotero",
      "items",
      library,
      collectionKey,
      search,
    ],
    enabled:
      isOpen && mode === "items" && Boolean(library) && Boolean(collectionKey),
  })
  // Surfaced only after the backend reports the target .bib already exists, so
  // the user can choose to replace it.
  const [conflict, setConflict] = useState(false)
  const resetAndClose = () => {
    setCheckedItems({})
    setSearch("")
    setBibPath("references.bib")
    setConflict(false)
    onClose()
  }
  const importMutation = useMutation({
    mutationFn: (overwrite: boolean) => {
      const selectedItemKeys = Object.entries(checkedItems)
        .filter(([, checked]) => checked)
        .map(([key]) => key)
      return ProjectsService.postProjectZoteroImport({
        ownerName,
        projectName,
        requestBody: {
          library_type: libraryType as "user" | "group",
          library_id: libraryId,
          collection_key: mode === "collection" ? collectionKey : null,
          item_keys: mode === "items" ? selectedItemKeys : null,
          bib_path: bibPath.trim(),
          overwrite,
        },
      })
    },
    onSuccess: () => {
      showToast("Success!", "References imported from Zotero.", "success")
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "references"],
      })
      resetAndClose()
    },
    onError: (err: ApiError) => {
      if (err.status === 409) {
        setConflict(true)
        return
      }
      handleError(err, showToast)
    },
  })
  const selectedCount = Object.values(checkedItems).filter(Boolean).length
  const bibPathValid = bibPath.trim().toLowerCase().endsWith(".bib")
  const canImport =
    Boolean(library) &&
    bibPathValid &&
    ((mode === "collection" && Boolean(collectionKey)) ||
      (mode === "items" && selectedCount > 0))

  return (
    <Modal isOpen={isOpen} onClose={resetAndClose} size="lg" isCentered>
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Import from Zotero</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          {librariesQuery.isPending ? (
            <LoadingSpinner height="80px" />
          ) : (
            <>
              <FormControl mb={4}>
                <FormLabel>Library</FormLabel>
                <Select
                  placeholder="Select a library"
                  value={library}
                  onChange={(e) => {
                    setLibrary(e.target.value)
                    setCollectionKey("")
                    setCheckedItems({})
                  }}
                  data-form-type="other"
                  data-lpignore="true"
                >
                  {librariesQuery.data?.map((lib) => (
                    <option
                      key={`${lib.library_type}:${lib.library_id}`}
                      value={`${lib.library_type}:${lib.library_id}`}
                    >
                      {lib.name}
                    </option>
                  ))}
                </Select>
              </FormControl>
              <FormControl mb={4}>
                <FormLabel>Collection</FormLabel>
                <Select
                  placeholder="Select a collection"
                  value={collectionKey}
                  isDisabled={!library || collectionsQuery.isPending}
                  onChange={(e) => {
                    setCollectionKey(e.target.value)
                    setCheckedItems({})
                  }}
                  data-form-type="other"
                  data-lpignore="true"
                >
                  {collectionsQuery.data?.map((c) => (
                    <option key={c.collection_key} value={c.collection_key}>
                      {c.collection_name ?? c.collection_key}
                    </option>
                  ))}
                </Select>
              </FormControl>
              <FormControl mb={4}>
                <FormLabel>What to import</FormLabel>
                <RadioGroup value={mode} onChange={(v) => setMode(v as Mode)}>
                  <Stack>
                    <Radio value="collection" isDisabled={!collectionKey}>
                      The whole collection
                    </Radio>
                    <Radio value="items" isDisabled={!collectionKey}>
                      Selected items (copied into a new project collection)
                    </Radio>
                  </Stack>
                </RadioGroup>
              </FormControl>
              <FormControl mb={4} isInvalid={Boolean(bibPath) && !bibPathValid}>
                <FormLabel>Save to file</FormLabel>
                <Input
                  size="sm"
                  placeholder="references.bib"
                  value={bibPath}
                  onChange={(e) => {
                    setBibPath(e.target.value)
                    setConflict(false)
                  }}
                  autoComplete="off"
                  data-form-type="other"
                  data-lpignore="true"
                />
                <FormErrorMessage>Path must end with '.bib'</FormErrorMessage>
              </FormControl>
              {mode === "items" && collectionKey ? (
                <Box>
                  <InputGroup size="sm" mb={2}>
                    <Input
                      placeholder="Search items"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      autoComplete="off"
                      data-form-type="other"
                      data-lpignore="true"
                    />
                    {search ? (
                      <InputRightElement>
                        <IconButton
                          aria-label="Clear search"
                          icon={<CloseIcon boxSize={2.5} />}
                          size="xs"
                          variant="ghost"
                          onClick={() => setSearch("")}
                        />
                      </InputRightElement>
                    ) : null}
                  </InputGroup>
                  {itemsQuery.isPending ? (
                    <LoadingSpinner height="60px" />
                  ) : (
                    <Stack
                      maxH="240px"
                      overflowY="auto"
                      borderWidth={1}
                      borderRadius="md"
                      p={2}
                      spacing={1}
                    >
                      {itemsQuery.data?.length ? (
                        itemsQuery.data.map((item) => (
                          <Checkbox
                            key={item.item_key}
                            isChecked={Boolean(checkedItems[item.item_key])}
                            onChange={(e) =>
                              setCheckedItems((prev) => ({
                                ...prev,
                                [item.item_key]: e.target.checked,
                              }))
                            }
                          >
                            <Text as="span" fontSize="sm">
                              {item.title ?? item.item_key}
                              {item.first_author || item.year ? (
                                <Text as="span" color="gray.500">
                                  {" "}
                                  ({item.first_author ?? "?"}
                                  {item.year ? `, ${item.year}` : ""})
                                </Text>
                              ) : null}
                            </Text>
                          </Checkbox>
                        ))
                      ) : (
                        <Text fontSize="sm" color="gray.500">
                          No items found.
                        </Text>
                      )}
                    </Stack>
                  )}
                </Box>
              ) : null}
            </>
          )}
          {conflict ? (
            <Text fontSize="sm" color="red.500" mt={2}>
              {`'${bibPath.trim()}' already exists. Overwrite it?`}
            </Text>
          ) : null}
        </ModalBody>
        <ModalFooter gap={3}>
          {conflict ? (
            <Button
              colorScheme="red"
              onClick={() => importMutation.mutate(true)}
              isLoading={importMutation.isPending}
            >
              Overwrite
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => importMutation.mutate(false)}
              isDisabled={!canImport}
              isLoading={importMutation.isPending}
            >
              Import
              {mode === "items" && selectedCount > 0
                ? ` (${selectedCount})`
                : ""}
            </Button>
          )}
          <Button onClick={resetAndClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default ImportFromZoteroModal
