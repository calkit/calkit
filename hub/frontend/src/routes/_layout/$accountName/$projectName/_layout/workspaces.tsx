import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  Grid,
  Heading,
  Input,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useClipboard,
} from "@chakra-ui/react"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  createFileRoute,
  redirect,
  useRouterState,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { FiPlus } from "react-icons/fi"
import { z } from "zod"

import {
  type OperatorOut,
  OperatorsService,
  type Workspace,
} from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Tooltip from "../../../../../components/Common/Tooltip"
import SecondFactorPrompt from "../../../../../components/Operators/SecondFactorPrompt"
import TerminalPane from "../../../../../components/Operators/TerminalPane"
import type {
  OperatorConnection,
  Pane,
} from "../../../../../components/Operators/connection"
import useOperatorConnections from "../../../../../components/Operators/useOperatorConnections"
import WorkspaceBadges from "../../../../../components/Workspace/WorkspaceBadges"
import WorkspacePanel, {
  type Modal as WorkspaceModal,
} from "../../../../../components/Workspace/WorkspacePanel"
import useAuth from "../../../../../hooks/useAuth"
import useCustomToast from "../../../../../hooks/useCustomToast"
import useProject from "../../../../../hooks/useProject"

const workspacesSearchSchema = z.object({
  // Open terminal panes, as "<operator ID>:<session ID>", so a link reopens
  // them
  panes: z.array(z.string()).optional(),
  // The workspace whose details are shown, as "<operator ID>:<path>"
  workspace: z.string().optional(),
  // An open modal for acting on that workspace
  modal: z.enum(["save", "discard", "new_stage", "new_workspace"]).optional(),
  // Which of its pipeline's stages are listed, if not all
  stages: z.enum(["not_up_to_date", "running"]).optional(),
  // The Operator a workspace is being created on, by ID
  create: z.string().optional(),
})

declare module "@tanstack/history" {
  interface HistoryState {
    // A run asked for from another page, e.g., the pipeline's, which waits
    // for a click here: a stage's name, or "*" for the whole pipeline. Kept
    // out of the URL so a link can't ask.
    confirmRun?: string
  }
}

// The open panes and workspace, kept for the browser tab so leaving for
// another page and coming back, e.g., through the sidebar, restores them
type WorkspacesState = { panes?: string[]; workspace?: string }

const workspacesStateKey = (accountName: string, projectName: string) =>
  `calkit-workspaces:${accountName}/${projectName}`

function readWorkspacesState(key: string): WorkspacesState {
  try {
    return JSON.parse(sessionStorage.getItem(key) ?? "{}")
  } catch {
    return {}
  }
}

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/workspaces",
)({
  component: Workspaces,
  validateSearch: (search) => workspacesSearchSchema.parse(search),
  beforeLoad: ({ cause, params, search, location }) => {
    // Only on arriving, since closing the last pane leaves none on purpose
    if (cause !== "enter") return
    const stored = readWorkspacesState(
      workspacesStateKey(params.accountName, params.projectName),
    )
    const restored = {
      panes: search.panes ?? stored.panes,
      workspace: search.workspace ?? stored.workspace,
    }
    if (
      restored.panes === search.panes &&
      restored.workspace === search.workspace
    ) {
      return
    }
    throw redirect({
      to: "/$accountName/$projectName/workspaces",
      params,
      search: { ...search, ...restored },
      state: location.state,
      replace: true,
    })
  },
})

function Workspaces() {
  const { accountName, projectName } = Route.useParams()
  const navigate = Route.useNavigate()
  const search = Route.useSearch()
  const confirmRun = useRouterState({
    select: (s) => s.location.state.confirmRun,
  })
  const showToast = useCustomToast()
  const project = useProject(accountName, projectName).projectRequest.data
  // Operators in cron mode asked to connect, which do at their next check-in
  const [waking, setWaking] = useState<Set<string>>(new Set())
  const workspacesQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "workspaces"],
    queryFn: () =>
      OperatorsService.getProjectWorkspaces({
        owner_name: accountName,
        project_name: projectName,
      }).then((r) => r.data),
    // Faster while waiting for a woken Operator to show up
    refetchInterval: waking.size ? 10000 : 30000,
  })
  const workspaces = workspacesQuery.data ?? []
  // Operators without this project, which a workspace can be created on
  const operatorsQuery = useQuery({
    queryKey: ["user", "operators"],
    queryFn: () => OperatorsService.getOperators().then((r) => r.data),
  })
  const operators = operatorsQuery.data ?? []
  const createTargets = operators.filter(
    (op) =>
      (op.is_online || op.is_asleep) &&
      !workspaces.some(
        (ws) => ws.operator_id === op.id && ws.kind === "personal",
      ),
  )
  const creatingOn = createTargets.find(
    (op) => op.is_online && String(op.id) === search.create,
  )
  // Connect to every online Operator with a workspace for this project, and
  // the one a workspace is being created on
  const {
    connections,
    getConnection,
    onlineOperators,
    sessions,
    refreshSessions,
    secondFactorError,
    retryRefused,
  } = useOperatorConnections([
    ...workspaces.filter((w) => w.operator_online).map((w) => w.operator_id),
    ...(creatingOn ? [String(creatingOn.id)] : []),
  ])
  useEffect(() => {
    const state: WorkspacesState = {
      panes: search.panes,
      workspace: search.workspace,
    }
    try {
      sessionStorage.setItem(
        workspacesStateKey(accountName, projectName),
        JSON.stringify(state),
      )
    } catch {
      // Only a convenience
    }
  }, [accountName, projectName, search.panes, search.workspace])
  const panes: Pane[] = (search.panes ?? []).map((p) => {
    const [operatorId, session] = p.split(":")
    return { operatorId, session }
  })
  const setPanes = (next: Pane[]) =>
    navigate({
      search: (prev) => ({
        ...prev,
        panes: next.length
          ? next.map((p) => `${p.operatorId}:${p.session}`)
          : undefined,
      }),
    })
  const openPane = (operatorId: string, session: string) => {
    if (!panes.some((p) => p.session === session)) {
      setPanes([...panes, { operatorId, session }])
    }
  }
  const getLabel = (pane: Pane) =>
    sessions[pane.operatorId]?.find((s) => s.id === pane.session)?.label ??
    "shell"
  const newSession = async (ws: Workspace, command?: string) => {
    const conn = getConnection(ws.operator_id)
    try {
      const { session } = await conn.request("sessions.open", {
        workspace: ws.path,
        cols: 80,
        rows: 24,
        command,
      })
      openPane(ws.operator_id, session)
      refreshSessions()
    } catch (e: any) {
      showToast("Could not start a session", e.message, "error")
    }
  }
  const wakeOperator = async (operatorId: string) => {
    try {
      await OperatorsService.postOperatorWake({ operator_id: operatorId })
      setWaking((prev) => new Set(prev).add(operatorId))
    } catch (e: any) {
      showToast("Could not wake Operator", e.message, "error")
    }
  }
  // Stop waiting on Operators once they're online
  useEffect(() => {
    const online = new Set(onlineOperators)
    if ([...waking].some((id) => online.has(id))) {
      setWaking(new Set([...waking].filter((id) => !online.has(id))))
    }
  }, [onlineOperators, waking])
  const workspaceKey = (ws: Workspace) => `${ws.operator_id}:${ws.path}`
  const selected = workspaces.find(
    (ws) => workspaceKey(ws) === search.workspace,
  )
  const selectWorkspace = (ws: Workspace) =>
    navigate({
      search: (prev) => ({
        ...prev,
        workspace:
          prev.workspace === workspaceKey(ws) ? undefined : workspaceKey(ws),
        modal: undefined,
      }),
    })
  const setModal = (modal: WorkspaceModal | undefined) =>
    navigate({ search: (prev) => ({ ...prev, modal }) })
  const setCreate = (operatorId: string | undefined) =>
    navigate({ search: (prev) => ({ ...prev, create: operatorId }) })
  const closePane = (pane: Pane, end: boolean) => {
    const conn = connections.get(pane.operatorId)
    if (conn) {
      conn.send({
        type: end ? "sessions.close" : "sessions.detach",
        session: pane.session,
      })
    }
    setPanes(panes.filter((p) => p.session !== pane.session))
    refreshSessions()
  }
  if (workspacesQuery.isPending || operatorsQuery.isPending) {
    return <LoadingSpinner />
  }
  return (
    <Box p={4} maxH="100%" overflowY="auto" w="100%">
      <Heading size="md" mb={3}>
        Workspaces
      </Heading>
      <SecondFactorPrompt error={secondFactorError} onVerified={retryRefused} />
      {operators.length === 0 ? (
        <Text mb={4}>
          No Operators yet. Install the Calkit CLI and run{" "}
          <Code>calkit operator install</Code> to install the Operator and
          connect to a workspace.
        </Text>
      ) : workspaces.length === 0 ? (
        <Text mb={4}>
          No workspaces for this project yet. Create one on a machine below, or
          if it's already on one, run <Code>calkit operator add-workspace</Code>{" "}
          there.
        </Text>
      ) : (
        <Table size="sm" mb={6}>
          <Thead>
            <Tr>
              <Th>Operator</Th>
              <Th>Path</Th>
              <Th>State</Th>
              <Th>Sessions</Th>
              <Th />
            </Tr>
          </Thead>
          <Tbody>
            {workspaces.map((ws) => {
              const conn = connections.get(ws.operator_id)
              const wsSessions = (sessions[ws.operator_id] ?? []).filter(
                (s) => s.workspace === ws.path,
              )
              // Listed over the relay once it connects, which takes a moment
              const sessionsLoading =
                ws.operator_online &&
                ws.kind === "personal" &&
                ws.operator_platform !== "windows" &&
                !conn?.error &&
                sessions[ws.operator_id] === undefined
              return (
                <Tr key={`${ws.operator_id}:${ws.path}`}>
                  <Td>
                    <Flex align="center" gap={2}>
                      <Box
                        w={2}
                        h={2}
                        borderRadius="full"
                        bg={
                          ws.operator_online
                            ? "ui.success"
                            : ws.operator_asleep
                              ? "yellow.400"
                              : "gray.400"
                        }
                      />
                      {ws.operator_name}
                      {ws.operator_asleep && (
                        <Badge fontSize="2xs">
                          {waking.has(ws.operator_id) ? "waking" : "asleep"}
                        </Badge>
                      )}
                    </Flex>
                  </Td>
                  <Td>
                    <Tooltip label={ws.path}>
                      <Code fontSize="xs">
                        {ws.path.split("/").slice(-2).join("/")}
                      </Code>
                    </Tooltip>
                    {ws.kind === "managed" && (
                      <Badge ml={2} fontSize="2xs">
                        managed
                      </Badge>
                    )}
                  </Td>
                  <Td fontSize="xs">
                    {ws.branch ?? "detached"}@{ws.commit?.slice(0, 7) ?? "?"}
                    <WorkspaceBadges ws={ws} />
                  </Td>
                  <Td>
                    <Flex gap={1} wrap="wrap" align="center">
                      {sessionsLoading && (
                        <Tooltip label="Loading sessions">
                          <Spinner size="xs" color="ui.dim" />
                        </Tooltip>
                      )}
                      {wsSessions.map((s) => (
                        <Button
                          key={s.id}
                          size="xs"
                          variant="outline"
                          onClick={() => openPane(ws.operator_id, s.id)}
                        >
                          {s.label}
                        </Button>
                      ))}
                    </Flex>
                  </Td>
                  <Td>
                    {ws.kind === "personal" && ws.operator_asleep && (
                      <Button
                        size="xs"
                        isLoading={waking.has(ws.operator_id)}
                        loadingText="Waking"
                        onClick={() => wakeOperator(ws.operator_id)}
                      >
                        Wake
                      </Button>
                    )}
                    <Flex gap={1}>
                      {ws.kind === "personal" &&
                        !ws.operator_asleep &&
                        ws.operator_platform !== "windows" && (
                          <Tooltip
                            label={
                              secondFactorError
                                ? "Enter a code from your authenticator app above first"
                                : "Waiting for the Operator to connect"
                            }
                            isDisabled={!!conn?.connected}
                          >
                            {/* A disabled button doesn't show a tooltip */}
                            <span>
                              <Button
                                size="xs"
                                leftIcon={<FiPlus />}
                                isDisabled={!conn?.connected}
                                onClick={() => newSession(ws)}
                              >
                                Session
                              </Button>
                            </span>
                          </Tooltip>
                        )}
                      {ws.operator_online && (
                        <Button
                          size="xs"
                          variant={
                            search.workspace === workspaceKey(ws)
                              ? "solid"
                              : "outline"
                          }
                          onClick={() => selectWorkspace(ws)}
                        >
                          Details
                        </Button>
                      )}
                    </Flex>
                  </Td>
                </Tr>
              )
            })}
          </Tbody>
        </Table>
      )}
      {project?.git_repo_url && createTargets.length > 0 && (
        <Box mb={6}>
          <Text mb={2} fontSize="sm" color="ui.dim">
            {workspaces.length === 0
              ? "Create a workspace on"
              : "Create a workspace on another machine"}
          </Text>
          {createTargets.map((op) => (
            <Flex key={op.id} align="center" gap={2} mb={1}>
              <Box
                w={2}
                h={2}
                borderRadius="full"
                bg={op.is_online ? "ui.success" : "yellow.400"}
              />
              <Text fontSize="sm">{op.name}</Text>
              {op.is_online ? (
                <Button
                  size="xs"
                  leftIcon={<FiPlus />}
                  onClick={() => setCreate(String(op.id))}
                >
                  Create workspace
                </Button>
              ) : (
                <Button
                  size="xs"
                  isLoading={waking.has(String(op.id))}
                  loadingText="Waking"
                  onClick={() => wakeOperator(String(op.id))}
                >
                  Wake
                </Button>
              )}
            </Flex>
          ))}
        </Box>
      )}
      {creatingOn && project?.git_repo_url && (
        <CreateWorkspace
          operator={creatingOn}
          conn={getConnection(String(creatingOn.id))}
          gitRepoUrl={project.git_repo_url}
          defaultPath={`~/calkit/${projectName}`}
          onClose={() => setCreate(undefined)}
          onCreated={() => {
            operatorsQuery.refetch()
            workspacesQuery.refetch()
          }}
        />
      )}
      {/* The summary on the left and sessions on the right, side by side
          when there's room for both */}
      <Grid
        templateColumns={
          selected && panes.length
            ? { base: "minmax(0, 1fr)", xl: "minmax(0, 2fr) minmax(0, 3fr)" }
            : "minmax(0, 1fr)"
        }
        gap={4}
        alignItems="start"
      >
        {selected && (
          <Box minW={0}>
            <WorkspacePanel
              key={workspaceKey(selected)}
              ws={selected}
              conn={getConnection(selected.operator_id)}
              connected={getConnection(selected.operator_id).connected}
              modal={search.modal}
              stageFilter={search.stages}
              setStageFilter={(stages) =>
                navigate({ search: (prev) => ({ ...prev, stages }) })
              }
              setModal={setModal}
              narrow={panes.length > 0}
              onChanged={() => workspacesQuery.refetch()}
              confirmRun={confirmRun}
              clearConfirmRun={() =>
                navigate({
                  search: (prev) => prev,
                  state: (prev) => ({ ...prev, confirmRun: undefined }),
                  replace: true,
                })
              }
            />
          </Box>
        )}
        {panes.length > 0 && (
          <Box minW={0}>
            {panes.map((pane) => {
              const conn = getConnection(pane.operatorId)
              return (
                <TerminalPane
                  key={pane.session}
                  conn={conn}
                  pane={pane}
                  label={getLabel(pane)}
                  connected={conn.connected}
                  onClose={() => closePane(pane, true)}
                  onDetach={() => closePane(pane, false)}
                />
              )
            })}
          </Box>
        )}
      </Grid>
    </Box>
  )
}

// What the Operator found the machine still needs before cloning, from
// 'machine.check'
type MachineSetup = {
  git_name: string | null
  git_email: string | null
  repo: { host: string; ssh: boolean; error: string | null }
  token: boolean
}

// Creates a workspace for the project on an Operator's machine, setting up
// what it needs first, e.g., Git's name and email
function CreateWorkspace({
  operator,
  conn,
  gitRepoUrl,
  defaultPath,
  onClose,
  onCreated,
}: {
  operator: OperatorOut
  conn: OperatorConnection
  gitRepoUrl: string
  defaultPath: string
  onClose: () => void
  onCreated: () => void
}) {
  const showToast = useCustomToast()
  const { user } = useAuth()
  const [path, setPath] = useState(defaultPath)
  const [gitName, setGitName] = useState(user?.full_name ?? "")
  const [gitEmail, setGitEmail] = useState(user?.email ?? "")
  const [makeToken, setMakeToken] = useState(true)
  // Checking contacts the repo's host from the machine, so it waits for a
  // click
  const [checkAsked, setCheckAsked] = useState(false)
  const setupQuery = useQuery({
    queryKey: ["operators", operator.id, "machine-setup", gitRepoUrl],
    queryFn: async (): Promise<MachineSetup> => {
      await conn.waitUntilConnected()
      return conn.request("machine.check", { git_repo_url: gitRepoUrl })
    },
    enabled: checkAsked,
    retry: false,
  })
  const setup = setupQuery.data
  // The machine's SSH key, for the owner to add to their Git host, as with
  // 'calkit config github-ssh'
  const sshKeyMutation = useMutation({
    mutationFn: (): Promise<{ public_key: string; created: boolean }> =>
      conn.request("machine.ssh_key"),
    onError: (err: Error) =>
      showToast("Could not set up SSH", err.message, "error"),
  })
  const sshKey = sshKeyMutation.data?.public_key ?? ""
  const { onCopy, hasCopied } = useClipboard(sshKey)
  const needsGit = !!setup && (!setup.git_name || !setup.git_email)
  const createMutation = useMutation({
    mutationFn: async () => {
      if (!setup) throw new Error("The machine hasn't been checked yet")
      const fields: Record<string, string | boolean> = {}
      if (!setup.git_name) fields.git_name = gitName
      if (!setup.git_email) fields.git_email = gitEmail
      // The Operator fetches its token from the hub itself, once asked here
      if (!setup.token && makeToken) {
        await OperatorsService.postOperatorCliTokenRequest(
          { operator_id: String(operator.id) },
          // For the second factor's cookie
          { withCredentials: true },
        )
        fields.token = true
      }
      if (Object.keys(fields).length) {
        await conn.request("machine.configure", fields)
        // So trying again doesn't set it up twice
        await setupQuery.refetch()
      }
      return conn.request("workspaces.clone", {
        git_repo_url: gitRepoUrl,
        path,
      })
    },
    onSuccess: (result: { path: string }) => {
      showToast(
        "Workspace created",
        `${result.path} on ${operator.name}`,
        "success",
      )
      onCreated()
      onClose()
    },
    onError: (err: Error) =>
      showToast("Could not create workspace", err.message, "error"),
  })
  const ready =
    !!setup &&
    !setup.repo.error &&
    path.trim() !== "" &&
    (!needsGit || (gitName.trim() !== "" && gitEmail.includes("@")))
  return (
    <Modal isOpen onClose={onClose} size="lg">
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>Create workspace on {operator.name}</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          <FormControl mb={4}>
            <FormLabel htmlFor="path">Path</FormLabel>
            <Input
              id="path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
            />
          </FormControl>
          {!checkAsked ? (
            <Flex align="center" gap={2} fontSize="sm">
              <Text>
                {operator.name} will check it can reach{" "}
                <Code fontSize="xs" wordBreak="break-all">
                  {gitRepoUrl}
                </Code>
              </Text>
              <Button size="xs" onClick={() => setCheckAsked(true)}>
                Check
              </Button>
            </Flex>
          ) : setupQuery.isPending ? (
            <Flex align="center" gap={2} fontSize="sm" color="ui.dim">
              <Spinner size="sm" />
              Checking {operator.name}
            </Flex>
          ) : setupQuery.error ? (
            <Text fontSize="sm" color="red.400">
              {setupQuery.error.message}
            </Text>
          ) : setup ? (
            <>
              {setup.repo.error && (
                <Alert status="warning" borderRadius="md" mb={4} gap={2}>
                  <AlertIcon />
                  <Box flex={1} fontSize="sm">
                    {setup.repo.ssh ? (
                      <>
                        <Text>
                          {operator.name} can't reach {setup.repo.host} over
                          SSH.
                        </Text>
                        {sshKey ? (
                          <>
                            <Text mt={2}>
                              Add this key to your {setup.repo.host} account,
                              then check again.
                            </Text>
                            <Code
                              display="block"
                              p={2}
                              my={2}
                              fontSize="xs"
                              wordBreak="break-all"
                            >
                              {sshKey}
                            </Code>
                            <Flex gap={2} align="center">
                              <Button size="xs" onClick={onCopy}>
                                {hasCopied ? "Copied" : "Copy"}
                              </Button>
                              {setup.repo.host === "github.com" && (
                                <Link
                                  href="https://github.com/settings/ssh/new"
                                  isExternal
                                  color="ui.main"
                                >
                                  Open GitHub's SSH settings
                                </Link>
                              )}
                            </Flex>
                          </>
                        ) : (
                          <Button
                            size="xs"
                            mt={2}
                            isLoading={sshKeyMutation.isPending}
                            onClick={() => sshKeyMutation.mutate()}
                          >
                            Set up SSH
                          </Button>
                        )}
                      </>
                    ) : (
                      <Text>
                        {operator.name} can't reach the repository on{" "}
                        {setup.repo.host}. Sign in to {setup.repo.host} on that
                        machine, e.g., with <Code>gh auth login</Code>.
                      </Text>
                    )}
                    <Text color="ui.dim" fontSize="xs" mt={1}>
                      {setup.repo.error}
                    </Text>
                  </Box>
                  <Button
                    size="xs"
                    isLoading={setupQuery.isFetching}
                    onClick={() => setupQuery.refetch()}
                  >
                    Check again
                  </Button>
                </Alert>
              )}
              {needsGit && (
                <Box mb={4}>
                  <Text fontSize="sm" mb={2}>
                    Git needs a name and email for commits on {operator.name}.
                  </Text>
                  <Flex gap={2}>
                    <Input
                      size="sm"
                      placeholder="Name"
                      value={gitName}
                      onChange={(e) => setGitName(e.target.value)}
                      isDisabled={!!setup.git_name}
                      autoComplete="off"
                      data-form-type="other"
                      data-lpignore="true"
                    />
                    <Input
                      size="sm"
                      placeholder="Email"
                      value={gitEmail}
                      onChange={(e) => setGitEmail(e.target.value)}
                      isDisabled={!!setup.git_email}
                      autoComplete="off"
                      data-form-type="other"
                      data-lpignore="true"
                    />
                  </Flex>
                </Box>
              )}
              {!setup.token && (
                <FormControl>
                  <Checkbox
                    isChecked={makeToken}
                    onChange={(e) => setMakeToken(e.target.checked)}
                  >
                    Authenticate this Operator with the Calkit CLI.
                  </Checkbox>
                  <FormHelperText>
                    So it can pull and push data with the hub.
                  </FormHelperText>
                </FormControl>
              )}
            </>
          ) : null}
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            isDisabled={!ready}
            isLoading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            Create
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}
