import {
  Box,
  Button,
  FormControl,
  FormErrorMessage,
  FormLabel,
  HStack,
  Heading,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  SkeletonText,
  Text,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { useEffect, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { z } from "zod"

import {
  type StorageResourcePost,
  StorageService,
  UsersService,
} from "../../../../../client"
import useCustomToast from "../../../../../hooks/useCustomToast"
import useProject from "../../../../../hooks/useProject"
import { handleError } from "../../../../../lib/errors"
import { startHuggingFaceAuth } from "../../../../../lib/huggingface"

const settingsSearchSchema = z.object({
  add_storage: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/settings",
)({
  component: ProjectSettings,
  validateSearch: (search) => settingsSearchSchema.parse(search),
})

interface AddStorageProps {
  accountName: string
  isOpen: boolean
  onClose: () => void
  hfConnected: boolean | undefined
  onConnect: () => void
  isConnecting: boolean
}

const AddStorage = ({
  accountName,
  isOpen,
  onClose,
  hfConnected,
  onConnect,
  isConnecting,
}: AddStorageProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const hfAccountQuery = useQuery({
    queryKey: ["user", "huggingface-account"],
    queryFn: () =>
      UsersService.getUserHuggingfaceAccount().then(
        (response) => response.data,
      ),
    enabled: isOpen && !!hfConnected,
  })
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors },
  } = useForm<StorageResourcePost>({
    mode: "onBlur",
    defaultValues: { name: "hf", kind: "hf-bucket", bucket: "" },
  })
  const hfUsername = hfAccountQuery.data?.username
  useEffect(() => {
    if (hfUsername) {
      setValue("bucket", `${hfUsername}/calkit`)
    }
  }, [hfUsername, setValue])
  const mutation = useMutation({
    mutationFn: (data: StorageResourcePost) =>
      StorageService.postAccountStorage({
        account_name: accountName,
        storageResourcePost: data,
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Storage added.", "success")
      reset()
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["accounts", accountName, "storage"],
      })
    },
  })
  const onSubmit: SubmitHandler<StorageResourcePost> = (data) => {
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
        <ModalHeader>Add Hugging Face bucket</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          {hfConnected === undefined ? (
            <SkeletonText noOfLines={2} />
          ) : !hfConnected ? (
            <Text>Hugging Face not connected</Text>
          ) : (
            <>
              <FormControl isInvalid={!!errors.name}>
                <FormLabel htmlFor="name">Name</FormLabel>
                <Input
                  id="name"
                  autoComplete="off"
                  data-form-type="other"
                  data-1p-ignore
                  data-lpignore="true"
                  {...register("name", {
                    required: "Name is required",
                    pattern: {
                      value: /^[a-z0-9][a-z0-9-]*$/,
                      message: "Use lowercase letters, numbers, and dashes",
                    },
                  })}
                />
                {errors.name && (
                  <FormErrorMessage>{errors.name.message}</FormErrorMessage>
                )}
              </FormControl>
              <FormControl mt={4} isInvalid={!!errors.bucket}>
                <FormLabel htmlFor="bucket">Bucket</FormLabel>
                <Input
                  id="bucket"
                  autoComplete="off"
                  data-form-type="other"
                  data-1p-ignore
                  data-lpignore="true"
                  placeholder="namespace/bucket-name"
                  {...register("bucket", {
                    required: "Bucket is required",
                    pattern: {
                      value: /^[\w.-]+\/[\w.-]+$/,
                      message: "Use the form namespace/bucket-name",
                    },
                  })}
                />
                {errors.bucket && (
                  <FormErrorMessage>{errors.bucket.message}</FormErrorMessage>
                )}
              </FormControl>
            </>
          )}
        </ModalBody>
        <ModalFooter gap={3}>
          {hfConnected === false ? (
            <Button
              variant="primary"
              onClick={onConnect}
              isLoading={isConnecting}
            >
              Connect Hugging Face
            </Button>
          ) : (
            <Button
              variant="primary"
              type="submit"
              isLoading={mutation.isPending}
              isDisabled={!hfConnected}
            >
              Add
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

function ProjectSettings() {
  const { accountName, projectName } = Route.useParams()
  const { add_storage } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { projectRequest } = useProject(accountName, projectName)
  const isOwner = projectRequest.data?.current_user_access === "owner"
  const storageQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "storage"],
    queryFn: () =>
      StorageService.getProjectStorage({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
  })
  const accountStorageQuery = useQuery({
    queryKey: ["accounts", accountName, "storage"],
    queryFn: () =>
      StorageService.getAccountStorage({ account_name: accountName }).then(
        (response) => response.data,
      ),
    enabled: isOwner,
  })
  // Separate from the settings, since it's slow to measure
  const usageQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "storage", "usage"],
    queryFn: () =>
      StorageService.getProjectStorageUsage({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
  })
  const formatGb = (gb: number) =>
    gb < 1 ? `${(gb * 1000).toFixed(1)} MB` : `${gb.toFixed(2)} GB`
  const connectedAccountsQuery = useQuery({
    queryKey: ["user", "connected-accounts"],
    queryFn: () =>
      UsersService.getUserConnectedAccounts().then((response) => response.data),
    enabled: isOwner,
  })
  const hfConnected = connectedAccountsQuery.data
    ? Boolean(connectedAccountsQuery.data.huggingface)
    : undefined
  // Comes back here with the bucket form open once connected
  const connectMutation = useMutation({
    mutationFn: () =>
      startHuggingFaceAuth(
        `/${accountName}/${projectName}/settings?add_storage=true`,
      ),
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const openAddStorage = () =>
    navigate({ search: (prev) => ({ ...prev, add_storage: true }) })
  // An empty string means the hub's own storage
  const current = storageQuery.data?.dvc?.name ?? ""
  const [selected, setSelected] = useState(current)
  useEffect(() => {
    setSelected(current)
  }, [current])
  const mutation = useMutation({
    mutationFn: (name: string) =>
      StorageService.putProjectStorage({
        owner_name: accountName,
        project_name: projectName,
        projectStoragePut: { dvc_storage_name: name || null },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Storage updated.", "success")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "storage"],
      })
    },
  })
  const describe = (name: string, bucket: string) =>
    `${name} (Hugging Face bucket ${bucket})`

  return (
    <Box>
      <Heading size="md">Settings</Heading>
      <Heading size="sm" mt={6} mb={2}>
        Storage
      </Heading>
      {storageQuery.isPending ? (
        <SkeletonText noOfLines={2} />
      ) : (
        <>
          <Text>
            Large files are stored in{" "}
            {storageQuery.data?.dvc
              ? describe(
                  storageQuery.data.dvc.name,
                  storageQuery.data.dvc.bucket,
                )
              : "Calkit Hub storage"}
            .
          </Text>
          {usageQuery.isPending ? (
            <SkeletonText mt={2} noOfLines={2} maxW="xs" />
          ) : (
            usageQuery.data && (
              <Box mt={2}>
                <Text>
                  Calkit Hub storage used by project:{" "}
                  {formatGb(usageQuery.data.project_used_gb)}
                </Text>
                {usageQuery.data.account && (
                  <Text>
                    Calkit Hub storage used by {accountName}:{" "}
                    {formatGb(usageQuery.data.account.used_gb)} of{" "}
                    {usageQuery.data.account.limit_gb} GB
                  </Text>
                )}
              </Box>
            )
          )}
          {storageQuery.data && storageQuery.data.previous.length > 0 && (
            <Text mt={2} color="ui.dim">
              Files pushed earlier are still read from{" "}
              {storageQuery.data.previous
                .map((r) => describe(r.name, r.bucket))
                .join(", ")}
              {storageQuery.data.dvc ? " and Calkit Hub storage" : ""}.
            </Text>
          )}
          {isOwner && (
            <HStack mt={4} maxW="xl">
              <Select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                isDisabled={accountStorageQuery.isPending}
              >
                <option value="">Calkit Hub storage</option>
                {accountStorageQuery.data?.map((r) => (
                  <option key={r.name} value={r.name}>
                    {describe(r.name, r.bucket)}
                  </option>
                ))}
              </Select>
              <Button
                variant="primary"
                onClick={() => mutation.mutate(selected)}
                isLoading={mutation.isPending}
                isDisabled={selected === current}
              >
                Save
              </Button>
              <Button
                flexShrink={0}
                onClick={() =>
                  hfConnected ? openAddStorage() : connectMutation.mutate()
                }
                isLoading={connectMutation.isPending}
                isDisabled={hfConnected === undefined}
              >
                Add Hugging Face bucket
              </Button>
            </HStack>
          )}
        </>
      )}
      {isOwner && (
        <AddStorage
          accountName={accountName}
          isOpen={!!add_storage}
          onClose={() =>
            navigate({
              search: (prev) => ({ ...prev, add_storage: undefined }),
            })
          }
          hfConnected={hfConnected}
          onConnect={() => connectMutation.mutate()}
          isConnecting={connectMutation.isPending}
        />
      )}
    </Box>
  )
}
