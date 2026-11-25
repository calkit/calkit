import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormErrorMessage,
  FormHelperText,
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
import mixpanel from "mixpanel-browser"
import { useEffect, useRef, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { z } from "zod"

import {
  type StorageResourcePublic,
  StorageService,
  UsersService,
} from "../../../../../client"
import S3ConnectionFields, {
  type S3ConnectionForm,
  emptyS3Connection,
} from "../../../../../components/Common/S3ConnectionFields"
import useCustomToast from "../../../../../hooks/useCustomToast"
import useProject from "../../../../../hooks/useProject"
import { startBoxAuth } from "../../../../../lib/box"
import { handleError } from "../../../../../lib/errors"
import { startHuggingFaceAuth } from "../../../../../lib/huggingface"
import { getStorageServiceName } from "../../../../../lib/storage"

const settingsSearchSchema = z.object({
  add_storage: z.boolean().optional(),
  add_s3: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/settings",
)({
  component: ProjectSettings,
  validateSearch: (search) => settingsSearchSchema.parse(search),
})

interface NewHfBucketProps {
  accountName: string
  projectName: string
  isOpen: boolean
  onClose: () => void
  hfConnected: boolean | undefined
  onConnect: () => void
  isConnecting: boolean
}

interface NewHfBucketForm {
  namespace: string
  name: string
}

const NewHfBucket = ({
  accountName,
  projectName,
  isOpen,
  onClose,
  hfConnected,
  onConnect,
  isConnecting,
}: NewHfBucketProps) => {
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
  } = useForm<NewHfBucketForm>({
    mode: "onBlur",
    defaultValues: { namespace: "", name: projectName },
  })
  // The user's HF account, then their orgs
  const hfUsername = hfAccountQuery.data?.username
  const namespaces = [
    ...(hfUsername ? [hfUsername] : []),
    ...(hfAccountQuery.data?.orgs ?? []),
  ]
  useEffect(() => {
    if (hfUsername) {
      setValue("namespace", hfUsername)
    }
  }, [hfUsername, setValue])
  const mutation = useMutation({
    mutationFn: (data: NewHfBucketForm) =>
      StorageService.postProjectHfBucket({
        owner_name: accountName,
        project_name: projectName,
        projectHfBucketPost: { bucket: `${data.namespace}/${data.name}` },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Bucket created.", "success")
      reset({ namespace: hfUsername ?? "", name: projectName })
      onClose()
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
  const onSubmit: SubmitHandler<NewHfBucketForm> = (data) => {
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
        <ModalHeader>New Hugging Face bucket</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          {hfConnected === undefined ||
          (hfConnected && hfAccountQuery.isPending) ? (
            <SkeletonText noOfLines={2} />
          ) : !hfConnected ? (
            <Text>Hugging Face not connected</Text>
          ) : (
            <>
              <FormControl>
                <FormLabel htmlFor="namespace">Hugging Face account</FormLabel>
                <Select id="namespace" {...register("namespace")}>
                  {namespaces.map((namespace) => (
                    <option key={namespace} value={namespace}>
                      {namespace}
                    </option>
                  ))}
                </Select>
              </FormControl>
              <FormControl mt={4} isInvalid={!!errors.name}>
                <FormLabel htmlFor="bucket-name">Bucket name</FormLabel>
                <Input
                  id="bucket-name"
                  autoComplete="off"
                  data-form-type="other"
                  data-1p-ignore
                  data-lpignore="true"
                  {...register("name", {
                    required: "Bucket name required",
                    pattern: {
                      value: /^[\w.-]{2,96}$/,
                      message: "Use letters, numbers, dashes, and dots",
                    },
                  })}
                />
                {errors.name && (
                  <FormErrorMessage>{errors.name.message}</FormErrorMessage>
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
              isDisabled={!hfConnected || namespaces.length === 0}
            >
              Create
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

interface UseS3BucketProps {
  accountName: string
  projectName: string
  isOpen: boolean
  onClose: () => void
}

interface UseS3BucketForm extends S3ConnectionForm {
  // An existing connection's name, or empty for new keys
  connection: string
  url: string
  dedicated: boolean
}

const emptyS3Bucket: UseS3BucketForm = {
  ...emptyS3Connection,
  connection: "",
  url: "",
  dedicated: false,
}

// New keys can be added here too, so a bucket takes one step
const UseS3Bucket = ({
  accountName,
  projectName,
  isOpen,
  onClose,
}: UseS3BucketProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const connectionsQuery = useQuery({
    queryKey: ["user", "s3-connections"],
    queryFn: () =>
      UsersService.getUserS3Connections().then((response) => response.data),
    enabled: isOpen,
  })
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<UseS3BucketForm>({
    mode: "onBlur",
    defaultValues: emptyS3Bucket,
  })
  // Starts fresh each time it opens, with saved keys selected if any, but
  // not again while it's open, so a failed attempt keeps what was typed
  const firstConnection = connectionsQuery.data?.[0]?.name
  const connectionsLoaded = !connectionsQuery.isPending
  const wasReset = useRef(false)
  useEffect(() => {
    if (!isOpen) {
      wasReset.current = false
    } else if (connectionsLoaded && !wasReset.current) {
      wasReset.current = true
      reset({ ...emptyS3Bucket, connection: firstConnection ?? "" })
    }
  }, [isOpen, connectionsLoaded, firstConnection, reset])
  const isNew = !watch("connection")
  const mutation = useMutation({
    mutationFn: async (data: UseS3BucketForm) => {
      if (!data.connection) {
        await UsersService.putUserS3Connection({
          name: data.name,
          s3ConnectionPut: {
            endpoint_url: data.endpoint_url || null,
            region: data.region || null,
            access_key_id: data.access_key_id,
            secret_access_key: data.secret_access_key,
          },
        })
        // Saved, so trying again, e.g., with another bucket, reuses them
        await queryClient.invalidateQueries({
          queryKey: ["user", "s3-connections"],
        })
        setValue("connection", data.name)
      }
      return StorageService.postProjectS3Bucket({
        owner_name: accountName,
        project_name: projectName,
        projectS3BucketPost: {
          connection: data.connection || data.name,
          url: data.url,
          dedicated: data.dedicated,
        },
      }).then((response) => response.data)
    },
    onSuccess: (data, variables) => {
      mixpanel.track("Used S3 bucket", {
        new_connection: !variables.connection,
        dedicated: variables.dedicated,
        read_only: data.added.read_only,
      })
      showToast(
        "Success!",
        data.added.read_only ? "Read-only bucket added." : "Storage updated.",
        "success",
      )
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["user", "s3-connections"] })
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "storage"],
      })
      queryClient.invalidateQueries({
        queryKey: ["accounts", accountName, "storage"],
      })
    },
  })
  const onSubmit: SubmitHandler<UseS3BucketForm> = (data) => {
    mutation.mutate(data)
  }
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "sm", md: "md" }}
      isCentered
      motionPreset="none"
      scrollBehavior="inside"
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
        <ModalHeader>Use S3 bucket</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          {connectionsQuery.isPending ? (
            <SkeletonText noOfLines={3} />
          ) : (
            <>
              <FormControl mb={4}>
                <FormLabel htmlFor="s3-connection">Keys</FormLabel>
                <Select id="s3-connection" {...register("connection")}>
                  {connectionsQuery.data?.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                  <option value="">New keys</option>
                </Select>
              </FormControl>
              {isNew && (
                <Box mb={4}>
                  <S3ConnectionFields register={register} errors={errors} />
                </Box>
              )}
              <FormControl isInvalid={!!errors.url}>
                <FormLabel htmlFor="s3-url">Bucket</FormLabel>
                <Input
                  id="s3-url"
                  placeholder="s3://bucket/prefix"
                  autoComplete="off"
                  data-form-type="other"
                  data-1p-ignore
                  data-lpignore="true"
                  {...register("url", {
                    required: "Bucket required",
                    pattern: {
                      value:
                        /^(s3:\/\/)?[A-Za-z0-9][A-Za-z0-9._-]+[A-Za-z0-9](\/\S*)?$/,
                      message: "Use s3://bucket or s3://bucket/prefix",
                    },
                  })}
                />
                {errors.url && (
                  <FormErrorMessage>{errors.url.message}</FormErrorMessage>
                )}
              </FormControl>
              <FormControl mt={4}>
                <Checkbox {...register("dedicated")}>
                  Only this project's files
                </Checkbox>
                <FormHelperText>E.g., an existing DVC remote</FormHelperText>
              </FormControl>
            </>
          )}
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={mutation.isPending}
            isDisabled={connectionsQuery.isPending}
          >
            Use bucket
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

function ProjectSettings() {
  const { accountName, projectName } = Route.useParams()
  const { add_storage, add_s3 } = Route.useSearch()
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
    mutationFn: () => {
      mixpanel.track("Clicked connect Hugging Face", {
        from: "project settings",
      })
      return startHuggingFaceAuth(
        `/${accountName}/${projectName}/settings?add_storage=true`,
      )
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const openAddStorage = () =>
    navigate({ search: (prev) => ({ ...prev, add_storage: true }) })
  // An empty string means the hub's own storage
  const current = storageQuery.data?.dvc?.id ?? ""
  const [selected, setSelected] = useState(current)
  useEffect(() => {
    setSelected(current)
  }, [current])
  const mutation = useMutation({
    mutationFn: (id: string) =>
      StorageService.putProjectStorage({
        owner_name: accountName,
        project_name: projectName,
        projectStoragePut: { dvc_storage_id: id || null },
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
  const describe = (r: StorageResourcePublic) =>
    r.kind === "box-folder"
      ? `Box (${r.connected_by})`
      : r.kind === "hf-bucket" || r.kind === "s3-bucket"
        ? `${getStorageServiceName(r.kind)} bucket ${r.bucket}${r.read_only ? " (read-only)" : ""}`
        : r.bucket
  const boxConnected = connectedAccountsQuery.data
    ? Boolean(connectedAccountsQuery.data.box)
    : undefined
  // Comes back here once connected, to click again
  const connectBoxMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked connect Box", { from: "project settings" })
      return startBoxAuth(`/${accountName}/${projectName}/settings`)
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const selectBoxMutation = useMutation({
    mutationFn: () =>
      StorageService.postProjectBoxFolder({
        owner_name: accountName,
        project_name: projectName,
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
      queryClient.invalidateQueries({
        queryKey: ["accounts", accountName, "storage"],
      })
    },
  })
  // What the project can use: its own, and what its account shares
  const options = [
    ...(storageQuery.data?.dvc ? [storageQuery.data.dvc] : []),
    ...(storageQuery.data?.previous ?? []),
    ...(accountStorageQuery.data ?? []),
  ]
    .filter((r, i, all) => all.findIndex((o) => o.id === r.id) === i)
    // Read-only storage can't hold new files
    .filter((r) => !r.read_only)

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
            Large files:{" "}
            {storageQuery.data?.dvc
              ? describe(storageQuery.data.dvc)
              : "Calkit Hub storage"}
          </Text>
          {usageQuery.isPending ? (
            <SkeletonText mt={2} noOfLines={2} maxW="xs" />
          ) : (
            usageQuery.data && (
              <Box mt={2}>
                <Text>
                  Project's Calkit Hub storage:{" "}
                  {formatGb(usageQuery.data.project_used_gb)}
                </Text>
                {usageQuery.data.account && (
                  <Text>
                    {accountName}'s Calkit Hub storage:{" "}
                    {formatGb(usageQuery.data.account.used_gb)} of{" "}
                    {usageQuery.data.account.limit_gb} GB
                  </Text>
                )}
              </Box>
            )
          )}
          {storageQuery.data && storageQuery.data.previous.length > 0 && (
            <Text mt={2} color="ui.dim">
              Older files also read from:{" "}
              {storageQuery.data.previous.map((r) => describe(r)).join(", ")}
              {storageQuery.data.dvc ? ", Calkit Hub storage" : ""}
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
                {options.map((r) => (
                  <option key={r.id} value={r.id}>
                    {describe(r)}
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
                onClick={() => {
                  mixpanel.track("Clicked new Hugging Face bucket", {
                    hf_connected: hfConnected,
                  })
                  hfConnected ? openAddStorage() : connectMutation.mutate()
                }}
                isLoading={connectMutation.isPending}
                isDisabled={hfConnected === undefined}
              >
                New Hugging Face bucket
              </Button>
              <Button
                flexShrink={0}
                onClick={() => {
                  mixpanel.track("Clicked use Box", {
                    box_connected: boxConnected,
                  })
                  boxConnected
                    ? selectBoxMutation.mutate()
                    : connectBoxMutation.mutate()
                }}
                isLoading={
                  selectBoxMutation.isPending || connectBoxMutation.isPending
                }
                isDisabled={boxConnected === undefined}
              >
                Use Box
              </Button>
              <Button
                flexShrink={0}
                onClick={() => {
                  mixpanel.track("Clicked use S3 bucket")
                  navigate({ search: (prev) => ({ ...prev, add_s3: true }) })
                }}
              >
                Use S3 bucket
              </Button>
            </HStack>
          )}
        </>
      )}
      {isOwner && (
        <NewHfBucket
          accountName={accountName}
          projectName={projectName}
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
      {isOwner && (
        <UseS3Bucket
          accountName={accountName}
          projectName={projectName}
          isOpen={!!add_s3}
          onClose={() =>
            navigate({ search: (prev) => ({ ...prev, add_s3: undefined }) })
          }
        />
      )}
    </Box>
  )
}
