import { ExternalLinkIcon } from "@chakra-ui/icons"
import { Button, HStack, Link } from "@chakra-ui/react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { FaGithub } from "react-icons/fa"
import { SiOverleaf, SiZotero } from "react-icons/si"

import { UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import useOnboardingFlags, { useLocalServer } from "../../hooks/useOnboarding"
import { handleError } from "../../lib/errors"
import { startGitHubOAuth } from "../../lib/github"
import { DISMISSED, buildAccountSteps } from "../../lib/onboarding"
import { stashZoteroReturn } from "../../lib/zotero"
import ChecklistCard from "./ChecklistCard"
import CommandBlock from "./CommandBlock"

/**
 * Account setup that every project shares: the accounts Calkit talks to on
 * the user's behalf, and the CLI that does the actual work.
 *
 * Separate from the project checklist because it's done once. Connecting
 * Zotero or Overleaf is offered rather than required -- plenty of people
 * use neither, and a checklist that can't be finished is one people learn
 * to ignore.
 */
const AccountSetupCard = ({ projectCount }: { projectCount: number }) => {
  const showToast = useCustomToast()
  const { accountFlags, setFlag } = useOnboardingFlags()
  const { cliRunning } = useLocalServer()
  const connectedAccountsQuery = useQuery({
    queryKey: ["user", "connected-accounts"],
    queryFn: () =>
      UsersService.getUserConnectedAccounts().then((response) => response.data),
  })
  // Zotero is OAuth 1.0a, whose request must be signed with our secret, so
  // the authorization URL comes from the backend rather than being built here.
  const zoteroMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserZoteroAuthStart().then((response) => response.data),
    onSuccess: (data) => {
      stashZoteroReturn()
      location.href = data.authorize_url
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const connected = connectedAccountsQuery.data
  const steps = buildAccountSteps({
    githubConnected: Boolean(connected?.github),
    zoteroConnected: Boolean(connected?.zotero),
    overleafConnected: Boolean(connected?.overleaf),
    cliRunning,
    projectCount,
    flags: accountFlags,
  })
  if (connectedAccountsQuery.isPending) {
    return null
  }
  const actions: Record<string, React.ReactNode> = {
    github: (
      <Button
        size="xs"
        variant="primary"
        leftIcon={<FaGithub />}
        onClick={() => startGitHubOAuth("/")}
      >
        Connect GitHub
      </Button>
    ),
    project: (
      <Button size="xs" variant="primary" as={RouterLink} to="/new">
        Start a project
      </Button>
    ),
    cli: (
      <>
        <CommandBlock
          label="macOS, Linux, or Git Bash"
          command="curl -LsSf install.calkit.org | sh"
        />
        <Link
          fontSize="xs"
          variant="blue"
          href="https://docs.calkit.org/installation/"
          isExternal
        >
          Windows and other options <ExternalLinkIcon mb={0.5} />
        </Link>
      </>
    ),
    overleaf: (
      <HStack spacing={3}>
        <Button
          size="xs"
          leftIcon={<SiOverleaf />}
          as={RouterLink}
          to="/settings"
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          search={{ tab: "connected-accounts" } as any}
        >
          Connect Overleaf
        </Button>
      </HStack>
    ),
    zotero: (
      <Button
        size="xs"
        leftIcon={<SiZotero />}
        isLoading={zoteroMutation.isPending}
        onClick={() => zoteroMutation.mutate()}
      >
        Connect Zotero
      </Button>
    ),
  }
  return (
    <ChecklistCard
      title="Set up your workspace"
      intro={
        "Connect the tools you already use. Nothing moves into Calkit that " +
        "you can't take back out -- your repo, your .bib, your Overleaf " +
        "project stay yours."
      }
      steps={steps}
      actions={actions}
      onMarkDone={setFlag}
      dismissed={accountFlags.includes(DISMISSED)}
      onDismissedChange={(dismissed) => setFlag(DISMISSED, dismissed)}
      doneMessage="You're all set up. Everything's connected."
    />
  )
}

export default AccountSetupCard
