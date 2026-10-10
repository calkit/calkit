import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Grid,
  Heading,
  Select,
  Spinner,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  redirect,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { FiChevronDown, FiChevronRight, FiTerminal } from "react-icons/fi"
import { z } from "zod"

import {
  type OperatorOut,
  OperatorsService,
  type Workspace,
} from "../../client"
import ClearableInput from "../../components/Common/ClearableInput"
import LoadingSpinner from "../../components/Common/LoadingSpinner"
import Tooltip from "../../components/Common/Tooltip"
import SecondFactorPrompt from "../../components/Operators/SecondFactorPrompt"
import TerminalPane from "../../components/Operators/TerminalPane"
import type { SessionInfo } from "../../components/Operators/connection"
import useOperatorConnections from "../../components/Operators/useOperatorConnections"
import WorkspaceBadges from "../../components/Workspace/WorkspaceBadges"
import WorkspacePanel from "../../components/Workspace/WorkspacePanel"
import useCustomToast from "../../hooks/useCustomToast"

const computeSearchSchema = z.object({
  // The workspace shown, as "<operator ID>:<path>"
  workspace: z.string().optional(),
  // The session shown, as "<operator ID>:<session ID>", in its workspace
  session: z.string().optional(),
  // An open modal for acting on the workspace
  modal: z.enum(["save", "discard", "new_stage", "new_workspace"]).optional(),
  // Narrowing the list down
  q: z.string().optional(),
  show: z
    .enum(["running", "changes", "out_of_sync", "sessions", "not_on_hub"])
    .optional(),
  // Most recently active first, unless sorted by name
  sort: z.enum(["name"]).optional(),
  // IDs of Operators whose workspaces are hidden
  collapsed: z.array(z.string()).optional(),
})

type ComputeSearch = z.infer<typeof computeSearchSchema>

// What's shown, kept for the browser tab so coming back through the top bar
// restores it
const STATE_KEY = "calkit-compute"

export const Route = createFileRoute("/_layout/compute")({
  component: Compute,
  validateSearch: (search) => computeSearchSchema.parse(search),
  beforeLoad: ({ cause, search }) => {
    if (cause !== "enter" || search.workspace || search.session) return
    let stored: ComputeSearch = {}
    try {
      stored = JSON.parse(sessionStorage.getItem(STATE_KEY) ?? "{}")
    } catch {
      return
    }
    if (!stored.workspace && !stored.session) return
    throw redirect({
      to: "/compute",
      search: {
        ...search,
        workspace: stored.workspace,
        session: stored.session,
      },
      replace: true,
    })
  },
})

const workspaceKey = (ws: Workspace) => `${ws.operator_id}:${ws.path}`

function Compute() {
  const navigate = Route.useNavigate()
  const search = Route.useSearch()
  const showToast = useCustomToast()
  const selectedBg = useColorModeValue("gray.100", "whiteAlpha.100")
  const listBorder = useColorModeValue("gray.200", "whiteAlpha.200")
  // Operators in cron mode asked to connect, which do at their next check-in
  const [waking, setWaking] = useState<Set<string>>(new Set())
  const operatorsQuery = useQuery({
    queryKey: ["user", "operators"],
    queryFn: () => OperatorsService.getOperators().then((r) => r.data),
    refetchInterval: waking.size ? 10000 : 30000,
  })
  const workspacesQuery = useQuery({
    queryKey: ["user", "workspaces"],
    queryFn: () => OperatorsService.getWorkspaces().then((r) => r.data),
    refetchInterval: waking.size ? 10000 : 30000,
  })
  const operators = operatorsQuery.data ?? []
  const workspaces = workspacesQuery.data ?? []
  const {
    connections,
    getConnection,
    onlineOperators,
    sessions,
    refreshSessions,
    secondFactorError,
    retryRefused,
  } = useOperatorConnections(
    operators.filter((op) => op.is_online).map((op) => String(op.id)),
  )
  useEffect(() => {
    try {
      sessionStorage.setItem(
        STATE_KEY,
        JSON.stringify({
          workspace: search.workspace,
          session: search.session,
        }),
      )
    } catch {
      // Only a convenience
    }
  }, [search.workspace, search.session])
  // Stop waiting on Operators once they're online
  useEffect(() => {
    const online = new Set(onlineOperators)
    if ([...waking].some((id) => online.has(id))) {
      setWaking(new Set([...waking].filter((id) => !online.has(id))))
    }
  }, [onlineOperators, waking])
  const wakeOperator = async (operatorId: string) => {
    try {
      await OperatorsService.postOperatorWake({ operator_id: operatorId })
      setWaking((prev) => new Set(prev).add(operatorId))
    } catch (e: any) {
      showToast("Could not wake Operator", e.message, "error")
    }
  }
  const select = (next: Partial<ComputeSearch>) =>
    navigate({
      search: (prev) => ({
        ...prev,
        workspace: undefined,
        session: undefined,
        modal: undefined,
        ...next,
      }),
    })
  const selectedWorkspace = workspaces.find(
    (ws) => workspaceKey(ws) === search.workspace,
  )
  const [sessionOperator, sessionId] = (search.session ?? "").split(":")
  const selectedSession = sessionId
    ? sessions[sessionOperator]?.find((s) => s.id === sessionId)
    : undefined
  const newSession = async (ws: Workspace) => {
    const conn = getConnection(ws.operator_id)
    try {
      const { session } = await conn.request("sessions.open", {
        workspace: ws.path,
        cols: 80,
        rows: 24,
      })
      select({
        workspace: workspaceKey(ws),
        session: `${ws.operator_id}:${session}`,
      })
      refreshSessions()
    } catch (e: any) {
      showToast("Could not start a session", e.message, "error")
    }
  }
  const closeSession = (end: boolean) => {
    const conn = connections.get(sessionOperator)
    conn?.send({
      type: end ? "sessions.close" : "sessions.detach",
      session: sessionId,
    })
    select({ workspace: search.workspace })
    refreshSessions()
  }
  const getSessions = (ws: Workspace) =>
    (sessions[ws.operator_id] ?? []).filter((s) => s.workspace === ws.path)
  // What the filters leave, by the text in the box and the state chosen;
  // projects that aren't on the hub are only shown when asked for
  const query = (search.q ?? "").toLowerCase()
  const shown = (ws: Workspace) =>
    (!query ||
      `${ws.project ?? ""} ${ws.path} ${ws.operator_name}`
        .toLowerCase()
        .includes(query)) &&
    (search.show === "not_on_hub" ? !ws.on_hub : ws.on_hub) &&
    (search.show === "running"
      ? ws.running
      : search.show === "changes"
        ? ws.dirty
        : search.show === "out_of_sync"
          ? Boolean(ws.ahead || ws.behind)
          : search.show === "sessions"
            ? getSessions(ws).length > 0
            : true)
  const filtering = Boolean(query || search.show)
  const byActivity = (a: Workspace, b: Workspace) =>
    (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
  const collapsed = new Set(search.collapsed ?? [])
  const toggleCollapsed = (opId: string) => {
    const next = new Set(collapsed)
    next.has(opId) ? next.delete(opId) : next.add(opId)
    navigate({
      search: (prev) => ({
        ...prev,
        collapsed: next.size ? [...next] : undefined,
      }),
    })
  }
  // Online first, since that's what can be used
  const sortedOperators = [...operators].sort(
    (a, b) =>
      Number(b.is_online) - Number(a.is_online) || a.name.localeCompare(b.name),
  )
  const operatorStatus = (op: OperatorOut) =>
    op.is_online ? "online" : op.is_asleep ? "asleep" : "offline"
  const sessionRow = (ws: Workspace, s: SessionInfo) => {
    const key = `${ws.operator_id}:${s.id}`
    return (
      <Flex
        key={s.id}
        align="center"
        gap={2}
        pl={8}
        pr={2}
        py={1}
        cursor="pointer"
        borderRadius="md"
        bg={search.session === key ? selectedBg : undefined}
        _hover={{ bg: selectedBg }}
        onClick={() => select({ workspace: workspaceKey(ws), session: key })}
      >
        <FiTerminal />
        <Text fontSize="sm" fontFamily="mono" noOfLines={1}>
          {s.label}
        </Text>
        {s.attached > 0 && (
          <Tooltip label="Browsers attached">
            <Badge fontSize="2xs">{s.attached}</Badge>
          </Tooltip>
        )}
      </Flex>
    )
  }
  if (operatorsQuery.isPending || workspacesQuery.isPending) {
    return <LoadingSpinner />
  }
  const selectedConn = selectedWorkspace
    ? getConnection(selectedWorkspace.operator_id)
    : undefined
  return (
    <Flex h="100%" w="100%" direction={{ base: "column", lg: "row" }}>
      <Box
        w={{ base: "100%", lg: "380px" }}
        flexShrink={0}
        borderRightWidth={{ lg: "1px" }}
        borderColor={listBorder}
        p={3}
        overflowY="auto"
        maxH={{ lg: "100%" }}
      >
        <Heading size="md" mb={3}>
          Compute
        </Heading>
        <ClearableInput
          size="sm"
          mb={2}
          placeholder="Filter by project, path, or Operator"
          value={search.q ?? ""}
          onValueChange={(q) =>
            navigate({
              search: (prev) => ({ ...prev, q: q || undefined }),
              replace: true,
            })
          }
          autoComplete="off"
          data-form-type="other"
          data-lpignore="true"
        />
        <Flex gap={2} mb={3}>
          <Select
            size="sm"
            aria-label="Show"
            value={search.show ?? ""}
            onChange={(e) =>
              navigate({
                search: (prev) => ({
                  ...prev,
                  show: (e.target.value || undefined) as ComputeSearch["show"],
                }),
              })
            }
          >
            <option value="">All</option>
            <option value="running">Running</option>
            <option value="changes">Uncommitted</option>
            <option value="out_of_sync">Out of sync</option>
            <option value="sessions">With sessions</option>
            <option value="not_on_hub">Not on the hub</option>
          </Select>
          <Select
            size="sm"
            aria-label="Sort"
            value={search.sort ?? ""}
            onChange={(e) =>
              navigate({
                search: (prev) => ({
                  ...prev,
                  sort: e.target.value === "name" ? "name" : undefined,
                }),
              })
            }
          >
            <option value="">Recently active</option>
            <option value="name">Name</option>
          </Select>
        </Flex>
        {operators.length === 0 && (
          <Text color="ui.dim" fontSize="sm">
            You have no Operators. Install one with{" "}
            <Code>calkit operator install</Code>.
          </Text>
        )}
        {sortedOperators.map((op) => {
          const opId = String(op.id)
          const opWorkspaces = workspaces.filter(
            (ws) => ws.operator_id === opId && shown(ws),
          )
          if (search.sort !== "name") opWorkspaces.sort(byActivity)
          if (filtering && opWorkspaces.length === 0) return null
          const isCollapsed = collapsed.has(opId)
          const conn = connections.get(opId)
          // Listed over the relay once it connects, which takes a moment
          const sessionsLoading =
            op.is_online &&
            op.platform !== "windows" &&
            !conn?.error &&
            sessions[opId] === undefined
          return (
            <Box key={opId} mb={4}>
              <Flex
                align="center"
                gap={2}
                mb={1}
                cursor="pointer"
                onClick={() => toggleCollapsed(opId)}
              >
                {isCollapsed ? <FiChevronRight /> : <FiChevronDown />}
                <Box
                  w={2}
                  h={2}
                  borderRadius="full"
                  flexShrink={0}
                  bg={
                    op.is_online
                      ? "ui.success"
                      : op.is_asleep
                        ? "yellow.400"
                        : "gray.400"
                  }
                />
                <Tooltip
                  label={`${op.hostname ?? ""}${op.platform ? ` (${op.platform})` : ""}, ${operatorStatus(op)}`}
                >
                  <Text fontWeight="semibold" noOfLines={1}>
                    {op.name}
                  </Text>
                </Tooltip>
                <Text fontSize="xs" color="ui.dim">
                  {opWorkspaces.length}
                </Text>
                {op.restart_pending && (
                  <Badge fontSize="2xs">restart pending</Badge>
                )}
                {sessionsLoading && <Spinner size="xs" color="ui.dim" />}
                {op.is_asleep && (
                  <Button
                    size="xs"
                    ml="auto"
                    isLoading={waking.has(opId)}
                    loadingText="Waking"
                    onClick={(e) => {
                      e.stopPropagation()
                      wakeOperator(opId)
                    }}
                  >
                    Wake
                  </Button>
                )}
              </Flex>
              {!isCollapsed && opWorkspaces.length === 0 && (
                <Text fontSize="sm" color="ui.dim" pl={4}>
                  No workspaces
                </Text>
              )}
              {(isCollapsed ? [] : opWorkspaces).map((ws) => {
                const key = workspaceKey(ws)
                const wsSessions = getSessions(ws)
                return (
                  <Box key={key}>
                    <Box
                      pl={4}
                      pr={2}
                      py={1}
                      cursor="pointer"
                      borderRadius="md"
                      bg={
                        search.workspace === key && !search.session
                          ? selectedBg
                          : undefined
                      }
                      _hover={{ bg: selectedBg }}
                      onClick={() => select({ workspace: key })}
                    >
                      <Flex align="center" gap={2}>
                        <Text fontSize="sm" fontWeight="medium" noOfLines={1}>
                          {ws.project ?? ws.path.split("/").pop()}
                        </Text>
                        {ws.kind === "managed" && (
                          <Badge fontSize="2xs">managed</Badge>
                        )}
                      </Flex>
                      <Flex align="center" wrap="wrap" rowGap={1}>
                        <Tooltip label={ws.path}>
                          <Text fontSize="xs" color="ui.dim" noOfLines={1}>
                            {ws.branch ?? "detached"}@
                            {ws.commit?.slice(0, 7) ?? "?"}
                          </Text>
                        </Tooltip>
                        <WorkspaceBadges ws={ws} />
                      </Flex>
                    </Box>
                    {wsSessions.map((s) => sessionRow(ws, s))}
                  </Box>
                )
              })}
            </Box>
          )
        })}
      </Box>
      <Box flex={1} minW={0} p={4} overflowY="auto">
        <SecondFactorPrompt
          error={secondFactorError}
          onVerified={retryRefused}
        />
        {!selectedWorkspace ? (
          <Text color="ui.dim">
            Choose a workspace or session to see it here.
          </Text>
        ) : (
          <>
            <Flex align="center" gap={2} mb={3} wrap="wrap">
              <Heading size="sm">
                {selectedWorkspace.project ?? selectedWorkspace.path}
              </Heading>
              {selectedSession && (
                <Code fontSize="xs">{selectedSession.label}</Code>
              )}
              <Flex gap={2} ml="auto">
                {selectedWorkspace.project && (
                  <Button
                    as={RouterLink}
                    size="xs"
                    variant="outline"
                    to={`/${selectedWorkspace.project}/compute` as any}
                    search={
                      { workspace: workspaceKey(selectedWorkspace) } as any
                    }
                  >
                    Open project
                  </Button>
                )}
                {selectedWorkspace.kind === "personal" &&
                  selectedWorkspace.operator_online &&
                  selectedWorkspace.operator_platform !== "windows" && (
                    <Button
                      size="xs"
                      leftIcon={<FiPlus />}
                      isDisabled={!selectedConn?.connected}
                      onClick={() => newSession(selectedWorkspace)}
                    >
                      Session
                    </Button>
                  )}
              </Flex>
            </Flex>
            {search.session && selectedConn ? (
              <TerminalPane
                key={search.session}
                conn={selectedConn}
                pane={{ operatorId: sessionOperator, session: sessionId }}
                label={selectedSession?.label ?? "shell"}
                connected={selectedConn.connected}
                onClose={() => closeSession(true)}
                onDetach={() => closeSession(false)}
                height="60vh"
              />
            ) : selectedWorkspace.operator_online && selectedConn ? (
              <WorkspacePanel
                key={search.workspace}
                ws={selectedWorkspace}
                conn={selectedConn}
                connected={selectedConn.connected}
                modal={search.modal}
                setModal={(modal) =>
                  navigate({ search: (prev) => ({ ...prev, modal }) })
                }
                onChanged={() => workspacesQuery.refetch()}
                confirmRun={undefined}
                clearConfirmRun={() => {}}
              />
            ) : (
              <Text color="ui.dim">
                {selectedWorkspace.operator_name} isn't connected.
              </Text>
            )}
          </>
        )}
      </Box>
    </Flex>
  )
}
