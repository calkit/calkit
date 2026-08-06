import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
  Box,
  Button,
  ButtonGroup,
  Checkbox,
  Code,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  HStack,
  Icon,
  Input,
  InputGroup,
  InputRightElement,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Text,
  Textarea,
  useClipboard,
} from "@chakra-ui/react"
import Tooltip from "../Common/Tooltip"
import { useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { FiExternalLink, FiThumbsUp } from "react-icons/fi"

import {
  FeatureVotesService,
  type ReleasePublic,
  ReleasesService,
} from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import {
  releasePagePath,
  releasePageUrl,
  validateReleaseName,
} from "../../lib/releases"
import PathPicker from "./PathPicker"
import ShareDialog from "./ShareDialog"

interface NewReleaseProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  // Path of the artifact being released (e.g., the selected publication).
  defaultPath?: string
  // Calkit release kind; defaults to "publication".
  kind?: string
  // When provided, a created internal release skips the link-success screen and
  // is handed back to the caller (e.g., to immediately open Share).
  onCreated?: (release: ReleasePublic) => void
}

// Create a new internal release, or import an already-published external one.
type Mode = "create" | "import"

interface NewReleaseForm {
  name: string
  path: string
  description: string
  // Acknowledgement required when the producing stage is stale.
  acknowledge: boolean
  // "import" mode
  lookupUrl: string
  publisher: string
  url: string
  doi: string
  date: string
}

// Feature users can vote for: creating external (published) releases from
// within Calkit instead of the CLI. Must match VOTABLE_FEATURES on the backend.
const EXTERNAL_RELEASE_FEATURE = "external-releases-in-app"

const NewRelease = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  defaultPath,
  kind = "publication",
  onCreated,
}: NewReleaseProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [mode, setMode] = useState<Mode>("create")
  // A created internal release returns a record with its hosted page link.
  const [created, setCreated] = useState<ReleasePublic | null>(null)
  // Whether the share dialog is stacked over the success screen.
  const [sharing, setSharing] = useState(false)
  const [importDone, setImportDone] = useState(false)
  // Whether metadata has been fetched for the pasted URL (gates Import).
  const [fetched, setFetched] = useState(false)
  // Release kind from the parsed URL (e.g., dataset vs publication).
  const [importKind, setImportKind] = useState(kind)
  const link = created
    ? releasePageUrl(ownerName, projectName, created.name)
    : ""
  const { onCopy, hasCopied } = useClipboard(link)
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<NewReleaseForm>({
    mode: "onBlur",
    defaultValues: {
      name: "",
      path: defaultPath ?? "",
      description: "",
      acknowledge: false,
      lookupUrl: "",
      publisher: "",
      url: "",
      doi: "",
      date: "",
    },
  })
  // Keep the path field in sync with the prefill when the modal is (re)opened,
  // since defaultValues only apply on first mount.
  useEffect(() => {
    if (isOpen) {
      reset((prev) => ({ ...prev, path: defaultPath ?? "" }))
    }
  }, [isOpen, defaultPath, reset])
  const path = watch("path")
  const acknowledged = watch("acknowledge")
  const lookupUrl = watch("lookupUrl")
  // Debounce the staleness lookup so we don't hit the repo on every keystroke.
  // Releases always pin to the latest commit, so staleness is checked there.
  const [stalenessPath, setStalenessPath] = useState("")
  useEffect(() => {
    const handle = setTimeout(() => {
      setStalenessPath(path.trim())
      // A new artifact means any prior acknowledgement no longer applies.
      setValue("acknowledge", false)
    }, 500)
    return () => clearTimeout(handle)
  }, [path, setValue])
  // Only an internal release of a specific path can be gated on staleness.
  const stalenessEnabled =
    isOpen && mode === "create" && stalenessPath.length > 0
  const { data: staleness } = useQuery({
    queryKey: [
      "projects",
      ownerName,
      projectName,
      "release-staleness",
      stalenessPath,
    ],
    queryFn: () =>
      ReleasesService.getReleaseStaleness({
        ownerName,
        projectName,
        path: stalenessPath || undefined,
      }),
    enabled: stalenessEnabled,
    retry: false,
  })
  const isStale = stalenessEnabled && staleness?.up_to_date === false
  const needsAck = isStale && !acknowledged
  // Demand signal for creating external releases from within Calkit.
  const { data: voteStatus } = useQuery({
    queryKey: ["feature-votes", EXTERNAL_RELEASE_FEATURE],
    queryFn: () =>
      FeatureVotesService.getFeatureVoteStatus({
        feature: EXTERNAL_RELEASE_FEATURE,
      }),
    enabled: isOpen,
  })
  const voteMutation = useMutation({
    mutationFn: (voted: boolean) =>
      voted
        ? FeatureVotesService.deleteFeatureVote({
            feature: EXTERNAL_RELEASE_FEATURE,
          })
        : FeatureVotesService.postFeatureVote({
            feature: EXTERNAL_RELEASE_FEATURE,
          }),
    onSuccess: (data) =>
      queryClient.setQueryData(
        ["feature-votes", EXTERNAL_RELEASE_FEATURE],
        data,
      ),
    onError: (err: ApiError) => handleError(err, showToast),
  })
  // Per-field opt-out for password managers (Dashlane especially keeps trying
  // to autofill even with a form-level opt-out), spread onto each text input.
  const noAutofill = {
    autoComplete: "off",
    "data-form-type": "other",
    "data-1p-ignore": true,
    "data-lpignore": "true",
  } as const

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: ["projects", ownerName, projectName, "releases"],
    })

  const parseMutation = useMutation({
    mutationFn: (url: string) =>
      ReleasesService.parseReleaseUrl({
        ownerName,
        projectName,
        requestBody: { url },
      }),
    onSuccess: (meta) => {
      // Pre-fill the editable form from the looked-up metadata. The fetched
      // title becomes the release name (no separate title field); the user can
      // shorten it. git_rev isn't knowable from a URL, so it's left unset.
      if (meta.title) {
        setValue("name", meta.title)
      }
      setValue("publisher", meta.publisher ?? "")
      setValue("url", meta.url ?? "")
      setValue("doi", meta.doi ?? "")
      setValue("date", meta.date ?? "")
      setValue("description", meta.description ?? "")
      setImportKind(meta.kind ?? kind)
      setFetched(true)
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })

  const createMutation = useMutation({
    mutationFn: (data: NewReleaseForm) =>
      ReleasesService.postProjectRelease({
        ownerName,
        projectName,
        requestBody: {
          name: data.name,
          kind,
          path: data.path.trim() || null,
          description: data.description || null,
          // Pinned to the latest commit; private link by default (share it,
          // or make it public, afterward).
          public: false,
          acknowledge_non_reproducible: data.acknowledge,
        },
      }),
    onSuccess: (data) => {
      if (onCreated) {
        onCreated(data)
        handleClose()
        return
      }
      setCreated(data)
      reset()
    },
    onError: (err: ApiError) => handleError(err, showToast),
    onSettled: invalidate,
  })

  const importMutation = useMutation({
    mutationFn: (data: NewReleaseForm) =>
      ReleasesService.postExternalRelease({
        ownerName,
        projectName,
        requestBody: {
          name: data.name,
          kind: importKind,
          path: data.path.trim() || null,
          publisher: data.publisher || null,
          url: data.url || null,
          doi: data.doi || null,
          date: data.date || null,
          description: data.description || null,
          public: true,
        },
      }),
    onSuccess: () => {
      setImportDone(true)
      reset()
    },
    onError: (err: ApiError) => handleError(err, showToast),
    onSettled: invalidate,
  })

  const onSubmit: SubmitHandler<NewReleaseForm> = (data) => {
    if (mode === "import") {
      if (!fetched) {
        return
      }
      importMutation.mutate(data)
    } else {
      createMutation.mutate(data)
    }
  }

  const switchMode = (next: Mode) => {
    setMode(next)
    setFetched(false)
  }

  const handleClose = () => {
    setCreated(null)
    setSharing(false)
    setImportDone(false)
    setFetched(false)
    setMode("create")
    reset()
    onClose()
  }

  const navigate = useNavigate()
  const openRelease = () => {
    if (!created) return
    handleClose()
    navigate({
      to: releasePagePath(ownerName, projectName, created.name) as any,
    })
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      size={{ base: "sm", md: "md" }}
      isCentered
    >
      <ModalOverlay />
      {created ? (
        <ModalContent>
          <ModalHeader>Release created</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <Text mb={2}>
              Recorded in <Code>calkit.yaml</Code> and pushed. Open the release
              page for <Code>{created.path ?? "the project"}</Code> at{" "}
              <Code>{created.git_ref ?? created.git_rev_abbrev}</Code>:
            </Text>
            <InputGroup>
              <Input value={link} isReadOnly pr="4.5rem" />
              <InputRightElement width="4.5rem">
                <Button h="1.75rem" size="sm" onClick={onCopy}>
                  {hasCopied ? "Copied" : "Copy"}
                </Button>
              </InputRightElement>
            </InputGroup>
            <Text mt={3} fontSize="sm" color="gray.500">
              To let teammates or external reviewers view and comment without an
              account, use <b>Share</b> on the release to create an email-scoped
              link.
            </Text>
          </ModalBody>
          <ModalFooter gap={3}>
            <Button variant="primary" onClick={openRelease}>
              Open release
            </Button>
            <Button onClick={() => setSharing(true)}>Create share link</Button>
            <Button onClick={handleClose}>Done</Button>
          </ModalFooter>
        </ModalContent>
      ) : importDone ? (
        <ModalContent>
          <ModalHeader>Release imported</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <Text>
              Recorded in <Code>calkit.yaml</Code> and pushed. It will appear in
              your project's releases. If the producing commit is known, you can
              set its Git revision in <Code>calkit.yaml</Code> later.
            </Text>
          </ModalBody>
          <ModalFooter>
            <Button variant="primary" onClick={handleClose}>
              Done
            </Button>
          </ModalFooter>
        </ModalContent>
      ) : (
        <ModalContent
          as="form"
          onSubmit={handleSubmit(onSubmit)}
          autoComplete="off"
          // Opt the whole form out of password managers (Dashlane, 1Password,
          // LastPass), which otherwise pop suggestions over these fields.
          data-form-type="other"
          data-1p-ignore
          data-lpignore="true"
        >
          <ModalHeader>New release</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <ButtonGroup isAttached variant="outline" size="sm" mb={4}>
              <Button
                type="button"
                isActive={mode === "create"}
                onClick={() => switchMode("create")}
              >
                Create
              </Button>
              <Button
                type="button"
                isActive={mode === "import"}
                onClick={() => switchMode("import")}
              >
                Import from URL
              </Button>
            </ButtonGroup>

            {mode === "create" ? (
              <Text fontSize="sm" color="gray.600" mb={4}>
                Snapshot the project (or a single artifact) at its latest commit
                and host it on Calkit, so you can share it for review.
              </Text>
            ) : (
              <Text fontSize="sm" color="gray.600" mb={4}>
                Record a release that's already published elsewhere. Paste its
                DOI or link (Zenodo, a journal, arXiv, OSF, etc.) and we'll look
                up the details.
              </Text>
            )}

            {mode === "import" && (
              <FormControl mb={4}>
                <FormLabel htmlFor="lookupUrl">URL or DOI</FormLabel>
                <HStack>
                  <Input
                    id="lookupUrl"
                    placeholder="https://doi.org/… or arXiv link"
                    {...register("lookupUrl")}
                    {...noAutofill}
                  />
                  <Button
                    type="button"
                    onClick={() => parseMutation.mutate(lookupUrl.trim())}
                    isLoading={parseMutation.isPending}
                    isDisabled={!lookupUrl.trim()}
                  >
                    Look up
                  </Button>
                </HStack>
                <FormHelperText>
                  Supported: DOIs, arXiv and OSF URLs.
                </FormHelperText>
              </FormControl>
            )}

            {(mode === "create" || fetched) && (
              <>
                <FormControl isRequired isInvalid={!!errors.name}>
                  <FormLabel htmlFor="name">
                    {mode === "import" ? "Name" : "Name"}
                  </FormLabel>
                  <Input
                    id="name"
                    placeholder="Ex: v1.0"
                    {...register("name", {
                      required: "Name is required",
                      validate: (v) => validateReleaseName(v) ?? true,
                    })}
                    {...noAutofill}
                  />
                  {errors.name ? (
                    <FormErrorMessage>{errors.name.message}</FormErrorMessage>
                  ) : (
                    <FormHelperText>
                      Used as a Git tag: no spaces or ~ ^ : ? * [ \ etc.
                    </FormHelperText>
                  )}
                </FormControl>
                <FormControl mt={4}>
                  <FormLabel htmlFor="path">Path</FormLabel>
                  <input type="hidden" {...register("path")} />
                  <PathPicker
                    ownerName={ownerName}
                    projectName={projectName}
                    value={path}
                    onChange={(p) => setValue("path", p, { shouldDirty: true })}
                  />
                  <FormHelperText>
                    Pick a file to release, or release the whole project.
                  </FormHelperText>
                </FormControl>

                {mode === "create" && !path.trim() && (
                  <Text mt={2} fontSize="sm" color="gray.500">
                    Releasing the whole project here pins it for review. To
                    create a downloadable archive snapshot, use the CLI:{" "}
                    <Code>calkit new release --internal</Code>.{" "}
                    <Link
                      isExternal
                      variant="blue"
                      href="https://docs.calkit.org/releases/"
                    >
                      Learn how
                      <Icon as={FiExternalLink} mb="-2px" ml={1} />
                    </Link>
                  </Text>
                )}

                {mode === "create" && isStale && (
                  <Alert
                    status="warning"
                    mt={4}
                    borderRadius="md"
                    alignItems="flex-start"
                    flexDirection="column"
                  >
                    <Box display="flex">
                      <AlertIcon />
                      <Box>
                        <AlertTitle>This artifact may be stale</AlertTitle>
                        <AlertDescription fontSize="sm">
                          {staleness?.stage ? (
                            <>
                              The pipeline stage <Code>
                                {staleness.stage}
                              </Code>{" "}
                            </>
                          ) : (
                            "The pipeline stage that produced this path "
                          )}
                          {staleness?.status === "not-run"
                            ? "has not been run, so this file may not exist or match the current code."
                            : "is out of date, so this file may not match the current code."}{" "}
                          Re-run the pipeline to be safe.
                        </AlertDescription>
                      </Box>
                    </Box>
                    <Checkbox mt={3} {...register("acknowledge")}>
                      I understand I may be sharing a non-reproducible artifact
                    </Checkbox>
                  </Alert>
                )}

                {mode === "import" && (
                  <>
                    <FormControl mt={4}>
                      <FormLabel htmlFor="publisher">
                        Publisher / venue
                      </FormLabel>
                      <Input
                        id="publisher"
                        {...register("publisher")}
                        {...noAutofill}
                      />
                    </FormControl>
                    <FormControl mt={4}>
                      <FormLabel htmlFor="url">URL</FormLabel>
                      <Input id="url" {...register("url")} {...noAutofill} />
                    </FormControl>
                    <FormControl mt={4}>
                      <FormLabel htmlFor="doi">DOI</FormLabel>
                      <Input id="doi" {...register("doi")} {...noAutofill} />
                    </FormControl>
                    <FormControl mt={4}>
                      <FormLabel htmlFor="date">Date</FormLabel>
                      <Input id="date" type="date" {...register("date")} />
                    </FormControl>
                  </>
                )}

                <FormControl mt={4}>
                  <FormLabel htmlFor="description">Description</FormLabel>
                  <Textarea
                    id="description"
                    placeholder="Optional (Markdown supported)"
                    {...register("description")}
                    {...noAutofill}
                  />
                </FormControl>
              </>
            )}

            {mode === "create" && (
              <Box mt={6} pt={4} borderTopWidth="1px">
                <Text fontSize="sm" color="gray.600">
                  Want to <b>publish</b> to an external venue (Zenodo, arXiv, a
                  journal, …), not just record one? Create that release from the
                  CLI with <Code>calkit new release</Code>.{" "}
                  <Link
                    isExternal
                    variant="blue"
                    href="https://docs.calkit.org/releases/"
                  >
                    Learn how
                    <Icon as={FiExternalLink} mb="-2px" ml={1} />
                  </Link>
                </Text>
                <HStack mt={3} spacing={3}>
                  <Tooltip
                    label={
                      voteStatus?.has_voted ? "Click to remove your vote" : ""
                    }
                    isDisabled={!voteStatus?.has_voted}
                  >
                    <Button
                      type="button"
                      size="sm"
                      variant={voteStatus?.has_voted ? "solid" : "outline"}
                      colorScheme={voteStatus?.has_voted ? "green" : "gray"}
                      leftIcon={<FiThumbsUp />}
                      onClick={() =>
                        voteMutation.mutate(voteStatus?.has_voted ?? false)
                      }
                      isLoading={voteMutation.isPending}
                      isDisabled={voteStatus == null}
                    >
                      {voteStatus?.has_voted
                        ? "Voted to do this in Calkit"
                        : "Vote to do this in Calkit"}
                    </Button>
                  </Tooltip>
                  {voteStatus != null && (
                    <Text fontSize="sm" color="gray.500">
                      {voteStatus.count}{" "}
                      {voteStatus.count === 1 ? "vote" : "votes"}
                    </Text>
                  )}
                </HStack>
              </Box>
            )}
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="primary"
              type="submit"
              isLoading={
                isSubmitting ||
                createMutation.isPending ||
                importMutation.isPending
              }
              isDisabled={
                (mode === "create" && needsAck) ||
                (mode === "import" && !fetched)
              }
            >
              {mode === "import" ? "Import" : "Save"}
            </Button>
            <Button type="button" onClick={handleClose}>
              Cancel
            </Button>
          </ModalFooter>
        </ModalContent>
      )}
      {created && (
        <ShareDialog
          isOpen={sharing}
          onClose={() => setSharing(false)}
          ownerName={ownerName}
          projectName={projectName}
          releaseName={created.name}
        />
      )}
    </Modal>
  )
}

export default NewRelease
