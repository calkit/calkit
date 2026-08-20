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
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import { type DatasetPost, ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface NewDatasetProps {
  isOpen: boolean
  onClose: () => void
  ownerName?: string
  projectName?: string
}

/**
 * Where the data came from, in the words someone would use themselves.
 *
 * Provenance is the thing people skip when it's a free-text box, and the
 * thing that makes a dataset reusable later. Asking it as four concrete
 * situations is what makes it answerable in a few seconds.
 */
type Source = "primary" | "url" | "doi" | "git_repo"

const SOURCES: { value: Source; label: string; help: string }[] = [
  {
    value: "primary",
    label: "I collected this myself",
    help: "Measured or generated for this project, so there's no upstream source.",
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
    label: "I got it from a Git repo",
    help: "Pinned to a commit, so it's the same data next time.",
  },
]

interface DatasetForm {
  path: string
  title: string
  description: string
  url: string
  doi: string
  repo_url: string
  repo_rev: string
  repo_path: string
  date_retrieved: string
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
}: NewDatasetProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeParams = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const accountName = ownerName ?? routeParams.accountName ?? ""
  const projectName = projectNameProp ?? routeParams.projectName ?? ""
  const [source, setSource] = useState<Source>("primary")
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<DatasetForm>({
    mode: "onBlur",
    defaultValues: {
      path: "",
      title: "",
      description: "",
      url: "",
      doi: "",
      repo_url: "",
      repo_rev: "",
      repo_path: "",
      date_retrieved: "",
    },
  })
  const mutation = useMutation({
    mutationFn: (data: DatasetForm) => {
      const post: DatasetPost = {
        path: data.path,
        title: data.title || null,
        description: data.description || null,
      }
      if (source === "primary") {
        post.primary = true
      } else {
        const retrieved = data.date_retrieved || null
        if (source === "url") {
          post.imported_from = { url: data.url, date_retrieved: retrieved }
        } else if (source === "doi") {
          post.imported_from = { doi: data.doi, date_retrieved: retrieved }
        } else {
          post.imported_from = {
            git_repo: {
              url: data.repo_url,
              rev: data.repo_rev,
              path: data.repo_path || null,
            },
            date_retrieved: retrieved,
          }
        }
      }
      return ProjectsService.postProjectDataset({
        owner_name: accountName,
        project_name: projectName,
        datasetPost: post,
      }).then((response) => response.data)
    },
    onSuccess: () => {
      showToast("Success!", "Dataset added.", "success")
      reset()
      setSource("primary")
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
      size={{ base: "sm", md: "lg" }}
      isCentered
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
          {source === "url" ? (
            <FormControl isRequired isInvalid={!!errors.url} mb={4}>
              <FormLabel htmlFor="url">URL</FormLabel>
              <Input
                id="url"
                {...register("url", { required: "A URL is required." })}
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
                {...register("doi", { required: "A DOI is required." })}
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
                  {...register("repo_url", {
                    required: "A repo URL is required.",
                  })}
                  placeholder="https://github.com/owner/repo"
                  autoComplete="off"
                />
                {errors.repo_url ? (
                  <FormErrorMessage>{errors.repo_url.message}</FormErrorMessage>
                ) : null}
              </FormControl>
              <FormControl isRequired isInvalid={!!errors.repo_rev} mb={4}>
                <FormLabel htmlFor="repo_rev">Revision</FormLabel>
                <Input
                  id="repo_rev"
                  {...register("repo_rev", {
                    required: "A revision is required.",
                  })}
                  placeholder="Commit hash, tag, or branch"
                  autoComplete="off"
                />
                {errors.repo_rev ? (
                  <FormErrorMessage>{errors.repo_rev.message}</FormErrorMessage>
                ) : (
                  <FormHelperText>
                    A commit hash is what makes this reproducible — a branch
                    moves.
                  </FormHelperText>
                )}
              </FormControl>
              <FormControl mb={4}>
                <FormLabel htmlFor="repo_path">Path within the repo</FormLabel>
                <Input
                  id="repo_path"
                  {...register("repo_path")}
                  placeholder="Leave blank for the whole repo"
                  autoComplete="off"
                />
              </FormControl>
            </>
          ) : null}
          {source !== "primary" ? (
            <FormControl mb={4}>
              <FormLabel htmlFor="date_retrieved">Date retrieved</FormLabel>
              <Input
                id="date_retrieved"
                type="date"
                {...register("date_retrieved")}
              />
              <FormHelperText>
                Optional. Without it, the commit that adds this entry says when.
              </FormHelperText>
            </FormControl>
          ) : null}
          <FormControl isRequired isInvalid={!!errors.path} mb={4}>
            <FormLabel htmlFor="path">Path in this project</FormLabel>
            <Input
              id="path"
              {...register("path", { required: "A path is required." })}
              placeholder="Ex: data/raw/measurements.csv"
              autoComplete="off"
            />
            {errors.path ? (
              <FormErrorMessage>{errors.path.message}</FormErrorMessage>
            ) : (
              <FormHelperText>
                {source === "primary"
                  ? "Must already exist in the repo."
                  : "Where it will live once it's fetched."}
              </FormHelperText>
            )}
          </FormControl>
          <FormControl
            isRequired={source === "primary"}
            isInvalid={!!errors.title}
            mb={4}
          >
            <FormLabel htmlFor="title">Title</FormLabel>
            <Input
              id="title"
              {...register("title", {
                required:
                  source === "primary"
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
            isRequired={source === "primary"}
            isInvalid={!!errors.description}
          >
            <FormLabel htmlFor="description">Description</FormLabel>
            <Textarea
              id="description"
              {...register("description", {
                required:
                  source === "primary"
                    ? "Data you collected needs a description."
                    : false,
              })}
              placeholder={
                source === "primary"
                  ? "How it was collected: instrument, conditions, units"
                  : "What it contains"
              }
              rows={3}
            />
            {errors.description ? (
              <FormErrorMessage>{errors.description.message}</FormErrorMessage>
            ) : source === "primary" ? (
              <FormHelperText>
                Nobody else can reconstruct how primary data was made, so this
                is the only record of it.
              </FormHelperText>
            ) : null}
          </FormControl>
          {source === "primary" ? (
            <Text fontSize="xs" color="ui.dim" mt={4}>
              Data your pipeline produces doesn't need declaring here — name the
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
