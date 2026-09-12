/**
 * What a publication's folder is made of, file by file, with each file's
 * origin: the stage that made it, the person who wrote it, the source it
 * was brought in from, or nothing anyone has said, which a reader can't
 * follow up on and which the modal here offers to fix.
 */
import {
  Badge,
  Box,
  Button,
  ButtonGroup,
  Code,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  HStack,
  Link,
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
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link as RouterLink,
  getRouteApi,
  useNavigate,
} from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { Fragment, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import {
  type MiscArtifactPost,
  ProjectsService,
  type Publication,
  type PublicationComponent,
} from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import {
  IMPORTED_FROM_DEFAULTS,
  type ImportSource,
  ImportedFromFields,
  type ImportedFromForm,
  buildImportedFrom,
} from "../Datasets/NewDataset"
import {
  AttestationFields,
  type AttestationForm,
  creatorFromUser,
} from "../Figures/UploadFigure"
import { isTemplatePublication } from "./ImportOverleaf"

// What the folder holds, by origin

// Unknowns first, since they're what needs doing; then in the order a
// reader wants: what the pipeline made, what people wrote, vouched for,
// or brought in
const KIND_RANK: Record<PublicationComponent["kind"], number> = {
  unknown: 0,
  produced: 1,
  authored: 2,
  attested: 3,
  imported: 4,
}

/**
 * Sort components for the table: by kind as ranked above, then by path
 * within a kind. An unrecognized kind reads as unknown.
 */
export function sortComponents(
  items: PublicationComponent[],
): PublicationComponent[] {
  const rank = (item: PublicationComponent) =>
    KIND_RANK[item.kind] ?? KIND_RANK.unknown
  return [...items].sort(
    (a, b) => rank(a) - rank(b) || a.path.localeCompare(b.path),
  )
}

/** A component's path as shown inside its folder, e.g., `figures/a.png`. */
export function relativeComponentPath(path: string, folder: string): string {
  const prefix = folder.replace(/\/+$/, "")
  if (prefix && path.startsWith(`${prefix}/`))
    return path.slice(prefix.length + 1)
  return path
}

// Giving a file of unknown origin a known one: copy it in from a project
// figure by a stage, record who made it, or record where it was brought
// in from

type ResolveMode = "figure" | "attest" | "import"

interface ResolveTarget {
  ownerName: string
  projectName: string
  publication: Publication
  folder: string
}

function invalidateResolved(
  queryClient: ReturnType<typeof useQueryClient>,
  ownerName: string,
  projectName: string,
) {
  for (const key of ["publication-components", "pipeline", "publications"])
    queryClient.invalidateQueries({
      queryKey: ["projects", ownerName, projectName, key],
    })
}

/**
 * Copy a project figure into the publication folder by a map-paths stage
 * wired into the publication's build stage, so the file's origin is the
 * figure's.
 */
function useLinkComponentToFigure({
  ownerName,
  projectName,
  publication,
  folder,
}: ResolveTarget) {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  return useMutation({
    mutationFn: ({ src, dest }: { src: string; dest: string }) =>
      ProjectsService.postProjectMapPaths({
        owner_name: ownerName,
        project_name: projectName,
        mapPathsPost: {
          paths: [{ src, dest, kind: "file-to-file" }],
          target_stage: publication.stage ?? null,
          message: `Copy ${src} into ${folder}`,
        },
      }).then((response) => response.data),
    onSuccess: (stage, { src, dest }) => {
      showToast(
        `Linked ${relativeComponentPath(dest, folder)}`,
        `Copied from ${src} by stage ${stage.name} on each pipeline run.`,
        "success",
      )
      invalidateResolved(queryClient, ownerName, projectName)
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
}

interface ResolveFormValues extends AttestationForm, ImportedFromForm {
  figure: string
}

/** The form in the row expanded under a file of unknown origin. */
function ResolveRowForm({
  item,
  mode,
  onDone,
  ownerName,
  projectName,
  publication,
  folder,
}: ResolveTarget & {
  item: PublicationComponent
  mode: ResolveMode
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { user } = useAuth()
  const [source, setSource] = useState<ImportSource>("url")
  const figuresQuery = useQuery({
    queryKey: ["projects", ownerName, projectName, "figures"],
    queryFn: () =>
      ProjectsService.getProjectFigures({
        owner_name: ownerName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: mode === "figure",
    retry: false,
  })
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ResolveFormValues>({
    mode: "onBlur",
    defaultValues: {
      figure: item.matching_figure ?? "",
      created_with_ai: "",
      ...IMPORTED_FROM_DEFAULTS,
    },
  })
  const linkMutation = useLinkComponentToFigure({
    ownerName,
    projectName,
    publication,
    folder,
  })
  const miscMutation = useMutation({
    mutationFn: (data: ResolveFormValues) => {
      const post: MiscArtifactPost = {
        path: item.path,
        message: `Record where ${item.path} came from`,
      }
      if (mode === "attest") {
        post.created_by = [creatorFromUser(user, data.created_with_ai)]
      } else {
        post.imported_from = buildImportedFrom(source, data)
      }
      return ProjectsService.postProjectMisc({
        owner_name: ownerName,
        project_name: projectName,
        miscArtifactPost: post,
      }).then((response) => response.data)
    },
    onSuccess: () => {
      showToast(
        "Origin recorded",
        `${relativeComponentPath(item.path, folder)} is now accounted for.`,
        "success",
      )
      invalidateResolved(queryClient, ownerName, projectName)
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const onSubmit: SubmitHandler<ResolveFormValues> = async (data) => {
    // Errors are toasted by the mutations; the row stays open on one
    try {
      if (mode === "figure") {
        if (!data.figure) return
        await linkMutation.mutateAsync({ src: data.figure, dest: item.path })
      } else {
        await miscMutation.mutateAsync(data)
      }
    } catch {
      return
    }
    onDone()
  }
  const relPath = relativeComponentPath(item.path, folder)
  return (
    <Box
      as="form"
      autoComplete="off"
      onSubmit={handleSubmit(onSubmit)}
      py={2}
      px={1}
    >
      {mode === "figure" ? (
        <FormControl isRequired>
          <FormLabel htmlFor="figure" fontSize="sm">
            Figure to copy to <Code fontSize="xs">{relPath}</Code>
          </FormLabel>
          <Select
            id="figure"
            size="sm"
            {...register("figure", { required: true })}
            placeholder={
              figuresQuery.isPending ? "Loading figures..." : "Choose a figure"
            }
          >
            {figuresQuery.data?.items.map((figure) => (
              <option key={figure.path} value={figure.path}>
                {figure.title
                  ? `${figure.title} (${figure.path})`
                  : figure.path}
              </option>
            ))}
          </Select>
          <FormHelperText>
            A stage copies the figure there on each pipeline run, so the file in
            the paper is always the one the pipeline made.
          </FormHelperText>
        </FormControl>
      ) : null}
      {mode === "attest" ? (
        <AttestationFields
          register={register}
          user={user}
          subject="This file"
        />
      ) : null}
      {mode === "import" ? (
        <>
          <FormControl mb={4}>
            <FormLabel fontSize="sm">Where did it come from?</FormLabel>
            <RadioGroup
              value={source}
              onChange={(value) => setSource(value as ImportSource)}
            >
              <Stack direction={{ base: "column", md: "row" }} spacing={4}>
                <Radio value="url" colorScheme="teal" size="sm">
                  A website
                </Radio>
                <Radio value="doi" colorScheme="teal" size="sm">
                  A DOI (Figshare, Zenodo, etc.)
                </Radio>
                <Radio value="git_repo" colorScheme="teal" size="sm">
                  A Git repo
                </Radio>
              </Stack>
            </RadioGroup>
          </FormControl>
          <ImportedFromFields
            source={source}
            register={register}
            errors={errors}
          />
        </>
      ) : null}
      <HStack mt={3} spacing={2}>
        <Button
          size="sm"
          variant="primary"
          type="submit"
          isLoading={
            isSubmitting || linkMutation.isPending || miscMutation.isPending
          }
        >
          Save
        </Button>
        <Button size="sm" onClick={onDone}>
          Cancel
        </Button>
      </HStack>
    </Box>
  )
}

// The modal: every file in the folder and where it came from

function OriginCell({ item }: { item: PublicationComponent }) {
  if (item.kind === "produced")
    return (
      <>
        {item.stage_kind === "map-paths"
          ? "Copied in by stage"
          : "Pipeline stage"}{" "}
        <Link
          as={RouterLink}
          to="../pipeline"
          search={{ stage: item.stage } as any}
        >
          <Code fontSize="xs" cursor="pointer" wordBreak="break-all">
            {item.stage}
          </Code>
        </Link>
      </>
    )
  if (item.kind === "authored")
    return item.source === "overleaf"
      ? "Written in Overleaf"
      : "Written in this repo"
  if (item.kind === "attested") return "Made by hand or with AI"
  if (item.kind === "imported") return "Imported from elsewhere"
  return (
    <>
      <Badge colorScheme="orange">Unknown</Badge>
      {item.matching_figure ? (
        <Text as="span" ml={2}>
          Same bytes as figure <Code fontSize="xs">{item.matching_figure}</Code>
        </Text>
      ) : null}
    </>
  )
}

function ComponentsModal({
  isOpen,
  onClose,
  items,
  nUnknown,
  canResolve,
  resolvePath,
  resolveAs,
  onResolve,
  onCancelResolve,
  ownerName,
  projectName,
  publication,
  folder,
}: ResolveTarget & {
  isOpen: boolean
  onClose: () => void
  items: PublicationComponent[]
  nUnknown: number
  canResolve: boolean
  resolvePath?: string
  resolveAs?: ResolveMode
  onResolve: (path: string, mode: ResolveMode) => void
  onCancelResolve: () => void
}) {
  const linkMutation = useLinkComponentToFigure({
    ownerName,
    projectName,
    publication,
    folder,
  })
  const target = { ownerName, projectName, publication, folder }
  const sorted = sortComponents(items)
  return (
    <Modal isOpen={isOpen} onClose={onClose} size="3xl" scrollBehavior="inside">
      <ModalOverlay />
      <ModalContent>
        <ModalHeader pb={1}>
          Components of {publication.title || publication.path}
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={4}>
          <Text fontSize="sm" color="ui.dim" mb={3}>
            Everything in <Code fontSize="xs">{folder}</Code>, plus what its
            build stage reads from elsewhere in the project, and where each came
            from. A reader can only trust a figure or table whose origin is
            recorded.
          </Text>
          {sorted.length === 0 ? (
            <Text fontSize="sm">
              Nothing in <Code fontSize="xs">{folder}</Code> yet.
            </Text>
          ) : (
            <Table size="sm">
              <Thead>
                <Tr>
                  <Th>File</Th>
                  <Th>Origin</Th>
                  <Th w="1%" />
                </Tr>
              </Thead>
              <Tbody>
                {sorted.map((item) => {
                  const expanded =
                    canResolve &&
                    item.kind === "unknown" &&
                    resolvePath === item.path &&
                    resolveAs
                  const linking =
                    linkMutation.isPending &&
                    linkMutation.variables?.dest === item.path
                  return (
                    <Fragment key={item.path}>
                      <Tr>
                        <Td>
                          <Link
                            as={RouterLink}
                            to="../files"
                            search={{ path: item.path } as any}
                          >
                            <Code
                              fontSize="xs"
                              cursor="pointer"
                              wordBreak="break-all"
                            >
                              {relativeComponentPath(item.path, folder)}
                            </Code>
                          </Link>
                          {item.via === "input" ? (
                            <Text as="span" fontSize="xs" color="ui.dim" ml={1}>
                              input
                            </Text>
                          ) : null}
                        </Td>
                        <Td>
                          <OriginCell item={item} />
                        </Td>
                        <Td whiteSpace="nowrap" px={2}>
                          {canResolve && item.kind === "unknown" ? (
                            <ButtonGroup size="xs" variant="outline">
                              <Button
                                isActive={expanded === "figure"}
                                isLoading={linking}
                                onClick={() =>
                                  item.matching_figure
                                    ? linkMutation.mutate({
                                        src: item.matching_figure,
                                        dest: item.path,
                                      })
                                    : onResolve(item.path, "figure")
                                }
                              >
                                Link figure
                              </Button>
                              <Button
                                isActive={expanded === "attest"}
                                onClick={() => onResolve(item.path, "attest")}
                              >
                                Made here
                              </Button>
                              <Button
                                isActive={expanded === "import"}
                                onClick={() => onResolve(item.path, "import")}
                              >
                                Imported
                              </Button>
                            </ButtonGroup>
                          ) : null}
                        </Td>
                      </Tr>
                      {expanded ? (
                        <Tr>
                          <Td colSpan={3} pt={0}>
                            <ResolveRowForm
                              key={`${item.path}:${expanded}`}
                              item={item}
                              mode={expanded}
                              onDone={onCancelResolve}
                              {...target}
                            />
                          </Td>
                        </Tr>
                      ) : null}
                    </Fragment>
                  )
                })}
              </Tbody>
            </Table>
          )}
        </ModalBody>
        <ModalFooter>
          <Flex w="100%" align="center" justify="space-between">
            <Text fontSize="sm" color="ui.dim">
              {nUnknown} of {items.length} still unknown
            </Text>
            <Button onClick={onClose}>Close</Button>
          </Flex>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

// The line in the info panel

const routeApi = getRouteApi(
  "/_layout/$accountName/$projectName/_layout/publications",
)

export default function PublicationComponents({
  ownerName,
  projectName,
  publication,
  gitRef,
  userHasWriteAccess,
}: {
  ownerName: string
  projectName: string
  publication: Publication
  gitRef?: string
  userHasWriteAccess: boolean
}) {
  const {
    components_open: componentsOpen,
    resolve_path: resolvePath,
    resolve_as: resolveAs,
  } = routeApi.useSearch()
  const navigate = useNavigate({
    from: "/$accountName/$projectName/publications",
  })
  const componentsQuery = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "publication-components",
      publication.path,
      gitRef,
    ],
    queryFn: () =>
      ProjectsService.getProjectPublicationComponents({
        owner_name: ownerName,
        project_name: projectName,
        path: publication.path,
        ref: gitRef,
      }).then((response) => response.data),
    enabled: Boolean(publication.path),
    retry: false,
  })
  const canResolve = userHasWriteAccess && !gitRef
  const data = componentsQuery.data
  if (!publication.path || !data) return null
  const nItems = data.items.length
  const nUnknown = data.n_unknown
  // A placeholder from the template has nothing worth raising
  const raise = nUnknown > 0 && !isTemplatePublication(publication)
  const openModal = () =>
    navigate({ search: (prev) => ({ ...prev, components_open: true }) })
  const closeModal = () =>
    navigate({
      search: (prev) => ({
        ...prev,
        components_open: undefined,
        resolve_path: undefined,
        resolve_as: undefined,
      }),
    })
  return (
    <Box fontSize="sm" mb={1} wordBreak="break-word">
      <Text as="span" fontWeight="semibold">
        Components:
      </Text>{" "}
      <Link onClick={openModal}>
        {nItems} {nItems === 1 ? "file" : "files"} in{" "}
        <Code fontSize="xs" cursor="pointer" wordBreak="break-all">
          {data.folder}
        </Code>
        {data.items.some((item) => item.via === "input")
          ? " and its inputs"
          : ""}
      </Link>
      {raise ? (
        <Badge colorScheme="orange" ml={1}>
          {nUnknown} of unknown origin
        </Badge>
      ) : null}
      {raise && canResolve ? (
        <Button size="xs" variant="outline" ml={1} onClick={openModal}>
          Fix
        </Button>
      ) : null}
      <ComponentsModal
        isOpen={Boolean(componentsOpen)}
        onClose={closeModal}
        items={data.items}
        nUnknown={nUnknown}
        canResolve={canResolve}
        resolvePath={resolvePath}
        resolveAs={resolveAs}
        onResolve={(path, mode) =>
          navigate({
            search: (prev) => ({
              ...prev,
              resolve_path: path,
              resolve_as: mode,
            }),
          })
        }
        onCancelResolve={() =>
          navigate({
            search: (prev) => ({
              ...prev,
              resolve_path: undefined,
              resolve_as: undefined,
            }),
          })
        }
        ownerName={ownerName}
        projectName={projectName}
        publication={publication}
        folder={data.folder}
      />
    </Box>
  )
}
