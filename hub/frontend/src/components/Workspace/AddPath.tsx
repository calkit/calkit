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

interface AddPathProps {
  request: (type: string, fields?: object) => Promise<any>
  onDone: () => void
  path: string
}

interface AddPost {
  path: string
  commit_message: string
  push: boolean
}

const AddPath = ({ path, request, onDone }: AddPathProps) => {
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AddPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: { commit_message: `Add ${path}`, push: true },
  })
  const modalDisclosure = useDisclosure()
  const mutation = useMutation({
    mutationFn: (data: AddPost) => {
      return request("workspace.save", {
        paths: [path],
        message: data.commit_message,
        push: data.push,
      })
    },
    onSuccess: () => {
      showToast("Success!", "Paths added.", "success")
      reset()
      modalDisclosure.onClose()
    },
    onError: (err: Error) => {
      showToast("Error", err.message, "error")
    },
    onSettled: onDone,
  })
  const onSubmit: SubmitHandler<AddPost> = (data) => {
    mutation.mutate(data)
  }

  return (
    <>
      <Button
        variant="primary"
        size="xs"
        onClick={modalDisclosure.onOpen}
        mr={1}
      >
        Add
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
            Add <Code>{path}</Code> to project repo
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={4}>
            <FormControl isRequired isInvalid={!!errors.commit_message} mb={2}>
              <FormLabel htmlFor="name">Commit message</FormLabel>
              <Input
                autoComplete="off"
                id="commit_message"
                {...register("commit_message", {})}
                placeholder="Ex: Add my-file.png"
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

export default AddPath
