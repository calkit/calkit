import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Code,
  Flex,
  Heading,
  IconButton,
  Grid,
  Input,
  SimpleGrid,
  Spinner,
  Table,
  Tag,
  TagLabel,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  redirect,
} from "@tanstack/react-router"
import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import "@xterm/xterm/css/xterm.css"
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import {
  FiChevronDown,
  FiChevronRight,
  FiMinus,
  FiPlay,
  FiPlus,
  FiRefreshCw,
  FiX,
} from "react-icons/fi"
import { z } from "zod"

import {
  OperatorsService,
  type Workspace,
  UsersService,
} from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import Tooltip from "../../../../../components/Common/Tooltip"
import AddPath from "../../../../../components/Workspace/AddPath"
import DiscardChanges from "../../../../../components/Workspace/DiscardChanges"
import IgnorePath from "../../../../../components/Workspace/IgnorePath"
import NewStage from "../../../../../components/Workspace/NewStage"
import SaveFiles from "../../../../../components/Workspace/SaveFiles"
import useCustomToast from "../../../../../hooks/useCustomToast"
import {
  getSecondFactorToken,
  storeSecondFactorToken,
} from "../../../../../lib/auth"
import useProject from "../../../../../hooks/useProject"

const computeSearchSchema = z.object({
  // Open terminal panes, as "<operator ID>:<session ID>", so a link reopens
  // them
  panes: z.array(z.string()).optional(),
  // The workspace whose details are shown, as "<operator ID>:<path>"
  workspace: z.string().optional(),
  // An open modal for acting on that workspace
  modal: z.enum(["save", "discard", "new_stage"]).optional(),
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

interface SessionInfo {
  id: string
  workspace: string
  label: string
  attached: number
}

type Listener = (msg: any) => void

// Why the hub refused a relay token, from app/users.py
const SECOND_FACTOR_SETUP_REQUIRED = "Two-factor authentication setup required"
const SECOND_FACTOR_REQUIRED = "Two-factor authentication code required"

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
  // Why connecting failed, if the user has to do something about it
  error: string | null = null
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
        "x-second-factor": getSecondFactorToken(),
      })
      // Closed while the token was on its way, e.g., by leaving the page,
      // so it mustn't open a channel that would keep the Operator awake
      if (this.closed) return
      const { relay_url, token } = resp.data
      ws = new WebSocket(`${relay_url}/browser`)
      // Sent in a message rather than the URL to stay out of logs
      ws.addEventListener("open", () =>
        ws.send(JSON.stringify({ type: "auth", token })),
      )
    } catch (e: any) {
      const detail = e.response?.data?.detail
      // Retrying won't help until the user enters a code
      if (
        detail === SECOND_FACTOR_REQUIRED ||
        detail === SECOND_FACTOR_SETUP_REQUIRED
      ) {
        this.error = detail
        this.notify()
        return
      }
      this.scheduleReconnect()
      return
    }
    this.error = null
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

  retryNow() {
    this.error = null
    this.retryDelay = 1000
    this.connect()
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
    // Replayed chunks still being written, during which the terminal's
    // replies to queries in them, e.g., a cursor position report, are
    // dropped: they were answered when first asked, and would now reach the
    // shell as text
    let replaying = 0
    const input = term.onData((data) => {
      if (replaying) return
      conn.send({ type: "sessions.input", session: pane.session, data })
    })
    const resize = term.onResize(({ cols, rows }) =>
      conn.send({ type: "sessions.resize", session: pane.session, cols, rows }),
    )
    const unsubscribe = conn.onSession(pane.session, (msg) => {
      if (msg.type === "sessions.output") {
        // Replays start by clearing the screen they redraw. It's written as
        // a reset sequence rather than calling reset(), which would take
        // effect before earlier writes that are still queued
        const data = msg.reset ? `\x1bc${msg.data}` : msg.data
        if (msg.replay) {
          replaying++
          term.write(data, () => replaying--)
        } else {
          term.write(data)
        }
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
      {/* The padding is on a wrapper, since the fit addon sizes the
          terminal to its element's full height, padding included, which
          would cut off the last row */}
      <Box bg="black" p={1}>
        <Box ref={ref} h="352px" />
      </Box>
    </Box>
  )
}

type Modal = "save" | "discard" | "new_stage"

const PANEL_COLLAPSED_KEY = "calkit-workspace-panel-collapsed"

// One part of the workspace panel: a small card with a title and actions
function PanelSection({
  title,
  actions,
  children,
}: {
  title: string
  actions?: ReactNode
  children: ReactNode
}) {
  const border = useColorModeValue("gray.200", "whiteAlpha.200")
  return (
    <Box borderWidth="1px" borderColor={border} borderRadius="md" p={3}>
      <Flex align="center" gap={2} mb={2} minH="24px">
        <Text
          fontSize="xs"
          fontWeight="semibold"
          textTransform="uppercase"
          letterSpacing="wide"
          color="ui.dim"
        >
          {title}
        </Text>
        <Flex gap={1} ml="auto">
          {actions}
        </Flex>
      </Flex>
      {children}
    </Box>
  )
}

function WorkspacePanel({
  ws,
  conn,
  connected,
  modal,
  setModal,
  onChanged,
  confirmRun,
  clearConfirmRun,
  narrow,
}: {
  ws: Workspace
  conn: OperatorConnection
  connected: boolean
  modal: Modal | undefined
  setModal: (modal: Modal | undefined) => void
  onChanged: () => void
  confirmRun: string | undefined
  clearConfirmRun: () => void
  // Shown with sessions, which it sits beside on wide screens
  narrow?: boolean
}) {
  const showToast = useCustomToast()
  const bg = useColorModeValue("ui.secondary", "ui.darkSlate")
  const editable = ws.kind === "personal"
  const request = useCallback(
    (type: string, fields: object = {}) =>
      conn.request(type, { workspace: ws.path, ...fields }),
    [conn, ws.path],
  )
  // When a run was started from here, which may take a moment to show up
  const [runStartedAt, setRunStartedAt] = useState(0)
  const statusQuery = useQuery({
    queryKey: ["workspace-status", ws.operator_id, ws.path],
    queryFn: () => request("workspace.status", { fetch: true }),
    enabled: connected,
    retry: false,
    refetchOnWindowFocus: false,
    // Followed while a run is in progress, like VS Code's sidebar, or
    // may be, having just been started or reported at check-in
    refetchInterval: (query) =>
      query.state.data?.status?.pipeline?.running ||
      ws.running ||
      Date.now() - runStartedAt < 60000
        ? 5000
        : false,
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
  // What `calkit status --json` reports, the same as VS Code shows
  const status = statusQuery.data?.status
  const untracked: string[] = status?.git?.untracked_files ?? []
  // DVC calls a path committed when its DVC file is staged
  const changed: string[] = (status?.git?.changed_files ?? []).concat(
    status?.dvc?.uncommitted?.modified ?? [],
  )
  const staged: string[] = (status?.git?.staged_files ?? []).concat(
    status?.dvc?.committed?.modified ?? [],
  )
  const staleStages: string[] = status?.pipeline?.stale_stage_names ?? []
  const staleDetail: Record<string, any> = status?.pipeline?.stale_stages ?? {}
  // From the latest check-in until the live status arrives
  const runningStages: string[] =
    status?.pipeline?.running_stages ?? ws.running_stages ?? []
  // Environments aren't checked here, since that can build them; this is
  // what the record of their last checks says
  const envStates: Record<string, any> =
    status?.pipeline?.environment_states ?? {}
  const running = Boolean(status?.pipeline?.running) || ws.running
  const ahead = statusQuery.data?.commits_ahead ?? 0
  const behind = statusQuery.data?.commits_behind ?? 0
  const dvcToPull = (status?.dvc?.not_in_cache ?? []).length > 0
  const dvcToPush = (status?.dvc?.not_in_remote ?? []).length > 0
  const errors: string[] = (statusQuery.data?.errors ?? []).map(
    (e: any) => e.info,
  )
  // Why the pipeline's status couldn't be worked out, e.g., it doesn't
  // compile, in which case it can't be said to be up to date
  const pipelineErrors: string[] = (status?.pipeline?.errors ?? []).map(
    (e: any) => (typeof e === "string" ? e : JSON.stringify(e)),
  )
  // Say why a stage is stale, as VS Code's sidebar does
  const describeStale = (stage: string) => {
    const d = staleDetail[stage] ?? {}
    const reasons = [
      d.modified_command ? "command changed" : "",
      d.modified_inputs?.length
        ? `inputs changed: ${d.modified_inputs.join(", ")}`
        : "",
      d.modified_outputs?.length
        ? `outputs changed: ${d.modified_outputs.join(", ")}`
        : "",
      d.stale_outputs?.length
        ? `outputs missing or out of date: ${d.stale_outputs.join(", ")}`
        : "",
      d.always_run ? "always runs" : "",
    ].filter(Boolean)
    return reasons.join("; ") || "out of date"
  }
  // Runs without a terminal, followed here through the run's log
  const runMutation = useMutation({
    mutationFn: (stages?: string[]) =>
      request("workspace.run", stages ? { stages } : {}),
    onSuccess: (result) =>
      result.ok
        ? showToast("Success!", "The pipeline ran.", "success")
        : showToast("Error", "The pipeline failed.", "error"),
    onError: (err: Error) => showToast("Error", err.message, "error"),
    onSettled: () => {
      refresh()
      runLogQuery.refetch()
    },
  })
  const stopMutation = useMutation({
    mutationFn: () => request("workspace.stop"),
    onError: (err: Error) => showToast("Error", err.message, "error"),
  })
  // The whole pipeline, or just some stages
  const run = (stages?: string[]) => {
    setRunStartedAt(Date.now())
    runMutation.mutate(stages)
  }
  // The latest run's log, however it was started, followed while it runs
  const runLogQuery = useQuery({
    queryKey: ["workspace-run-log", ws.operator_id, ws.path],
    queryFn: () => request("workspace.run_log"),
    enabled: connected,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: running || runMutation.isPending ? 2000 : false,
  })
  const runLogRef = useRef<HTMLPreElement>(null)
  const runLog: string | null = runLogQuery.data?.log ?? null
  // Logs are named by when the run started, e.g., 2026-10-10T14-02-59-...
  const runLogStarted = (runLogQuery.data?.name ?? "").match(
    /^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})/,
  )
  useEffect(() => {
    // Kept at the end, where a running log grows
    const el = runLogRef.current
    if (el && runLog) el.scrollTop = el.scrollHeight
  }, [runLog])
  // Collapsing is remembered per browser, since it's how someone prefers
  // to see the page rather than anything about the workspace
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(PANEL_COLLAPSED_KEY) === "1"
    } catch {
      return false
    }
  })
  const toggleCollapsed = () => {
    setCollapsed(!collapsed)
    try {
      localStorage.setItem(PANEL_COLLAPSED_KEY, collapsed ? "0" : "1")
    } catch {
      // Without storage it just isn't remembered
    }
  }
  const outOfSync = ahead || behind || dvcToPull || dvcToPush
  const syncSummary = [
    ahead ? `${ahead} to push` : "",
    behind ? `${behind} to pull` : "",
    dvcToPull || dvcToPush ? "data to sync" : "",
  ]
    .filter(Boolean)
    .join(", ")
  const changeCount = untracked.length + changed.length + staged.length
  const ready = connected && !statusQuery.isPending && !statusQuery.error
  const fileRow = (path: string, mark: string, color: string) => (
    <Flex key={`${mark}:${path}`} align="center" gap={2} minH="24px">
      <Text
        as="span"
        fontFamily="mono"
        fontSize="xs"
        fontWeight="bold"
        color={color}
        w="1em"
        flexShrink={0}
      >
        {mark}
      </Text>
      <Text fontFamily="mono" fontSize="sm" noOfLines={1} title={path}>
        {path}
      </Text>
    </Flex>
  )
  return (
    <Box bg={bg} borderRadius="lg" p={3} mb={6}>
      <Flex align="center" gap={2} wrap="wrap">
        <IconButton
          aria-label={collapsed ? "Show details" : "Hide details"}
          icon={collapsed ? <FiChevronRight /> : <FiChevronDown />}
          size="xs"
          variant="ghost"
          onClick={toggleCollapsed}
        />
        <Heading size="sm">{ws.operator_name}</Heading>
        <Tooltip label={ws.path}>
          <Code fontSize="xs" noOfLines={1} maxW="320px">
            {ws.path}
          </Code>
        </Tooltip>
        {ready && (
          <Flex gap={1} wrap="wrap">
            <Tooltip label="Compared with the project's remotes">
              <Badge colorScheme={outOfSync ? "yellow" : "green"}>
                {outOfSync ? syncSummary : "in sync"}
              </Badge>
            </Tooltip>
            <Badge colorScheme={changeCount ? "yellow" : "green"}>
              {changeCount ? `${changeCount} uncommitted` : "nothing to commit"}
            </Badge>
            <Badge
              colorScheme={
                running
                  ? "blue"
                  : pipelineErrors.length
                    ? "red"
                    : staleStages.length
                      ? "yellow"
                      : "green"
              }
            >
              {running
                ? "pipeline running"
                : pipelineErrors.length
                  ? "pipeline error"
                  : staleStages.length
                    ? `${staleStages.length} stage${staleStages.length === 1 ? "" : "s"} out of date`
                    : "pipeline up to date"}
            </Badge>
          </Flex>
        )}
        <IconButton
          aria-label="Refresh status"
          icon={<FiRefreshCw />}
          size="xs"
          variant="ghost"
          ml="auto"
          onClick={refresh}
          isLoading={statusQuery.isFetching}
          isDisabled={!connected}
        />
      </Flex>
      {confirmRun && editable && (
        <Alert status="info" borderRadius="md" mt={3} gap={2}>
          <AlertIcon />
          <Text flex={1}>
            Run{" "}
            {confirmRun === "*" ? (
              "the pipeline"
            ) : (
              <Code fontSize="xs">{confirmRun}</Code>
            )}{" "}
            on {ws.operator_name}?
          </Text>
          <Button
            size="xs"
            variant="primary"
            isDisabled={!connected}
            onClick={() => {
              run(confirmRun === "*" ? undefined : [confirmRun])
              clearConfirmRun()
            }}
          >
            Run
          </Button>
          <Button size="xs" onClick={clearConfirmRun}>
            Cancel
          </Button>
        </Alert>
      )}
      {collapsed ? null : !connected ? (
        <Text mt={3} color="ui.dim">
          Waiting for the Operator to connect.
        </Text>
      ) : statusQuery.isPending ? (
        <LoadingSpinner />
      ) : statusQuery.error ? (
        <Alert status="error" borderRadius="md" mt={3}>
          <AlertIcon />
          {statusQuery.error.message}
        </Alert>
      ) : (
        <>
          <SimpleGrid
            // Stacked above the sessions on smaller screens, beside them on
            // larger ones
            columns={narrow ? { base: 1, lg: 2, xl: 1 } : { base: 1, lg: 2 }}
            spacing={3}
            mt={3}
          >
            <PanelSection
              title="Sync"
              actions={
                editable && (
                  <>
                    <Button
                      size="xs"
                      onClick={() => syncMutation.mutate("pull")}
                      isLoading={
                        syncMutation.isPending &&
                        syncMutation.variables === "pull"
                      }
                    >
                      Pull
                    </Button>
                    <Button
                      size="xs"
                      onClick={() => syncMutation.mutate("push")}
                      isLoading={
                        syncMutation.isPending &&
                        syncMutation.variables === "push"
                      }
                    >
                      Push
                    </Button>
                  </>
                )
              }
            >
              {outOfSync ? (
                [
                  ahead ? `${ahead} commits to push` : "",
                  behind ? `${behind} commits to pull` : "",
                  dvcToPull ? "Data to pull" : "",
                  dvcToPush ? "Data to push" : "",
                ]
                  .filter(Boolean)
                  .map((line) => (
                    <Text key={line} fontSize="sm">
                      {line}
                    </Text>
                  ))
              ) : (
                <Text fontSize="sm" color="ui.dim">
                  In sync with the remotes
                </Text>
              )}
            </PanelSection>
            <PanelSection
              title="Changes"
              actions={
                editable &&
                (changed.length > 0 || staged.length > 0) && (
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
                )
              }
            >
              {changeCount === 0 && (
                <Text fontSize="sm" color="ui.dim">
                  No uncommitted changes
                </Text>
              )}
              <Box maxH="220px" overflowY="auto">
                {staged.map((path) => fileRow(path, "A", "green.400"))}
                {changed.map((path) => fileRow(path, "M", "yellow.500"))}
                {untracked.map((path) => (
                  <Flex key={`?:${path}`} align="center" gap={1}>
                    <Box flex={1} minW={0}>
                      {fileRow(path, "?", "ui.dim")}
                    </Box>
                    {editable && (
                      <>
                        <AddPath
                          path={path}
                          request={request}
                          onDone={refresh}
                        />
                        <IgnorePath
                          path={path}
                          request={request}
                          onDone={refresh}
                        />
                      </>
                    )}
                  </Flex>
                ))}
              </Box>
            </PanelSection>
            <PanelSection
              title="Pipeline"
              actions={
                editable && (
                  <>
                    <Button
                      size="xs"
                      variant="primary"
                      isLoading={runMutation.isPending}
                      isDisabled={running}
                      onClick={() => run()}
                    >
                      Run
                    </Button>
                    <Button
                      size="xs"
                      leftIcon={<FiPlus />}
                      onClick={() => setModal("new_stage")}
                    >
                      New stage
                    </Button>
                  </>
                )
              }
            >
              {pipelineErrors.map((e) => (
                <Text key={e} fontSize="sm" color="red.400" mb={1}>
                  {e}
                </Text>
              ))}
              {!running &&
                staleStages.length === 0 &&
                pipelineErrors.length === 0 && (
                  <Text fontSize="sm" color="ui.dim">
                    Up to date
                  </Text>
                )}
              <Flex gap={1} wrap="wrap">
                {runningStages.map((stage) => (
                  <Tag key={stage} size="sm" colorScheme="blue">
                    <TagLabel>{stage}</TagLabel>
                    <Spinner size="xs" ml={1} />
                  </Tag>
                ))}
                {staleStages
                  .filter((stage) => !runningStages.includes(stage))
                  .map((stage) => (
                    <Tag key={stage} size="sm" colorScheme="yellow">
                      <Tooltip label={describeStale(stage)}>
                        <TagLabel>{stage}</TagLabel>
                      </Tooltip>
                      {editable && (
                        <Tooltip label={`Run ${stage}`}>
                          <IconButton
                            aria-label={`Run ${stage}`}
                            icon={<FiPlay />}
                            size="xs"
                            variant="ghost"
                            minW="18px"
                            h="18px"
                            ml={1}
                            isDisabled={running}
                            onClick={() => run([stage])}
                          />
                        </Tooltip>
                      )}
                    </Tag>
                  ))}
              </Flex>
            </PanelSection>
            {Object.keys(envStates).length > 0 && (
              <PanelSection title="Environments">
                {Object.entries(envStates).map(([name, state]) => (
                  <Flex key={name} align="center" gap={2} minH="24px">
                    <Code fontSize="xs">{name}</Code>
                    {state.checked_at === null ? (
                      <Badge fontSize="2xs">never checked</Badge>
                    ) : !state.success ? (
                      <Badge colorScheme="red" fontSize="2xs">
                        last check failed
                      </Badge>
                    ) : state.changed ? (
                      <Badge colorScheme="yellow" fontSize="2xs">
                        changed since last check
                      </Badge>
                    ) : (
                      <Text fontSize="xs" color="ui.dim">
                        checked{" "}
                        {new Date(`${state.checked_at}Z`).toLocaleString()}
                      </Text>
                    )}
                  </Flex>
                ))}
              </PanelSection>
            )}
          </SimpleGrid>
          {(runLog || running || runMutation.isPending) && (
            <Box mt={3}>
              <PanelSection
                title={
                  running || runMutation.isPending
                    ? "Run in progress"
                    : runLogStarted
                      ? `Last run, ${new Date(
                          `${runLogStarted[1]}T${runLogStarted[2]}:${runLogStarted[3]}:${runLogStarted[4]}Z`,
                        ).toLocaleString()}`
                      : "Last run"
                }
                actions={
                  editable &&
                  (running || runMutation.isPending) && (
                    <Button
                      size="xs"
                      variant="danger"
                      isLoading={stopMutation.isPending}
                      onClick={() => stopMutation.mutate()}
                    >
                      Stop
                    </Button>
                  )
                }
              >
                <Box
                  as="pre"
                  ref={runLogRef}
                  fontSize="xs"
                  p={2}
                  maxH="320px"
                  overflowY="auto"
                  bg="black"
                  color="white"
                  borderRadius="md"
                  whiteSpace="pre-wrap"
                >
                  {/* A run that failed before it logged anything, e.g.,
                      because the pipeline doesn't compile, says why in its
                      output instead */}
                  {runMutation.data && !runMutation.data.ok && !running
                    ? runMutation.data.output
                    : runLog ?? "Starting"}
                </Box>
              </PanelSection>
            </Box>
          )}
          {errors.length > 0 && (
            <Alert status="error" borderRadius="md" mt={3} alignItems="start">
              <AlertIcon />
              <Box>
                {errors.map((e) => (
                  <Text key={e} fontSize="sm">
                    {e}
                  </Text>
                ))}
              </Box>
            </Alert>
          )}
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
  const connections = useRef(new Map<string, OperatorConnection>())
  const [, setVersion] = useState(0)
  const rerender = useCallback(() => setVersion((v) => v + 1), [])
  const [sessions, setSessions] = useState<Record<string, SessionInfo[]>>({})
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
  const [code, setCode] = useState("")
  const secondFactorError = [...connections.current.values()].find(
    (c) => c.error,
  )?.error
  const verifyMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserTotpVerify({ totpCode: { code } }).then(
        (r) => r.data,
      ),
    onSuccess: (data) => {
      storeSecondFactorToken(data.second_factor_token)
      setCode("")
      for (const conn of connections.current.values()) {
        if (conn.error) conn.retryNow()
      }
    },
    onError: (e: any) =>
      showToast("Error", e.response?.data?.detail ?? e.message, "error"),
  })
  if (workspacesQuery.isPending) return <LoadingSpinner />
  return (
    <Box p={4} maxH="100%" overflowY="auto" w="100%">
      <Heading size="md" mb={3}>
        Workspaces
      </Heading>
      {secondFactorError === SECOND_FACTOR_SETUP_REQUIRED && (
        <Alert status="warning" borderRadius="md" mb={4}>
          <AlertIcon />
          <Text>
            Opening sessions and running things on your machines takes
            two-factor authentication.{" "}
            <RouterLink to="/settings" search={{ tab: "operators" }}>
              <Text as="span" color="ui.main" textDecoration="underline">
                Set it up
              </Text>
            </RouterLink>{" "}
            in your settings first.
          </Text>
        </Alert>
      )}
      {secondFactorError === SECOND_FACTOR_REQUIRED && (
        <Alert
          status="warning"
          borderRadius="md"
          mb={4}
          gap={2}
          flexWrap="wrap"
        >
          <AlertIcon />
          <Text>
            Opening sessions and running things on your machines takes a code
            from your authenticator app.
          </Text>
          <Input
            size="sm"
            maxW="140px"
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && code.length >= 6) verifyMutation.mutate()
            }}
            inputMode="numeric"
            autoComplete="one-time-code"
          />
          <Button
            size="sm"
            variant="primary"
            isDisabled={code.length < 6}
            isLoading={verifyMutation.isPending}
            onClick={() => verifyMutation.mutate()}
          >
            Verify
          </Button>
        </Alert>
      )}
      {workspaces.length === 0 ? (
        <Text mb={4}>
          None of your Operators has a workspace for this project. Install one
          with <Code>calkit operator install</Code> on a machine with this
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
                    {ws.running ? (
                      <Tooltip
                        label={
                          ws.running_since
                            ? `Since ${new Date(ws.running_since).toLocaleString()}`
                            : "Pipeline running"
                        }
                      >
                        <Badge ml={2} colorScheme="blue" fontSize="2xs">
                          running
                          {ws.running_stages?.length
                            ? ` ${ws.running_stages.join(", ")}`
                            : ""}
                        </Badge>
                      </Tooltip>
                    ) : ws.last_run ? (
                      <Tooltip
                        label={`Last run ${ws.last_run.status}${
                          ws.last_run.ended
                            ? ` ${new Date(ws.last_run.ended).toLocaleString()}`
                            : ""
                        }`}
                      >
                        <Badge
                          ml={2}
                          colorScheme={
                            ws.last_run.status === "failed" ? "red" : "green"
                          }
                          fontSize="2xs"
                        >
                          {ws.last_run.status === "failed"
                            ? `failed${
                                ws.last_run.failed_stages?.length
                                  ? ` at ${ws.last_run.failed_stages.join(", ")}`
                                  : ""
                              }`
                            : "last run ok"}
                        </Badge>
                      </Tooltip>
                    ) : null}
                    {ws.in_use_by && (
                      <Tooltip
                        label={`The Operator for ${ws.in_use_by} on this machine is using it, so this one can't until it's done`}
                      >
                        <Badge ml={2} colorScheme="orange" fontSize="2xs">
                          in use from {ws.in_use_by.replace(/^https?:\/\//, "")}
                        </Badge>
                      </Tooltip>
                    )}
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
