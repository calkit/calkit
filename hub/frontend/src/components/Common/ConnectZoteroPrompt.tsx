import { Button, Text, VStack } from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { SiZotero } from "react-icons/si"

import { UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import { stashZoteroReturn } from "../../lib/zotero"

interface ConnectZoteroPromptProps {
  /** What the user was trying to do, e.g. "sync this collection". */
  action: string
  /** Reopen the Zotero import modal once back. */
  reopenImport?: boolean
}

/**
 * Shown in place of an action that can't work without a linked Zotero
 * account.
 *
 * Without this the API answers "User needs to authenticate with Zotero",
 * which lands as a toast that says what's wrong but not what to do about
 * it, leaving the user to find Connected accounts in settings on their own.
 */
const ConnectZoteroPrompt = ({
  action,
  reopenImport,
}: ConnectZoteroPromptProps) => {
  const showToast = useCustomToast()
  // Zotero uses OAuth 1.0a, whose requests must be signed with our client
  // secret, so the backend hands us the authorization URL.
  const connectMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserZoteroAuthStart().then((response) => response.data),
    onSuccess: (data) => {
      // Come back to whatever this prompt interrupted, rather than to
      // account settings, which is not where the user was headed
      stashZoteroReturn({ reopenImport })
      location.href = data.authorize_url
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  return (
    <VStack align="stretch" spacing={4} py={2}>
      <Text>
        Connecting a Zotero account is required to {action}, so Calkit can read
        your libraries and keep them in step with the project's references.
      </Text>
      <Button
        variant="primary"
        size="sm"
        alignSelf="center"
        leftIcon={<SiZotero />}
        isLoading={connectMutation.isPending}
        onClick={() => connectMutation.mutate()}
      >
        Connect Zotero
      </Button>
    </VStack>
  )
}

export default ConnectZoteroPrompt
