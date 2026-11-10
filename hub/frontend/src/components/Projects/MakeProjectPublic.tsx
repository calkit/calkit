import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
  Checkbox,
  Text,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import type { AxiosError } from "axios"
import {
  type ProjectPatch,
  type ProjectPublic,
  ProjectsService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface MakeProjectPublicProps {
  project: ProjectPublic
  isOpen: boolean
  onClose: () => void
}

const MakeProjectPublic = ({
  project,
  isOpen,
  onClose,
}: MakeProjectPublicProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [shareGoogleFiles, setShareGoogleFiles] = useState(false)
  // Only projects with Google Slides presentations are asked about them
  const presentationsQuery = useQuery({
    queryKey: [
      "projects",
      project.owner_account_name,
      project.name,
      "presentations",
      undefined,
    ],
    queryFn: () =>
      ProjectsService.getProjectPresentations({
        owner_name: project.owner_account_name,
        project_name: project.name,
      }).then((response) => response.data),
    enabled: isOpen,
  })
  const hasGoogleSlides = !!presentationsQuery.data?.some((p) => p.edit_url)
  const {
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<ProjectPatch>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: project,
  })

  const mutation = useMutation({
    mutationFn: (data: ProjectPatch) =>
      ProjectsService.patchProject({
        owner_name: project.owner_account_name,
        project_name: project.name,
        projectPatch: data,
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Project updated successfully.", "success")
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
    },
  })

  const onSubmit: SubmitHandler<ProjectPatch> = async () => {
    mutation.mutate({
      is_public: true,
      share_google_files: hasGoogleSlides && shareGoogleFiles,
    })
  }

  const cancelRef = useRef(null)

  return (
    <>
      <AlertDialog
        isOpen={isOpen}
        onClose={onClose}
        leastDestructiveRef={cancelRef}
        size={{ base: "sm", md: "md" }}
        isCentered
        motionPreset="none"
      >
        <AlertDialogOverlay>
          <AlertDialogContent as="form" onSubmit={handleSubmit(onSubmit)}>
            <AlertDialogHeader>Make project public</AlertDialogHeader>
            <AlertDialogBody>
              <Text>
                Are you sure? You will not be able to undo this action.
              </Text>
              {hasGoogleSlides && (
                // TODO: needs human review
                <Checkbox
                  mt={4}
                  isChecked={shareGoogleFiles}
                  onChange={(e) => setShareGoogleFiles(e.target.checked)}
                >
                  Also let anyone with the link view its Google Slides
                  presentations, including speaker notes and skipped slides
                </Checkbox>
              )}
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button
                variant="danger"
                type="submit"
                isLoading={isSubmitting || mutation.isPending}
              >
                Make public
              </Button>
              <Button
                ref={cancelRef}
                onClick={onClose}
                isDisabled={isSubmitting}
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

export default MakeProjectPublic
