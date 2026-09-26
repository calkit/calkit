import {
  Box,
  Button,
  Checkbox,
  FormControl,
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
import { useEffect } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import useCustomToast from "../../hooks/useCustomToast"

interface SaveFilesProps {
  request: (type: string, fields?: object) => Promise<any>
  onDone: () => void
  isOpen: boolean
  onClose: () => void
  changedFiles: string[]
  stagedFiles: string[]
}

interface CommitPost {
  paths: string[]
  commit_message: string
  push: boolean
}

const SaveFiles = ({
  isOpen,
  onClose,
  changedFiles,
  stagedFiles,
  request,
  onDone,
}: SaveFilesProps) => {
  const allPaths = changedFiles.concat(stagedFiles)
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<CommitPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      paths: allPaths,
      commit_message: `Update ${allPaths}`,
      push: true,
    },
  })
  const mutation = useMutation({
    mutationFn: (data: CommitPost) => {
      return request("workspace.save", {
        paths: data.paths,
        message: data.commit_message,
        push: data.push,
      })
    },
    onSuccess: () => {
      showToast("Success!", "Committed.", "success")
      reset()
      onClose()
    },
    onError: (err: Error) => {
      showToast("Error", err.message, "error")
    },
    onSettled: onDone,
  })
  const onSubmit: SubmitHandler<CommitPost> = (data) => {
    mutation.mutate(data)
  }
  // Watch paths variable and automatically update commit message
  const watchPaths = watch("paths")
  useEffect(() => {
    const message = `Update ${watchPaths.join(", ")}`
    setValue("commit_message", message)
  }, [watchPaths, setValue])

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
        motionPreset="none"
      >
        <ModalOverlay />
        <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
          <ModalHeader>Commit changes</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={4}>
            <FormControl isInvalid={!!errors.paths}>
              <FormLabel>Selected files</FormLabel>
              {changedFiles.map((fpath: string) => (
                <Box key={fpath}>
                  <Checkbox
                    colorScheme="teal"
                    textColor="red.500"
                    value={fpath}
                    type="checkbox"
                    {...register("paths", { required: true })}
                  >
                    {fpath}
                  </Checkbox>
                </Box>
              ))}
              {stagedFiles.map((fpath: string) => (
                <Box key={fpath}>
                  <Checkbox
                    colorScheme="teal"
                    textColor="green.500"
                    type="checkbox"
                    value={fpath}
                    {...register("paths", { required: true })}
                  >
                    {fpath}
                  </Checkbox>
                </Box>
              ))}
              {errors.paths ? (
                <FormHelperText color="red.500">
                  At least one must be selected.
                </FormHelperText>
              ) : (
                ""
              )}
            </FormControl>
            <FormControl
              isRequired
              mb={2}
              mt={4}
              isInvalid={!!errors.commit_message}
            >
              <FormLabel htmlFor="commit-message">Commit message</FormLabel>
              <Input
                autoComplete="off"
                id="commit-message"
                {...register("commit_message", {})}
                placeholder="Ex: Update test.py"
              />
            </FormControl>
            <FormControl mt={4}>
              <Checkbox {...register("push")} colorScheme="teal">
                Push after committing
              </Checkbox>
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

export default SaveFiles
