// Modal for adding keys to S3 or S3-compatible storage, or replacing them

import {
  Button,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import mixpanel from "mixpanel-browser"
import { useEffect } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import { type S3ConnectionPublic, UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import S3ConnectionFields, {
  type S3ConnectionForm,
  emptyS3Connection,
} from "../Common/S3ConnectionFields"

interface S3ConnectionModalProps {
  isOpen: boolean
  onClose: () => void
  // The connection whose keys are being replaced, if any
  connection?: S3ConnectionPublic
}

const S3ConnectionModal = ({
  isOpen,
  onClose,
  connection,
}: S3ConnectionModalProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<S3ConnectionForm>({
    mode: "onBlur",
    defaultValues: emptyS3Connection,
  })
  useEffect(() => {
    reset(
      connection
        ? {
            ...emptyS3Connection,
            name: connection.name,
            endpoint_url: connection.endpoint_url ?? "",
            region: connection.region ?? "",
            access_key_id: connection.access_key_id,
          }
        : emptyS3Connection,
    )
  }, [connection, reset])
  const mutation = useMutation({
    mutationFn: (data: S3ConnectionForm) =>
      UsersService.putUserS3Connection({
        name: data.name,
        s3ConnectionPut: {
          endpoint_url: data.endpoint_url || null,
          region: data.region || null,
          access_key_id: data.access_key_id,
          secret_access_key: data.secret_access_key,
        },
      }).then((response) => response.data),
    onSuccess: () => {
      mixpanel.track("Saved S3 connection", { replaced: !!connection })
      showToast("Success!", "S3 keys saved.", "success")
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["user", "s3-connections"] })
    },
  })
  const onSubmit: SubmitHandler<S3ConnectionForm> = (data) => {
    mutation.mutate(data)
  }
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "sm", md: "md" }}
      isCentered
      motionPreset="none"
    >
      <ModalOverlay />
      <ModalContent
        as="form"
        onSubmit={handleSubmit(onSubmit)}
        autoComplete="off"
        // Per-field opt-outs alone don't stop Dashlane
        data-form-type="other"
        data-1p-ignore
        data-lpignore="true"
      >
        <ModalHeader>
          {connection ? "Replace S3 keys" : "Add S3 keys"}
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <S3ConnectionFields
            register={register}
            errors={errors}
            nameReadOnly={!!connection}
          />
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={mutation.isPending}
          >
            Save
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default S3ConnectionModal
