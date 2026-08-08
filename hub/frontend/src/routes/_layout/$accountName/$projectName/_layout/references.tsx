import { CloseIcon } from "@chakra-ui/icons"
import {
  Badge,
  Box,
  Button,
  Flex,
  HStack,
  Heading,
  Icon,
  IconButton,
  Input,
  InputGroup,
  InputRightElement,
  Link,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Portal,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate, useSearch } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { BsFilePdf } from "react-icons/bs"
import { FaChevronDown, FaChevronRight, FaPlus, FaTrash } from "react-icons/fa"
import { IoLibraryOutline } from "react-icons/io5"
import { MdEdit } from "react-icons/md"
import { z } from "zod"

import type { AxiosError } from "axios"
import {
  ProjectsService,
  type ReferenceEntry,
  type References as ReferencesCollection,
  UsersService,
} from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import PageMenu from "../../../../../components/Common/PageMenu"
import Tooltip from "../../../../../components/Common/Tooltip"
import DeleteReferenceItemDialog from "../../../../../components/References/DeleteReferenceItemDialog"
import EditReferenceItemModal from "../../../../../components/References/EditReferenceItemModal"
import FileViewModal from "../../../../../components/References/FileViewModal"
import ImportFromZoteroModal from "../../../../../components/References/ImportFromZoteroModal"
import LabelExistingReferences from "../../../../../components/References/LabelExistingReferences"
import NewReferencesCollection from "../../../../../components/References/NewReferencesCollection"
import ReferenceItemModal from "../../../../../components/References/ReferenceItemModal"
import ReferencesInfoPanel from "../../../../../components/References/ReferencesInfoPanel"
import useCustomToast from "../../../../../hooks/useCustomToast"
import useProject from "../../../../../hooks/useProject"
import { formatBibField } from "../../../../../lib/bibtex"
import { handleError } from "../../../../../lib/errors"
import { stashZoteroReturn } from "../../../../../lib/zotero"

const referencesSearchSchema = z.object({
  // Selected collection path, so a link restores the same collection.
  path: z.string().optional(),
  // Open reference item (its bib key), for the item detail modal.
  item: z.string().optional(),
  import_zotero_open: z.boolean().optional(),
  new_collection_open: z.boolean().optional(),
  label_existing_open: z.boolean().optional(),
  // Whether the selected collection's items are collapsed in the sidebar tree.
  items_collapsed: z.boolean().optional(),
  resolved: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/references",
)({
  component: References,
  validateSearch: (search) => referencesSearchSchema.parse(search),
})

interface ReferenceEntryTableProps {
  referenceEntry: ReferenceEntry
}

const ReferenceEntryTable = memo(function ReferenceEntryTable({
  referenceEntry,
}: ReferenceEntryTableProps) {
  return (
    <TableContainer whiteSpace="wrap">
      <Table variant="simple" size="sm">
        <Thead>
          <Tr>
            <Th w="100px" />
            <Th />
          </Tr>
        </Thead>
        <Tbody>
          {referenceEntry.attrs
            ? Object.entries(referenceEntry.attrs).map(([k, v]) => {
                const value = formatBibField(k, String(v))
                const key = k.toLowerCase()
                let href: string | undefined
                if (key === "doi") {
                  href = value.startsWith("http")
                    ? value
                    : `https://doi.org/${value}`
                } else if (key === "url" && /^https?:\/\//i.test(value)) {
                  href = value
                }
                return (
                  <Tr key={k}>
                    <Td>{k}</Td>
                    <Td>
                      {href ? (
                        <Link href={href} isExternal variant="blue">
                          {value}
                        </Link>
                      ) : (
                        value
                      )}
                    </Td>
                  </Tr>
                )
              })
            : ""}
        </Tbody>
      </Table>
    </TableContainer>
  )
})

// How many items to show under an expanded collection before "Show more".
const SIDEBAR_ITEM_PAGE = 50

interface CollectionTreeProps {
  collections: ReferencesCollection[]
  selectedPath?: string
  // The selected collection's items, already filtered by the shared search.
  selectedEntries: ReferenceEntry[]
  searching: boolean
  itemsCollapsed: boolean
  activeItemKey?: string
  onSelectCollection: (path: string) => void
  onToggleItems: () => void
  onSelectItem: (key: string) => void
}

// The left sidebar tree of collections. Memoized so typing in the center
// search box, which lives in a sibling component, doesn't re-render the
// (potentially long) item list. Only the debounced query reaches this via
// `selectedEntries`, so it re-renders at most once per debounce interval.
const CollectionTree = memo(function CollectionTree({
  collections,
  selectedPath,
  selectedEntries,
  searching,
  itemsCollapsed,
  activeItemKey,
  onSelectCollection,
  onToggleItems,
  onSelectItem,
}: CollectionTreeProps) {
  const [limit, setLimit] = useState(SIDEBAR_ITEM_PAGE)
  // Reset the cap when the collection or the filtered result set changes.
  useEffect(() => {
    setLimit(SIDEBAR_ITEM_PAGE)
  }, [selectedPath, selectedEntries])
  const shownEntries = selectedEntries.slice(0, limit)
  const remaining = selectedEntries.length - shownEntries.length
  return (
    <>
      {collections.map((references) => {
        const isSelected = references.path === selectedPath
        const expanded = isSelected && !itemsCollapsed
        return (
          <Box key={references.path}>
            <HStack
              role="button"
              tabIndex={0}
              px={1}
              py={0.5}
              borderRadius="md"
              cursor="pointer"
              fontWeight={isSelected ? "semibold" : "normal"}
              color={isSelected ? "blue.500" : undefined}
              _hover={{ color: "blue.500" }}
              _focusVisible={{ boxShadow: "outline" }}
              onClick={() => onSelectCollection(references.path)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  onSelectCollection(references.path)
                }
              }}
              spacing={1}
            >
              <IconButton
                aria-label={expanded ? "Collapse items" : "Expand items"}
                icon={
                  <Icon
                    as={expanded ? FaChevronDown : FaChevronRight}
                    fontSize="0.6em"
                  />
                }
                size="xs"
                variant="ghost"
                minW="16px"
                h="16px"
                onClick={(e) => {
                  e.stopPropagation()
                  if (isSelected) onToggleItems()
                  else onSelectCollection(references.path)
                }}
              />
              <Icon as={IoLibraryOutline} flexShrink={0} />
              <Tooltip label={references.path} placement="right">
                <Text fontSize="sm" noOfLines={1}>
                  {references.path}
                </Text>
              </Tooltip>
              {references.zotero ? (
                <Badge colorScheme="red" fontSize="0.6em">
                  Zotero
                </Badge>
              ) : null}
            </HStack>
            {expanded ? (
              <Box pl={6} pb={1}>
                {selectedEntries.length === 0 ? (
                  <Text fontSize="xs" color="gray.500" py={0.5}>
                    {searching ? "No matches" : "No items"}
                  </Text>
                ) : (
                  <>
                    {shownEntries.map((item) => {
                      const isActive = item.key === activeItemKey
                      return (
                        <Text
                          key={item.key}
                          role="button"
                          tabIndex={0}
                          fontSize="xs"
                          noOfLines={1}
                          py={0.5}
                          cursor="pointer"
                          fontWeight={isActive ? "semibold" : "normal"}
                          color={isActive ? "blue.500" : undefined}
                          _hover={{ color: "blue.500" }}
                          _focusVisible={{ boxShadow: "outline" }}
                          onClick={() => onSelectItem(item.key)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault()
                              onSelectItem(item.key)
                            }
                          }}
                        >
                          {item.key}
                        </Text>
                      )
                    })}
                    {remaining > 0 ? (
                      <Text
                        role="button"
                        tabIndex={0}
                        fontSize="xs"
                        color="blue.500"
                        py={0.5}
                        cursor="pointer"
                        _hover={{ textDecoration: "underline" }}
                        _focusVisible={{ boxShadow: "outline" }}
                        onClick={() => setLimit((l) => l + SIDEBAR_ITEM_PAGE)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault()
                            setLimit((l) => l + SIDEBAR_ITEM_PAGE)
                          }
                        }}
                      >
                        Show {Math.min(remaining, SIDEBAR_ITEM_PAGE)} more (
                        {remaining} remaining)
                      </Text>
                    ) : null}
                  </>
                )}
              </Box>
            ) : null}
          </Box>
        )
      })}
    </>
  )
})

interface CollectionSearchBarProps {
  userHasWriteAccess: boolean
  onQueryChange: (q: string) => void
  onAddItem: () => void
}

// The single search box driving both the center list and the sidebar tree. The
// immediate input value is local, so keystrokes don't re-render either list;
// only the debounced query is lifted to the parent. Remounted (via a `key` on
// the caller) when the collection changes to reset the text.
const CollectionSearchBar = memo(function CollectionSearchBar({
  userHasWriteAccess,
  onQueryChange,
  onAddItem,
}: CollectionSearchBarProps) {
  const [text, setText] = useState("")
  useEffect(() => {
    if (text === "") {
      onQueryChange("")
      return
    }
    const t = setTimeout(() => onQueryChange(text.trim().toLowerCase()), 200)
    return () => clearTimeout(t)
  }, [text, onQueryChange])
  return (
    <HStack mb={3} align="center">
      <InputGroup maxW="400px">
        <Input
          placeholder="Search references"
          size="sm"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setText("")
          }}
          autoComplete="off"
          data-form-type="other"
          data-lpignore="true"
        />
        {text ? (
          <InputRightElement h="100%">
            <IconButton
              aria-label="Clear search"
              icon={<CloseIcon boxSize={2.5} />}
              size="xs"
              variant="ghost"
              onClick={() => setText("")}
            />
          </InputRightElement>
        ) : null}
      </InputGroup>
      {userHasWriteAccess ? (
        <Button
          size="sm"
          variant="primary"
          leftIcon={<FaPlus />}
          flexShrink={0}
          onClick={onAddItem}
        >
          Add item
        </Button>
      ) : null}
    </HStack>
  )
})

interface CollectionEntriesProps {
  collectionPath: string
  // Entries already filtered by the shared search.
  entries: ReferenceEntry[]
  // Whether the collection has any entries at all, to distinguish "empty" from
  // "no matches".
  hasEntries: boolean
  userHasWriteAccess: boolean
  // A key + nonce identifying the entry to scroll into view; the nonce lets the
  // same key re-trigger a scroll.
  scrollTarget: { key: string; nonce: number } | null
  onOpenItem: (key: string) => void
  onEditItem: (entry: ReferenceEntry) => void
  onDeleteItem: (entry: ReferenceEntry) => void
  onLinkClick: (entry: ReferenceEntry) => void
}

// The center column list. Memoized and fed only the debounced-filtered entries,
// so it re-renders at most once per debounce interval, not per keystroke.
const CollectionEntries = memo(function CollectionEntries({
  collectionPath,
  entries,
  hasEntries,
  userHasWriteAccess,
  scrollTarget,
  onOpenItem,
  onEditItem,
  onDeleteItem,
  onLinkClick,
}: CollectionEntriesProps) {
  const [visibleCount, setVisibleCount] = useState(25)
  const [highlightKey, setHighlightKey] = useState<string | null>(null)
  // The card DOM nodes, so a sidebar click can scroll one into view.
  const itemRefs = useRef(new Map<string, HTMLDivElement>())
  const [pendingScrollKey, setPendingScrollKey] = useState<string | null>(null)
  // Reset pagination when the filtered result set changes (new search).
  useEffect(() => {
    setVisibleCount(25)
  }, [entries])
  const totalEntries = entries.length
  const visibleEntries = entries.slice(0, visibleCount)
  // A sidebar click sets scrollTarget: make sure the item is paginated in, then
  // scroll to it and briefly highlight it. Keyed on the nonce so re-clicking the
  // same item re-scrolls; entries is read via ref to avoid re-running on every
  // result-set change.
  const entriesRef = useRef(entries)
  entriesRef.current = entries
  useEffect(() => {
    const key = scrollTarget?.key
    if (!key) return
    const idx = entriesRef.current.findIndex((e) => e.key === key)
    if (idx === -1) return
    setVisibleCount((c) => Math.max(c, idx + 1))
    setPendingScrollKey(key)
    setHighlightKey(key)
  }, [scrollTarget?.key, scrollTarget?.nonce])
  useEffect(() => {
    if (!pendingScrollKey) return
    const el = itemRefs.current.get(pendingScrollKey)
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" })
      setPendingScrollKey(null)
    }
  }, [pendingScrollKey, visibleEntries])
  useEffect(() => {
    if (!highlightKey) return
    const t = setTimeout(() => setHighlightKey(null), 1500)
    return () => clearTimeout(t)
  }, [highlightKey])
  return (
    <Box flex={1} overflowY="auto" minH={0} pb={4}>
      {totalEntries === 0 ? (
        <Text fontSize="sm" color="gray.500">
          {!hasEntries
            ? "This collection has no references."
            : "No references match your search."}
        </Text>
      ) : null}
      {visibleEntries.map((entry) => (
        <Box
          key={`${collectionPath}-${entry.key}`}
          ref={(el) => {
            if (el) itemRefs.current.set(entry.key, el)
            else itemRefs.current.delete(entry.key)
          }}
          borderRadius="lg"
          borderWidth={1}
          borderColor={highlightKey === entry.key ? "blue.400" : undefined}
          transition="border-color 0.2s"
          mb={2}
          p={2}
          boxSizing="border-box"
        >
          <Flex alignItems="center">
            <Heading
              size="sm"
              cursor="pointer"
              _hover={{ color: "blue.500" }}
              onClick={() => onOpenItem(entry.key)}
            >
              {entry.key}
            </Heading>
            {entry.type ? (
              <Badge ml={2} colorScheme="purple" fontSize="0.6em">
                {entry.type}
              </Badge>
            ) : null}
            <Text ml={1} fontSize="sm">
              {entry.file_path ? (
                <Link onClick={() => onLinkClick(entry)}>
                  {`(${entry.file_path})`}
                </Link>
              ) : (
                ""
              )}
            </Text>
            {entry.has_pdf || entry.url ? (
              <Icon
                as={BsFilePdf}
                ml={1}
                color="red.500"
                cursor="pointer"
                onClick={() => onOpenItem(entry.key)}
              />
            ) : null}
            {entry.note_count ? (
              <Badge ml={1} colorScheme="blue" fontSize="0.6em">
                {entry.note_count} note
                {entry.note_count > 1 ? "s" : ""}
              </Badge>
            ) : null}
            {userHasWriteAccess ? (
              <>
                <IconButton
                  aria-label="Edit reference"
                  icon={<MdEdit />}
                  size="xs"
                  variant="ghost"
                  ml="auto"
                  onClick={() => onEditItem(entry)}
                />
                <IconButton
                  aria-label="Delete reference"
                  icon={<FaTrash />}
                  size="xs"
                  variant="ghost"
                  colorScheme="red"
                  onClick={() => onDeleteItem(entry)}
                />
              </>
            ) : null}
          </Flex>
          <ReferenceEntryTable referenceEntry={entry} />
        </Box>
      ))}
      {visibleCount < totalEntries && (
        <Flex justify="center" mt={2} mb={4}>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setVisibleCount((n) => n + 25)}
          >
            Show more ({totalEntries - visibleCount} remaining)
          </Button>
        </Flex>
      )}
    </Box>
  )
})

function References() {
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const navigate = useNavigate({ from: Route.fullPath })
  const {
    path: selectedPath,
    item: openItemKey,
    import_zotero_open: importZoteroOpen,
    new_collection_open: newCollectionOpen,
    label_existing_open: labelExistingOpen,
    items_collapsed: itemsCollapsed,
    resolved: showResolved,
  } = Route.useSearch()
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const connectedAccountsQuery = useQuery({
    queryFn: () =>
      UsersService.getUserConnectedAccounts().then((response) => response.data),
    queryKey: ["user", "connected-accounts"],
  })
  const zoteroConnected = Boolean(connectedAccountsQuery.data?.zotero)
  const showToast = useCustomToast()
  // Zotero uses OAuth 1.0a, whose authorize URL must be signed server-side, so
  // the backend hands it back to us to redirect to.
  const connectZoteroMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserZoteroAuthStart().then((response) => response.data),
    onSuccess: (data) => {
      mixpanel.track("Clicked connect Zotero", { source: "references import" })
      stashZoteroReturn({ reopenImport: true })
      location.href = data.authorize_url
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const openImportZotero = () =>
    navigate({ search: (prev) => ({ ...prev, import_zotero_open: true }) })
  // Connect first when needed, then the OAuth callback reopens the modal.
  const startImportZotero = () =>
    zoteroConnected ? openImportZotero() : connectZoteroMutation.mutate()
  const closeImportZotero = () =>
    navigate({ search: (prev) => ({ ...prev, import_zotero_open: undefined }) })
  const openNewCollection = () =>
    navigate({ search: (prev) => ({ ...prev, new_collection_open: true }) })
  const closeNewCollection = () =>
    navigate({
      search: (prev) => ({ ...prev, new_collection_open: undefined }),
    })
  const openLabelExisting = () =>
    navigate({ search: (prev) => ({ ...prev, label_existing_open: true }) })
  const closeLabelExisting = () =>
    navigate({
      search: (prev) => ({ ...prev, label_existing_open: undefined }),
    })
  // Stable callbacks so the memoized sidebar tree only re-renders when its data
  // (not an unrelated parent state change) actually changes.
  const selectCollection = useCallback(
    (path: string) =>
      navigate({
        search: (prev) => ({
          ...prev,
          path,
          item: undefined,
          items_collapsed: undefined,
        }),
      }),
    [navigate],
  )
  const toggleItemsCollapsed = useCallback(
    () =>
      navigate({
        search: (prev) => ({
          ...prev,
          items_collapsed: prev.items_collapsed ? undefined : true,
        }),
      }),
    [navigate],
  )
  const openItem = useCallback(
    (key: string) => navigate({ search: (prev) => ({ ...prev, item: key }) }),
    [navigate],
  )
  const closeItem = () =>
    navigate({ search: (prev) => ({ ...prev, item: undefined }) })
  const setShowResolved = (resolved: boolean) =>
    navigate({
      search: (prev) => ({ ...prev, resolved: resolved || undefined }),
    })
  const {
    isPending,
    error,
    data: allReferences,
  } = useQuery({
    queryKey: ["projects", accountName, projectName, "references", ref],
    queryFn: () =>
      ProjectsService.getProjectReferences({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })
  const fileViewModal = useDisclosure()
  const editItemModal = useDisclosure()
  const [editEntry, setEditEntry] = useState<ReferenceEntry>()
  const [deleteEntry, setDeleteEntry] = useState<ReferenceEntry>()
  const [selectedEntry, setSelectedEntry] = useState<ReferenceEntry>()
  // Filter for the left collection list (shown when the list gets long).
  const [collectionSearch, setCollectionSearch] = useState("")
  // The shared item search: a single, debounced query filtering both the center
  // list and the sidebar tree. Only the debounced value lives here; the input
  // (immediate value) lives in CollectionSearchBar so keystrokes don't churn the
  // lists.
  const [itemQuery, setItemQuery] = useState("")
  const handleItemQuery = useCallback((q: string) => setItemQuery(q), [])
  // Which entry the center column should scroll to, set by a sidebar click. The
  // nonce lets clicking the same entry again re-trigger the scroll.
  const [scrollTarget, setScrollTarget] = useState<{
    key: string
    nonce: number
  } | null>(null)
  const selectItem = useCallback(
    (key: string) =>
      setScrollTarget((prev) => ({ key, nonce: (prev?.nonce ?? 0) + 1 })),
    [],
  )
  const handleLinkClick = useCallback(
    (entry: ReferenceEntry) => {
      if (!entry.url) {
        return
      }
      setSelectedEntry(entry)
      fileViewModal.onOpen()
    },
    [fileViewModal.onOpen],
  )
  const openAddItem = useCallback(() => {
    setEditEntry(undefined)
    editItemModal.onOpen()
  }, [editItemModal.onOpen])
  const openEditItem = useCallback(
    (entry: ReferenceEntry) => {
      setEditEntry(entry)
      editItemModal.onOpen()
    },
    [editItemModal.onOpen],
  )
  const openDeleteItem = useCallback(
    (entry: ReferenceEntry) => setDeleteEntry(entry),
    [],
  )
  // Default to the first collection when none is selected in the URL.
  const selectedCollection =
    allReferences?.find((r) => r.path === selectedPath) ?? allReferences?.[0]
  // Show a search box for the collection list once it gets long enough to be
  // worth filtering.
  const showCollectionSearch = (allReferences?.length ?? 0) > 8
  const collectionQuery = collectionSearch.trim().toLowerCase()
  // Memoized so the reference stays stable across unrelated parent re-renders,
  // keeping the memoized CollectionTree from re-rendering needlessly.
  const filteredCollections = useMemo(
    () =>
      (allReferences ?? []).filter(
        (r) =>
          !collectionQuery || r.path.toLowerCase().includes(collectionQuery),
      ),
    [allReferences, collectionQuery],
  )
  const selectedItem = openItemKey
    ? selectedCollection?.entries?.find((e) => e.key === openItemKey)
    : undefined
  // Reset the item search when switching collections, so a query typed for one
  // collection doesn't linger on the next.
  useEffect(() => {
    setItemQuery("")
  }, [selectedCollection?.path])
  const selectedEntries = selectedCollection?.entries ?? []
  // Precompute a per-entry search haystack (key + formatted attribute values)
  // once per collection, then filter both the center list and the sidebar tree
  // off the shared debounced query. Memoized so re-renders that don't change the
  // query or the collection keep the same filtered array reference.
  const entryHaystacks = useMemo(
    () =>
      selectedEntries.map((e) => ({
        entry: e,
        haystack: [
          e.key,
          ...Object.entries(e.attrs ?? {}).map(([k, v]) =>
            formatBibField(k, String(v)),
          ),
        ]
          .join(" ")
          .toLowerCase(),
      })),
    [selectedEntries],
  )
  const itemQueryNorm = itemQuery.trim().toLowerCase()
  const filteredEntries = useMemo(
    () =>
      itemQueryNorm
        ? entryHaystacks
            .filter((x) => x.haystack.includes(itemQueryNorm))
            .map((x) => x.entry)
        : selectedEntries,
    [entryHaystacks, itemQueryNorm, selectedEntries],
  )

  return (
    <>
      {isPending ? (
        <LoadingSpinner />
      ) : error ? (
        <Box>
          <Text>Could not read references</Text>
        </Box>
      ) : (
        <Flex width="full" height="100%" gap={0}>
          <FileViewModal
            isOpen={fileViewModal.isOpen}
            onClose={fileViewModal.onClose}
            entry={selectedEntry}
          />
          {userHasWriteAccess ? (
            <>
              <ImportFromZoteroModal
                isOpen={Boolean(importZoteroOpen)}
                onClose={closeImportZotero}
                ownerName={accountName}
                projectName={projectName}
              />
              <NewReferencesCollection
                isOpen={Boolean(newCollectionOpen)}
                onClose={closeNewCollection}
                ownerName={accountName}
                projectName={projectName}
              />
              <LabelExistingReferences
                isOpen={Boolean(labelExistingOpen)}
                onClose={closeLabelExisting}
                ownerName={accountName}
                projectName={projectName}
                existingPaths={(allReferences ?? []).map((r) => r.path)}
              />
              {selectedCollection ? (
                <>
                  <EditReferenceItemModal
                    isOpen={editItemModal.isOpen}
                    onClose={editItemModal.onClose}
                    ownerName={accountName}
                    projectName={projectName}
                    bibPath={selectedCollection.path}
                    entry={editEntry}
                  />
                  <DeleteReferenceItemDialog
                    isOpen={Boolean(deleteEntry)}
                    onClose={() => setDeleteEntry(undefined)}
                    ownerName={accountName}
                    projectName={projectName}
                    bibPath={selectedCollection.path}
                    entry={deleteEntry}
                  />
                </>
              ) : null}
            </>
          ) : null}
          {selectedCollection ? (
            <ReferenceItemModal
              isOpen={Boolean(openItemKey && selectedItem)}
              onClose={closeItem}
              ownerName={accountName}
              projectName={projectName}
              bibPath={selectedCollection.path}
              entry={selectedItem}
              userHasWriteAccess={userHasWriteAccess}
            />
          ) : null}
          {/* Left: collection index (selectable) */}
          <PageMenu>
            <Flex align="center" mb={2}>
              <Heading size="md">References</Heading>
              {userHasWriteAccess ? (
                <Menu>
                  <MenuButton
                    as={Button}
                    variant="primary"
                    height="25px"
                    width="9px"
                    px={1}
                    ml={2}
                  >
                    <Icon as={FaPlus} fontSize="xs" />
                  </MenuButton>
                  <Portal>
                    <MenuList zIndex="popover">
                      <MenuItem onClick={openNewCollection}>
                        New references collection
                      </MenuItem>
                      <MenuItem onClick={openLabelExisting}>
                        Label existing .bib file
                      </MenuItem>
                      <MenuItem
                        onClick={startImportZotero}
                        isDisabled={connectZoteroMutation.isPending}
                      >
                        {zoteroConnected
                          ? "Import from Zotero"
                          : "Connect Zotero to import"}
                      </MenuItem>
                    </MenuList>
                  </Portal>
                </Menu>
              ) : null}
            </Flex>
            {allReferences?.length === 0 ? (
              <Text fontSize="sm" color="gray.500">
                No references yet.
              </Text>
            ) : null}
            {showCollectionSearch ? (
              <InputGroup size="sm" mb={2}>
                <Input
                  placeholder="Search collections"
                  value={collectionSearch}
                  onChange={(e) => setCollectionSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setCollectionSearch("")
                  }}
                  autoComplete="off"
                  data-form-type="other"
                  data-lpignore="true"
                />
                {collectionSearch ? (
                  <InputRightElement>
                    <IconButton
                      aria-label="Clear search"
                      icon={<CloseIcon boxSize={2} />}
                      size="xs"
                      variant="ghost"
                      onClick={() => setCollectionSearch("")}
                    />
                  </InputRightElement>
                ) : null}
              </InputGroup>
            ) : null}
            {(allReferences?.length ?? 0) > 0 &&
            filteredCollections.length === 0 ? (
              <Text fontSize="sm" color="gray.500">
                No matching collections.
              </Text>
            ) : null}
            <CollectionTree
              collections={filteredCollections}
              selectedPath={selectedCollection?.path}
              selectedEntries={filteredEntries}
              searching={Boolean(itemQueryNorm)}
              itemsCollapsed={Boolean(itemsCollapsed)}
              activeItemKey={scrollTarget?.key}
              onSelectCollection={selectCollection}
              onToggleItems={toggleItemsCollapsed}
              onSelectItem={selectItem}
            />
          </PageMenu>
          {/* Center: selected collection's entries. A flex column with a fixed
              search header and an independently scrolling entries body, like
              the left/right columns. */}
          <Box
            flex={1}
            minW={0}
            mr={6}
            display="flex"
            flexDirection="column"
            minH={0}
          >
            {selectedCollection ? (
              <>
                <CollectionSearchBar
                  key={selectedCollection.path}
                  userHasWriteAccess={userHasWriteAccess}
                  onQueryChange={handleItemQuery}
                  onAddItem={openAddItem}
                />
                <CollectionEntries
                  collectionPath={selectedCollection.path}
                  entries={filteredEntries}
                  hasEntries={(selectedCollection.entries?.length ?? 0) > 0}
                  userHasWriteAccess={userHasWriteAccess}
                  scrollTarget={scrollTarget}
                  onOpenItem={openItem}
                  onEditItem={openEditItem}
                  onDeleteItem={openDeleteItem}
                  onLinkClick={handleLinkClick}
                />
              </>
            ) : null}
          </Box>
          {/* Right: info + comments for the selected collection */}
          {selectedCollection ? (
            <Box w="280px" flexShrink={0} overflowY="auto">
              <ReferencesInfoPanel
                references={selectedCollection}
                ownerName={accountName}
                projectName={projectName}
                gitRef={ref}
                userHasWriteAccess={userHasWriteAccess}
                showResolved={Boolean(showResolved)}
                onShowResolvedChange={setShowResolved}
                onDeleted={() =>
                  navigate({
                    search: (prev) => ({
                      ...prev,
                      path: undefined,
                      item: undefined,
                    }),
                  })
                }
              />
            </Box>
          ) : null}
        </Flex>
      )}
    </>
  )
}
