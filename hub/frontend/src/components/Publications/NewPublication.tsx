import {
  Button,
  FormControl,
  FormErrorMessage,
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
import { type SubmitHandler, useForm } from "react-hook-form"
import { getRouteApi } from "@tanstack/react-router"

import { ProjectsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface NewPublicationProps {
  isOpen: boolean
  onClose: () => void
  variant: "upload" | "label" | "template"
}

interface PublicationPostWithFile {
  path: string
  title: string
  description: string
  kind:
    | "journal-article"
    | "conference-paper"
    | "presentation"
    | "poster"
    | "report"
    | "book"
  template?: "latex/article" | "latex/jfm"
  stage?: string
  environment?: string
  file?: FileList
}

const NewPublication = ({ isOpen, onClose, variant }: NewPublicationProps) => {
  const uploadFile = variant === "upload"
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PublicationPostWithFile>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      path: "",
      title: "",
      description: "",
    },
  })
  const mutation = useMutation({
    mutationFn: (data: PublicationPostWithFile) =>
      ProjectsService.postProjectPublication({
        formData: {
          title: data.title,
          path: data.path,
          description: data.description,
          kind: data.kind,
          template: data.template,
          stage: data.stage,
          environment: data.environment,
          file: data.file ? data.file[0] : null,
        },
        ownerName: accountName,
        projectName: projectName,
      }),
    onSuccess: () => {
      showToast("Success!", "Publication created.", "success")
      reset()
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "publications"],
      })
    },
  })
  const onSubmit: SubmitHandler<PublicationPostWithFile> = (data) => {
    mutation.mutate(data)
  }
  const titles = {
    template: "Create new publication from template",
    upload: "Upload new publication",
    label: "Label existing file as publication",
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
          <ModalHeader>{titles[variant]}</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl isRequired isInvalid={!!errors.path}>
              <FormLabel htmlFor="path">
                Path (relative to project folder)
              </FormLabel>
              <Input
                id="path"
                {...register("path", {
                  required: "Path is required",
                })}
                placeholder={
                  variant === "template" ? "Ex: paper" : "Ex: paper/paper.pdf"
                }
                type="text"
              />
              {errors.path && (
                <FormErrorMessage>{errors.path.message}</FormErrorMessage>
              )}
            </FormControl>
            {variant === "template" ? (
              <FormControl
                mt={4}
                isRequired={variant === "template"}
                isInvalid={!!errors.template}
              >
                <FormLabel htmlFor="template">Template</FormLabel>

                <Select
                  id="template"
                  placeholder="Select template"
                  {...register("template", {
                    required: "Template is required",
                  })}
                >
                  <option value="latex/article">latex/article</option>
                  <option value="latex/jfm">latex/jfm</option>
                </Select>
                {errors.template && (
                  <FormErrorMessage>
                    {errors.template?.message}
                  </FormErrorMessage>
                )}
              </FormControl>
            ) : (
              ""
            )}
            <FormControl mt={4} isRequired isInvalid={!!errors.kind}>
              <FormLabel htmlFor="kind">Type</FormLabel>
              <Select
                id="kind"
                placeholder="Select type"
                {...register("kind", {
                  required: "Type is required",
                })}
              >
                <option value="journal-article">Journal article</option>
                <option value="presentation">Presentation</option>
                <option value="conference-paper">Conference paper</option>
                <option value="poster">Poster</option>
                <option value="report">Report</option>
                <option value="book">Book</option>
              </Select>
            </FormControl>
            <FormControl mt={4} isRequired isInvalid={!!errors.title}>
              <FormLabel htmlFor="title">Title</FormLabel>
              <Input
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
            {/* Environment name */}
            {variant === "template" ? (
              <FormControl mt={4} isRequired isInvalid={!!errors.environment}>
                <FormLabel htmlFor="environment">
                  Docker environment name
                </FormLabel>
                <Input
                  id="environment"
                  {...register("environment")}
                  placeholder="Ex: latex"
                  type="text"
                />
                {errors.environment && (
                  <FormErrorMessage>
                    {errors.environment.message}
                  </FormErrorMessage>
                )}
              </FormControl>
            ) : (
              ""
            )}
            {/* Stage name */}
            {variant === "template" ? (
              <FormControl mt={4} isRequired isInvalid={!!errors.stage}>
                <FormLabel htmlFor="title">Pipeline stage name</FormLabel>
                <Input
                  id="stage"
                  {...register("stage")}
                  placeholder="Ex: build-paper"
                  type="text"
                />
                {errors.stage && (
                  <FormErrorMessage>{errors.stage.message}</FormErrorMessage>
                )}
              </FormControl>
            ) : (
              ""
            )}
            {/* File upload */}
            {uploadFile ? (
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
            ) : (
              ""
            )}
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

export default NewPublication
