import {
  Button,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Modal,
  ModalBody,
  ModalCloseButton,
  Input,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Code,
  Flex,
  Checkbox,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"
import { getRouteApi } from "@tanstack/react-router"
import axios from "axios"

import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface IgnorePathProps {
  path: string
}

interface IgnorePut {
  path: string
  commit_message: string
  push: boolean
}

const IgnorePath = ({ path }: IgnorePathProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<IgnorePut>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: { commit_message: `Ignore ${path}`, push: true },
  })
  const modalDisclosure = useDisclosure()
  const mutation = useMutation({
    mutationFn: (data: IgnorePut) => {
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/git/ignored`
      const payload = {
        path: path,
        commit: true,
        commit_message: data.commit_message,
        push: data.push,
      }
      return axios.put(url, payload)
    },
    onSuccess: () => {
      showToast("Success!", "Path is now ignored.", "success")
      reset()
      modalDisclosure.onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "pipeline"],
      })
    },
  })
  const onSubmit: SubmitHandler<IgnorePut> = (data) => {
    mutation.mutate(data)
  }

  return (
    <>
      <Button variant="primary" size="xs" onClick={modalDisclosure.onOpen}>
        Ignore
      </Button>
      <Modal
        isOpen={modalDisclosure.isOpen}
        onClose={modalDisclosure.onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
          <ModalHeader>
            Ignore <Code>{path}</Code> in project repo
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={4}>
            <FormControl isRequired isInvalid={!!errors.commit_message} mb={2}>
              <FormLabel htmlFor="commit_message">Commit message</FormLabel>
              <Input
                id="commit_message"
                {...register("commit_message", {})}
                placeholder="Ex: Ignore my-file.png"
              />
              {errors.commit_message && (
                <FormErrorMessage>
                  {errors.commit_message.message}
                </FormErrorMessage>
              )}
            </FormControl>
            <Flex mt={4}>
              <FormControl>
                <Checkbox {...register("push")} colorScheme="teal">
                  Push after committing
                </Checkbox>
              </FormControl>
            </Flex>
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting || mutation.isPending}
            >
              Save
            </Button>
            <Button onClick={modalDisclosure.onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}

export default IgnorePath
