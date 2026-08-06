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
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { ProjectsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import LoadingSpinner from "../Common/LoadingSpinner"

interface LabelExistingReferencesProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  // Paths already registered as references collections, excluded from the list.
  existingPaths: string[]
}

const LabelExistingReferences = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  existingPaths,
}: LabelExistingReferencesProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [path, setPath] = useState("")
  const pathsQuery = useQuery({
    queryFn: () =>
      ProjectsService.getProjectContentPaths({ ownerName, projectName }),
    queryKey: ["projects", ownerName, projectName, "contents-paths"],
    enabled: isOpen,
  })
  const existing = new Set(existingPaths)
  const candidates = (pathsQuery.data ?? []).filter(
    (p) => p.toLowerCase().endsWith(".bib") && !existing.has(p),
  )
  useEffect(() => {
    if (!isOpen) setPath("")
  }, [isOpen])
  const mutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectReferences({
        ownerName,
        projectName,
        requestBody: { path, label_existing: true },
      }),
    onSuccess: () => {
      showToast("Success!", "References collection added.", "success")
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "references"],
      })
      onClose()
    },
    onError: (err: ApiError) => handleError(err, showToast),
  })

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="md" isCentered>
      <ModalOverlay />
      <ModalContent
        as="form"
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault()
          if (path) mutation.mutate()
        }}
      >
        <ModalHeader>Label an existing .bib file</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          {pathsQuery.isPending ? (
            <LoadingSpinner height="80px" />
          ) : candidates.length === 0 ? (
            <Text fontSize="sm" color="gray.500">
              No unregistered .bib files were found in this project.
            </Text>
          ) : (
            <FormControl isRequired>
              <FormLabel htmlFor="path">File</FormLabel>
              <Select
                id="path"
                placeholder="Select a .bib file"
                value={path}
                onChange={(e) => setPath(e.target.value)}
              >
                {candidates.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </Select>
            </FormControl>
          )}
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isDisabled={!path}
            isLoading={mutation.isPending}
          >
            Add
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default LabelExistingReferences
