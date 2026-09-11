import {
  Button,
  AlertDialog,
  AlertDialogBody,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogContent,
  AlertDialogOverlay,
  AlertDialogCloseButton,
} from "@chakra-ui/react"
import { useQueryClient, useMutation } from "@tanstack/react-query"
import { getRouteApi } from "@tanstack/react-router"
import axios from "axios"
import { useRef } from "react"

import useCustomToast from "../../hooks/useCustomToast"

interface DiscardChangesProps {
  isOpen: boolean
  onClose: () => void
}

const DiscardChanges = ({ isOpen, onClose }: DiscardChangesProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const mutation = useMutation({
    mutationFn: () => {
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/actions/discard-changes`
      return axios.post(url)
    },
    onSuccess: () => {
      showToast("Success!", "Changes discarded.", "success")
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
  const cancelRef = useRef<HTMLButtonElement | null>(null)

  return (
    <>
      <AlertDialog
        isOpen={isOpen}
        leastDestructiveRef={cancelRef}
        onClose={onClose}
        isCentered
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader fontSize="lg" fontWeight="bold">
              Discard changes
            </AlertDialogHeader>
            <AlertDialogCloseButton />
            <AlertDialogBody>
              Are you sure? You can't undo this action afterwards.
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button
                variant="danger"
                type="submit"
                onClick={() => mutation.mutate()}
                isLoading={mutation.isPending}
              >
                Discard
              </Button>
              <Button
                ref={cancelRef}
                onClick={onClose}
                disabled={mutation.isPending}
              >
                Cancel
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  )
}

export default DiscardChanges
