import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Grid,
  Heading,
  Spinner,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { FiPlus } from "react-icons/fi"
import { z } from "zod"

import { OperatorsService, type Workspace } from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Tooltip from "../../../../../components/Common/Tooltip"
import SecondFactorPrompt from "../../../../../components/Operators/SecondFactorPrompt"
import TerminalPane from "../../../../../components/Operators/TerminalPane"
import type { Pane } from "../../../../../components/Operators/connection"
import useOperatorConnections from "../../../../../components/Operators/useOperatorConnections"
import WorkspaceBadges from "../../../../../components/Workspace/WorkspaceBadges"
import WorkspacePanel, {
  type Modal,
} from "../../../../../components/Workspace/WorkspacePanel"
import useCustomToast from "../../../../../hooks/useCustomToast"
import useProject from "../../../../../hooks/useProject"

const computeSearchSchema = z.object({
  // Open terminal panes, as "<operator ID>:<session ID>", so a link reopens
  // them
  panes: z.array(z.string()).optional(),
  // The workspace whose details are shown, as "<operator ID>:<path>"
  workspace: z.string().optional(),
  // An open modal for acting on that workspace
  modal: z.enum(["save", "discard", "new_stage", "new_workspace"]).optional(),
  // A run asked for from another page, e.g., the pipeline's, which waits
  // for a click here: a stage's name, or "*" for the whole pipeline
  confirm_run: z.string().optional(),
})

// The open panes and workspace, kept for the browser tab so leaving for
// another page and coming back, e.g., through the sidebar, restores them
type ComputeState = { panes?: string[]; workspace?: string }

const computeStateKey = (accountName: string, projectName: string) =>
  `calkit-compute:${accountName}/${projectName}`

function readComputeState(key: string): ComputeState {
  try {
    return JSON.parse(sessionStorage.getItem(key) ?? "{}")
  } catch {
    return {}
  }
}

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/compute",
)({
  component: Compute,
  validateSearch: (search) => computeSearchSchema.parse(search),
  beforeLoad: ({ cause, params, search }) => {
    // Only on arriving, since closing the last pane leaves none on purpose
    if (cause !== "enter") return
    const stored = readComputeState(
      computeStateKey(params.accountName, params.projectName),
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
      to: "/$accountName/$projectName/compute",
      params,
      search: { ...search, ...restored },
      replace: true,
    })
  },
})

function Compute() {
  const { accountName, projectName } = Route.useParams()
  const navigate = Route.useNavigate()
  const search = Route.useSearch()
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
  // Connect to every online Operator with a workspace for this project
  const {
    connections,
    getConnection,
    onlineOperators,
    sessions,
    refreshSessions,
    secondFactorError,
    retryRefused,
  } = useOperatorConnections(
    workspaces.filter((w) => w.operator_online).map((w) => w.operator_id),
  )
  useEffect(() => {
    const state: ComputeState = {
      panes: search.panes,
      workspace: search.workspace,
    }
    try {
      sessionStorage.setItem(
        computeStateKey(accountName, projectName),
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
  const setModal = (modal: Modal | undefined) =>
    navigate({ search: (prev) => ({ ...prev, modal }) })
  // Online Operators without this project, which it could be cloned onto
  const operatorsQuery = useQuery({
    queryKey: ["user", "operators"],
    queryFn: () => OperatorsService.getOperators().then((r) => r.data),
  })
  const cloneTargets = (operatorsQuery.data ?? []).filter(
    (op) =>
      op.is_online &&
      !workspaces.some(
        (ws) => ws.operator_id === op.id && ws.kind === "personal",
      ),
  )
  const cloneMutation = useMutation({
    mutationFn: async (operatorId: string) => {
      const conn = getConnection(operatorId)
      await conn.waitUntilConnected()
      return conn.request("workspaces.clone", {
        git_repo_url: project?.git_repo_url,
      })
    },
    onSuccess: (result) =>
      showToast("Cloned", `The project is now in ${result.path}.`, "success"),
    onError: (err: Error) => showToast("Could not clone", err.message, "error"),
    onSettled: () => workspacesQuery.refetch(),
  })
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
  if (workspacesQuery.isPending) return <LoadingSpinner />
  return (
    <Box p={4} maxH="100%" overflowY="auto" w="100%">
      <Heading size="md" mb={3}>
        Workspaces
      </Heading>
      <SecondFactorPrompt error={secondFactorError} onVerified={retryRefused} />
      {workspaces.length === 0 ? (
        <Text mb={4}>
          None of your Operators has a workspace for this project. Install one
          with <Code>calkit operator install</Code> on a machine with this
          project in <Code>~/calkit</Code> or <Code>~/dev</Code>, or add it with{" "}
          <Code>calkit operator add-workspace</Code>.
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
      {project?.git_repo_url && cloneTargets.length > 0 && (
        <Flex align="center" gap={2} mb={6} wrap="wrap">
          <Text>Clone this project onto</Text>
          {cloneTargets.map((op) => (
            <Button
              key={op.id}
              size="xs"
              isLoading={
                cloneMutation.isPending && cloneMutation.variables === op.id
              }
              onClick={() => cloneMutation.mutate(String(op.id))}
            >
              {op.name}
            </Button>
          ))}
        </Flex>
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
              setModal={setModal}
              narrow={panes.length > 0}
              onChanged={() => workspacesQuery.refetch()}
              confirmRun={search.confirm_run}
              clearConfirmRun={() =>
                navigate({
                  search: (prev) => ({ ...prev, confirm_run: undefined }),
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
