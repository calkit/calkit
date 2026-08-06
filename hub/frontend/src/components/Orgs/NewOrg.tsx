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

import { type ApiError, type OrgPost, OrgsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface NewOrgProps {
  isOpen: boolean
  onClose: () => void
}

const NewOrg = ({ isOpen, onClose }: NewOrgProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<OrgPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      github_name: "",
    },
  })
  const mutation = useMutation({
    mutationFn: (data: OrgPost) => {
      return OrgsService.postOrg({ requestBody: data })
    },
    onSuccess: () => {
      mixpanel.track("Created new organization")
      showToast("Success!", "Organization created successfully.", "success")
      reset()
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["orgs"] })
    },
  })
  const onSubmit: SubmitHandler<OrgPost> = (data) => {
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
          <ModalHeader>New organization</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <Text mb={4}>
              To import an organization from GitHub,{" "}
              <Link
                variant="blue"
                isExternal
                href="https://github.com/apps/calkit/installations/select_target"
              >
                ensure the Calkit GitHub app is installed for the organization
              </Link>
              .
            </Text>
            <FormControl isRequired isInvalid={!!errors.github_name}>
              <FormLabel htmlFor="github_name">Name (on GitHub)</FormLabel>
              <Input
                id="github_name"
                {...register("github_name", {
                  required: "Name is required.",
                })}
                type="text"
              />
              {errors.github_name && (
                <FormErrorMessage>
                  {errors.github_name.message}
                </FormErrorMessage>
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

export default NewOrg
