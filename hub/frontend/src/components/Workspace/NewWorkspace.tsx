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
import { useMutation } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"

import useCustomToast from "../../hooks/useCustomToast"

interface NewWorkspaceProps {
  request: (type: string, fields?: object) => Promise<any>
  onDone: () => void
  isOpen: boolean
  onClose: () => void
}

interface NewWorkspacePost {
  branch: string
}

const NewWorkspace = ({
  isOpen,
  onClose,
  request,
  onDone,
}: NewWorkspaceProps) => {
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewWorkspacePost>({ mode: "onBlur" })
  const mutation = useMutation({
    mutationFn: (data: NewWorkspacePost) =>
      request("workspace.new", { branch: data.branch }),
    onSuccess: (result: { path: string }) => {
      showToast("Workspace created", result.path, "success")
      reset()
      onClose()
    },
    onError: (err: Error) => showToast("Error", err.message, "error"),
    onSettled: onDone,
  })
  const onSubmit: SubmitHandler<NewWorkspacePost> = (data) =>
    mutation.mutate(data)
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "sm", md: "md" }}
      isCentered
    >
      <ModalOverlay />
      <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
        <ModalHeader>New workspace</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          <FormControl isRequired isInvalid={!!errors.branch}>
            <FormLabel htmlFor="branch">Branch</FormLabel>
            <Input
              id="branch"
              {...register("branch", {
                required: "A branch is required",
                pattern: {
                  value: /^[A-Za-z0-9][A-Za-z0-9._/-]*$/,
                  message: "Letters, numbers, and . _ / - only",
                },
              })}
              placeholder="fix-axes"
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
            />
            <FormHelperText>
              Created from the current commit unless it exists. The workspace
              shares this one's data cache.
            </FormHelperText>
            {errors.branch && (
              <FormErrorMessage>{errors.branch.message}</FormErrorMessage>
            )}
          </FormControl>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={mutation.isPending}
          >
            Create
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default NewWorkspace
