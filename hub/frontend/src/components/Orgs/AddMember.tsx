import {
  Button,
  FormControl,
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
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"

import { OrgsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface AddMemberProps {
  isOpen: boolean
  onClose: () => void
  orgName: string
}

type Form = {
  username: string
  role: "read" | "write" | "admin" | "owner"
}

const AddMember = ({ isOpen, onClose, orgName }: AddMemberProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<Form>({
    mode: "onBlur",
    defaultValues: { username: "", role: "write" },
  })

  const mutation = useMutation({
    mutationFn: (data: Form) =>
      OrgsService.addOrgMember({ orgName, requestBody: data }),
    onSuccess: () => {
      showToast("Success!", "Member added to org.", "success")
      reset()
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["org-users", orgName] })
    },
  })

  const onSubmit: SubmitHandler<Form> = (data) => {
    mutation.mutate(data)
  }

  return (
    <>
      <Modal isOpen={isOpen} onClose={onClose} isCentered>
        <ModalOverlay />
        <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
          <ModalHeader>Add org member</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl isRequired isInvalid={!!errors.username}>
              <FormLabel htmlFor="username">Username</FormLabel>
              <Input
                id="username"
                {...register("username", { required: "Username is required" })}
                placeholder="Ex: someuser"
                type="text"
              />
            </FormControl>
            <FormControl mt={4} isRequired>
              <FormLabel htmlFor="role">Role</FormLabel>
              <Select id="role" {...register("role")}>
                <option value="read">Read</option>
                <option value="write">Write</option>
                <option value="admin">Admin</option>
                <option value="owner">Owner</option>
              </Select>
            </FormControl>
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
    </>
  )
}

export default AddMember
