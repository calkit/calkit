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
  Textarea,
} from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import { useRef } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { getRouteApi } from "@tanstack/react-router"

import { type Issue, ProjectsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface CreateIssueProps {
  isOpen: boolean
  onClose: () => void
  // Hands the created issue to the issues hook, which keeps it visible
  // through reconciles until GitHub's list endpoint returns it.
  onCreated: (issue: Issue) => void
}

interface IssuePost {
  title: string
  body?: string
}

const CreateIssue = ({ isOpen, onClose, onCreated }: CreateIssueProps) => {
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<IssuePost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      title: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: IssuePost) =>
      ProjectsService.postProjectIssue({
        ownerName: accountName,
        projectName: projectName,
        requestBody: data,
      }),
    onSuccess: (createdIssue) => {
      showToast("Success!", "Issue created successfully.", "success")
      reset()
      onClose()
      onCreated(createdIssue)
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
  })

  const onSubmit: SubmitHandler<IssuePost> = (data) => {
    mutation.mutate(data)
  }

  // Focus the title field when the modal opens.
  const initialFocusRef = useRef<HTMLInputElement | null>(null)
  const { ref: titleFieldRef, ...titleField } = register("title", {
    required: "Title is required",
  })

  // Submit on Cmd/Ctrl+Enter (e.g. from the multi-line Details field).
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSubmit(onSubmit)()
    }
  }

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
        initialFocusRef={initialFocusRef}
      >
        <ModalOverlay />
        <ModalContent
          as="form"
          onSubmit={handleSubmit(onSubmit)}
          onKeyDown={onKeyDown}
        >
          <ModalHeader>Create new issue</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl isRequired isInvalid={!!errors.title}>
              <FormLabel htmlFor="title">Title</FormLabel>
              <Input
                id="title"
                {...titleField}
                ref={(e) => {
                  titleFieldRef(e)
                  initialFocusRef.current = e
                }}
                placeholder="Ex: Process the data"
                type="text"
              />
              {errors.title && (
                <FormErrorMessage>{errors.title.message}</FormErrorMessage>
              )}
            </FormControl>
            <FormControl mt={4}>
              <FormLabel htmlFor="body">Details</FormLabel>
              <Textarea id="body" {...register("body")} placeholder="Details" />
            </FormControl>
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

export default CreateIssue
