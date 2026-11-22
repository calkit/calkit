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
import { appName } from "../../lib/core"
import { handleError } from "../../lib/errors"
import { startGitHubOAuth } from "../../lib/github"
import {
  createGoogleOAuthState,
  getGoogleAuthUrl,
  getGoogleRedirectUri,
} from "../../lib/google"
import { startHuggingFaceAuth } from "../../lib/huggingface"
import {
  getZenodoAuthUrl,
  getZenodoRedirectUri,
  zenodoAuthStateParam,
} from "../../lib/zenodo"
import UpdateOverleafToken from "./UpdateOverleafToken"

type StorageAction = "transfer" | "delete" | "orphan"

function ConnectedAccounts() {
  const clientId = import.meta.env.VITE_ZENODO_CLIENT_ID
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { disconnect } = useSearch({ from: "/_layout/settings" })
  const navigate = useNavigate({ from: "/settings" })
  const setDisconnect = (provider: string | undefined) =>
    navigate({ search: (prev) => ({ ...prev, disconnect: provider }) })
  // Storage reached with the HF account, which disconnecting would strand
  const hfStorageQuery = useQuery({
    queryKey: ["user", "huggingface-storage"],
    queryFn: () =>
      StorageService.getUserHuggingfaceStorage().then(
        (response) => response.data,
      ),
    enabled: disconnect === "huggingface",
  })
  // A transfer to Calkit Hub storage runs on the server, so it's checked
  // until it's done
  const transferQuery = useQuery({
    queryKey: ["user", "huggingface-storage-transfer"],
    queryFn: () =>
      StorageService.getUserHuggingfaceStorageTransfer().then(
        (response) => response.data,
      ),
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 5000 : false,
  })
  // Once it's done, HF is disconnected
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
  const disconnectHuggingFaceMutation = useMutation({
    mutationFn: () =>
      UsersService.deleteUserExternalCredential({
        provider: "huggingface",
        storage_action: hfStorageQuery.data?.length ? storageAction : null,
      }).then((response) => response.data),
    onSuccess: (data) => {
      mixpanel.track("Disconnected account", {
        provider: "huggingface",
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
        queryKey: ["user", "huggingface-storage"],
      })
      queryClient.invalidateQueries({
        queryKey: ["user", "huggingface-storage-transfer"],
      })
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
      mixpanel.track("Clicked connect Hugging Face")
      return startHuggingFaceAuth("/settings?tab=connected-accounts")
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
              <Icon as={FaCheck} color="green.500" />
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
                {transferQuery.data?.status === "running" ? (
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
                {transferQuery.data?.status === "failed" && (
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
          <UpdateOverleafToken
            isOpen={overleafTokenModal.isOpen}
            onClose={overleafTokenModal.onClose}
          />
          <Modal
            isOpen={disconnect === "huggingface"}
            onClose={() => setDisconnect(undefined)}
            size={{ base: "sm", md: "md" }}
            isCentered
            motionPreset="none"
          >
            <ModalOverlay />
            <ModalContent>
              <ModalHeader>Disconnect Hugging Face</ModalHeader>
              <ModalCloseButton />
              <ModalBody>
                {hfStorageQuery.isPending ? (
                  <SkeletonText noOfLines={3} />
                ) : hfStorageQuery.data?.length ? (
                  <>
                    <Text>Storage using this account:</Text>
                    <UnorderedList mt={2}>
                      {hfStorageQuery.data.map((r) => (
                        <ListItem key={r.id}>
                          {r.bucket}
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
                        <Radio value="delete">Delete from Hugging Face</Radio>
                        <Radio value="orphan">
                          Leave on Hugging Face (projects lose access)
                        </Radio>
                      </Stack>
                    </RadioGroup>
                  </>
                ) : (
                  <Text>No storage uses this account.</Text>
                )}
              </ModalBody>
              <ModalFooter gap={3}>
                <Button
                  variant="danger"
                  onClick={() => disconnectHuggingFaceMutation.mutate()}
                  isLoading={disconnectHuggingFaceMutation.isPending}
                  isDisabled={hfStorageQuery.isPending}
                >
                  Disconnect
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
