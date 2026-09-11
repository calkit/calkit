import {
  Button,
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
  Select,
  Textarea,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { getRouteApi } from "@tanstack/react-router"
import { type SubmitHandler, useForm } from "react-hook-form"

import type { AxiosError } from "axios"
import { useEffect } from "react"
import {
  type ContentPatch,
  type ContentsItem,
  ProjectsService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { dataOrNull } from "../../lib/api"
import { handleError } from "../../lib/errors"

interface EditFileProps {
  isOpen: boolean
  onClose: () => void
  item: ContentsItem
}

const EditFileInfo = ({ isOpen, onClose, item }: EditFileProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  type CalkitKind =
    | "figure"
    | "publication"
    | "dataset"
    | "environment"
    | "references"
    | null
  const {
    register,
    unregister,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<ContentPatch>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      kind: item.calkit_object?.kind
        ? (item.calkit_object?.kind as CalkitKind)
        : null,
    },
  })
  const mutation = useMutation({
    mutationFn: (data: ContentPatch) => {
      if (!data.kind) {
        data.kind = null
      }
      return ProjectsService.patchProjectContents({
        owner_name: accountName,
        project_name: projectName,
        path: item.path,
        contentPatch: data,
      }).then(dataOrNull)
    },
    onSuccess: () => {
      showToast("Success!", "File info updated.", "success")
      reset()
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "files"],
      })
    },
  })
  const onSubmit: SubmitHandler<ContentPatch> = (data) => {
    mutation.mutate(data)
  }
  // Add a watcher for the "kind" key so we can modify the form fields
  const watchKind = watch("kind")
  const kindsWithTitle = ["publication", "figure", "dataset"]
  const kindsWithName = ["references", "environment"]

  useEffect(() => {
    if (kindsWithTitle.includes(String(watchKind))) {
      register("attrs.title")
    } else {
      unregister("attrs.title")
    }
    if (kindsWithName.includes(String(watchKind))) {
      register("attrs.name")
    } else {
      unregister("attrs.name")
    }
    if (watchKind) {
      register("attrs.description")
    } else {
      unregister("attrs.description")
    }
    if (item.calkit_object && item.calkit_object.kind === watchKind) {
      const attrs: Record<string, unknown> = {
        description: item.calkit_object.description,
      }
      if (kindsWithTitle.includes(String(watchKind))) {
        attrs.title = item.calkit_object.title
      }
      if (kindsWithName.includes(String(watchKind))) {
        attrs.name = item.calkit_object.name
      }
      setValue("attrs", attrs)
    }
  }, [register, unregister, watchKind, setValue, item])

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
          <ModalHeader>Edit artifact info</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={4}>
            <FormControl isRequired isInvalid={!!errors.kind} mb={2}>
              <FormLabel htmlFor="path">Artifact type</FormLabel>
              <Select
                id="kind"
                {...register("kind", {})}
                placeholder="Select a type..."
              >
                <option value="">None</option>
                <option value="figure">Figure</option>
                <option value="dataset">Dataset</option>
                <option value="publication">Publication</option>
                <option value="references">References</option>
                <option value="environment">Environment</option>
              </Select>
              {errors.kind && (
                <FormErrorMessage>{errors.kind.message}</FormErrorMessage>
              )}
            </FormControl>
            {/* Add other properties depending on kind */}
            {kindsWithTitle.includes(String(watchKind)) ? (
              <FormControl mb={2}>
                <FormLabel htmlFor="attrs.title">Title</FormLabel>
                <Input
                  autoComplete="off"
                  id="attrs.title"
                  {...register("attrs.title", {})}
                  placeholder="Enter title..."
                />
              </FormControl>
            ) : (
              ""
            )}
            {kindsWithName.includes(String(watchKind)) ? (
              <FormControl mb={2}>
                <FormLabel htmlFor="attrs.name">Name</FormLabel>
                <Input
                  autoComplete="off"
                  id="attrs.name"
                  {...register("attrs.name", {})}
                  placeholder="Enter name..."
                />
              </FormControl>
            ) : (
              ""
            )}
            {watchKind ? (
              <FormControl mb={2}>
                <FormLabel htmlFor="attrs.description">Description</FormLabel>
                <Textarea
                  id="attrs.description"
                  {...register("attrs.description", {})}
                  placeholder="Enter description..."
                />
              </FormControl>
            ) : (
              ""
            )}
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

export default EditFileInfo
