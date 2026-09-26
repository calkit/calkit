import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Heading,
  Icon,
  IconButton,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import "@xterm/xterm/css/xterm.css"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { FiCheck, FiMinus, FiPlus, FiRefreshCw, FiX } from "react-icons/fi"
import { z } from "zod"

import {
  OperatorsService,
  type ProjectPublic,
  type ProjectWorkspace,
} from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Tooltip from "../../../../../components/Common/Tooltip"
import AddPath from "../../../../../components/Workspace/AddPath"
import DiscardChanges from "../../../../../components/Workspace/DiscardChanges"
import IgnorePath from "../../../../../components/Workspace/IgnorePath"
import NewStage from "../../../../../components/Workspace/NewStage"
import SaveFiles from "../../../../../components/Workspace/SaveFiles"
import useCustomToast from "../../../../../hooks/useCustomToast"

const computeSearchSchema = z.object({
  // Open terminal panes, as "<operator ID>:<session ID>", so a link reopens
  // them
  panes: z.array(z.string()).optional(),
  // The workspace whose details are shown, as "<operator ID>:<path>"
  workspace: z.string().optional(),
  // An open modal for acting on that workspace
  modal: z.enum(["save", "discard", "new_stage"]).optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/compute",
)({
  component: Compute,
  validateSearch: (search) => computeSearchSchema.parse(search),
})

interface SessionInfo {
  id: string
  workspace: string
  label: string
  attached: number
}

type Listener = (msg: any) => void

// One browser connection to an Operator through the relay. See
// docs/dev/operator-protocol.md for the messages.
class OperatorConnection {
  operatorId: string
  ws: WebSocket | null = null
  nextId = 1
  pending = new Map<
    number,
    { resolve: (r: any) => void; reject: (e: Error) => void }
  >()
  sessionListeners = new Map<string, Set<Listener>>()
  statusListeners = new Set<() => void>()
  connected = false
  closed = false
  retryDelay = 1000

  constructor(operatorId: string) {
    this.operatorId = operatorId
    this.connect()
  }

  async connect() {
    let ws: WebSocket
    try {
      const resp = await OperatorsService.postOperatorRelayToken({
        operator_id: this.operatorId,
      })
      const { relay_url, token } = resp.data
      ws = new WebSocket(`${relay_url}/browser?token=${token}`)
    } catch {
      this.scheduleReconnect()
      return
    }
    this.ws = ws
    ws.onopen = () => {
      this.connected = true
      this.retryDelay = 1000
      this.notify()
    }
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.type === "result" || msg.type === "error") {
        const p = this.pending.get(msg.id)
        if (p) {
          this.pending.delete(msg.id)
          if (msg.type === "result") p.resolve(msg.result)
          else p.reject(new Error(msg.error))
        }
        return
      }
      for (const listener of this.sessionListeners.get(msg.session) ?? []) {
        listener(msg)
      }
    }
    ws.onclose = () => {
      this.connected = false
      this.ws = null
      for (const p of this.pending.values()) {
        p.reject(new Error("Disconnected from Operator"))
      }
      this.pending.clear()
      this.notify()
      this.scheduleReconnect()
    }
  }

  scheduleReconnect() {
    if (this.closed) return
    window.setTimeout(() => this.connect(), this.retryDelay)
    this.retryDelay = Math.min(this.retryDelay * 2, 30000)
  }

  notify() {
    for (const listener of this.statusListeners) listener()
  }

  send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  request(type: string, fields: object = {}): Promise<any> {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        reject(new Error("Not connected to Operator"))
        return
      }
      this.pending.set(id, { resolve, reject })
      this.send({ type, id, ...fields })
    })
  }

  onSession(session: string, listener: Listener) {
    let listeners = this.sessionListeners.get(session)
    if (!listeners) {
      listeners = new Set()
      this.sessionListeners.set(session, listeners)
    }
    listeners.add(listener)
    return () => listeners.delete(listener)
  }

  async waitUntilConnected(timeoutMs = 10000) {
    const start = Date.now()
    while (!this.connected) {
      if (Date.now() - start > timeoutMs) {
        throw new Error("Could not connect to Operator")
      }
      await new Promise((resolve) => window.setTimeout(resolve, 200))
    }
  }

  close() {
    this.closed = true
    this.ws?.close()
  }
}

interface Pane {
  operatorId: string
  session: string
}

function TerminalPane({
  conn,
  pane,
  label,
  connected,
  onClose,
  onDetach,
}: {
  conn: OperatorConnection
  pane: Pane
  label: string
  connected: boolean
  onClose: () => void
  onDetach: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const [exited, setExited] = useState<number | null | undefined>(undefined)
  const headerBg = useColorModeValue("gray.100", "gray.700")
  // The terminal lives as long as the pane
  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "Menlo, Monaco, 'Courier New', monospace",
      scrollback: 5000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(ref.current!)
    fit.fit()
    termRef.current = term
    fitRef.current = fit
    const input = term.onData((data) =>
      conn.send({ type: "sessions.input", session: pane.session, data }),
    )
    const resize = term.onResize(({ cols, rows }) =>
      conn.send({ type: "sessions.resize", session: pane.session, cols, rows }),
    )
    const unsubscribe = conn.onSession(pane.session, (msg) => {
      if (msg.type === "sessions.output") {
        // Replays start by clearing the screen they redraw. It's written as
        // a reset sequence rather than calling reset(), which would take
        // effect before earlier writes that are still queued
        term.write(msg.reset ? `\x1bc${msg.data}` : msg.data)
      }
      if (msg.type === "sessions.exit") setExited(msg.code)
    })
    const observer = new ResizeObserver(() => fit.fit())
    observer.observe(ref.current!)
    return () => {
      observer.disconnect()
      unsubscribe()
      input.dispose()
      resize.dispose()
      term.dispose()
    }
  }, [conn, pane.session])
  // Attach whenever the connection is (re)established; the Operator replays
  // recent output onto a cleared screen
  useEffect(() => {
    const term = termRef.current
    if (!connected || !term) return
    conn
      .request("sessions.attach", {
        session: pane.session,
        cols: term.cols,
        rows: term.rows,
      })
      .catch((e) => term.write(`\r\n[${e.message}]\r\n`))
  }, [conn, connected, pane.session])
  return (
    <Box borderWidth={1} borderRadius="md" overflow="hidden" mb={3}>
      <Flex bg={headerBg} px={2} py={1} align="center" gap={2}>
        <Code fontSize="xs">{label}</Code>
        {!connected && <Badge colorScheme="orange">Reconnecting</Badge>}
        {exited !== undefined && (
          <Badge colorScheme="gray">Exited ({exited ?? "?"})</Badge>
        )}
        <Box flex={1} />
        <Tooltip label="Hide (keeps running)">
          <IconButton
            aria-label="Hide session"
            icon={<FiMinus />}
            size="xs"
            variant="ghost"
            onClick={onDetach}
          />
        </Tooltip>
        <Tooltip label="End session">
          <IconButton
            aria-label="End session"
            icon={<FiX />}
            size="xs"
            variant="ghost"
            onClick={onClose}
          />
        </Tooltip>
      </Flex>
      <Box ref={ref} h="360px" bg="black" p={1} />
    </Box>
  )
}

type Modal = "save" | "discard" | "new_stage"

function WorkspacePanel({
  ws,
  conn,
  connected,
  modal,
  setModal,
  runInSession,
  onChanged,
}: {
  ws: ProjectWorkspace
  conn: OperatorConnection
  connected: boolean
  modal: Modal | undefined
  setModal: (modal: Modal | undefined) => void
  runInSession: (command: string) => void
  onChanged: () => void
}) {
  const showToast = useCustomToast()
  const bg = useColorModeValue("ui.secondary", "ui.darkSlate")
  const editable = ws.kind === "personal"
  const request = useCallback(
    (type: string, fields: object = {}) =>
      conn.request(type, { workspace: ws.path, ...fields }),
    [conn, ws.path],
  )
  const statusQuery = useQuery({
    queryKey: ["workspace-status", ws.operator_id, ws.path],
    queryFn: () => request("workspace.status", { fetch: true }),
    enabled: connected,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const refresh = () => {
    statusQuery.refetch()
    onChanged()
  }
  const syncMutation = useMutation({
    mutationFn: (kind: "pull" | "push") => request(`workspace.${kind}`),
    onSuccess: (_, kind) =>
      showToast("Success!", kind === "pull" ? "Pulled." : "Pushed.", "success"),
    onError: (err: Error) => showToast("Error", err.message, "error"),
    onSettled: refresh,
  })
  const status = statusQuery.data
  const untracked: string[] = status?.git?.untracked ?? []
  const changed: string[] = (status?.git?.changed ?? []).concat(
    status?.dvc?.data?.changed ?? [],
  )
  const staged: string[] = (status?.git?.staged ?? []).concat(
    status?.dvc?.data?.staged ?? [],
  )
  const staleStages = Object.keys(status?.dvc?.pipeline ?? {})
  const ahead = status?.git?.commits_ahead ?? 0
  const behind = status?.git?.commits_behind ?? 0
  const dvcToPull = (status?.dvc?.data?.not_in_cache ?? []).length > 0
  const dvcToPush = (status?.dvc?.data?.not_in_remote ?? []).length > 0
  const canRun = editable && ws.operator_platform !== "windows"
  const check = <Icon ml={1} as={FiCheck} color="green.500" />
  return (
    <Box bg={bg} borderRadius="lg" p={4} mb={6}>
      <Flex align="center" gap={2} mb={3}>
        <Heading size="sm">
          {ws.operator_name}: <Code fontSize="sm">{ws.path}</Code>
        </Heading>
        <IconButton
          aria-label="Refresh status"
          icon={<FiRefreshCw />}
          size="xs"
          onClick={refresh}
          isLoading={statusQuery.isFetching}
          isDisabled={!connected}
        />
      </Flex>
      {!connected ? (
        <Text>Waiting for the Operator to connect.</Text>
      ) : statusQuery.isPending ? (
        <LoadingSpinner />
      ) : statusQuery.error ? (
        <Text color="red.500">{statusQuery.error.message}</Text>
      ) : (
        <>
          <Heading size="xs" mb={1}>
            Sync
          </Heading>
          <Flex align="center" gap={2} mb={3} wrap="wrap">
            {ahead || behind || dvcToPull || dvcToPush ? (
              <Text color="yellow.500">
                {[
                  ahead ? `${ahead} commits to push` : "",
                  behind ? `${behind} commits to pull` : "",
                  dvcToPull ? "data to pull" : "",
                  dvcToPush ? "data to push" : "",
                ]
                  .filter(Boolean)
                  .join(", ")}
              </Text>
            ) : (
              <Text>
                In sync with the remotes
                {check}
              </Text>
            )}
            {editable && (
              <>
                <Button
                  size="xs"
                  onClick={() => syncMutation.mutate("pull")}
                  isLoading={
                    syncMutation.isPending && syncMutation.variables === "pull"
                  }
                >
                  Pull
                </Button>
                <Button
                  size="xs"
                  onClick={() => syncMutation.mutate("push")}
                  isLoading={
                    syncMutation.isPending && syncMutation.variables === "push"
                  }
                >
                  Push
                </Button>
              </>
            )}
          </Flex>
          {untracked.length > 0 && (
            <>
              <Heading size="xs" mb={1}>
                Untracked files
              </Heading>
              {untracked.map((path) => (
                <Flex key={path} align="center" mb={1}>
                  <Text color="red.500" mr={1}>
                    {path}
                  </Text>
                  {editable && (
                    <>
                      <AddPath path={path} request={request} onDone={refresh} />
                      <IgnorePath
                        path={path}
                        request={request}
                        onDone={refresh}
                      />
                    </>
                  )}
                </Flex>
              ))}
            </>
          )}
          <Flex align="center" gap={2} mt={3} mb={1}>
            <Heading size="xs">Uncommitted changes</Heading>
            {editable && (changed.length > 0 || staged.length > 0) && (
              <>
                <Button
                  size="xs"
                  variant="primary"
                  onClick={() => setModal("save")}
                >
                  Commit
                </Button>
                <Button
                  size="xs"
                  variant="danger"
                  onClick={() => setModal("discard")}
                >
                  Discard
                </Button>
              </>
            )}
          </Flex>
          {staged.map((path) => (
            <Text key={path} color="green.500">
              {path}
            </Text>
          ))}
          {changed.map((path) => (
            <Text key={path} color="red.500">
              {path}
            </Text>
          ))}
          {changed.length === 0 && staged.length === 0 && (
            <Text>
              None
              {check}
            </Text>
          )}
          <Flex align="center" gap={2} mt={3} mb={1}>
            <Heading size="xs">Pipeline</Heading>
            {staleStages.length ? (
              <Badge colorScheme="yellow">Out of date</Badge>
            ) : (
              <Badge colorScheme="green">Up to date</Badge>
            )}
            {canRun && (
              <Button
                size="xs"
                variant="primary"
                onClick={() => runInSession("calkit run")}
              >
                Run
              </Button>
            )}
            {editable && (
              <Button
                size="xs"
                leftIcon={<FiPlus />}
                onClick={() => setModal("new_stage")}
              >
                New stage
              </Button>
            )}
          </Flex>
          {staleStages.map((stage) => (
            <Code key={stage} fontSize="xs" mr={1} color="yellow.500">
              {stage}
            </Code>
          ))}
          {(status?.errors ?? []).map((e: any) => (
            <Text key={e.info} color="red.500" fontSize="sm" mt={2}>
              {e.info}
            </Text>
          ))}
        </>
      )}
      {editable && (
        <>
          <SaveFiles
            isOpen={modal === "save"}
            onClose={() => setModal(undefined)}
            changedFiles={changed}
            stagedFiles={staged}
            request={request}
            onDone={refresh}
          />
          <DiscardChanges
            isOpen={modal === "discard"}
            onClose={() => setModal(undefined)}
            request={request}
            onDone={refresh}
          />
          <NewStage
            isOpen={modal === "new_stage"}
            onClose={() => setModal(undefined)}
            request={request}
            onDone={refresh}
          />
        </>
      )}
    </Box>
  )
}

function Compute() {
  const { accountName, projectName } = Route.useParams()
  const navigate = Route.useNavigate()
  const search = Route.useSearch()
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  const project = queryClient.getQueryData<ProjectPublic>([
    "projects",
    accountName,
    projectName,
  ])
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
  const connections = useRef(new Map<string, OperatorConnection>())
  const [, setVersion] = useState(0)
  const rerender = useCallback(() => setVersion((v) => v + 1), [])
  const [sessions, setSessions] = useState<Record<string, SessionInfo[]>>({})
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
  const getConnection = useCallback(
    (operatorId: string) => {
      let conn = connections.current.get(operatorId)
      if (!conn) {
        conn = new OperatorConnection(operatorId)
        conn.statusListeners.add(rerender)
        connections.current.set(operatorId, conn)
      }
      return conn
    },
    [rerender],
  )
  // Connect to every online Operator with a workspace for this project
  const onlineKey = [
    ...new Set(
      workspaces.filter((w) => w.operator_online).map((w) => w.operator_id),
    ),
  ].join(",")
  const onlineOperators = useMemo(
    () => (onlineKey ? onlineKey.split(",") : []),
    [onlineKey],
  )
  useEffect(() => {
    for (const operatorId of onlineOperators) getConnection(operatorId)
  }, [onlineOperators, getConnection])
  useEffect(() => {
    const conns = connections.current
    return () => {
      for (const conn of conns.values()) conn.close()
      conns.clear()
    }
  }, [])
  const refreshSessions = useCallback(async () => {
    const next: Record<string, SessionInfo[]> = {}
    for (const [operatorId, conn] of connections.current) {
      if (!conn.connected) continue
      try {
        next[operatorId] = (await conn.request("sessions.list")).sessions
      } catch {
        // Shown as disconnected instead
      }
    }
    setSessions(next)
  }, [])
  useEffect(() => {
    // Sessions are per Operator, so refresh when the set of them changes
    if (onlineOperators.length) refreshSessions()
    const interval = window.setInterval(refreshSessions, 5000)
    return () => window.clearInterval(interval)
  }, [refreshSessions, onlineOperators])
  const openPane = (operatorId: string, session: string) => {
    if (!panes.some((p) => p.session === session)) {
      setPanes([...panes, { operatorId, session }])
    }
  }
  const getLabel = (pane: Pane) =>
    sessions[pane.operatorId]?.find((s) => s.id === pane.session)?.label ??
    "shell"
  const newSession = async (ws: ProjectWorkspace, command?: string) => {
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
  const workspaceKey = (ws: ProjectWorkspace) => `${ws.operator_id}:${ws.path}`
  const selected = workspaces.find(
    (ws) => workspaceKey(ws) === search.workspace,
  )
  const selectWorkspace = (ws: ProjectWorkspace) =>
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
    const conn = connections.current.get(pane.operatorId)
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
      {workspaces.length === 0 ? (
        <Text mb={4}>
          None of your Operators has a workspace for this project. Install one
          with <Code>calkit install operator</Code> on a machine with this
          project in <Code>~/calkit</Code>, or add it with{" "}
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
              const conn = connections.current.get(ws.operator_id)
              const wsSessions = (sessions[ws.operator_id] ?? []).filter(
                (s) => s.workspace === ws.path,
              )
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
                    {ws.dirty && (
                      <Badge ml={2} colorScheme="yellow" fontSize="2xs">
                        uncommitted
                      </Badge>
                    )}
                    {!!ws.ahead && (
                      <Badge ml={2} fontSize="2xs">
                        {ws.ahead} ahead
                      </Badge>
                    )}
                    {!!ws.behind && (
                      <Badge ml={2} fontSize="2xs">
                        {ws.behind} behind
                      </Badge>
                    )}
                  </Td>
                  <Td>
                    <Flex gap={1} wrap="wrap">
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
                          <Button
                            size="xs"
                            leftIcon={<FiPlus />}
                            isDisabled={!conn?.connected}
                            onClick={() => newSession(ws)}
                          >
                            Session
                          </Button>
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
      {selected && (
        <WorkspacePanel
          key={workspaceKey(selected)}
          ws={selected}
          conn={getConnection(selected.operator_id)}
          connected={getConnection(selected.operator_id).connected}
          modal={search.modal}
          setModal={setModal}
          runInSession={(command) => newSession(selected, command)}
          onChanged={() => workspacesQuery.refetch()}
        />
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
  )
}
