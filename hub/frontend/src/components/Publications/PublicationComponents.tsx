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

// What a publication is made of, worst first

// A component nothing accounts for is what needs doing; after that, order
// by what the thing is, so a file's siblings stay together and the page
// content reads as its own group.
const STATUS_RANK: Record<string, number> = {
  missing: 0,
  stale: 1,
  unknown: 2,
  ok: 3,
}
const KIND_RANK: Record<PublicationComponent["kind"], number> = {
  file: 0,
  value: 1,
  figure: 2,
  text: 3,
  block: 4,
}

/**
 * Sort for the table: anything undeclared or out of date first, then by
 * kind, then by path and key.
 */
export function sortComponents(
  items: PublicationComponent[],
): PublicationComponent[] {
  const needsAttention = (item: PublicationComponent) =>
    item.provenance === "undeclared" ||
    item.status === "stale" ||
    item.status === "missing"
      ? 0
      : 1
  const rank = (item: PublicationComponent) =>
    STATUS_RANK[item.status ?? "unknown"] ?? STATUS_RANK.unknown
  return [...items].sort(
    (a, b) =>
      needsAttention(a) - needsAttention(b) ||
      rank(a) - rank(b) ||
      (KIND_RANK[a.kind] ?? 0) - (KIND_RANK[b.kind] ?? 0) ||
      a.path.localeCompare(b.path) ||
      (a.key ?? "").localeCompare(b.key ?? ""),
  )
}

/** How a component is named in the table: the path, and the key within it. */
export function componentLabel(
  item: PublicationComponent,
  folder: string,
): string {
  const shown = relativeComponentPath(item.path, folder)
  return item.key ? `${shown}:${item.key}` : shown
}

/** "pp. 3, 7", or nothing for a component that reached no page. */
export function pagesText(pages: number[] | undefined): string {
  if (!pages || pages.length === 0) return ""
  return `${pages.length === 1 ? "p." : "pp."} ${pages.join(", ")}`
}

const STALE_EXPLANATIONS: Record<string, string> = {
  "stage-out-of-date": "its stage needs a rerun",
  "changed-since-build": "the project has moved on since this was built",
  "answer-stale": "the answer no longer matches its evidence",
}

/** Why a component is not current, in a reader's terms. */
export function staleExplanation(item: PublicationComponent): string {
  return (item.stale_reasons ?? [])
    .map((reason) => STALE_EXPLANATIONS[reason] ?? reason)
    .join(", and ")
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
  if (item.provenance === "pipeline")
    return (
      <>
        <Link
          as={RouterLink}
          to="../pipeline"
          search={{ stage: item.stage } as any}
        >
          <Code fontSize="xs" cursor="pointer" wordBreak="break-all">
            {item.stage}
          </Code>
        </Link>
        <Text fontSize="xs" color="ui.dim">
          {item.stage_kind === "map-paths"
            ? "copied in by this stage"
            : item.script ?? "pipeline stage"}
        </Text>
      </>
    )
  if (item.provenance === "authored")
    return item.source === "overleaf"
      ? "Written in Overleaf"
      : "Written in this repo"
  if (item.provenance === "attested") return "Made by hand or with AI"
  if (item.provenance === "imported") return "Imported from elsewhere"
  if (item.provenance === "project") return "The project's own words"
  return (
    <>
      <Badge colorScheme="orange">No provenance</Badge>
      {item.matching_figure ? (
        <Text fontSize="xs" color="ui.dim">
          Same bytes as figure <Code fontSize="xs">{item.matching_figure}</Code>
        </Text>
      ) : null}
    </>
  )
}

function StateCell({ item }: { item: PublicationComponent }) {
  if (item.status === "missing") return <Badge colorScheme="red">Missing</Badge>
  if (item.status === "stale")
    return (
      <>
        <Badge colorScheme="orange">Out of date</Badge>
        <Text fontSize="xs" color="ui.dim">
          {staleExplanation(item)}
        </Text>
      </>
    )
  if (item.kind === "file") return null
  if (item.status === "ok") return <Badge colorScheme="green">Current</Badge>
  return <Badge>Unchecked</Badge>
}

function ComponentsModal({
  isOpen,
  onClose,
  items,
  nUndeclared,
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
  nUndeclared: number
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
            Everything in <Code fontSize="xs">{folder}</Code>, what its build
            stage reads from elsewhere in the project, and the values, figures
            and blocks the document takes from the project rather than copies. A
            reader can only trust a number or figure whose origin is recorded.
          </Text>
          {sorted.length === 0 ? (
            <Text fontSize="sm">
              Nothing in <Code fontSize="xs">{folder}</Code> yet.
            </Text>
          ) : (
            <Table size="sm">
              <Thead>
                <Tr>
                  <Th>What</Th>
                  <Th>From</Th>
                  <Th>Where</Th>
                  <Th>State</Th>
                  <Th w="1%" />
                </Tr>
              </Thead>
              <Tbody>
                {sorted.map((item) => {
                  const expanded =
                    canResolve &&
                    item.kind === "file" &&
                    item.provenance === "undeclared" &&
                    resolvePath === item.path &&
                    resolveAs
                  const linking =
                    linkMutation.isPending &&
                    linkMutation.variables?.dest === item.path
                  return (
                    <Fragment key={item.path}>
                      <Tr>
                        <Td>
                          {item.kind !== "file" ? (
                            <Badge mr={1}>{item.kind}</Badge>
                          ) : null}
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
                              {componentLabel(item, folder)}
                            </Code>
                          </Link>
                          {item.via === "input" ? (
                            <Text as="span" fontSize="xs" color="ui.dim" ml={1}>
                              input
                            </Text>
                          ) : null}
                          {item.kind === "value" &&
                          item.current_value !== null &&
                          item.current_value !== undefined ? (
                            <Text fontSize="xs" color="ui.dim">
                              {String(item.current_value)}
                            </Text>
                          ) : null}
                        </Td>
                        <Td>
                          <OriginCell item={item} />
                        </Td>
                        <Td fontSize="xs" color="ui.dim" whiteSpace="nowrap">
                          {pagesText(item.pages)}
                        </Td>
                        <Td>
                          <StateCell item={item} />
                        </Td>
                        <Td whiteSpace="nowrap" px={2}>
                          {canResolve &&
                          item.kind === "file" &&
                          item.provenance === "undeclared" ? (
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
                          <Td colSpan={5} pt={0}>
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
              {nUndeclared} of {items.length} with no provenance
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
  const items = data?.items ?? []
  if (!publication.path || !data) return null
  const nFiles = items.filter((item) => item.kind === "file").length
  const nContent = items.length - nFiles
  const nUndeclared = data.n_undeclared ?? 0
  const nStale = data.n_stale ?? 0
  // A placeholder from the template has nothing worth raising
  const raise = nUndeclared > 0 && !isTemplatePublication(publication)
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
        {nFiles} {nFiles === 1 ? "file" : "files"} in{" "}
        <Code fontSize="xs" cursor="pointer" wordBreak="break-all">
          {data.folder}
        </Code>
        {items.some((item) => item.via === "input") ? " and its inputs" : ""}
        {nContent > 0 ? `, ${nContent} from the project` : ""}
      </Link>
      {nStale > 0 ? (
        <Badge colorScheme="orange" ml={1}>
          {nStale} out of date
        </Badge>
      ) : null}
      {raise ? (
        <Badge colorScheme="orange" ml={1}>
          {nUndeclared} with no provenance
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
        items={items}
        nUndeclared={nUndeclared}
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
