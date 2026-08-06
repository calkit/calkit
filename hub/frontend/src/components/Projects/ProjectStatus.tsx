import {
  Button,
  FormControl,
  FormLabel,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Textarea,
  Text,
  Select,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"
import { getRouteApi } from "@tanstack/react-router"

import {
  type ProjectPublic,
  ProjectsService,
  type ProjectStatusPost,
} from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { formatTimestamp, capitalizeFirstLetter } from "../../lib/strings"
import { handleError } from "../../lib/errors"

interface ProjectStatusProps {
  project: ProjectPublic
  isOpen: boolean
  onClose: () => void
}

const ProjectStatus = ({ project, isOpen, onClose }: ProjectStatusProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ProjectStatusPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      status: project.status
        ? (project.status as "in-progress" | "on-hold" | "completed")
        : "in-progress",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: ProjectStatusPost) =>
      ProjectsService.postProjectStatus({
        ownerName: accountName,
        projectName: projectName,
        requestBody: data,
      }),
    onSuccess: () => {
      showToast("Success!", "Status updated successfully.", "success")
      reset()
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName],
      })
    },
  })

  const onSubmit: SubmitHandler<ProjectStatusPost> = (data) => {
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
          <ModalHeader>Project status</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <Text>
              Current status:{" "}
              {project.status
                ? capitalizeFirstLetter(project.status.replaceAll("-", " "))
                : ""}
            </Text>
            <Text>
              Updated:{" "}
              {project.status_updated
                ? formatTimestamp(project.status_updated)
                : ""}
            </Text>
            <Text mb={6}>
              Details: {project.status_message ? project.status_message : ""}
            </Text>
            <FormControl isInvalid={!!errors.status}>
              <FormLabel htmlFor="status">New status</FormLabel>
              <Select
                id="status"
                {...register("status", {
                  required: "status is required",
                })}
              >
                <option value="on-hold">On hold</option>
                <option value="in-progress">In progress</option>
                <option value="completed">Completed</option>
              </Select>
            </FormControl>
            <FormControl mt={4}>
              <FormLabel htmlFor="message">Details</FormLabel>
              <Textarea
                id="message"
                {...register("message")}
                placeholder="Details"
              />
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

export default ProjectStatus
