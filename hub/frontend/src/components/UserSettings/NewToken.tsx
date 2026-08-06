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
  Select,
  Text,
  Input,
  Code,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"

import { UsersService, type TokenPost } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface NewTokenProps {
  isOpen: boolean
  onClose: () => void
}

interface TokenFormInput {
  purpose: "api" | "dvc"
  expires_days: number
  description?: string
}

const NewToken = ({ isOpen, onClose }: NewTokenProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<TokenFormInput>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: { purpose: "api", expires_days: 365 },
  })
  const mutation = useMutation({
    mutationFn: (data: TokenPost) =>
      UsersService.postUserToken({
        requestBody: data,
      }),
    onSuccess: () => {
      showToast("Success!", "Token created successfully.", "success")
      reset()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["user", "tokens"],
      })
    },
  })
  const onSubmit: SubmitHandler<TokenFormInput> = (data) => {
    mutation.mutate({
      scope: data.purpose === "api" ? null : data.purpose,
      expires_days: data.expires_days,
      description: data.description,
    })
  }
  const handleClose = () => {
    mutation.reset()
    onClose()
  }

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={handleClose}
        size={{ base: "sm", md: "md" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
          <ModalHeader>Create new user token</ModalHeader>
          <ModalCloseButton />
          {mutation.isSuccess ? (
            <ModalBody pb={6}>
              <Text mb={4}>
                Token created successfully. Be sure to store this in a safe
                location because you won't be able to access it after closing
                this page:
              </Text>
              <Code
                px={1}
                py={1}
                display={"inline-block"}
                wordBreak={"break-all"}
              >
                {mutation.data.access_token}
              </Code>
            </ModalBody>
          ) : (
            <>
              <ModalBody pb={6}>
                <FormControl isInvalid={!!errors.purpose}>
                  <FormLabel htmlFor="purpose">Purpose</FormLabel>
                  <Select id="scope" {...register("purpose")}>
                    <option value={"api"}>API</option>
                    <option value={"dvc"}>DVC</option>
                  </Select>
                </FormControl>
                <FormControl mt={4}>
                  <FormLabel htmlFor="expires_days">
                    Expiration (days)
                  </FormLabel>
                  <Input
                    id="expires_days"
                    min={1}
                    max={365 * 3}
                    type="number"
                    {...register("expires_days", {
                      valueAsNumber: true,
                      min: 1,
                      max: 365 * 3,
                    })}
                  />
                </FormControl>
                <FormControl mt={4} isInvalid={!!errors.description}>
                  <FormLabel htmlFor="description">Description</FormLabel>
                  <Input
                    id="description"
                    placeholder="Ex: For my MacBook Pro"
                    {...register("description")}
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
            </>
          )}
        </ModalContent>
      </Modal>
    </>
  )
}

export default NewToken
