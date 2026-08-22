import { Button, Divider, HStack, Text } from "@chakra-ui/react"
import mixpanel from "mixpanel-browser"
import { FaGithub, FaGoogle } from "react-icons/fa"

import { startGitHubOAuth } from "../../lib/github"
import { setPostLoginRedirect } from "../../lib/auth"
import { startGoogleOAuth } from "../../lib/google"

interface OAuthButtonsProps {
  /** "Sign in" or "Sign up"; the flows behind the buttons are identical. */
  verb: string
  /** Which page the click came from, for telemetry. */
  page: "login" | "signup"
  githubLoading?: boolean
  googleLoading?: boolean
}

/**
 * GitHub and Google buttons followed by an "or" rule.
 *
 * Both providers create the account on first sign-in, so the same two
 * buttons serve the login and signup pages; only the verb differs.
 */
const OAuthButtons = ({
  verb,
  page,
  githubLoading,
  googleLoading,
}: OAuthButtonsProps) => (
  <>
    <Button
      width="full"
      variant="primary"
      isLoading={githubLoading}
      onClick={() => {
        mixpanel.track("Clicked login", { provider: "github", page })
        if (page === "signup") setPostLoginRedirect("/new")
        startGitHubOAuth()
      }}
      rightIcon={<FaGithub />}
    >
      {verb} with GitHub
    </Button>
    <Button
      width="full"
      isLoading={googleLoading}
      onClick={() => {
        mixpanel.track("Clicked Google login", { page })
        if (page === "signup") setPostLoginRedirect("/new")
        startGoogleOAuth()
      }}
      rightIcon={<FaGoogle />}
    >
      {verb} with Google
    </Button>
    <HStack width="full">
      <Divider />
      <Text fontSize="xs" color="ui.dim" whiteSpace="nowrap">
        or
      </Text>
      <Divider />
    </HStack>
  </>
)

export default OAuthButtons
