import {
  Badge,
  Box,
  Button,
  Flex,
  Heading,
  Icon,
  IconButton,
  Image,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  SimpleGrid,
  Spinner,
  Text,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useCallback, useEffect, useState } from "react"
import {
  FaAngleDoubleLeft,
  FaAngleDoubleRight,
  FaComment,
  FaPlus,
  FaRegFileImage,
  FaRegFilePdf,
} from "react-icons/fa"
import { FiFile } from "react-icons/fi"
import { useDebounce } from "use-debounce"
import { z } from "zod"
import ClearableInput from "../../../../../components/Common/ClearableInput"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"

import { type Figure, ProjectsService } from "../../../../../client"
import { ArtifactCompareModal } from "../../../../../components/Common/ArtifactCompareModal"
import Markdown from "../../../../../components/Common/Markdown"
import PdfCanvas from "../../../../../components/Common/PdfCanvas"
import LabelAsFigure from "../../../../../components/Figures/FigureFromExisting"
import UploadFigure from "../../../../../components/Figures/UploadFigure"
import useProject from "../../../../../hooks/useProject"

const figuresSearchSchema = z.object({
  ref: z.string().optional(),
  path: z.string().optional(),
  base_ref: z.string().optional(),
  compare_ref: z.string().optional(),
  page: z.coerce.number().int().min(1).optional(),
  q: z.string().optional(),
})

// Each figure's content is fetched and inlined by the API, so pages are kept
// small; projects with hundreds of figures otherwise take minutes to load.
const FIGURES_PER_PAGE = 20

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/figures",
)({
  component: ProjectFigures,
  validateSearch: (search) => figuresSearchSchema.parse(search),
})

const getIcon = (figure: Figure) => {
  const lp = figure.path.toLowerCase()
  if (
    lp.endsWith(".png") ||
    lp.endsWith(".jpg") ||
    lp.endsWith(".jpeg") ||
    lp.endsWith(".svg")
  ) {
    return FaRegFileImage
  }
  if (lp.endsWith(".pdf")) {
    return FaRegFilePdf
  }
  return FiFile
}

/** Small thumbnail card for a figure in the gallery. */
function FigureThumbnail({
  figure,
  onClick,
}: {
  figure: Figure
  onClick: () => void
}) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const bg = useColorModeValue("white", "gray.800")
  const hoverBg = useColorModeValue("gray.50", "gray.700")

  const renderThumb = () => {
    const lowerPath = figure.path.toLowerCase()
    if (
      (lowerPath.endsWith(".png") ||
        lowerPath.endsWith(".jpg") ||
        lowerPath.endsWith(".jpeg") ||
        lowerPath.endsWith(".svg")) &&
      (figure.content || figure.url)
    ) {
      const ext = lowerPath.split(".").pop() ?? "png"
      const mimeMap: Record<string, string> = {
        png: "image/png",
        jpg: "image/jpeg",
        jpeg: "image/jpeg",
        svg: "image/svg+xml",
      }
      const mime = mimeMap[ext] ?? "image/png"
      return (
        <Image
          src={
            figure.content
              ? `data:${mime};base64,${figure.content}`
              : String(figure.url)
          }
          alt={figure.title}
          objectFit="contain"
          width="100%"
          height="140px"
        />
      )
    }
    if (lowerPath.endsWith(".pdf") && (figure.content || figure.url)) {
      return (
        <Box height="140px" overflow="hidden">
          <PdfCanvas
            src={
              figure.content
                ? `data:application/pdf;base64,${figure.content}`
                : String(figure.url)
            }
            maxPages={1}
          />
        </Box>
      )
    }
    return (
      <Flex
        height="140px"
        align="center"
        justify="center"
        color="gray.400"
        fontSize="3xl"
      >
        <Icon as={getIcon(figure)} />
      </Flex>
    )
  }

  return (
    <Box
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="lg"
      overflow="hidden"
      bg={bg}
      cursor="pointer"
      _hover={{ bg: hoverBg, shadow: "md" }}
      onClick={onClick}
      transition="all 0.15s"
    >
      <Box overflow="hidden" bg="gray.50">
        {renderThumb()}
      </Box>
      <Box p={3}>
        <Flex align="center" justify="space-between" gap={1}>
          <Box fontWeight="semibold" fontSize="sm" flex={1} minW={0}>
            <Markdown inline noOfLines={1}>
              {figure.title}
            </Markdown>
          </Box>
          {(figure.comment_count ?? 0) > 0 && (
            <Flex align="center" gap={1} color="gray.500" flexShrink={0}>
              <Icon as={FaComment} fontSize="xs" />
              <Badge fontSize="xs" variant="subtle" colorScheme="gray">
                {figure.comment_count}
              </Badge>
            </Flex>
          )}
        </Flex>
        {figure.description && (
          <Box fontSize="xs" color="gray.500" mt={0.5}>
            <Markdown inline noOfLines={2}>
              {figure.description}
            </Markdown>
          </Box>
        )}
      </Box>
    </Box>
  )
}

function ProjectFigures() {
  const { accountName, projectName } = Route.useParams()
  const {
    ref,
    path: selectedPath,
    base_ref,
    compare_ref,
    page,
    q,
  } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { userHasWriteAccess } = useProject(accountName, projectName)
  // Seeded from the URL so a shared link opens on the same results, then kept
  // local while typing and mirrored back below.
  const [search, setSearch] = useState(q ?? "")
  const [debouncedSearch] = useDebounce(search, 300)
  const currentPage = page ?? 1
  const offset = (currentPage - 1) * FIGURES_PER_PAGE

  const {
    isPending: figuresPending,
    data: figuresPage,
    isPlaceholderData,
  } = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "figures",
      ref,
      debouncedSearch,
      offset,
    ],
    queryFn: () =>
      ProjectsService.getProjectFigures({
        owner_name: accountName,
        project_name: projectName,
        ref,
        limit: FIGURES_PER_PAGE,
        offset,
        // Filtering happens server-side, across every figure in the project
        // rather than just the ones on this page.
        q: debouncedSearch || undefined,
      }).then((response) => response.data),
    // Keep the previous page rendered while the next one loads, so paging
    // doesn't flash the empty state.
    placeholderData: (prev) => prev,
  })
  const figures = figuresPage?.items
  const totalFigures = figuresPage?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(totalFigures / FIGURES_PER_PAGE))
  const goToPage = useCallback(
    (p: number) =>
      navigate({
        search: (prev) => ({ ...prev, page: p === 1 ? undefined : p }),
      }),
    [navigate],
  )

  // Mirror the search box into the URL so a link reproduces the same results.
  // A new query filters the whole project, so the result set changes out from
  // under whatever page we're on: go back to the first one. Replacing rather
  // than pushing keeps every keystroke out of the history stack, and the
  // equality guard stops this from firing on a shared link (which would
  // otherwise clobber its `page`).
  useEffect(() => {
    if ((q ?? "") === debouncedSearch) return
    navigate({
      search: (prev) => ({
        ...prev,
        q: debouncedSearch || undefined,
        page: undefined,
      }),
      replace: true,
    })
  }, [debouncedSearch, q, navigate])

  // `page` comes from the URL, so it can point past the end: a shared link, or
  // a ref/search change that shrank the result set. Once the API reports the
  // real total, fall back to the last page that actually exists.
  useEffect(() => {
    if (isPlaceholderData || !figuresPage || currentPage <= pageCount) return
    navigate({
      search: (prev) => ({
        ...prev,
        page: pageCount === 1 ? undefined : pageCount,
      }),
      replace: true,
    })
  }, [isPlaceholderData, figuresPage, currentPage, pageCount, navigate])

  const uploadFigureModal = useDisclosure()
  const labelFigureModal = useDisclosure()

  const selectedFigure = figures?.find((f) => f.path === selectedPath) ?? null

  const openFigure = (figure: Figure) =>
    navigate({
      search: (prev) => ({ ...prev, path: figure.path }),
    })

  const closeCompare = () =>
    navigate({
      search: (prev) => ({
        ...prev,
        path: undefined,
        base_ref: undefined,
        compare_ref: undefined,
      }),
    })

  const selectedIndex = figures?.findIndex((f) => f.path === selectedPath) ?? -1
  const pageSize = figures?.length ?? 0

  // Stepping off either end of a page continues onto the neighbouring one.
  // Which figure to open isn't known until that page arrives, so record where
  // we're heading and open it once the data settles.
  const [pendingEdge, setPendingEdge] = useState<{
    offset: number
    edge: "first" | "last"
  } | null>(null)
  useEffect(() => {
    if (!pendingEdge || isPlaceholderData || !figuresPage) return
    // Wait for the page we actually asked for. Setting `pendingEdge` and the
    // new `page` happens in one tick, so the first render after it still
    // holds the outgoing page's items -- and those are real, not placeholder,
    // data. Matching on the offset the response echoes back is what stops us
    // opening a figure from the page we just left.
    if (figuresPage.offset !== pendingEdge.offset) return
    const items = figuresPage.items
    const target =
      pendingEdge.edge === "first" ? items[0] : items[items.length - 1]
    setPendingEdge(null)
    if (target) {
      navigate({ search: (prev) => ({ ...prev, path: target.path }) })
    }
  }, [pendingEdge, isPlaceholderData, figuresPage, navigate])

  const stepToPage = (p: number, edge: "first" | "last") => {
    setPendingEdge({ offset: (p - 1) * FIGURES_PER_PAGE, edge })
    goToPage(p)
  }

  // Left/right page the grid when no figure is open. The modal binds the same
  // keys for its own carousel, so it takes over whenever one is.
  useEffect(() => {
    if (selectedPath) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return
      // Never steal the arrow keys from a field being typed in (the search
      // box lives on this page) or from a modifier-based browser shortcut.
      const el = e.target as HTMLElement | null
      if (
        el?.isContentEditable ||
        ["INPUT", "TEXTAREA", "SELECT"].includes(el?.tagName ?? "") ||
        e.metaKey ||
        e.ctrlKey ||
        e.altKey
      ) {
        return
      }
      const next = e.key === "ArrowLeft" ? currentPage - 1 : currentPage + 1
      if (next < 1 || next > pageCount) return
      e.preventDefault()
      goToPage(next)
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [selectedPath, currentPage, pageCount, goToPage])

  // Mid-rollover the open figure belongs to the page being left, so it isn't
  // in `figures` and neither arrow can be computed. Hand back inert handlers
  // rather than nothing, so the carousel's buttons stay put instead of
  // blinking out until the next page lands.
  const rolling = pendingEdge !== null
  const inert = () => {}

  const openPrev = rolling
    ? inert
    : selectedIndex > 0
      ? () => openFigure(figures![selectedIndex - 1])
      : selectedIndex === 0 && currentPage > 1
        ? () => stepToPage(currentPage - 1, "last")
        : undefined

  const openNext = rolling
    ? inert
    : selectedIndex >= 0 && selectedIndex < pageSize - 1
      ? () => openFigure(figures![selectedIndex + 1])
      : selectedIndex === pageSize - 1 && currentPage < pageCount
        ? () => stepToPage(currentPage + 1, "first")
        : undefined

  return (
    <>
      <Box>
        <Flex align="center" mb={4} gap={2} wrap="wrap">
          <Heading size="md">Figures</Heading>
          {userHasWriteAccess && !ref ? (
            <>
              <Menu>
                <MenuButton
                  as={Button}
                  variant="primary"
                  height="25px"
                  width="9px"
                  px={1}
                >
                  <Icon as={FaPlus} fontSize="xs" />
                </MenuButton>
                <MenuList>
                  <MenuItem onClick={uploadFigureModal.onOpen}>
                    Upload new figure
                  </MenuItem>
                  <MenuItem onClick={labelFigureModal.onOpen}>
                    Label existing file as figure
                  </MenuItem>
                </MenuList>
              </Menu>
              <UploadFigure
                isOpen={uploadFigureModal.isOpen}
                onClose={uploadFigureModal.onClose}
              />
              <LabelAsFigure
                isOpen={labelFigureModal.isOpen}
                onClose={labelFigureModal.onClose}
              />
            </>
          ) : null}
          <ClearableInput
            placeholder="Search figures…"
            size="sm"
            maxW="220px"
            value={search}
            onValueChange={setSearch}
          />
          {pageSize > 0 && (
            <Text fontSize="sm" color="gray.500" ml="auto">
              {offset + 1}–{offset + pageSize} of {totalFigures}
            </Text>
          )}
        </Flex>

        {figuresPending ? (
          <LoadingSpinner height="300px" />
        ) : pageSize === 0 ? (
          debouncedSearch ? (
            <NoArtifactFound
              icon={FaRegFileImage}
              title={`No figures match "${debouncedSearch}"`}
              height="200px"
            />
          ) : (
            <NoArtifactFound
              icon={FaRegFileImage}
              title="No figures found"
              hint="Declare one in calkit.yaml, or add a pipeline stage that produces an image."
              docsUrl="https://docs.calkit.org/calkit-yaml/"
            >
              {ref && (
                <Button
                  mt={3}
                  size="sm"
                  variant="ghost"
                  onClick={() => navigate({ search: {} })}
                >
                  Clear ref filter
                </Button>
              )}
            </NoArtifactFound>
          )
        ) : (
          // The previous page stays mounted while the next one loads so the
          // grid doesn't collapse and rebound. Dimming it behind a spinner is
          // what distinguishes "still loading" from "these are your figures",
          // which stale thumbnails on their own can't.
          <Box position="relative">
            <SimpleGrid
              columns={{ base: 2, md: 3, lg: 4, xl: 5 }}
              spacing={4}
              opacity={isPlaceholderData ? 0.4 : 1}
              transition="opacity 0.15s"
              pointerEvents={isPlaceholderData ? "none" : undefined}
              aria-busy={isPlaceholderData}
            >
              {figures!.map((figure) => (
                <FigureThumbnail
                  key={figure.path}
                  figure={figure}
                  onClick={() => openFigure(figure)}
                />
              ))}
            </SimpleGrid>
            {isPlaceholderData && (
              <Flex
                position="absolute"
                inset={0}
                align="center"
                justify="center"
              >
                <Spinner size="lg" thickness="3px" color="ui.main" />
              </Flex>
            )}
          </Box>
        )}

        {pageCount > 1 && (
          <Flex align="center" justify="center" gap={3} mt={6}>
            <IconButton
              size="sm"
              variant="ghost"
              aria-label="First page"
              title="First page"
              icon={<FaAngleDoubleLeft />}
              isDisabled={currentPage <= 1}
              onClick={() => goToPage(1)}
            />
            <Button
              size="sm"
              variant="ghost"
              isDisabled={currentPage <= 1}
              onClick={() => goToPage(currentPage - 1)}
            >
              Previous
            </Button>
            <Text fontSize="sm" color="gray.500">
              Page {currentPage} of {pageCount}
            </Text>
            <Button
              size="sm"
              variant="ghost"
              isDisabled={currentPage >= pageCount}
              onClick={() => goToPage(currentPage + 1)}
            >
              Next
            </Button>
            <IconButton
              size="sm"
              variant="ghost"
              aria-label="Last page"
              title="Last page"
              icon={<FaAngleDoubleRight />}
              isDisabled={currentPage >= pageCount}
              onClick={() => goToPage(pageCount)}
            />
          </Flex>
        )}
      </Box>

      {/* A shared link can point at a figure that isn't on the current page;
          the modal fetches it itself when we have no preloaded copy. */}
      {selectedPath && (
        <ArtifactCompareModal
          isOpen={Boolean(selectedPath)}
          onClose={closeCompare}
          ownerName={accountName}
          projectName={projectName}
          path={selectedPath}
          kind="figure"
          initialRef={base_ref ?? ref}
          initialRef2={compare_ref}
          initialArtifact={selectedFigure ?? undefined}
          onRefsChange={(r1, r2) =>
            navigate({
              search: (prev) => ({
                ...prev,
                // base_ref defaults to the current ref, so don't write it to
                // the URL unless the user picked a different comparison base.
                base_ref: r1 === ref ? undefined : r1,
                compare_ref: r2,
              }),
            })
          }
          onPrev={openPrev}
          onNext={openNext}
        />
      )}
    </>
  )
}
