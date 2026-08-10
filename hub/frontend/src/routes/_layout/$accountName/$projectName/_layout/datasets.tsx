import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import {
  Box,
  Heading,
  Flex,
  Text,
  Code,
  Badge,
  SimpleGrid,
  Card,
  Menu,
  MenuButton,
  Icon,
  MenuList,
  MenuItem,
  Button,
  useDisclosure,
  Link,
} from "@chakra-ui/react"
import {
  createFileRoute,
  Link as RouterLink,
  useSearch,
} from "@tanstack/react-router"
import { FaPlus } from "react-icons/fa"

import DatasetFromExisting from "../../../../../components/Datasets/DatasetFromExisting"
import UploadDataset from "../../../../../components/Datasets/UploadDataset"
import useProject, { useProjectDatasets } from "../../../../../hooks/useProject"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/datasets",
)({
  component: ProjectData,
})

function ProjectDataView() {
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const { userHasWriteAccess } = useProject(accountName, projectName)
  const { datasetsRequest } = useProjectDatasets(accountName, projectName, ref)
  const { isPending: dataPending, data: datasets } = datasetsRequest
  const uploadDataModal = useDisclosure()
  const labelDataModal = useDisclosure()

  return (
    <>
      <Flex align="center" mb={2}>
        <Heading size="md">Datasets</Heading>
        {userHasWriteAccess ? (
          <>
            <Menu>
              <MenuButton
                as={Button}
                variant="primary"
                height={"25px"}
                width={"9px"}
                px={1}
                ml={2}
              >
                <Icon as={FaPlus} fontSize="xs" />
              </MenuButton>
              <MenuList>
                <MenuItem onClick={uploadDataModal.onOpen}>
                  Upload new dataset
                </MenuItem>
                <MenuItem onClick={labelDataModal.onOpen}>
                  Label existing file or folder as dataset
                </MenuItem>
              </MenuList>
            </Menu>
            <DatasetFromExisting
              onClose={labelDataModal.onClose}
              isOpen={labelDataModal.isOpen}
            />
            <UploadDataset
              onClose={uploadDataModal.onClose}
              isOpen={uploadDataModal.isOpen}
            />
          </>
        ) : (
          ""
        )}
      </Flex>
      {dataPending ? (
        <LoadingSpinner height="100vh" />
      ) : (
        <Box>
          <SimpleGrid columns={[3, null, 4]} gap={6}>
            {datasets?.map((dataset) => (
              <Card key={dataset.path} p={6} variant="elevated">
                <Heading size="sm" mb={2}>
                  <Code p={1} maxW="100%">
                    <Link
                      as={RouterLink}
                      to={"../files"}
                      search={{ path: dataset.path } as any}
                    >
                      {dataset.path}
                    </Link>
                    {dataset.imported_from ? (
                      <Badge ml={1} bgColor="green.500">
                        imported
                      </Badge>
                    ) : (
                      ""
                    )}
                  </Code>
                </Heading>
                {dataset.title ? (
                  <Text mb={1}>
                    <strong>Title:</strong> {dataset.title}
                  </Text>
                ) : (
                  ""
                )}
                {dataset.description ? (
                  <Text>
                    <strong>Description:</strong> {dataset.description}
                  </Text>
                ) : (
                  ""
                )}
              </Card>
            ))}
          </SimpleGrid>
        </Box>
      )}
    </>
  )
}

function ProjectData() {
  return <ProjectDataView />
}
