import { Button, Text, VStack } from "@chakra-ui/react"
import { FaGithub } from "react-icons/fa"

import { startGitHubOAuth } from "../../lib/github"

interface ConnectGitHubPromptProps {
  /** What the user was trying to do, e.g. "create a project". */
  action: string
  /** Where to send the user back to once GitHub is connected. */
  returnTo?: string
}

/**
 * Shown in place of a form that can't work without a linked GitHub account.
 *
 * Accounts created through Google or email start GitHub-less, so the first
 * time they try to create something backed by a repo they'd otherwise hit an
 * opaque failure from the API.
 */
const ConnectGitHubPrompt = ({
  action,
  returnTo,
}: ConnectGitHubPromptProps) => (
  <VStack align="stretch" spacing={4} py={2}>
    <Text>
      Connecting a GitHub account is required to {action}, since Calkit stores
      code and text in a Git repo hosted there.
    </Text>
    <Button
      variant="primary"
      size="sm"
      alignSelf="center"
      leftIcon={<FaGithub />}
      onClick={() => startGitHubOAuth(returnTo)}
    >
      Connect GitHub
    </Button>
  </VStack>
)

export default ConnectGitHubPrompt
