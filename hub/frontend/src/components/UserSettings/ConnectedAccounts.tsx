import {
  Button,
  Container,
  HStack,
  Heading,
  Icon,
  IconButton,
  Input,
  Link,
  ListItem,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Radio,
  RadioGroup,
  SkeletonText,
  Stack,
  Text,
  UnorderedList,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import { useEffect, useRef, useState } from "react"
import { FaCheck, FaPlus, FaTimes, FaTrash } from "react-icons/fa"
import { MdEdit } from "react-icons/md"
import LoadingSpinner from "../Common/LoadingSpinner"

import type { AxiosError } from "axios"
import { StorageService, type TokenPut, UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { startBoxAuth } from "../../lib/box"
import { appName } from "../../lib/core"
import { handleError } from "../../lib/errors"
import { startGitHubOAuth } from "../../lib/github"
import {
  createGoogleOAuthState,
  getGoogleAuthUrl,
  getGoogleRedirectUri,
} from "../../lib/google"
import { startHuggingFaceAuth } from "../../lib/huggingface"
import { getStorageLabel, getStorageUrl } from "../../lib/storage"
import {
  getZenodoAuthUrl,
  getZenodoRedirectUri,
  zenodoAuthStateParam,
} from "../../lib/zenodo"
import S3ConnectionModal from "./S3ConnectionModal"
import UpdateOverleafToken from "./UpdateOverleafToken"

type StorageAction = "transfer" | "orphan"
// Services storage can be connected from, by provider
const STORAGE_SERVICES: Record<string, string> = {
  huggingface: "Hugging Face",
  box: "Box",
  s3: "S3",
}

function ConnectedAccounts() {
  const clientId = import.meta.env.VITE_ZENODO_CLIENT_ID
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { disconnect, s3_connection } = useSearch({ from: "/_layout/settings" })
  const navigate = useNavigate({ from: "/settings" })
  const setDisconnect = (provider: string | undefined) =>
    navigate({ search: (prev) => ({ ...prev, disconnect: provider }) })
  const setS3Connection = (name: string | undefined) =>
    navigate({ search: (prev) => ({ ...prev, s3_connection: name }) })
  // An S3 connection is disconnected by name, e.g., "s3:osn"
  const [disconnectProvider, s3Label] = disconnect?.startsWith("s3:")
    ? ["s3", disconnect.slice(3)]
    : [disconnect, undefined]
  // A service whose storage disconnecting would strand, e.g., Hugging Face
  const storageProvider =
    disconnectProvider && disconnectProvider in STORAGE_SERVICES
      ? disconnectProvider
      : undefined
  const serviceName = storageProvider ? STORAGE_SERVICES[storageProvider] : ""
  const serviceStorageQuery = useQuery({
    queryKey: ["user", storageProvider, "storage", s3Label],
    queryFn: () =>
      StorageService.getUserServiceStorage({
        provider: storageProvider as "huggingface" | "box" | "s3",
        label: s3Label,
      }).then((response) => response.data),
    enabled: storageProvider !== undefined,
  })
  const s3ConnectionsQuery = useQuery({
    queryKey: ["user", "s3-connections"],
    queryFn: () =>
      UsersService.getUserS3Connections().then((response) => response.data),
  })
  // A transfer to Calkit Hub storage runs on the server, so it's checked
  // until it's done
  const transferQuery = useQuery({
    queryKey: ["user", "storage-transfer"],
    queryFn: () =>
      StorageService.getUserStorageTransfer().then((response) => response.data),
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 5000 : false,
  })
  // Once it's done, the service is disconnected
  const transferStatus = transferQuery.data?.status
  const lastTransferStatus = useRef(transferStatus)
  useEffect(() => {
    if (lastTransferStatus.current === "running" && !transferStatus) {
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
    }
    lastTransferStatus.current = transferStatus
  }, [transferStatus, queryClient])
  const [storageAction, setStorageAction] = useState<StorageAction>("transfer")
  const disconnectStorageServiceMutation = useMutation({
    mutationFn: () =>
      UsersService.deleteUserExternalCredential({
        provider: storageProvider as string,
        storage_action: serviceStorageQuery.data?.length ? storageAction : null,
        label: s3Label,
      }).then((response) => response.data),
    onSuccess: (data) => {
      mixpanel.track("Disconnected account", {
        provider: storageProvider,
        storage_action: storageAction,
      })
      showToast("Success!", data.message, "success")
      setDisconnect(undefined)
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
      queryClient.invalidateQueries({
        queryKey: ["user", storageProvider, "storage"],
      })
      queryClient.invalidateQueries({
        queryKey: ["user", "storage-transfer"],
      })
      queryClient.invalidateQueries({ queryKey: ["user", "s3-connections"] })
    },
  })
  const [isEditingOverleaf, setIsEditingOverleaf] = useState(false)
  const [overleafToken, setOverleafToken] = useState("")

  const handleConnectZenodo = () => {
    mixpanel.track("Clicked connect Zenodo")
    // TODO: Set correct redirect URI per environment
    location.href = `${getZenodoAuthUrl()}?client_id=${clientId}&state=${zenodoAuthStateParam}&scope=deposit%3Awrite+deposit%3Aactions&response_type=code&redirect_uri=${encodeURIComponent(getZenodoRedirectUri())}`
  }

  const handleConnectGoogle = () => {
    mixpanel.track("Clicked connect Google Drive")
    // Google Drive API scope
    const scope = "https://www.googleapis.com/auth/drive.file"
    location.href = `${getGoogleAuthUrl()}?client_id=${googleClientId}&state=${createGoogleOAuthState()}&scope=${encodeURIComponent(scope)}&access_type=offline&prompt=consent&response_type=code&redirect_uri=${encodeURIComponent(getGoogleRedirectUri())}`
  }
  // Zotero uses OAuth 1.0a, whose requests must be signed with our client
  // secret, so the backend has to hand us the authorization URL.
  const connectZoteroMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserZoteroAuthStart().then((response) => response.data),
    onSuccess: (data) => {
      mixpanel.track("Clicked connect Zotero")
      location.href = data.authorize_url
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const connectHuggingFaceMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked connect Hugging Face", {
        from: "connected accounts",
      })
      return startHuggingFaceAuth("/settings?tab=connected-accounts")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const connectBoxMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked connect Box", { from: "connected accounts" })
      return startBoxAuth("/settings?tab=connected-accounts")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const connectedAccountsQuery = useQuery({
    queryFn: () =>
      UsersService.getUserConnectedAccounts().then((response) => response.data),
    queryKey: ["user", "connected-accounts"],
  })
  // Which account each service is connected as, e.g., a username
  const getAccountNameText = (provider: string) => {
    const name = connectedAccountsQuery.data?.account_names?.[provider]
    return name ? <Text color="ui.dim">{name}</Text> : null
  }
  const ghInstallQuery = useQuery({
    queryFn: () =>
      UsersService.getUserGithubAppInstallations().then(
        (response) => response.data,
      ),
    queryKey: ["user", "github-app-installations"],
    // Only meaningful once GitHub is connected; otherwise it 401s ("needs to
    // authenticate with GitHub"), which is noise for GitHub-less users.
    enabled: Boolean(connectedAccountsQuery.data?.github),
  })
  const overleafTokenModal = useDisclosure()

  const updateOverleafTokenMutation = useMutation({
    mutationFn: (data: TokenPut) => {
      return UsersService.putUserOverleafToken({ tokenPut: data }).then(
        (response) => response.data,
      )
    },
    onSuccess: () => {
      mixpanel.track("Updated Overleaf token")
      showToast("Success!", "Overleaf token updated successfully.", "success")
      setIsEditingOverleaf(false)
      setOverleafToken("")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
    },
  })

  const disconnectAccountMutation = useMutation({
    mutationFn: (provider: string) => {
      return UsersService.deleteUserExternalCredential({ provider }).then(
        (response) => response.data,
      )
    },
    onSuccess: (_, provider) => {
      mixpanel.track("Disconnected account", { provider })
      showToast("Success!", `${provider} account disconnected.`, "success")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
    },
  })

  const handleUpdateOverleafToken = () => {
    if (overleafToken.trim()) {
      updateOverleafTokenMutation.mutate({ token: overleafToken })
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleUpdateOverleafToken()
    } else if (e.key === "Escape") {
      setIsEditingOverleaf(false)
      setOverleafToken("")
    }
  }

  const handleCancelEdit = () => {
    setIsEditingOverleaf(false)
    setOverleafToken("")
  }

  return (
    <Container maxW="full">
      <Heading size="md" py={4}>
        Connected accounts
      </Heading>
      {connectedAccountsQuery.isPending ? (
        <LoadingSpinner height="80px" />
      ) : (
        <>
          <HStack align="center">
            <Text>GitHub:</Text>
            {connectedAccountsQuery.data?.github ? (
              <>
                <Icon as={FaCheck} color="green.500" />
                {getAccountNameText("github")}
              </>
            ) : (
              // Accounts created through Google or email start without a
              // GitHub identity, which project creation needs
              <Button
                size="xs"
                variant="primary"
                onClick={() =>
                  startGitHubOAuth(undefined, { chooseAccount: true })
                }
              >
                Connect
              </Button>
            )}
            <Text>Installed for:</Text>
            {ghInstallQuery.data && ghInstallQuery.data.total_count > 0
              ? ghInstallQuery.data.installations.map((inst: any) => (
                  <Link
                    key={inst.id}
                    href={inst.html_url}
                    isExternal
                    variant="blue"
                  >
                    <Text key={inst.id}>{inst.account.login}</Text>
                  </Link>
                ))
              : ""}
            <IconButton
              as="a"
              href={`https://github.com/apps/${appName}/installations/new`}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Add GitHub installation"
              icon={<FaPlus />}
              size="xs"
              variant="ghost"
              p={-2}
              ml={-1}
            />
          </HStack>
          <HStack mt={4}>
            <Text>Zenodo:</Text>
            {connectedAccountsQuery.data?.zenodo ? (
              <>
                <Icon as={FaCheck} color="green.500" />
                <IconButton
                  aria-label="Disconnect Zenodo"
                  icon={<FaTrash />}
                  size="xs"
                  variant="ghost"
                  colorScheme="red"
                  onClick={() => disconnectAccountMutation.mutate("zenodo")}
                  isLoading={disconnectAccountMutation.isPending}
                />
              </>
            ) : (
              <Button variant="primary" size="xs" onClick={handleConnectZenodo}>
                Connect
              </Button>
            )}
          </HStack>
          <HStack mt={4}>
            <Text>Overleaf:</Text>
            {connectedAccountsQuery.data?.overleaf ? (
              <>
                {/* A Git token and a browser session are saved separately,
                    so either or both can be connected */}
                <Text>Git token</Text>
                {!connectedAccountsQuery.data.overleaf_token ? (
                  <Button
                    variant="primary"
                    size="xs"
                    onClick={overleafTokenModal.onOpen}
                  >
                    Add
                  </Button>
                ) : isEditingOverleaf ? (
                  <>
                    <Input
                      autoComplete="off"
                      size="sm"
                      placeholder="Enter new token"
                      value={overleafToken}
                      onChange={(e) => setOverleafToken(e.target.value)}
                      onKeyDown={handleKeyPress}
                      maxLength={50}
                      width="400px"
                      autoFocus
                    />
                    <IconButton
                      aria-label="Save token"
                      icon={<FaCheck />}
                      size="xs"
                      variant="ghost"
                      onClick={handleUpdateOverleafToken}
                      isLoading={updateOverleafTokenMutation.isPending}
                      p={-1}
                    />
                    <IconButton
                      aria-label="Cancel"
                      icon={<FaTimes />}
                      size="xs"
                      variant="ghost"
                      onClick={handleCancelEdit}
                      p={-1}
                    />
                  </>
                ) : (
                  <>
                    <Icon as={FaCheck} color="green.500" />
                    <IconButton
                      aria-label="Edit token"
                      icon={<MdEdit />}
                      size="sm"
                      variant="ghost"
                      onClick={() => setIsEditingOverleaf(true)}
                      p={-1}
                      ml={-1}
                      mr={-3}
                    />
                  </>
                )}
                {connectedAccountsQuery.data.overleaf_session ? (
                  <>
                    <Text ml={2}>Browser session</Text>
                    <Icon as={FaCheck} color="green.500" />
                  </>
                ) : null}
                <IconButton
                  aria-label="Disconnect Overleaf"
                  icon={<FaTrash />}
                  size="xs"
                  variant="ghost"
                  colorScheme="red"
                  onClick={() => disconnectAccountMutation.mutate("overleaf")}
                  isLoading={disconnectAccountMutation.isPending}
                />
              </>
            ) : (
              <Button
                variant="primary"
                size="xs"
                onClick={overleafTokenModal.onOpen}
              >
                Connect
              </Button>
            )}
          </HStack>
          <HStack mt={4}>
            <Text>Google:</Text>
            {connectedAccountsQuery.data?.google ? (
              <>
                <Icon as={FaCheck} color="green.500" />
                {getAccountNameText("google")}
                <IconButton
                  aria-label="Disconnect Google"
                  icon={<FaTrash />}
                  size="xs"
                  variant="ghost"
                  colorScheme="red"
                  onClick={() => disconnectAccountMutation.mutate("google")}
                  isLoading={disconnectAccountMutation.isPending}
                />
              </>
            ) : (
              <Button variant="primary" size="xs" onClick={handleConnectGoogle}>
                Connect
              </Button>
            )}
          </HStack>
          <HStack mt={4}>
            <Text>Zotero:</Text>
            {connectedAccountsQuery.data?.zotero ? (
              <>
                <Icon as={FaCheck} color="green.500" />
                {getAccountNameText("zotero")}
                <IconButton
                  aria-label="Disconnect Zotero"
                  icon={<FaTrash />}
                  size="xs"
                  variant="ghost"
                  colorScheme="red"
                  onClick={() => disconnectAccountMutation.mutate("zotero")}
                  isLoading={disconnectAccountMutation.isPending}
                />
              </>
            ) : (
              <Button
                variant="primary"
                size="xs"
                onClick={() => connectZoteroMutation.mutate()}
                isLoading={connectZoteroMutation.isPending}
              >
                Connect
              </Button>
            )}
          </HStack>
          <HStack mt={4}>
            <Text>Hugging Face:</Text>
            {connectedAccountsQuery.data?.huggingface ? (
              <>
                <Icon as={FaCheck} color="green.500" />
                {getAccountNameText("huggingface")}
                {transferQuery.data?.provider === "huggingface" &&
                transferQuery.data.status === "running" ? (
                  <Text color="ui.dim">Transferring to Calkit Hub storage</Text>
                ) : (
                  <IconButton
                    aria-label="Disconnect Hugging Face"
                    icon={<FaTrash />}
                    size="xs"
                    variant="ghost"
                    colorScheme="red"
                    onClick={() => setDisconnect("huggingface")}
                  />
                )}
                {transferQuery.data?.provider === "huggingface" &&
                  transferQuery.data?.status === "failed" && (
                    <Text color="ui.danger">
                      Transfer failed
                      {transferQuery.data.error
                        ? `: ${transferQuery.data.error}`
                        : ""}
                    </Text>
                  )}
              </>
            ) : (
              <Button
                variant="primary"
                size="xs"
                onClick={() => connectHuggingFaceMutation.mutate()}
                isLoading={connectHuggingFaceMutation.isPending}
              >
                Connect
              </Button>
            )}
          </HStack>
          <HStack mt={4}>
            <Text>Box:</Text>
            {connectedAccountsQuery.data?.box ? (
              <>
                <Icon as={FaCheck} color="green.500" />
                {getAccountNameText("box")}
                {transferQuery.data?.provider === "box" &&
                transferQuery.data.status === "running" ? (
                  <Text color="ui.dim">Transferring to Calkit Hub storage</Text>
                ) : (
                  <IconButton
                    aria-label="Disconnect Box"
                    icon={<FaTrash />}
                    size="xs"
                    variant="ghost"
                    colorScheme="red"
                    onClick={() => setDisconnect("box")}
                  />
                )}
                {transferQuery.data?.provider === "box" &&
                  transferQuery.data.status === "failed" && (
                    <Text color="ui.danger">
                      Transfer failed
                      {transferQuery.data.error
                        ? `: ${transferQuery.data.error}`
                        : ""}
                    </Text>
                  )}
              </>
            ) : (
              <Button
                variant="primary"
                size="xs"
                onClick={() => connectBoxMutation.mutate()}
                isLoading={connectBoxMutation.isPending}
              >
                Connect
              </Button>
            )}
          </HStack>
          <HStack mt={4} align="start">
            <Text>S3:</Text>
            <Stack spacing={1}>
              {s3ConnectionsQuery.data?.map((c) => (
                <HStack key={c.name}>
                  <Text>{c.name}</Text>
                  <Text color="ui.dim">
                    {c.endpoint_url
                      ? c.endpoint_url.replace(/^https?:\/\//, "")
                      : `AWS${c.region ? ` ${c.region}` : ""}`}
                  </Text>
                  <IconButton
                    aria-label={`Replace keys for ${c.name}`}
                    icon={<MdEdit />}
                    size="sm"
                    variant="ghost"
                    onClick={() => setS3Connection(c.name)}
                    p={-1}
                    mr={-3}
                  />
                  <IconButton
                    aria-label={`Remove ${c.name}`}
                    icon={<FaTrash />}
                    size="xs"
                    variant="ghost"
                    colorScheme="red"
                    onClick={() => setDisconnect(`s3:${c.name}`)}
                    isDisabled={
                      transferQuery.data?.provider === "s3" &&
                      transferQuery.data.status === "running"
                    }
                  />
                </HStack>
              ))}
              {transferQuery.data?.provider === "s3" &&
                transferQuery.data.status === "running" && (
                  <Text color="ui.dim">Transferring to Calkit Hub storage</Text>
                )}
              {transferQuery.data?.provider === "s3" &&
                transferQuery.data.status === "failed" && (
                  <Text color="ui.danger">
                    Transfer failed
                    {transferQuery.data.error
                      ? `: ${transferQuery.data.error}`
                      : ""}
                  </Text>
                )}
              <Button
                variant="primary"
                size="xs"
                alignSelf="start"
                onClick={() => setS3Connection("new")}
              >
                Add keys
              </Button>
            </Stack>
          </HStack>
          <S3ConnectionModal
            isOpen={s3_connection !== undefined}
            onClose={() => setS3Connection(undefined)}
            connection={s3ConnectionsQuery.data?.find(
              (c) => c.name === s3_connection,
            )}
          />
          <UpdateOverleafToken
            isOpen={overleafTokenModal.isOpen}
            onClose={overleafTokenModal.onClose}
          />
          <Modal
            isOpen={storageProvider !== undefined}
            onClose={() => setDisconnect(undefined)}
            size={{ base: "sm", md: "md" }}
            isCentered
            motionPreset="none"
          >
            <ModalOverlay />
            <ModalContent>
              <ModalHeader>
                {s3Label
                  ? `Remove S3 connection ${s3Label}`
                  : `Disconnect ${serviceName}`}
              </ModalHeader>
              <ModalCloseButton />
              <ModalBody>
                {serviceStorageQuery.isPending ? (
                  <SkeletonText noOfLines={3} />
                ) : serviceStorageQuery.data?.length ? (
                  <>
                    <Text>
                      Storage using this {s3Label ? "connection" : "account"}:
                    </Text>
                    <UnorderedList mt={2}>
                      {serviceStorageQuery.data.map((r) => (
                        <ListItem key={r.id}>
                          <Link href={getStorageUrl(r)} isExternal>
                            {getStorageLabel(r)}
                          </Link>
                          {r.projects.length > 0 &&
                            ` (${r.projects.join(", ")})`}
                        </ListItem>
                      ))}
                    </UnorderedList>
                    <RadioGroup
                      mt={4}
                      value={storageAction}
                      onChange={(value) =>
                        setStorageAction(value as StorageAction)
                      }
                    >
                      <Stack>
                        <Radio value="transfer">
                          Transfer to Calkit Hub storage
                        </Radio>
                        <Radio value="orphan">
                          Leave on {serviceName} (projects lose access)
                        </Radio>
                      </Stack>
                    </RadioGroup>
                    <Text mt={3} fontSize="sm" color="ui.dim">
                      Files stay on {serviceName} either way. To delete them, go
                      there.
                    </Text>
                  </>
                ) : (
                  <Text>
                    No storage uses this {s3Label ? "connection" : "account"}.
                  </Text>
                )}
              </ModalBody>
              <ModalFooter gap={3}>
                <Button
                  variant="danger"
                  onClick={() => disconnectStorageServiceMutation.mutate()}
                  isLoading={disconnectStorageServiceMutation.isPending}
                  isDisabled={serviceStorageQuery.isPending}
                >
                  {s3Label ? "Remove" : "Disconnect"}
                </Button>
                <Button onClick={() => setDisconnect(undefined)}>Cancel</Button>
              </ModalFooter>
            </ModalContent>
          </Modal>
        </>
      )}
    </Container>
  )
}

export default ConnectedAccounts
