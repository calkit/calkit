import {
  Button,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
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
  Stack,
  Text,
  Textarea,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import mixpanel from "mixpanel-browser"
import { useState } from "react"
import {
  Controller,
  type FieldErrors,
  type Path,
  type SubmitHandler,
  type UseFormRegister,
  useForm,
} from "react-hook-form"

import { type Table as TableData, toCsv } from "../../lib/csv"
import DataEntryGrid from "./DataEntryGrid"

import {
  type DatasetPost,
  type ImportedFromPost,
  ProjectsService,
  type UserPublic,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import FilterableSelect from "../Common/FilterableSelect"

// Where something brought into the project came from: a URL, a DOI, or a
// Git repo at a revision, plus when it was retrieved. Also used when
// resolving a file of unknown origin in a publication folder.
export type ImportSource = "url" | "doi" | "git_repo"

export interface ImportedFromForm {
  url: string
  doi: string
  repo_url: string
  repo_rev: string
  repo_path: string
  date_retrieved: string
}

export const IMPORTED_FROM_DEFAULTS: ImportedFromForm = {
  url: "",
  doi: "",
  repo_url: "",
  repo_rev: "",
  repo_path: "",
  date_retrieved: "",
}

/** The `imported_from` entry the form describes, as the API takes it. */
export function buildImportedFrom(
  source: ImportSource,
  data: ImportedFromForm,
): ImportedFromPost {
  const date = data.date_retrieved || null
  if (source === "url") return { url: data.url, date }
  if (source === "doi") return { doi: data.doi, date }
  return {
    git: {
      repo_url: data.repo_url,
      // Blank means the default branch's head, which the hub resolves and
      // records
      rev: data.repo_rev || null,
      path: data.repo_path || null,
    },
    date,
  }
}

export function ImportedFromFields<T extends ImportedFromForm>({
  source,
  register,
  errors: formErrors,
}: {
  source: ImportSource
  register: UseFormRegister<T>
  errors: FieldErrors<T>
}) {
  const errors = formErrors as FieldErrors<ImportedFromForm>
  const field = (name: keyof ImportedFromForm) => name as Path<T>
  return (
    <>
      {source === "url" ? (
        <FormControl isRequired isInvalid={!!errors.url} mb={4}>
          <FormLabel htmlFor="url">URL</FormLabel>
          <Input
            id="url"
            {...register(field("url"), { required: "A URL is required." })}
            placeholder="https://example.org/data/measurements.csv"
            autoComplete="off"
          />
          {errors.url ? (
            <FormErrorMessage>{errors.url.message}</FormErrorMessage>
          ) : null}
        </FormControl>
      ) : null}
      {source === "doi" ? (
        <FormControl isRequired isInvalid={!!errors.doi} mb={4}>
          <FormLabel htmlFor="doi">DOI</FormLabel>
          <Input
            id="doi"
            {...register(field("doi"), { required: "A DOI is required." })}
            placeholder="10.5281/zenodo.1234567"
            autoComplete="off"
          />
          {errors.doi ? (
            <FormErrorMessage>{errors.doi.message}</FormErrorMessage>
          ) : null}
        </FormControl>
      ) : null}
      {source === "git_repo" ? (
        <>
          <FormControl isRequired isInvalid={!!errors.repo_url} mb={4}>
            <FormLabel htmlFor="repo_url">Repo URL</FormLabel>
            <Input
              id="repo_url"
              {...register(field("repo_url"), {
                required: "A repo URL is required.",
              })}
              placeholder="https://github.com/owner/repo"
              autoComplete="off"
            />
            {errors.repo_url ? (
              <FormErrorMessage>{errors.repo_url.message}</FormErrorMessage>
            ) : null}
          </FormControl>
          <FormControl isInvalid={!!errors.repo_rev} mb={4}>
            <FormLabel htmlFor="repo_rev">Revision</FormLabel>
            <Input
              id="repo_rev"
              {...register(field("repo_rev"), {
                pattern: {
                  value: /^[0-9a-fA-F]{7,40}$/,
                  message:
                    "Must be a commit hash, or blank for the default " +
                    "branch's current head. A branch or tag can move, " +
                    "which would change the data under you.",
                },
              })}
              placeholder="Blank for the latest commit on the default branch"
              autoComplete="off"
            />
            {errors.repo_rev ? (
              <FormErrorMessage>{errors.repo_rev.message}</FormErrorMessage>
            ) : (
              <FormHelperText>
                Optional. Left blank, the head of the default branch is fetched
                and its commit recorded, so the data stays pinned.
              </FormHelperText>
            )}
          </FormControl>
          <FormControl mb={4}>
            <FormLabel htmlFor="repo_path">Path within the repo</FormLabel>
            <Input
              id="repo_path"
              {...register(field("repo_path"))}
              placeholder="Leave blank for the whole repo"
              autoComplete="off"
            />
          </FormControl>
        </>
      ) : null}
      <FormControl mb={4}>
        <FormLabel htmlFor="date_retrieved">Date retrieved</FormLabel>
        <Input
          id="date_retrieved"
          type="date"
          {...register(field("date_retrieved"))}
          autoComplete="off"
          data-form-type="other"
          data-lpignore="true"
          data-1p-ignore="true"
        />
        <FormHelperText>
          Optional. Without it, the commit that adds this entry says when.
        </FormHelperText>
      </FormControl>
    </>
  )
}

type Source = "primary" | "enter" | ImportSource

const EMPTY_TABLE: TableData = {
  columns: ["x", "y"],
  rows: [
    ["", ""],
    ["", ""],
    ["", ""],
  ],
}

interface NewDatasetProps {
  isOpen: boolean
  onClose: () => void
  ownerName?: string
  projectName?: string
  /** Which source to open on, when the caller already knows which it is. */
  defaultSource?: Source
  /** For "I collected this myself": whether the file is already in the
   * repo or is being uploaded now. */
  defaultPrimaryMode?: PrimaryMode
}

/** How data someone collected themselves gets into the project. */
type PrimaryMode = "existing" | "upload"

/**
 * Where the data came from, in the words someone would use themselves.
 *
 * Provenance is the thing people skip when it's a free-text box, and the
 * thing that makes a dataset reusable later. Asking it as four concrete
 * situations is what makes it answerable in a few seconds.
 */

const SOURCES: { value: Source; label: string; help: string }[] = [
  {
    value: "primary",
    label: "I collected this myself",
    help: "Measured or generated for this project, so there's no upstream source. Upload the file (a CSV, a spreadsheet) or point at one already in the repo.",
  },
  {
    value: "enter",
    label: "I'll type it in now",
    help: "Readings off an instrument, a tally, a table from a paper: enter it here and it's saved as a CSV you collected.",
  },
  {
    value: "url",
    label: "I downloaded it from a website",
    help: "A direct link to the file or the page it came from.",
  },
  {
    value: "doi",
    label: "I have a DOI for it (Figshare, Zenodo, etc.)",
    help: "The most durable option: a DOI stays resolvable and is citable.",
  },
  {
    value: "git_repo",
    label: "Download from a Git repo",
    help: "Fetched at the commit you give, or at the default branch's current head, which is then pinned so it's the same data next time.",
  },
]

interface DatasetForm extends ImportedFromForm {
  path: string
  title: string
  description: string
  created_by: string
}

/**
 * Declare a dataset, however it came to be part of the project.
 *
 * One form rather than one per source, since which of the four applies is
 * the first thing the user knows and everything else follows from it.
 */
const NewDataset = ({
  isOpen,
  onClose,
  ownerName,
  projectName: projectNameProp,
  defaultSource = "primary",
  defaultPrimaryMode = "existing",
}: NewDatasetProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const currentUser = queryClient.getQueryData<UserPublic>(["currentUser"])
  const routeParams = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const accountName = ownerName ?? routeParams.accountName ?? ""
  const projectName = projectNameProp ?? routeParams.projectName ?? ""
  const [source, setSource] = useState<Source>(defaultSource)
  const [primaryMode, setPrimaryMode] =
    useState<PrimaryMode>(defaultPrimaryMode)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [table, setTable] = useState<TableData>(EMPTY_TABLE)
  // Only fetched for the source that needs it: data collected here has to
  // already be in the repo, while an import names a path that doesn't
  // exist yet and so has nothing to pick from.
  const pathsQuery = useQuery({
    queryFn: () =>
      ProjectsService.getProjectContentPaths({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    queryKey: ["projects", accountName, projectName, "contents-paths"],
    enabled: isOpen && source === "primary",
  })
  const {
    register,
    handleSubmit,
    reset,
    control,
    getValues,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<DatasetForm>({
    mode: "onBlur",
    defaultValues: {
      path: "",
      title: "",
      description: "",
      ...IMPORTED_FROM_DEFAULTS,
      created_by: "",
    },
  })
  const mutation = useMutation({
    mutationFn: (data: DatasetForm) => {
      if (source === "enter") {
        // Typed-in data becomes a real CSV in the repo, tracked like any
        // uploaded file, with the person who entered it as its collector.
        const csv = toCsv({
          columns: table.columns,
          rows: table.rows.filter((row) => row.some((cell) => cell !== "")),
        })
        const file = new File([csv], data.path.split("/").pop() ?? "data.csv", {
          type: "text/csv",
        })
        return ProjectsService.postProjectDatasetUpload({
          "content-length": file.size,
          owner_name: accountName,
          project_name: projectName,
          bodyProjectsPostProjectDatasetUpload: {
            path: data.path,
            title: data.title,
            description: data.description,
            file,
            // Typed-in data is attested by the person typing it: the
            // signed-in user, not a free-text field.
            created_by: currentUser?.email ?? null,
            created_by_name: currentUser?.full_name ?? null,
          },
        }).then((response) => response.data)
      }
      if (source === "primary" && primaryMode === "upload") {
        if (!uploadFile) {
          return Promise.reject(new Error("Choose a file to upload."))
        }
        // The creator is whoever is named, defaulting to the uploader;
        // the hub decides Git or DVC from the size, as `calkit add` would
        return ProjectsService.postProjectDatasetUpload({
          "content-length": uploadFile.size,
          owner_name: accountName,
          project_name: projectName,
          bodyProjectsPostProjectDatasetUpload: {
            path: data.path,
            title: data.title,
            description: data.description,
            file: uploadFile,
            created_by: data.created_by || currentUser?.email || null,
            created_by_name:
              data.created_by && data.created_by !== currentUser?.email
                ? null
                : currentUser?.full_name ?? null,
          },
        }).then((response) => response.data)
      }
      const post: DatasetPost = {
        path: data.path,
        title: data.title || null,
        description: data.description || null,
      }
      if (source === "primary") {
        // Recording who created or collected it is what marks it primary,
        // and the person filling this in is almost always that person.
        post.created_by = [
          { email: data.created_by || currentUser?.email || "" },
        ]
      } else {
        post.imported_from = buildImportedFrom(source, data)
      }
      return ProjectsService.postProjectDataset({
        owner_name: accountName,
        project_name: projectName,
        datasetPost: post,
      }).then((response) => response.data)
    },
    onSuccess: () => {
      mixpanel.track("Added dataset", { source })
      showToast(
        "Success!",
        source === "url" || source === "doi" || source === "git_repo"
          ? "Dataset fetched and added."
          : "Dataset added.",
        "success",
      )
      reset()
      setSource(defaultSource)
      setPrimaryMode(defaultPrimaryMode)
      setUploadFile(null)
      setTable(EMPTY_TABLE)
      onClose()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "datasets"],
      }),
  })
  const onSubmit: SubmitHandler<DatasetForm> = (data) => mutation.mutate(data)
  const selected = SOURCES.find((s) => s.value === source)
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "sm", md: source === "enter" ? "2xl" : "lg" }}
      isCentered
      scrollBehavior="inside"
    >
      <ModalOverlay />
      <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
        <ModalHeader>Add a dataset</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <FormControl mb={4}>
            <FormLabel>Where did it come from?</FormLabel>
            <RadioGroup
              value={source}
              onChange={(value) => setSource(value as Source)}
            >
              <Stack>
                {SOURCES.map((option) => (
                  <Radio
                    key={option.value}
                    value={option.value}
                    colorScheme="teal"
                  >
                    {option.label}
                  </Radio>
                ))}
              </Stack>
            </RadioGroup>
            {selected ? <FormHelperText>{selected.help}</FormHelperText> : null}
          </FormControl>
          {source === "url" || source === "doi" || source === "git_repo" ? (
            <ImportedFromFields
              source={source}
              register={register}
              errors={errors}
            />
          ) : null}
          {source === "enter" ? (
            <FormControl mb={4}>
              <FormLabel>Data</FormLabel>
              <DataEntryGrid value={table} onChange={setTable} />
            </FormControl>
          ) : null}
          {source === "enter" ? (
            <Text fontSize="sm" color="ui.dim" mb={4}>
              Recorded as collected by{" "}
              <Text as="span" fontWeight="semibold">
                {currentUser?.full_name
                  ? `${currentUser.full_name} (${currentUser.email})`
                  : currentUser?.email}
              </Text>
              , written into calkit.yaml with the file.
            </Text>
          ) : null}
          {source === "primary" ? (
            <FormControl mb={4}>
              <FormLabel>The data</FormLabel>
              <RadioGroup
                value={primaryMode}
                onChange={(value) => setPrimaryMode(value as PrimaryMode)}
              >
                <Stack direction={{ base: "column", md: "row" }} spacing={4}>
                  <Radio value="upload">Upload a file</Radio>
                  <Radio value="existing">It's already in the repo</Radio>
                </Stack>
              </RadioGroup>
            </FormControl>
          ) : null}
          {source === "primary" && primaryMode === "upload" ? (
            <FormControl isRequired mb={4}>
              <FormLabel htmlFor="dataset_file">File</FormLabel>
              <Input
                id="dataset_file"
                type="file"
                p={1}
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null
                  setUploadFile(file)
                  // A sensible path from the file name, unless one was typed
                  if (file && !getValues("path")) {
                    setValue("path", `data/${file.name}`)
                  }
                }}
              />
              <FormHelperText>
                A CSV, a spreadsheet, an instrument export: whatever holds what
                you collected. Small files go in Git, large ones in DVC.
              </FormHelperText>
            </FormControl>
          ) : null}
          {source === "primary" ? (
            <FormControl mb={4}>
              <FormLabel htmlFor="created_by">
                Created or collected by
              </FormLabel>
              <Input
                id="created_by"
                type="email"
                {...register("created_by")}
                placeholder={currentUser?.email ?? "you@example.org"}
                autoComplete="off"
              />
              <FormHelperText>
                Defaults to you. Naming who created or collected the data is
                what marks it as primary.
              </FormHelperText>
            </FormControl>
          ) : null}
          <FormControl isRequired isInvalid={!!errors.path} mb={4}>
            <FormLabel htmlFor="path">Path in this project</FormLabel>
            {source === "primary" && primaryMode === "existing" ? (
              <Controller
                control={control}
                name="path"
                rules={{ required: "A path is required." }}
                render={({ field }) => (
                  <FilterableSelect
                    id="path"
                    options={(pathsQuery.data ?? []).map((item) => ({
                      value: item,
                    }))}
                    isLoading={pathsQuery.isPending}
                    value={field.value}
                    onChange={field.onChange}
                    onSelect={field.onChange}
                    placeholder="Start typing a file or folder…"
                    emptyMessage="Nothing in the repo matches that."
                  />
                )}
              />
            ) : (
              <Input
                id="path"
                {...register("path", { required: "A path is required." })}
                placeholder="Ex: data/raw/measurements.csv"
                autoComplete="off"
              />
            )}
            {errors.path ? (
              <FormErrorMessage>{errors.path.message}</FormErrorMessage>
            ) : (
              <FormHelperText>
                {source === "primary"
                  ? primaryMode === "upload"
                    ? "Where the file is saved."
                    : "Must already exist in the repo."
                  : source === "enter"
                    ? "Where the CSV will be written."
                    : source === "git_repo"
                      ? "Where the file or folder is copied to."
                      : "Where it's downloaded to: a file name for a " +
                        "single file, or a folder for a record with " +
                        "several."}
              </FormHelperText>
            )}
          </FormControl>
          <FormControl
            isRequired={source === "primary" || source === "enter"}
            isInvalid={!!errors.title}
            mb={4}
          >
            <FormLabel htmlFor="title">Title</FormLabel>
            <Input
              id="title"
              {...register("title", {
                required:
                  source === "primary" || source === "enter"
                    ? "Data you collected needs a title."
                    : false,
              })}
              placeholder="Ex: Wake velocity profiles"
              autoComplete="off"
            />
            {errors.title ? (
              <FormErrorMessage>{errors.title.message}</FormErrorMessage>
            ) : null}
          </FormControl>
          <FormControl
            isRequired={source === "primary" || source === "enter"}
            isInvalid={!!errors.description}
          >
            <FormLabel htmlFor="description">Description</FormLabel>
            <Textarea
              id="description"
              {...register("description", {
                required:
                  source === "primary" || source === "enter"
                    ? "Data you collected needs a description."
                    : false,
              })}
              placeholder={
                source === "primary" || source === "enter"
                  ? "How it was collected: instrument, conditions, units"
                  : "What it contains"
              }
              rows={3}
            />
            {errors.description ? (
              <FormErrorMessage>{errors.description.message}</FormErrorMessage>
            ) : source === "primary" || source === "enter" ? (
              <FormHelperText>
                Nobody else can reconstruct how primary data was made, so this
                is the only record of it.
              </FormHelperText>
            ) : null}
          </FormControl>
          {source === "primary" ? (
            <Text fontSize="xs" color="ui.dim" mt={4}>
              Data your pipeline produces doesn't need declaring here. Name the
              stage that makes it and it's tracked from there.
            </Text>
          ) : null}
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={isSubmitting || mutation.isPending}
          >
            Add
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default NewDataset
