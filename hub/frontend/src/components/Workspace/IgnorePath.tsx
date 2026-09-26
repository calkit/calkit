import {
  Button,
  Checkbox,
  Code,
  Flex,
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
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"

import useCustomToast from "../../hooks/useCustomToast"

interface IgnorePathProps {
  request: (type: string, fields?: object) => Promise<any>
  onDone: () => void
  path: string
}

interface IgnorePut {
  path: string
  commit_message: string
  push: boolean
}

const IgnorePath = ({ path, request, onDone }: IgnorePathProps) => {
  const showToast = useCustomToast()
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
      return request("workspace.ignore", {
        path: path,
        commit: true,
        message: data.commit_message,
        push: data.push,
      })
    },
    onSuccess: () => {
      showToast("Success!", "Path is now ignored.", "success")
      reset()
      modalDisclosure.onClose()
    },
    onError: (err: Error) => {
      showToast("Error", err.message, "error")
    },
    onSettled: onDone,
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
        motionPreset="none"
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
                autoComplete="off"
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
