import {
  Button,
  FormControl,
  FormErrorMessage,
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
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import mixpanel from "mixpanel-browser"
import { type SubmitHandler, useForm } from "react-hook-form"

import { type ApiError, type TokenPut, UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface UpdateOverleafTokenProps {
  isOpen: boolean
  onClose: () => void
}

const UpdateOverleafToken = ({ isOpen, onClose }: UpdateOverleafTokenProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<TokenPut>({
    mode: "onBlur",
    criteriaMode: "all",
  })
  const mutation = useMutation({
    mutationFn: (data: TokenPut) => {
      return UsersService.putUserOverleafToken({ requestBody: data })
    },
    onSuccess: () => {
      mixpanel.track("Updated Overleaf token")
      showToast("Success!", "Overleaf token saved successfully.", "success")
      reset()
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
    },
  })
  const onSubmit: SubmitHandler<TokenPut> = (data) => {
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
          <ModalHeader>Update Overleaf token</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <Text mb={4}>
              To generate an Overleaf token, see the "Git integration" section
              in your{" "}
              <Link
                variant="blue"
                isExternal
                href="https://www.overleaf.com/user/settings"
              >
                Overleaf user settings
              </Link>
              .
            </Text>
            <FormControl isRequired isInvalid={!!errors.token}>
              <FormLabel htmlFor="token">Token</FormLabel>
              <Input
                id="token"
                {...register("token", {
                  required: "Token is required.",
                })}
                type="text"
              />
              {errors.token && (
                <FormErrorMessage>{errors.token.message}</FormErrorMessage>
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

export default UpdateOverleafToken
