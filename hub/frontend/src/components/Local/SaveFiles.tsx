import {
  Button,
  FormControl,
  FormLabel,
  Modal,
  ModalBody,
  ModalCloseButton,
  Input,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Checkbox,
  Box,
  FormHelperText,
} from "@chakra-ui/react"
import { useQueryClient, useMutation } from "@tanstack/react-query"
import { getRouteApi } from "@tanstack/react-router"
import { type SubmitHandler, useForm } from "react-hook-form"
import axios from "axios"
import { useEffect } from "react"

import useCustomToast from "../../hooks/useCustomToast"

interface SaveFilesProps {
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
}: SaveFilesProps) => {
  const allPaths = changedFiles.concat(stagedFiles)
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
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
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/calkit/add-and-commit`
      return axios.post(url, data)
    },
    onSuccess: () => {
      showToast("Success!", "Committed.", "success")
      reset()
      onClose()
    },
    onError: (err: any) => {
      showToast("Error", String(err.response.data.detail), "error")
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
