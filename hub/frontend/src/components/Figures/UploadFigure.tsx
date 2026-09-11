import {
  Alert,
  AlertDescription,
  AlertIcon,
  Button,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  Input,
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
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink, getRouteApi } from "@tanstack/react-router"
import {
  type Path,
  type SubmitHandler,
  type UseFormRegister,
  useForm,
} from "react-hook-form"

import type { AxiosError } from "axios"
import { ProjectsService, type UserPublic } from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

// The fields that record a person, rather than a pipeline stage, as the
// origin of a file: who is signed in, and which generative AI tool helped,
// if one did. Also used when resolving a file of unknown origin in a
// publication folder.
export interface AttestationForm {
  created_with_ai?: string
}

/** The signed-in user as `created_by` entries take them. */
export function creatorFromUser(
  user: UserPublic | null | undefined,
  withAi?: string,
): { email: string; name: string | null; with_ai?: string[] } {
  return {
    email: user?.email ?? "",
    name: user?.full_name ?? null,
    ...(withAi?.trim() ? { with_ai: [withAi.trim()] } : {}),
  }
}

export function AttestationFields<T extends AttestationForm>({
  register,
  user,
  subject,
  mt = 4,
}: {
  register: UseFormRegister<T>
  user: UserPublic | null | undefined
  /** What is being attested to, as the start of a sentence, e.g.,
   * "An uploaded figure". */
  subject: string
  mt?: number
}) {
  return (
    <FormControl mt={mt}>
      <FormLabel htmlFor="created_with_ai">
        Made with generative AI (optional)
      </FormLabel>
      <Input
        id="created_with_ai"
        {...register("created_with_ai" as Path<T>)}
        placeholder="Ex: Claude Opus 5"
        autoComplete="off"
        data-form-type="other"
        data-lpignore="true"
      />
      <FormHelperText>
        {subject} has no pipeline stage behind it, so it is recorded as created
        by{" "}
        <Text as="span" fontWeight="semibold">
          {user?.full_name ? `${user.full_name} (${user.email})` : user?.email}
        </Text>
        . Name the tool here if one helped make it.
      </FormHelperText>
    </FormControl>
  )
}

interface UploadFigureProps {
  isOpen: boolean
  onClose: () => void
}

interface FigurePostWithFile extends AttestationForm {
  path: string
  title: string
  description: string
  file: FileList
}

const UploadFigure = ({ isOpen, onClose }: UploadFigureProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const { user } = useAuth()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FigurePostWithFile>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      path: "",
      title: "",
      description: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: FigurePostWithFile) =>
      ProjectsService.postProjectFigure({
        bodyProjectsPostProjectFigure: {
          title: data.title,
          path: data.path,
          description: data.description,
          file: data.file[0],
          // An uploaded figure has no stage to vouch for it, so the person
          // uploading it does; the hub refuses the upload otherwise.
          created_by: user?.email ?? null,
          created_by_name: user?.full_name ?? null,
          created_with_ai: data.created_with_ai || null,
        },
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Figure uploaded successfully.", "success")
      reset()
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "figures"],
      })
    },
  })

  const onSubmit: SubmitHandler<FigurePostWithFile> = (data) => {
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
        <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
          <ModalHeader>Upload a figure made outside the pipeline</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            {/* An upload is the right move only when no code made the
                figure; otherwise the code is the provenance, and a stage
                is what records it. */}
            <Alert status="info" borderRadius="md" mb={4} fontSize="sm">
              <AlertIcon />
              <AlertDescription>
                Upload only what no script or notebook produced: a photo, a
                hand-drawn schematic, a diagram from a drawing tool. If code
                made the figure, add a pipeline stage that runs it instead, so
                the figure traces back to the code and data and rebuilds when
                they change. Start from a dataset with{" "}
                <Link
                  as={RouterLink}
                  to={`/${accountName}/${projectName}/figures` as any}
                  search={{ editor: true } as any}
                  onClick={onClose}
                >
                  New figure from data
                </Link>
                , or{" "}
                <Link
                  as={RouterLink}
                  to={`/${accountName}/${projectName}/pipeline` as any}
                  onClick={onClose}
                >
                  write the stage
                </Link>{" "}
                for an existing script or notebook.
              </AlertDescription>
            </Alert>
            <FormControl isRequired isInvalid={!!errors.path}>
              <FormLabel htmlFor="path">
                Path (relative to project folder)
              </FormLabel>
              <Input
                autoComplete="off"
                id="path"
                {...register("path", {
                  required: "Path is required",
                })}
                placeholder="Ex: figures/my-plot.png"
                type="text"
              />
              {errors.path && (
                <FormErrorMessage>{errors.path.message}</FormErrorMessage>
              )}
            </FormControl>
            <FormControl mt={4} isRequired isInvalid={!!errors.title}>
              <FormLabel htmlFor="title">Title</FormLabel>
              <Input
                autoComplete="off"
                id="title"
                {...register("title")}
                placeholder="Title"
                type="text"
              />
              {errors.title && (
                <FormErrorMessage>{errors.title.message}</FormErrorMessage>
              )}
            </FormControl>
            <FormControl mt={4} isRequired isInvalid={!!errors.description}>
              <FormLabel htmlFor="description">Description</FormLabel>
              <Textarea
                id="description"
                {...register("description", {
                  required: "Description is required",
                })}
                placeholder="Description"
              />
              {errors.description && (
                <FormErrorMessage>
                  {errors.description.message}
                </FormErrorMessage>
              )}
            </FormControl>
            <FormControl mt={4} isRequired isInvalid={!!errors.file}>
              <FormLabel htmlFor="file">File</FormLabel>
              <Input
                pt={1}
                id="file"
                {...register("file", {
                  required: "File is required",
                })}
                type="file"
                name="file"
              />
              {errors.file && (
                <FormErrorMessage>{errors.file.message}</FormErrorMessage>
              )}
            </FormControl>
            <AttestationFields
              register={register}
              user={user}
              subject="An uploaded figure"
            />
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting || mutation.isPending}
            >
              Save
            </Button>
            <Button onClick={onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}

export default UploadFigure
