import {
  Heading,
  HStack,
  Text,
  Icon,
  Button,
  useDisclosure,
  Link,
  Input,
  IconButton,
} from "@chakra-ui/react"
import mixpanel from "mixpanel-browser"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { FaCheck, FaPlus, FaTimes, FaTrash } from "react-icons/fa"
import LoadingSpinner from "../Common/LoadingSpinner"
import { MdEdit } from "react-icons/md"
import { useState } from "react"

import {
  zenodoAuthStateParam,
  getZenodoRedirectUri,
  getZenodoAuthUrl,
} from "../../lib/zenodo"
import {
  createGoogleOAuthState,
  getGoogleRedirectUri,
  getGoogleAuthUrl,
} from "../../lib/google"
import { UsersService, type ApiError, type TokenPut } from "../../client"
import UpdateOverleafToken from "./UpdateOverleafToken"
import { appName } from "../../lib/core"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

function ConnectedAccounts() {
  const clientId = import.meta.env.VITE_ZENODO_CLIENT_ID
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [isEditingOverleaf, setIsEditingOverleaf] = useState(false)
  const [overleafToken, setOverleafToken] = useState("")

  const handleConnectZenodo = () => {
    mixpanel.track("Clicked connect Zenodo")
    // TODO: Set correct redirect URI per environment
    location.href =
      `${getZenodoAuthUrl()}?client_id=${clientId}` +
      `&state=${zenodoAuthStateParam}` +
      "&scope=deposit%3Awrite+deposit%3Aactions&response_type=code" +
      `&redirect_uri=${encodeURIComponent(getZenodoRedirectUri())}`
  }

  const handleConnectGoogle = () => {
    mixpanel.track("Clicked connect Google Drive")
    // Google Drive API scope
    const scope = "https://www.googleapis.com/auth/drive.file"
    location.href =
      `${getGoogleAuthUrl()}?client_id=${googleClientId}` +
      `&state=${createGoogleOAuthState()}` +
      `&scope=${encodeURIComponent(scope)}` +
      "&access_type=offline" +
      "&prompt=consent" +
      "&response_type=code" +
      `&redirect_uri=${encodeURIComponent(getGoogleRedirectUri())}`
  }
  // Zotero uses OAuth 1.0a, whose requests must be signed with our client
  // secret, so the backend has to hand us the authorization URL.
  const connectZoteroMutation = useMutation({
    mutationFn: () => UsersService.postUserZoteroAuthStart(),
    onSuccess: (data) => {
      mixpanel.track("Clicked connect Zotero")
      location.href = data.authorize_url
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
  })
  const connectedAccountsQuery = useQuery({
    queryFn: () => UsersService.getUserConnectedAccounts(),
    queryKey: ["user", "connected-accounts"],
  })
  const ghInstallQuery = useQuery({
    queryFn: () => UsersService.getUserGithubAppInstallations(),
    queryKey: ["user", "github-app-installations"],
    // Only meaningful once GitHub is connected; otherwise it 401s ("needs to
    // authenticate with GitHub"), which is noise for GitHub-less users.
    enabled: Boolean(connectedAccountsQuery.data?.github),
  })
  const overleafTokenModal = useDisclosure()

  const updateOverleafTokenMutation = useMutation({
    mutationFn: (data: TokenPut) => {
      return UsersService.putUserOverleafToken({ requestBody: data })
    },
    onSuccess: () => {
      mixpanel.track("Updated Overleaf token")
      showToast("Success!", "Overleaf token updated successfully.", "success")
      setIsEditingOverleaf(false)
      setOverleafToken("")
    },
    onError: (err: ApiError) => {
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
      return UsersService.deleteUserExternalCredential({ provider })
    },
    onSuccess: (_, provider) => {
      mixpanel.track("Disconnected account", { provider })
      showToast("Success!", `${provider} account disconnected.`, "success")
    },
    onError: (err: ApiError) => {
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
    <>
      <Heading size="md" mb={4}>
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
              ""
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
              <Button variant="primary" size="sm" onClick={handleConnectZenodo}>
                Connect
              </Button>
            )}
          </HStack>
          <HStack mt={4}>
            <Text>Overleaf:</Text>
            {connectedAccountsQuery.data?.overleaf ? (
              <>
                <Icon as={FaCheck} color="green.500" />
                {isEditingOverleaf ? (
                  <>
                    <Input
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
                    <IconButton
                      aria-label="Disconnect Overleaf"
                      icon={<FaTrash />}
                      size="xs"
                      variant="ghost"
                      colorScheme="red"
                      onClick={() =>
                        disconnectAccountMutation.mutate("overleaf")
                      }
                      isLoading={disconnectAccountMutation.isPending}
                    />
                  </>
                )}
              </>
            ) : (
              <Button
                variant="primary"
                size="sm"
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
              <Button variant="primary" size="sm" onClick={handleConnectGoogle}>
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
                size="sm"
                onClick={() => connectZoteroMutation.mutate()}
                isLoading={connectZoteroMutation.isPending}
              >
                Connect
              </Button>
            )}
          </HStack>
          <UpdateOverleafToken
            isOpen={overleafTokenModal.isOpen}
            onClose={overleafTokenModal.onClose}
          />
        </>
      )}
    </>
  )
}

export default ConnectedAccounts
