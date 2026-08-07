import {
  Button,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Textarea,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { getRouteApi } from "@tanstack/react-router"
import { type SubmitHandler, useForm } from "react-hook-form"

import type { AxiosError } from "axios"
import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import { submitOnCmdEnter } from "../../lib/keyboard"

interface CreateQuestionProps {
  isOpen: boolean
  onClose: () => void
}

interface QuestionPost {
  question: string
}

const CreateQuestion = ({ isOpen, onClose }: CreateQuestionProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<QuestionPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      question: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: QuestionPost) =>
      ProjectsService.postProjectQuestion({
        owner_name: accountName,
        project_name: projectName,
        questionPost: data,
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Question created successfully.", "success")
      reset()
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "questions"],
      })
    },
  })

  const onSubmit: SubmitHandler<QuestionPost> = (data) => {
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
          onSubmit={handleSubmit(onSubmit)}
          onKeyDown={submitOnCmdEnter(handleSubmit(onSubmit))}
        >
          <ModalHeader>Add new question</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl isRequired isInvalid={!!errors.question}>
              <FormLabel htmlFor="title">Question</FormLabel>
              <Textarea
                id="question"
                {...register("question", {
                  required: "Question is required",
                })}
                placeholder={
                  "Ex: Is the atmospheric boundary layer more stable at night?"
                }
              />
              {errors.question && (
                <FormErrorMessage>{errors.question.message}</FormErrorMessage>
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

export default CreateQuestion
