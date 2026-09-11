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
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"

import type { AxiosError } from "axios"
import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface NewReferencesCollectionProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
}

interface FormValues {
  path: string
}

const NewReferencesCollection = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
}: NewReferencesCollectionProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    mode: "onBlur",
    defaultValues: { path: "references.bib" },
  })
  const mutation = useMutation({
    mutationFn: (data: FormValues) =>
      ProjectsService.postProjectReferences({
        owner_name: ownerName,
        project_name: projectName,
        referencesPost: { path: data.path },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "References collection created.", "success")
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "references"],
      })
      reset()
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const onSubmit: SubmitHandler<FormValues> = (data) => {
    mutation.mutate(data)
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="md" isCentered>
      <ModalOverlay />
      <ModalContent
        as="form"
        autoComplete="off"
        onSubmit={handleSubmit(onSubmit)}
      >
        <ModalHeader>New references collection</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <FormControl isRequired isInvalid={!!errors.path}>
            <FormLabel htmlFor="path">File path</FormLabel>
            <Input
              id="path"
              placeholder="Ex: references.bib"
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
              {...register("path", {
                required: "Path is required",
                validate: (value) =>
                  value.trim().toLowerCase().endsWith(".bib") ||
                  "Path must end with '.bib'",
              })}
            />
            {errors.path && (
              <FormErrorMessage>{errors.path.message}</FormErrorMessage>
            )}
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

export default NewReferencesCollection
