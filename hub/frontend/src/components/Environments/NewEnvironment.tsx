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
  Select,
  Textarea,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface NewEnvironmentProps {
  isOpen: boolean
  onClose: () => void
  /** Supplied when rendered outside the project route. */
  ownerName?: string
  projectName?: string
  /** Called with the new environment's name once it's been created. */
  onCreated?: (name: string) => void
}

/**
 * The kinds offered here, with what each one needs.
 *
 * Not every kind Calkit understands: this is the set someone can set up from
 * a blank project without knowing the format first. The rest (Slurm, PBS,
 * Nix, MATLAB, R) carry options that belong in calkit.yaml with the docs
 * open, and the file is always editable directly.
 */
const KINDS: {
  kind: string
  label: string
  /** Default spec file path, or null when the kind has no spec file. */
  path: string | null
  pathLabel?: string
  /** Starting contents for the spec file, so it's never created empty. */
  template?: (name: string) => string
}[] = [
  {
    kind: "uv-venv",
    label: "Python (uv)—fast, from a requirements file",
    path: "requirements.txt",
    pathLabel: "Requirements file",
    template: () => "# One package per line, e.g.\n# pandas\n# matplotlib\n",
  },
  {
    kind: "venv",
    label: "Python (venv)—from a requirements file",
    path: "requirements.txt",
    pathLabel: "Requirements file",
    template: () => "# One package per line, e.g.\n# pandas\n# matplotlib\n",
  },
  {
    kind: "conda",
    label: "Conda—packages beyond Python, from an environment file",
    path: "environment.yml",
    pathLabel: "Environment file",
    template: (name) =>
      `name: ${name}\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.13\n  - pip\n`,
  },
  {
    kind: "docker",
    label: "Docker—a full image, for anything that isn't just packages",
    path: "Dockerfile",
    pathLabel: "Dockerfile",
    template: () =>
      "FROM python:3.13-slim\n\nRUN pip install --no-cache-dir \\\n    pandas \\\n    matplotlib\n",
  },
  {
    kind: "uv",
    label: "uv project—you already have a pyproject.toml",
    path: "pyproject.toml",
    pathLabel: "Project file",
  },
  {
    kind: "pixi",
    label: "Pixi—from a pixi.toml",
    path: "pixi.toml",
    pathLabel: "Pixi file",
  },
  {
    kind: "matlab",
    label: "MATLAB—scripts run in batch mode",
    path: null,
  },
]

interface EnvironmentForm {
  name: string
  kind: string
  path: string
  description: string
  file_content: string
}

/**
 * Create a computational environment without hand-editing calkit.yaml.
 *
 * The spec file is written alongside the calkit.yaml entry, since an
 * environment that points at a file which doesn't exist is one the pipeline
 * can't build. Kinds that use an existing file (uv, pixi) don't overwrite it.
 */
const NewEnvironment = ({
  isOpen,
  onClose,
  ownerName,
  projectName: projectNameProp,
  onCreated,
}: NewEnvironmentProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeParams = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const accountName = ownerName ?? routeParams.accountName ?? ""
  const projectName = projectNameProp ?? routeParams.projectName ?? ""
  const [kind, setKind] = useState(KINDS[0].kind)
  const selectedKind = KINDS.find((k) => k.kind === kind) ?? KINDS[0]
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<EnvironmentForm>({
    mode: "onBlur",
    defaultValues: {
      name: "",
      kind: KINDS[0].kind,
      path: KINDS[0].path ?? "",
      description: "",
      file_content: KINDS[0].template?.("main") ?? "",
    },
  })
  const name = watch("name")
  const onKindChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const next = KINDS.find((k) => k.kind === e.target.value) ?? KINDS[0]
    setKind(next.kind)
    setValue("path", next.path ?? "")
    setValue("file_content", next.template?.(name || "main") ?? "")
  }
  const mutation = useMutation({
    mutationFn: (data: EnvironmentForm) => {
      // all_attrs is what gets written into calkit.yaml verbatim, so it
      // carries exactly the keys this kind uses and nothing else.
      const attrs: Record<string, unknown> = { kind: data.kind }
      if (selectedKind.path) {
        attrs.path = data.path
      }
      if (data.description) {
        attrs.description = data.description
      }
      return ProjectsService.postProjectEnvironment({
        owner_name: accountName,
        project_name: projectName,
        environment: {
          name: data.name,
          kind: data.kind,
          path: selectedKind.path ? data.path : null,
          description: data.description || null,
          all_attrs: attrs,
          // Only send contents for a file we'd be creating; a kind that
          // reads an existing pyproject.toml must not overwrite it.
          file_content: selectedKind.template ? data.file_content : null,
        },
      }).then((response) => response.data)
    },
    onSuccess: (_env, vars) => {
      showToast("Success!", "Environment created.", "success")
      reset()
      onClose()
      onCreated?.(vars.name)
    },
    onError: (err: AxiosError) => handleError(err, showToast),
    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "environments"],
      }),
  })
  const onSubmit: SubmitHandler<EnvironmentForm> = (data) =>
    mutation.mutate(data)
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "sm", md: "lg" }}
      isCentered
    >
      <ModalOverlay />
      <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
        <ModalHeader>New environment</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <FormControl isRequired isInvalid={!!errors.name} mb={4}>
            <FormLabel htmlFor="name">Name</FormLabel>
            <Input
              id="name"
              {...register("name", {
                required: "A name is required.",
                pattern: {
                  value: /^[a-zA-Z0-9._-]+$/,
                  message: "Use letters, numbers, dots, dashes, underscores.",
                },
              })}
              placeholder="Ex: main"
              autoComplete="off"
            />
            {errors.name ? (
              <FormErrorMessage>{errors.name.message}</FormErrorMessage>
            ) : (
              <FormHelperText>How pipeline stages refer to it.</FormHelperText>
            )}
          </FormControl>
          <FormControl mb={4}>
            <FormLabel htmlFor="kind">Kind</FormLabel>
            <Select id="kind" {...register("kind", { onChange: onKindChange })}>
              {KINDS.map((k) => (
                <option key={k.kind} value={k.kind}>
                  {k.label}
                </option>
              ))}
            </Select>
          </FormControl>
          {selectedKind.path ? (
            <FormControl isRequired isInvalid={!!errors.path} mb={4}>
              <FormLabel htmlFor="path">
                {selectedKind.pathLabel ?? "Spec file"}
              </FormLabel>
              <Input
                id="path"
                {...register("path", { required: "A path is required." })}
                autoComplete="off"
              />
              {errors.path ? (
                <FormErrorMessage>{errors.path.message}</FormErrorMessage>
              ) : (
                <FormHelperText>
                  Lives in your repo, so the environment travels with the
                  project.
                </FormHelperText>
              )}
            </FormControl>
          ) : null}
          {selectedKind.template ? (
            <FormControl mb={4}>
              <FormLabel htmlFor="file_content">Contents</FormLabel>
              <Textarea
                id="file_content"
                {...register("file_content")}
                rows={7}
                fontFamily="mono"
                fontSize="sm"
              />
              <FormHelperText>
                Edit it here or later in the repo.
              </FormHelperText>
            </FormControl>
          ) : null}
          <FormControl>
            <FormLabel htmlFor="description">Description</FormLabel>
            <Input
              id="description"
              {...register("description")}
              placeholder="What this environment is for"
              autoComplete="off"
            />
          </FormControl>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={isSubmitting || mutation.isPending}
          >
            Create
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default NewEnvironment
