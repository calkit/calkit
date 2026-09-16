import {
  Box,
  Button,
  Code,
  Flex,
  HStack,
  Input,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink, useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import mixpanel from "mixpanel-browser"
import { useState } from "react"
import { useDebounce } from "use-debounce"

import { DatasetsService, ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import ClearableInput from "../Common/ClearableInput"

interface BrowseDatasetsProps {
  isOpen: boolean
  onClose: () => void
  /** Supplied when rendered outside the project route. */
  ownerName?: string
  projectName?: string
}

/**
 * Find a dataset in another Calkit project and bring it into this one.
 *
 * Data someone else already published on the hub is the cheapest data
 * there is: it has a title, a description, and a home. Importing records
 * that home and the revision it was taken at, so the copy here always
 * points back to where it came from.
 */
const BrowseDatasets = ({
  isOpen,
  onClose,
  ownerName,
  projectName: projectNameProp,
}: BrowseDatasetsProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeParams = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const accountName = ownerName ?? routeParams.accountName ?? ""
  const projectName = projectNameProp ?? routeParams.projectName ?? ""
  const rowBg = useColorModeValue("gray.50", "gray.700")
  const [searchText, setSearchText] = useState("")
  const [search] = useDebounce(searchText, 300)
  const [chosen, setChosen] = useState<string | null>(null)
  const [destPath, setDestPath] = useState("")
  const resultsQuery = useQuery({
    queryKey: ["datasets", "browse", search],
    queryFn: () =>
      DatasetsService.getDatasets({
        search_for: search || undefined,
        limit: 25,
      }).then((response) => response.data),
    enabled: isOpen,
  })
  const results = (resultsQuery.data?.data ?? []).filter(
    // The project's own datasets are already here
    (d) =>
      !(
        d.project.owner_account_name === accountName &&
        d.project.name === projectName
      ),
  )
  const importMutation = useMutation({
    mutationFn: (d: (typeof results)[number]) =>
      ProjectsService.postProjectDataset({
        owner_name: accountName,
        project_name: projectName,
        datasetPost: {
          path: destPath || d.path,
          title: d.title ?? null,
          description: d.description ?? null,
          imported_from: {
            project: `${d.project.owner_account_name}/${d.project.name}`,
            path: d.path,
          },
        },
      }).then((response) => response.data),
    onSuccess: (data) => {
      mixpanel.track("Added dataset", { source: "calkit-project" })
      showToast("Imported", `${data.path} is in the project.`, "success")
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "datasets"],
      })
      setChosen(null)
      setDestPath("")
      onClose()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  return (
    <Modal isOpen={isOpen} onClose={onClose} size="2xl" isCentered>
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Find a dataset on Calkit</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <ClearableInput
            placeholder="Search datasets and projects…"
            value={searchText}
            onValueChange={setSearchText}
            mb={3}
            name="calkit-dataset-search"
            autoComplete="off"
            data-form-type="other"
            data-lpignore="true"
            data-1p-ignore="true"
          />
          {resultsQuery.isPending ? (
            <Spinner size="sm" />
          ) : results.length === 0 ? (
            <Text fontSize="sm" color="ui.dim">
              Nothing matches yet. Public datasets from every project on this
              hub are searchable here.
            </Text>
          ) : (
            <Box maxH="50vh" overflowY="auto">
              {results.map((d) => {
                const key = `${d.project.owner_account_name}/${d.project.name}/${d.path}`
                const isChosen = chosen === key
                return (
                  <Box
                    key={key}
                    p={3}
                    mb={2}
                    borderRadius="md"
                    bg={isChosen ? rowBg : undefined}
                    borderWidth={1}
                  >
                    <Flex align="flex-start" gap={3}>
                      <Box flex={1} minW={0}>
                        <Text fontWeight="semibold" fontSize="sm">
                          {d.title || d.path}
                        </Text>
                        <Text fontSize="xs" color="ui.dim">
                          <Code fontSize="xs">{d.path}</Code> in{" "}
                          <Link
                            as={RouterLink}
                            to={
                              `/${d.project.owner_account_name}/${d.project.name}/datasets` as any
                            }
                            target="_blank"
                          >
                            {d.project.title || d.project.name}
                          </Link>{" "}
                          by {d.project.owner_account_name}
                        </Text>
                        {d.description ? (
                          <Text fontSize="xs" color="ui.dim" noOfLines={2}>
                            {d.description}
                          </Text>
                        ) : null}
                      </Box>
                      {!isChosen ? (
                        <Button
                          size="xs"
                          variant="primary"
                          onClick={() => {
                            setChosen(key)
                            setDestPath(d.path)
                          }}
                        >
                          Import
                        </Button>
                      ) : null}
                    </Flex>
                    {isChosen ? (
                      <HStack mt={2} spacing={2}>
                        <Input
                          size="sm"
                          value={destPath}
                          onChange={(e) => setDestPath(e.target.value)}
                          placeholder="Save as (path in this project)"
                          autoComplete="off"
                        />
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => importMutation.mutate(d)}
                          isLoading={importMutation.isPending}
                          isDisabled={!destPath.trim()}
                        >
                          Import here
                        </Button>
                        <Button size="sm" onClick={() => setChosen(null)}>
                          Cancel
                        </Button>
                      </HStack>
                    ) : null}
                  </Box>
                )
              })}
            </Box>
          )}
          <Text fontSize="xs" color="ui.dim" mt={3}>
            The import records the source project and revision. DVC-tracked data
            stays where it is and is pulled on demand; Git-tracked files are
            copied in.
          </Text>
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default BrowseDatasets
