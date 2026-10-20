import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Grid,
  Heading,
  Icon,
  IconButton,
  Select,
  Spinner,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  linkOptions,
  redirect,
} from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import {
  FiChevronDown,
  FiChevronRight,
  FiInfo,
  FiTerminal,
  FiX,
} from "react-icons/fi"
import { z } from "zod"

import { type MachineOut, MachinesService, type Workspace } from "../../client"
import ClearableInput from "../../components/Common/ClearableInput"
import LoadingSpinner from "../../components/Common/LoadingSpinner"
import Markdown from "../../components/Common/Markdown"
import Tooltip from "../../components/Common/Tooltip"
import SecondFactorPrompt from "../../components/Machines/SecondFactorPrompt"
import TerminalPane from "../../components/Machines/TerminalPane"
import type {
  MachineConnection,
  SessionInfo,
} from "../../components/Machines/connection"
import useMachineConnections from "../../components/Machines/useMachineConnections"
import WorkspaceBadges from "../../components/Workspace/WorkspaceBadges"
import WorkspacePanel from "../../components/Workspace/WorkspacePanel"
import { isLoggedIn } from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"

const workspacesSearchSchema = z.object({
  // The workspace shown, as "<machine ID>:<path>"
  workspace: z.string().optional(),
  // The session shown, as "<machine ID>:<session ID>", in its workspace
  session: z.string().optional(),
  // An open modal for acting on the workspace
  modal: z.enum(["save", "discard", "new_stage", "new_workspace"]).optional(),
  // Which of its pipeline's stages are listed, if not all
  stages: z.enum(["not_up_to_date", "running"]).optional(),
  // Narrowing the list down
  q: z.string().optional(),
  show: z
    .enum(["running", "changes", "out_of_sync", "sessions", "not_on_hub"])
    .optional(),
  // Most recently active first, unless sorted by name
  sort: z.enum(["name"]).optional(),
  // IDs of machines whose workspaces are hidden, and projects whose are,
  // as "<machine ID>:<project>"
  collapsed: z.array(z.string()).optional(),
  // An agent followed in the workspace, by its PID, when it isn't in one
  // of the link's sessions
  agent: z.coerce.number().optional(),
})

type WorkspacesSearch = z.infer<typeof workspacesSearchSchema>

// What's shown, kept for the browser tab so coming back through the top bar
// restores it
const STATE_KEY = "calkit-workspaces"

export const Route = createFileRoute("/_layout/workspaces")({
  component: Workspaces,
  validateSearch: (search) => workspacesSearchSchema.parse(search),
  beforeLoad: ({ cause, search }) => {
    if (!isLoggedIn()) {
      throw redirect({ to: "/login" })
    }
    if (cause !== "enter" || search.workspace || search.session) return
    let stored: WorkspacesSearch = {}
    try {
      stored = JSON.parse(sessionStorage.getItem(STATE_KEY) ?? "{}")
    } catch {
      return
    }
    if (!stored.workspace && !stored.session) return
    throw redirect({
      to: "/workspaces",
      search: {
        ...search,
        workspace: stored.workspace,
        session: stored.session,
      },
      replace: true,
    })
  },
})

const workspaceKey = (ws: Workspace) => `${ws.machine_id}:${ws.path}`

// The end of an agent's conversation, from the log it keeps, followed while
// it runs
function AgentLog({
  conn,
  workspace,
  pid,
  onClose,
}: {
  conn: MachineConnection
  workspace: Workspace
  pid: number
  onClose: () => void
}) {
  const bg = useColorModeValue("ui.secondary", "ui.darkSlate")
  const agent = (workspace.agents ?? []).find((a) => a.pid === pid)
  const logQuery = useQuery({
    queryKey: ["agent-log", workspace.machine_id, workspace.path, pid],
    queryFn: () =>
      conn.request("workspace.agent_log", { workspace: workspace.path, pid }),
    enabled: conn.connected,
    retry: false,
    refetchInterval: 5000,
  })
  const entries: { role: string; text: string; time: string | null }[] | null =
    logQuery.data?.entries ?? null
  const logRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Kept at the end, where the conversation goes on
    const el = logRef.current
    if (el && entries) el.scrollTop = el.scrollHeight
  }, [entries])
  return (
    <Box bg={bg} borderRadius="lg" p={3}>
      <Flex align="center" gap={2} mb={2}>
        <Code fontSize="xs">{agent?.tool ?? "agent"}</Code>
        {agent?.name && (
          <Text fontWeight="semibold" noOfLines={1}>
            {agent.name}
          </Text>
        )}
        {agent?.status && <Badge fontSize="2xs">{agent.status}</Badge>}
        {logQuery.isFetching && <Spinner size="xs" color="ui.dim" />}
        <IconButton
          aria-label="Close"
          icon={<FiX />}
          size="xs"
          variant="ghost"
          ml="auto"
          onClick={onClose}
        />
      </Flex>
      {logQuery.isPending ? (
        <Spinner size="sm" />
      ) : logQuery.error ? (
        <Text color="red.400" fontSize="sm">
          {logQuery.error.message}
        </Text>
      ) : entries === null ? (
        <Text color="ui.dim" fontSize="sm">
          Couldn't find this agent's conversation log on the machine.
        </Text>
      ) : (
        <Box ref={logRef} maxH="70vh" overflowY="auto">
          {entries.map((e, i) => (
            <Box key={i} mb={2}>
              {e.role === "tool" ? (
                <Text fontSize="xs" fontFamily="mono" color="ui.dim">
                  {e.text}
                </Text>
              ) : e.role === "event" ? (
                <Flex
                  align="center"
                  gap={2}
                  fontSize="xs"
                  color="ui.dim"
                  borderLeftWidth="2px"
                  borderColor="ui.dim"
                  pl={2}
                >
                  <Icon as={FiInfo} flexShrink={0} />
                  <Text whiteSpace="pre-wrap">{e.text}</Text>
                </Flex>
              ) : (
                <>
                  <Text
                    fontSize="xs"
                    fontWeight="semibold"
                    color={e.role === "user" ? "ui.main" : "ui.dim"}
                  >
                    {e.role === "user" ? "You" : agent?.tool ?? "Agent"}
                  </Text>
                  {e.role === "assistant" ? (
                    // Agents write Markdown, as their terminals render it,
                    // but what they read can steer it, so nothing loads
                    <Box fontSize="sm">
                      <Markdown untrusted>{e.text}</Markdown>
                    </Box>
                  ) : (
                    <Text fontSize="sm" whiteSpace="pre-wrap">
                      {e.text}
                    </Text>
                  )}
                </>
              )}
            </Box>
          ))}
        </Box>
      )}
    </Box>
  )
}

function Workspaces() {
  const navigate = Route.useNavigate()
  const search = Route.useSearch()
  const showToast = useCustomToast()
  const selectedBg = useColorModeValue("gray.100", "whiteAlpha.100")
  const listBorder = useColorModeValue("gray.200", "whiteAlpha.200")
  // Machines in cron mode asked to connect, which do at their next check-in
  const [waking, setWaking] = useState<Set<string>>(new Set())
  const machinesQuery = useQuery({
    queryKey: ["user", "machines"],
    queryFn: () => MachinesService.getMachines().then((r) => r.data),
    refetchInterval: waking.size ? 10000 : 30000,
  })
  const workspacesQuery = useQuery({
    queryKey: ["user", "workspaces"],
    queryFn: () => MachinesService.getWorkspaces().then((r) => r.data),
    refetchInterval: waking.size ? 10000 : 30000,
  })
  const machines = machinesQuery.data ?? []
  const workspaces = workspacesQuery.data ?? []
  const {
    connections,
    getConnection,
    onlineMachines,
    sessions,
    refreshSessions,
    secondFactorError,
    retryRefused,
  } = useMachineConnections(
    machines
      .filter((machine) => machine.is_online)
      .map((machine) => String(machine.id)),
    machinesQuery.refetch,
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
  // Stop waiting on machines once they're online
  useEffect(() => {
    const online = new Set(onlineMachines)
    if ([...waking].some((id) => online.has(id))) {
      setWaking(new Set([...waking].filter((id) => !online.has(id))))
    }
  }, [onlineMachines, waking])
  const wakeMachine = async (machineId: string) => {
    try {
      await MachinesService.postMachineWake({ machine_id: machineId })
      setWaking((prev) => new Set(prev).add(machineId))
    } catch (e: any) {
      showToast("Could not wake machine", e.message, "error")
    }
  }
  const select = (next: Partial<WorkspacesSearch>) =>
    navigate({
      search: (prev) => ({
        ...prev,
        workspace: undefined,
        session: undefined,
        agent: undefined,
        modal: undefined,
        ...next,
      }),
    })
  const selectedWorkspace = workspaces.find(
    (ws) => workspaceKey(ws) === search.workspace,
  )
  const [sessionMachine, sessionId] = (search.session ?? "").split(":")
  const selectedSession = sessionId
    ? sessions[sessionMachine]?.find((s) => s.id === sessionId)
    : undefined
  // A shell, or one attached to an agent's tmux pane
  const newSession = async (ws: Workspace, attach?: number) => {
    const conn = getConnection(ws.machine_id)
    try {
      const { session } = await conn.request("sessions.open", {
        workspace: ws.path,
        cols: 80,
        rows: 24,
        attach,
      })
      select({
        workspace: workspaceKey(ws),
        session: `${ws.machine_id}:${session}`,
      })
      refreshSessions()
    } catch (e: any) {
      showToast("Could not start a session", e.message, "error")
    }
  }
  const closeSession = (end: boolean) => {
    const conn = connections.get(sessionMachine)
    conn?.send({
      type: end ? "sessions.close" : "sessions.detach",
      session: sessionId,
    })
    select({ workspace: search.workspace })
    refreshSessions()
  }
  const getSessions = (ws: Workspace) =>
    (sessions[ws.machine_id] ?? []).filter((s) => s.workspace === ws.path)
  // What the filters leave, by the text in the box and the state chosen;
  // projects that aren't on the hub are only shown when asked for
  const query = (search.q ?? "").toLowerCase()
  const shown = (ws: Workspace) =>
    (!query ||
      `${ws.project ?? ""} ${ws.path} ${ws.machine_name}`
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
            ? getSessions(ws).length > 0 || (ws.agents ?? []).length > 0
            : true)
  const filtering = Boolean(query || search.show)
  const byActivity = (a: Workspace, b: Workspace) =>
    (b.last_activity ?? "").localeCompare(a.last_activity ?? "")
  const collapsed = new Set(search.collapsed ?? [])
  // Machines by ID, and projects' groups of workspaces as
  // "<machine ID>:<project>"
  const toggleCollapsed = (key: string) => {
    const next = new Set(collapsed)
    next.has(key) ? next.delete(key) : next.add(key)
    navigate({
      search: (prev) => ({
        ...prev,
        collapsed: next.size ? [...next] : undefined,
      }),
    })
  }
  // Online first, since that's what can be used
  const sortedMachines = [...machines].sort(
    (a, b) =>
      Number(b.is_online) - Number(a.is_online) || a.name.localeCompare(b.name),
  )
  const machineStatus = (machine: MachineOut) =>
    machine.is_online ? "online" : machine.is_asleep ? "asleep" : "offline"
  const sessionRow = (ws: Workspace, s: SessionInfo, nested: boolean) => {
    const key = `${ws.machine_id}:${s.id}`
    return (
      <Flex
        key={s.id}
        align="center"
        gap={2}
        pl={nested ? 12 : 8}
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
  // A workspace, under its machine, or its project when it has others
  const workspaceRow = (ws: Workspace, nested: boolean) => {
    const key = workspaceKey(ws)
    const wsSessions = getSessions(ws)
    return (
      <Box key={key}>
        <Box
          pl={nested ? 8 : 4}
          pr={2}
          py={1}
          cursor="pointer"
          borderRadius="md"
          bg={
            search.workspace === key && !search.session ? selectedBg : undefined
          }
          _hover={{ bg: selectedBg }}
          onClick={() => select({ workspace: key })}
        >
          <Flex align="center" gap={2}>
            <Text fontSize="sm" fontWeight="medium" noOfLines={1}>
              {nested
                ? ws.path.split("/").pop()
                : ws.project ?? ws.path.split("/").pop()}
            </Text>
            {ws.kind === "managed" && <Badge fontSize="2xs">managed</Badge>}
          </Flex>
          <Flex align="center" wrap="wrap" rowGap={1}>
            <Tooltip label={ws.path}>
              <Text fontSize="xs" color="ui.dim" noOfLines={1}>
                {ws.branch ?? "detached"}@{ws.commit?.slice(0, 7) ?? "?"}
              </Text>
            </Tooltip>
            <WorkspaceBadges ws={ws} />
            {(ws.agents ?? [])
              .filter((a) => a.where !== "session")
              .map((a) => (
                <Tooltip
                  key={a.pid}
                  label={[a.name, a.status].filter(Boolean).join(", ")}
                  isDisabled={!a.name && !a.status}
                >
                  <Badge ml={1} fontSize="2xs" colorScheme="purple">
                    {a.tool}
                  </Badge>
                </Tooltip>
              ))}
          </Flex>
        </Box>
        {wsSessions.map((s) => sessionRow(ws, s, nested))}
      </Box>
    )
  }
  if (machinesQuery.isPending || workspacesQuery.isPending) {
    return <LoadingSpinner height="60vh" />
  }
  const selectedConn = selectedWorkspace
    ? getConnection(selectedWorkspace.machine_id)
    : undefined
  // Reported by the machine, so only linked when it's a hub project name
  const projectMatch = selectedWorkspace?.project?.match(
    /^([a-z0-9][a-z0-9-]*)\/([A-Za-z0-9][A-Za-z0-9._-]*)$/,
  )
  const projectParams = projectMatch
    ? { accountName: projectMatch[1], projectName: projectMatch[2] }
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
          Workspaces
        </Heading>
        <ClearableInput
          size="sm"
          mb={2}
          placeholder="Filter by project, path, or machine"
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
                  show: (e.target.value ||
                    undefined) as WorkspacesSearch["show"],
                }),
              })
            }
          >
            <option value="">All</option>
            <option value="running">Running</option>
            <option value="changes">Uncommitted</option>
            <option value="out_of_sync">Out of sync</option>
            <option value="sessions">With sessions or agents</option>
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
        {machines.length === 0 && (
          <Text color="ui.dim" fontSize="sm">
            No machines yet. Install the Calkit CLI and run{" "}
            <Code>calkit hub link</Code> to link a machine and connect to a
            workspace.
          </Text>
        )}
        {sortedMachines.map((machine) => {
          const machineId = String(machine.id)
          const machineWorkspaces = workspaces.filter(
            (ws) => ws.machine_id === machineId && shown(ws),
          )
          if (search.sort !== "name") machineWorkspaces.sort(byActivity)
          if (filtering && machineWorkspaces.length === 0) return null
          // A project's workspaces together, where its first one would be
          const projectGroups: [string, Workspace[]][] = []
          for (const ws of machineWorkspaces) {
            const project = ws.project ?? ws.path
            const group = projectGroups.find(([p]) => p === project)
            group ? group[1].push(ws) : projectGroups.push([project, [ws]])
          }
          const isCollapsed = collapsed.has(machineId)
          const conn = connections.get(machineId)
          // Listed over the relay once it connects, which takes a moment
          const sessionsLoading =
            machine.is_online &&
            machine.platform !== "windows" &&
            !conn?.error &&
            sessions[machineId] === undefined
          return (
            <Box key={machineId} mb={4}>
              <Flex
                align="center"
                gap={2}
                mb={1}
                cursor="pointer"
                onClick={() => toggleCollapsed(machineId)}
              >
                {isCollapsed ? <FiChevronRight /> : <FiChevronDown />}
                <Box
                  w={2}
                  h={2}
                  borderRadius="full"
                  flexShrink={0}
                  bg={
                    machine.is_online
                      ? "ui.success"
                      : machine.is_asleep
                        ? "yellow.400"
                        : "gray.400"
                  }
                />
                <Tooltip
                  label={`${machine.hostname ?? ""}${machine.platform ? ` (${machine.platform})` : ""}, ${machineStatus(machine)}`}
                >
                  <Text fontWeight="semibold" noOfLines={1}>
                    {machine.name}
                  </Text>
                </Tooltip>
                <Text fontSize="xs" color="ui.dim">
                  {machineWorkspaces.length}
                </Text>
                {machine.restart_pending && (
                  <Badge fontSize="2xs">restart pending</Badge>
                )}
                {sessionsLoading && <Spinner size="xs" color="ui.dim" />}
                {machine.is_asleep && (
                  <Button
                    size="xs"
                    ml="auto"
                    isLoading={waking.has(machineId)}
                    loadingText="Waking"
                    onClick={(e) => {
                      e.stopPropagation()
                      wakeMachine(machineId)
                    }}
                  >
                    Wake
                  </Button>
                )}
              </Flex>
              {!isCollapsed && machineWorkspaces.length === 0 && (
                <Text fontSize="sm" color="ui.dim" pl={4}>
                  No workspaces
                </Text>
              )}
              {!isCollapsed &&
                projectGroups.map(([project, group]) => {
                  if (group.length === 1) return workspaceRow(group[0], false)
                  const groupKey = `${machineId}:${project}`
                  const isGroupCollapsed = collapsed.has(groupKey)
                  return (
                    <Box key={groupKey}>
                      <Flex
                        align="center"
                        gap={2}
                        pl={4}
                        pr={2}
                        py={1}
                        cursor="pointer"
                        borderRadius="md"
                        _hover={{ bg: selectedBg }}
                        onClick={() => toggleCollapsed(groupKey)}
                      >
                        {isGroupCollapsed ? (
                          <FiChevronRight />
                        ) : (
                          <FiChevronDown />
                        )}
                        <Text fontSize="sm" fontWeight="medium" noOfLines={1}>
                          {project}
                        </Text>
                        <Text fontSize="xs" color="ui.dim">
                          {group.length}
                        </Text>
                        {group.some((ws) => ws.running) && (
                          <Spinner size="xs" color="blue.400" />
                        )}
                      </Flex>
                      {!isGroupCollapsed &&
                        group.map((ws) => workspaceRow(ws, true))}
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
                {projectParams && (
                  <Button
                    as={RouterLink}
                    size="xs"
                    variant="outline"
                    // Checked here, since Chakra's "as" loses the types
                    {...linkOptions({
                      to: "/$accountName/$projectName/workspaces",
                      params: projectParams,
                      search: { workspace: workspaceKey(selectedWorkspace) },
                    })}
                  >
                    Open project
                  </Button>
                )}
              </Flex>
            </Flex>
            {selectedWorkspace.machine_online && selectedConn ? (
              // The details and the session side by side, when there's
              // room for both
              <Grid
                templateColumns={
                  search.session || search.agent
                    ? {
                        base: "minmax(0, 1fr)",
                        xl: "minmax(0, 2fr) minmax(0, 3fr)",
                      }
                    : "minmax(0, 1fr)"
                }
                gap={4}
                alignItems="start"
              >
                <Box minW={0}>
                  <WorkspacePanel
                    key={search.workspace}
                    ws={selectedWorkspace}
                    conn={selectedConn}
                    connected={selectedConn.connected}
                    modal={search.modal}
                    stageFilter={search.stages}
                    setStageFilter={(stages) =>
                      navigate({ search: (prev) => ({ ...prev, stages }) })
                    }
                    setModal={(modal) =>
                      navigate({ search: (prev) => ({ ...prev, modal }) })
                    }
                    onChanged={() => workspacesQuery.refetch()}
                    confirmRun={undefined}
                    clearConfirmRun={() => {}}
                    narrow={Boolean(search.session || search.agent)}
                    sessions={
                      selectedWorkspace.machine_platform === "windows"
                        ? undefined
                        : getSessions(selectedWorkspace)
                    }
                    activeSession={sessionId}
                    onOpenSession={(id) =>
                      select({
                        workspace: search.workspace,
                        session: `${selectedWorkspace.machine_id}:${id}`,
                      })
                    }
                    onNewSession={
                      selectedWorkspace.kind === "personal"
                        ? () => newSession(selectedWorkspace)
                        : undefined
                    }
                    activeAgent={search.agent}
                    onViewAgent={(pid) =>
                      select({ workspace: search.workspace, agent: pid })
                    }
                    onAttachAgent={
                      selectedWorkspace.kind === "personal"
                        ? (pid) => newSession(selectedWorkspace, pid)
                        : undefined
                    }
                  />
                </Box>
                {search.agent !== undefined && !search.session && (
                  <Box minW={0}>
                    <AgentLog
                      key={search.agent}
                      conn={selectedConn}
                      workspace={selectedWorkspace}
                      pid={search.agent}
                      onClose={() => select({ workspace: search.workspace })}
                    />
                  </Box>
                )}
                {search.session && (
                  <Box minW={0}>
                    <TerminalPane
                      key={search.session}
                      conn={selectedConn}
                      pane={{ machineId: sessionMachine, session: sessionId }}
                      label={selectedSession?.label ?? "shell"}
                      connected={selectedConn.connected}
                      onClose={() => closeSession(true)}
                      onDetach={() => closeSession(false)}
                      height="70vh"
                    />
                  </Box>
                )}
              </Grid>
            ) : (
              <Text color="ui.dim">
                {selectedWorkspace.machine_name} isn't connected.
              </Text>
            )}
          </>
        )}
      </Box>
    </Flex>
  )
}
