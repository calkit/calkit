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
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { getRouteApi } from "@tanstack/react-router"
import { type SubmitHandler, useForm } from "react-hook-form"

import { ProjectsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface AddCollabProps {
  isOpen: boolean
  onClose: () => void
}

interface AddCollabForm {
  // A GitHub username, or an email to add a GitHub-less collaborator.
  identifier: string
}

const AddCollaborator = ({ isOpen, onClose }: AddCollabProps) => {
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AddCollabForm>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      identifier: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: AddCollabForm) => {
      const value = data.identifier.trim()
      // An email adds a GitHub-less collaborator (native access); anything
      // else is treated as a GitHub username (repo collaborator).
      if (value.includes("@")) {
        return ProjectsService.postProjectCollaboratorByEmail({
          ownerName: accountName,
          projectName: projectName,
          requestBody: { email: value },
        })
      }
      return ProjectsService.putProjectCollaborator({
        githubUsername: value,
        ownerName: accountName,
        projectName: projectName,
      })
    },
    onSuccess: () => {
      showToast("Success!", "Collaborator added successfully.", "success")
      reset()
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "collaborators"],
      })
    },
  })

  const onSubmit: SubmitHandler<AddCollabForm> = (data) => {
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
          <ModalHeader>Add collaborator</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl isRequired isInvalid={!!errors.identifier}>
              <FormLabel htmlFor="identifier">
                GitHub username or email
              </FormLabel>
              <Input
                id="identifier"
                {...register("identifier", {
                  required: "A GitHub username or email is required",
                })}
                placeholder="octocat or user@example.com"
                type="string"
                autoComplete="off"
                data-form-type="other"
                data-lpignore="true"
              />
              <FormHelperText>
                Enter an email to add a collaborator without a GitHub account.
                They must already have a Calkit account; otherwise send them an
                invite link.
              </FormHelperText>
              {errors.identifier && (
                <FormErrorMessage>{errors.identifier.message}</FormErrorMessage>
              )}
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

export default AddCollaborator
