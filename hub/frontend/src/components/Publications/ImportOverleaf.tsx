import {
  ChevronDownIcon,
  ChevronRightIcon,
  DownloadIcon,
} from "@chakra-ui/icons"
import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
  Box,
  Button,
  Checkbox,
  Collapse,
  Flex,
  FormControl,
  FormErrorMessage,
  FormLabel,
  HStack,
  IconButton,
  Input,
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
  Switch,
  Text,
  Textarea,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"
import { useRef, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { useDebounce } from "use-debounce"

import type { AxiosError } from "axios"
import { ProjectsService, type Publication, UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface ImportOverleafProps {
  isOpen: boolean
  onClose: () => void
  // Supplied when the modal is opened outside a project route, e.g. from the
  // new-project wizard, which has the project but isn't rendered under it.
  ownerName?: string
  projectName?: string
}

interface OverleafImportPost {
  path: string
  title?: string | null
  description?: string | null
  kind:
    | "journal-article"
    | "conference-paper"
    | "masters-thesis"
    | "phd-thesis"
    | "report"
    | "book"
    | "other"
  overleaf_url: string
  stage?: string | null
  environment?: string | null
  overleaf_token?: string | null
  target_path?: string | null
  auto_build: boolean
  file?: FileList
}

/** What to do when the destination folder is already taken. */
type CollisionChoice = "replace" | "rename"

// How a new publication collides with what a project already has.

/** The folder a publication lives in, i.e., the directory of its path. */
export function publicationFolder(path: string): string {
  const i = path.lastIndexOf("/")
  return i < 0 ? "" : path.slice(0, i)
}

function normalizeFolder(path: string): string {
  return path
    .trim()
    .replace(/^\.?\/+/, "")
    .replace(/\/+$/, "")
}

/**
 * Whether a publication is the untouched one a new project's template
 * starts with, so replacing it costs nothing.
 */
export function isTemplatePublication(
  publication: Pick<Publication, "path" | "title">,
): boolean {
  return (
    publication.title === "The paper" || publication.path === "paper/paper.pdf"
  )
}

export interface PublicationCollision<P> {
  folder: string
  /** The publication already living in that folder, if there is one. */
  publication: P | null
  /** Whether the folder can be replaced without losing anything but the
   * template placeholder. */
  replaceable: boolean
}

/**
 * What importing into `path` would run into: a publication already declared
 * in that folder, or a folder that exists in the repo, whether or not a
 * publication is declared there.
 *
 * Returns null when the folder is free.
 */
export function findPublicationCollision<
  P extends Pick<Publication, "path" | "title">,
>(
  path: string,
  publications: P[],
  folderExists: boolean,
): PublicationCollision<P> | null {
  const folder = normalizeFolder(path)
  if (!folder) return null
  const publication =
    publications.find((pub) => {
      const pubFolder = publicationFolder(pub.path)
      return (
        pubFolder === folder ||
        pubFolder.startsWith(`${folder}/`) ||
        pub.path === folder
      )
    }) ?? null
  if (!publication && !folderExists) return null
  return {
    folder,
    publication,
    replaceable: publication ? isTemplatePublication(publication) : false,
  }
}

const ImportOverleaf = ({
  isOpen,
  onClose,
  ownerName,
  projectName: projectNameProp,
}: ImportOverleafProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  // Non-strict so this reads as empty rather than throwing when the modal is
  // rendered outside the project route.
  const routeParams = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const accountName = ownerName ?? routeParams.accountName ?? ""
  const projectName = projectNameProp ?? routeParams.projectName ?? ""
  const connectedAccountsQuery = useQuery({
    queryFn: () =>
      UsersService.getUserConnectedAccounts().then((response) => response.data),
    queryKey: ["user", "connected-accounts"],
  })
  const [importZip, setImportZip] = useState(false)
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<OverleafImportPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      path: "paper",
      title: null,
      description: null,
      kind: "journal-article",
      overleaf_url: "",
      stage: null,
      environment: null,
      overleaf_token: null,
      target_path: null,
      auto_build: false,
    },
  })
  const [showAdvanced, setShowAdvanced] = useState(false)
  // Whether the destination is already taken, checked as the user types
  // against the declared publications and the repo's folders. A folder
  // that isn't there 404s, which reads as free.
  const currentPath = watch("path")?.trim() ?? ""
  const [debouncedPath] = useDebounce(currentPath, 300)
  const projectKnown = Boolean(accountName && projectName)
  const publicationsQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "publications", undefined],
    queryFn: () =>
      ProjectsService.getProjectPublications({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    enabled: isOpen && projectKnown,
    retry: false,
  })
  const folderQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "contents", debouncedPath],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: accountName,
        project_name: projectName,
        path: debouncedPath,
      }).then((response) => response.data),
    enabled: isOpen && projectKnown && debouncedPath !== "",
    retry: false,
  })
  const collision = findPublicationCollision(
    debouncedPath,
    publicationsQuery.data ?? [],
    folderQuery.isSuccess,
  )
  const checking =
    projectKnown &&
    currentPath !== "" &&
    (currentPath !== debouncedPath ||
      folderQuery.isFetching ||
      publicationsQuery.isPending)
  // Transient form state: which way out of the collision the user picked,
  // remembered per folder so a new folder starts over from the default,
  // which is to replace only the template's placeholder.
  const [pickedChoice, setPickedChoice] = useState<{
    folder: string
    value: CollisionChoice
  } | null>(null)
  const collisionChoice: CollisionChoice =
    collision && pickedChoice?.folder === collision.folder
      ? pickedChoice.value
      : collision?.replaceable
        ? "replace"
        : "rename"
  const setCollisionChoice = (value: CollisionChoice) => {
    if (collision) setPickedChoice({ folder: collision.folder, value })
  }
  const pathInputRef = useRef<HTMLInputElement | null>(null)
  const { ref: registerPathRef, ...pathField } = register("path", {
    required: "Path is required",
    validate: (value) => value.trim() !== "" || "Path is required",
  })
  const replaceExisting = Boolean(collision) && collisionChoice === "replace"
  const collisionUnresolved = Boolean(collision) && !replaceExisting
  const mutation = useMutation({
    mutationFn: (data: OverleafImportPost) =>
      ProjectsService.postProjectOverleafPublication({
        bodyProjectsPostProjectOverleafPublication: {
          path: data.path,
          overleaf_project_url: data.overleaf_url,
          kind: data.kind,
          auto_build: data.auto_build,
          title: data.title || undefined,
          description: data.description || undefined,
          target_path: data.target_path || undefined,
          stage_name: data.stage || undefined,
          environment_name: data.environment || undefined,
          overleaf_token: data.overleaf_token || undefined,
          file: data.file ? data.file[0] : null,
          replace_existing: replaceExisting,
        },
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    onSuccess: (_pub, vars) => {
      showToast(
        "Success!",
        vars.file ? "Overleaf ZIP imported." : "Overleaf project linked.",
        "success",
      )
      reset()
      setImportZip(false)
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "publications"],
      })
      // Replacing rewires stages and rewrites the folder
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "pipeline"],
      })
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "contents"],
      })
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "files"],
      })
    },
  })
  const onSubmit: SubmitHandler<OverleafImportPost> = (data) => {
    if (collisionUnresolved) return
    mutation.mutate(data)
  }

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent
          as="form"
          name="overleaf-import"
          autoComplete="off"
          onSubmit={handleSubmit(onSubmit)}
        >
          <ModalHeader>Import from Overleaf</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl mb={4}>
              <HStack>
                <Text fontSize="sm" color={importZip ? "gray.500" : undefined}>
                  Import/link
                </Text>
                <Switch
                  isChecked={importZip}
                  onChange={(e) => setImportZip(e.target.checked)}
                  colorScheme="teal"
                  aria-label="Toggle ZIP import"
                />
                <Text fontSize="sm" color={!importZip ? "gray.500" : undefined}>
                  Import ZIP
                </Text>
              </HStack>
            </FormControl>
            {/* Overleaf URL field, required only if not importing ZIP */}
            <FormControl
              isRequired={!importZip}
              isInvalid={!!errors.overleaf_url}
            >
              <FormLabel htmlFor="overleaf_url">Overleaf project URL</FormLabel>
              <HStack>
                <Input
                  autoComplete="off"
                  id="overleaf_url"
                  {...register("overleaf_url", {
                    validate: (value) => {
                      // Skip validation if in ZIP import mode
                      if (watch("file")?.length) return true
                      // Otherwise require non-empty URL
                      return (
                        value.trim() !== "" ||
                        "Overleaf project URL is required"
                      )
                    },
                  })}
                  placeholder={"Ex: https://www.overleaf.com/project/abc123..."}
                  type="text"
                />
                {/* Show download button if in ZIP mode and URL has a value */}
                {importZip &&
                  (() => {
                    const overleafUrl = watch("overleaf_url")
                    return overleafUrl && overleafUrl.trim() !== "" ? (
                      <IconButton
                        as="a"
                        href={`${overleafUrl}/download/zip`}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="Download ZIP from Overleaf"
                        icon={<DownloadIcon />}
                        title="Download ZIP from Overleaf"
                        variant="outline"
                        size="md"
                      />
                    ) : null
                  })()}
              </HStack>
              {errors.overleaf_url && (
                <FormErrorMessage>
                  {errors.overleaf_url.message}
                </FormErrorMessage>
              )}
            </FormControl>
            {importZip ? (
              <FormControl mt={4} isRequired>
                <FormLabel htmlFor="zip_file">Overleaf ZIP file</FormLabel>
                <Input
                  pt={1}
                  id="zip_file"
                  {...register("file", {
                    required: importZip ? "ZIP file is required" : false,
                  })}
                  type="file"
                  accept=".zip"
                />
              </FormControl>
            ) : !connectedAccountsQuery.data?.overleaf ? (
              <FormControl
                mt={4}
                isRequired
                isInvalid={!!errors.overleaf_token}
              >
                <FormLabel htmlFor="overleaf_token">Overleaf token</FormLabel>
                <Input
                  autoComplete="off"
                  id="overleaf_token"
                  {...register("overleaf_token", {
                    validate: (value) => {
                      // Skip validation if in ZIP import mode
                      if (watch("file")?.length) return true
                      return (
                        (value && value.trim() !== "") ||
                        "Overleaf token is required"
                      )
                    },
                  })}
                  placeholder={"Ex: olp_..."}
                  type="text"
                />
                {errors.overleaf_token && (
                  <FormErrorMessage>
                    {errors.overleaf_token.message}
                  </FormErrorMessage>
                )}
              </FormControl>
            ) : null}
            {/* Destination folder */}
            <FormControl mt={4} isRequired isInvalid={!!errors.path}>
              <FormLabel htmlFor="path">Destination folder</FormLabel>
              <Input
                autoComplete="off"
                id="path"
                {...pathField}
                ref={(el) => {
                  registerPathRef(el)
                  pathInputRef.current = el
                }}
                placeholder={"Ex: paper"}
                type="text"
              />
              {errors.path && (
                <FormErrorMessage>{errors.path.message}</FormErrorMessage>
              )}
            </FormControl>
            {collision && (
              <Alert
                status="warning"
                borderRadius="md"
                mt={2}
                fontSize="sm"
                alignItems="flex-start"
              >
                <AlertIcon />
                <Box>
                  <AlertTitle fontSize="sm">
                    {collision.publication
                      ? `"${collision.publication.title}" is already at `
                      : "A folder already exists at "}
                    <Text as="code">{collision.folder}</Text>
                  </AlertTitle>
                  <AlertDescription>
                    <RadioGroup
                      mt={2}
                      value={collisionChoice}
                      onChange={(value) => {
                        setCollisionChoice(value as CollisionChoice)
                        if (value === "rename") pathInputRef.current?.focus()
                      }}
                    >
                      <Stack spacing={1}>
                        <Radio value="replace" colorScheme="teal" size="sm">
                          Replace what's at{" "}
                          <Text as="code">{collision.folder}</Text>
                        </Radio>
                        <Text fontSize="xs" color="ui.dim" pl={6}>
                          The current paper there is removed. Pipeline stages
                          that copy figures and results into it are kept and
                          wired to the new paper.
                        </Text>
                        <Radio value="rename" colorScheme="teal" size="sm">
                          Use a different folder
                        </Radio>
                      </Stack>
                    </RadioGroup>
                  </AlertDescription>
                </Box>
              </Alert>
            )}
            {/* Publication type */}
            <FormControl mt={4} isRequired isInvalid={!!errors.kind}>
              <FormLabel htmlFor="kind">Type</FormLabel>
              <Select
                id="kind"
                {...register("kind", {
                  required: "Type is required",
                })}
              >
                <option value="journal-article">Journal article</option>
                <option value="conference-paper">Conference paper</option>
                <option value="report">Report</option>
                <option value="book">Book</option>
                <option value="masters-thesis">Master's thesis</option>
                <option value="phd-thesis">PhD thesis</option>
                <option value="other">Other</option>
              </Select>
            </FormControl>
            {/* Title */}
            <FormControl mt={4} isInvalid={!!errors.title}>
              <FormLabel htmlFor="title">Title</FormLabel>
              <Input
                id="title"
                {...register("title")}
                placeholder="Title"
                type="text"
                autoComplete="off"
              />
              {errors.title && (
                <FormErrorMessage>{errors.title.message}</FormErrorMessage>
              )}
            </FormControl>
            {/* Description */}
            <FormControl mt={4} isInvalid={!!errors.description}>
              <FormLabel htmlFor="description">Description</FormLabel>
              <Textarea
                id="description"
                {...register("description")}
                placeholder="Description"
              />
              {errors.description && (
                <FormErrorMessage>
                  {errors.description.message}
                </FormErrorMessage>
              )}
            </FormControl>
            {/* Auto-build */}
            <Flex mt={4}>
              <FormControl>
                <Checkbox
                  {...register("auto_build")}
                  colorScheme="teal"
                  id="auto_build"
                >
                  Build PDF automatically when updated
                </Checkbox>
              </FormControl>
            </Flex>
            {/* Advanced section toggle */}
            <Box mt={3}>
              <Button
                pl={0}
                pr={2}
                variant="ghost"
                size="md"
                onClick={() => setShowAdvanced(!showAdvanced)}
                leftIcon={
                  showAdvanced ? <ChevronDownIcon /> : <ChevronRightIcon />
                }
                fontWeight="normal"
              >
                Advanced
              </Button>
            </Box>
            {/* Advanced collapsible section */}
            <Collapse in={showAdvanced} animateOpacity>
              <Box pl={2} borderLeft="2px" borderColor="gray.200">
                {/* Target TeX file path */}
                <FormControl mt={4} isInvalid={!!errors.target_path}>
                  <FormLabel htmlFor="target_path">
                    Target TeX file path
                  </FormLabel>
                  <Input
                    autoComplete="off"
                    id="target_path"
                    {...register("target_path")}
                    placeholder={"Ex: main.tex"}
                    type="text"
                  />
                  {errors.target_path && (
                    <FormErrorMessage>
                      {errors.target_path.message}
                    </FormErrorMessage>
                  )}
                </FormControl>
                {/* Environment name */}
                <FormControl mt={4} isInvalid={!!errors.environment}>
                  <FormLabel htmlFor="environment">
                    Docker environment name
                  </FormLabel>
                  <Input
                    autoComplete="off"
                    id="environment"
                    {...register("environment")}
                    placeholder="Ex: tex"
                    type="text"
                  />
                  {errors.environment && (
                    <FormErrorMessage>
                      {errors.environment.message}
                    </FormErrorMessage>
                  )}
                </FormControl>
                {/* Stage name */}
                <FormControl mt={4} isInvalid={!!errors.stage}>
                  <FormLabel htmlFor="stage">Pipeline stage name</FormLabel>
                  <Input
                    autoComplete="off"
                    id="stage"
                    {...register("stage")}
                    placeholder="Ex: build-paper"
                    type="text"
                  />
                  {errors.stage && (
                    <FormErrorMessage>{errors.stage.message}</FormErrorMessage>
                  )}
                </FormControl>
              </Box>
            </Collapse>
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting || mutation.isPending}
              isDisabled={checking || collisionUnresolved}
            >
              {replaceExisting ? "Replace and import" : "Save"}
            </Button>
            <Button onClick={onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}

export default ImportOverleaf
