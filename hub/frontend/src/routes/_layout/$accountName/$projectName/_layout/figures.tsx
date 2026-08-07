import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import ClearableInput from "../../../../../components/Common/ClearableInput"
import {
  Box,
  Heading,
  Flex,
  Text,
  Button,
  Icon,
  useDisclosure,
  Menu,
  MenuButton,
  MenuList,
  MenuItem,
  SimpleGrid,
  useColorModeValue,
  Image,
  Badge,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import { FaPlus, FaRegFileImage, FaRegFilePdf, FaComment } from "react-icons/fa"
import { FiFile } from "react-icons/fi"
import { z } from "zod"

import UploadFigure from "../../../../../components/Figures/UploadFigure"
import LabelAsFigure from "../../../../../components/Figures/FigureFromExisting"
import PdfCanvas from "../../../../../components/Common/PdfCanvas"
import { ProjectsService, type Figure } from "../../../../../client"
import useProject from "../../../../../hooks/useProject"
import { ArtifactCompareModal } from "../../../../../components/Common/ArtifactCompareModal"

const figuresSearchSchema = z.object({
  ref: z.string().optional(),
  path: z.string().optional(),
  base_ref: z.string().optional(),
  compare_ref: z.string().optional(),
})

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
          <Text fontWeight="semibold" fontSize="sm" noOfLines={1} flex={1}>
            {figure.title}
          </Text>
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
          <Text fontSize="xs" color="gray.500" noOfLines={2} mt={0.5}>
            {figure.description}
          </Text>
        )}
      </Box>
    </Box>
  )
}

function ProjectFigures() {
  const { accountName, projectName } = Route.useParams()
  const { ref, path: selectedPath, base_ref, compare_ref } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const [search, setSearch] = useState("")

  const { isPending: figuresPending, data: figures } = useQuery({
    queryKey: ["projects", accountName, projectName, "figures", ref],
    queryFn: () =>
      ProjectsService.getProjectFigures({
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
  })
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

  const filteredFigures = figures?.filter((f) => {
    const q = search.toLowerCase()
    return (
      f.title.toLowerCase().includes(q) ||
      f.path.toLowerCase().includes(q) ||
      (f.description ?? "").toLowerCase().includes(q)
    )
  })

  const selectedIndex =
    filteredFigures?.findIndex((f) => f.path === selectedPath) ?? -1

  const openPrev =
    selectedIndex > 0
      ? () => openFigure(filteredFigures![selectedIndex - 1])
      : undefined

  const openNext =
    selectedIndex < (filteredFigures?.length ?? 0) - 1
      ? () => openFigure(filteredFigures![selectedIndex + 1])
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
        </Flex>

        {figuresPending ? (
          <LoadingSpinner height="300px" />
        ) : !filteredFigures || figures?.length === 0 ? (
          <Flex
            direction="column"
            align="center"
            justify="center"
            height="300px"
            color="gray.500"
          >
            <Icon as={FaRegFileImage} fontSize="4xl" mb={3} />
            <Text>No figures found</Text>
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
          </Flex>
        ) : filteredFigures?.length === 0 ? (
          <Flex
            direction="column"
            align="center"
            justify="center"
            height="200px"
            color="gray.500"
          >
            <Text>No figures match "{search}"</Text>
          </Flex>
        ) : (
          <SimpleGrid columns={{ base: 2, md: 3, lg: 4, xl: 5 }} spacing={4}>
            {filteredFigures!.map((figure) => (
              <FigureThumbnail
                key={figure.path}
                figure={figure}
                onClick={() => openFigure(figure)}
              />
            ))}
          </SimpleGrid>
        )}
      </Box>

      {selectedFigure && (
        <ArtifactCompareModal
          isOpen={Boolean(selectedPath)}
          onClose={closeCompare}
          ownerName={accountName}
          projectName={projectName}
          path={selectedFigure.path}
          kind="figure"
          initialRef={base_ref ?? ref}
          initialRef2={compare_ref}
          initialArtifact={selectedFigure}
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
