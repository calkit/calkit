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
  SimpleGrid,
  Spinner,
  Tag,
  TagLabel,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react"
import {
  FiChevronDown,
  FiChevronRight,
  FiCpu,
  FiPlay,
  FiPlus,
  FiRefreshCw,
  FiTerminal,
} from "react-icons/fi"

import type { AgentInfo, Workspace } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import LoadingSpinner from "../Common/LoadingSpinner"
import Tooltip from "../Common/Tooltip"
import type { OperatorConnection, SessionInfo } from "../Operators/connection"
import AddPath from "./AddPath"
import DiscardChanges from "./DiscardChanges"
import IgnorePath from "./IgnorePath"
import NewStage from "./NewStage"
import NewWorkspace from "./NewWorkspace"
import SaveFiles from "./SaveFiles"

export type Modal = "save" | "discard" | "new_stage" | "new_workspace"

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

export default function WorkspacePanel({
  ws,
  conn,
  connected,
  modal,
  setModal,
  onChanged,
  confirmRun,
  clearConfirmRun,
  narrow,
  sessions,
  activeSession,
  onOpenSession,
  onNewSession,
  activeAgent,
  onViewAgent,
  onAttachAgent,
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
  // The workspace's sessions, listed here when given
  sessions?: SessionInfo[]
  activeSession?: string
  onOpenSession?: (session: string) => void
  onNewSession?: () => void
  // Following an agent running there outside the Operator's sessions, or
  // attaching to one in tmux
  activeAgent?: number
  onViewAgent?: (pid: number) => void
  onAttachAgent?: (pid: number) => void
}) {
  const showToast = useCustomToast()
  const bg = useColorModeValue("ui.secondary", "ui.darkSlate")
  const hoverBg = useColorModeValue("gray.100", "whiteAlpha.100")
  const editable = ws.kind === "personal"
  const request = useCallback(
    (type: string, fields: object = {}) =>
      conn.request(type, { workspace: ws.path, ...fields }),
    [conn, ws.path],
  )
  // When a run was started from here, which may take a moment to show up
  const [runStartedAt, setRunStartedAt] = useState(0)
  // Git's part comes quickly, so it's shown while the rest, which can take
  // a while for a large pipeline, is worked out; it fetches, so the rest
  // needn't
  const gitQuery = useQuery({
    queryKey: ["workspace-git-status", ws.operator_id, ws.path],
    queryFn: () => request("workspace.git_status", { fetch: true }),
    enabled: connected,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const statusQuery = useQuery({
    queryKey: ["workspace-status", ws.operator_id, ws.path],
    queryFn: () => request("workspace.status", { fetch: false }),
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
    gitQuery.refetch()
    statusQuery.refetch()
    onChanged()
  }
  // Set when a pull can't fast-forward, so merging can be offered
  const [diverged, setDiverged] = useState(false)
  const syncMutation = useMutation({
    mutationFn: (kind: "pull" | "merge" | "push") =>
      kind === "push"
        ? request("workspace.push")
        : request("workspace.pull", { merge: kind === "merge" }),
    onSuccess: (result, kind) => {
      setDiverged(Boolean(result?.diverged))
      if (!result?.diverged) {
        showToast(
          "Success!",
          kind === "push"
            ? "Pushed."
            : kind === "merge"
              ? "Merged."
              : "Pulled.",
          "success",
        )
      }
    },
    onError: (err: Error) => showToast("Error", err.message, "error"),
    onSettled: refresh,
  })
  // What `calkit status --json` reports, the same as VS Code shows
  const status = statusQuery.data?.status
  const git = gitQuery.data?.git ?? status?.git
  const untracked: string[] = git?.untracked_files ?? []
  // DVC calls a path committed when its DVC file is staged
  const changed: string[] = (git?.changed_files ?? []).concat(
    status?.dvc?.uncommitted?.modified ?? [],
  )
  const staged: string[] = (git?.staged_files ?? []).concat(
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
  const ahead =
    gitQuery.data?.commits_ahead ?? statusQuery.data?.commits_ahead ?? 0
  const behind =
    gitQuery.data?.commits_behind ?? statusQuery.data?.commits_behind ?? 0
  const dvcToPull = (status?.dvc?.not_in_cache ?? []).length > 0
  const dvcToPush = (status?.dvc?.not_in_remote ?? []).length > 0
  const errors: string[] = [
    ...(gitQuery.data?.errors ?? []),
    ...(statusQuery.data?.errors ?? []),
  ].map((e: any) => e.info)
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
  // Ones in the Operator's sessions are listed as those
  const agents: AgentInfo[] = (ws.agents ?? []).filter(
    (a) => a.where !== "session",
  )
  // An Operator from before Git's part came on its own only has the rest
  const gitReady = connected && Boolean(gitQuery.data || statusQuery.data)
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
        <Flex gap={1} wrap="wrap">
          {gitReady && (
            <>
              <Tooltip label="Compared with the project's remotes">
                <Badge colorScheme={outOfSync ? "yellow" : "green"}>
                  {outOfSync ? syncSummary : "in sync"}
                </Badge>
              </Tooltip>
              <Badge colorScheme={changeCount ? "yellow" : "green"}>
                {changeCount
                  ? `${changeCount} uncommitted`
                  : "nothing to commit"}
              </Badge>
            </>
          )}
          {ready && (
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
          )}
        </Flex>
        {editable && (
          <Tooltip label="Another workspace for this project, on a branch">
            <Button
              size="xs"
              variant="ghost"
              leftIcon={<FiPlus />}
              ml="auto"
              isDisabled={!connected}
              onClick={() => setModal("new_workspace")}
            >
              Workspace
            </Button>
          </Tooltip>
        )}
        <IconButton
          aria-label="Refresh status"
          icon={<FiRefreshCw />}
          size="xs"
          variant="ghost"
          ml={editable ? undefined : "auto"}
          onClick={refresh}
          isLoading={gitQuery.isFetching || statusQuery.isFetching}
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
      ) : !gitReady && (gitQuery.isPending || statusQuery.isPending) ? (
        <LoadingSpinner />
      ) : !gitReady ? (
        <Alert status="error" borderRadius="md" mt={3}>
          <AlertIcon />
          {(statusQuery.error ?? gitQuery.error)?.message}
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
                        syncMutation.variables !== "push"
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
              {diverged && (
                <Alert status="warning" borderRadius="md" mb={2} gap={2}>
                  <AlertIcon />
                  {/* TODO: copy for a human to write */}
                  <Text flex={1} fontSize="sm">
                    This branch and its remote have diverged.
                  </Text>
                  <Button
                    size="xs"
                    isLoading={
                      syncMutation.isPending &&
                      syncMutation.variables === "merge"
                    }
                    onClick={() => syncMutation.mutate("merge")}
                  >
                    Merge
                  </Button>
                </Alert>
              )}
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
              {statusQuery.isPending && <Spinner size="sm" color="ui.dim" />}
              {statusQuery.error && (
                <Text fontSize="sm" color="red.400">
                  {statusQuery.error.message}
                </Text>
              )}
              {pipelineErrors.map((e) => (
                <Text key={e} fontSize="sm" color="red.400" mb={1}>
                  {e}
                </Text>
              ))}
              {ready &&
                !running &&
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
            {sessions && (
              <PanelSection
                title={`Sessions (${sessions.length + agents.length})`}
                actions={
                  onNewSession && (
                    <Button
                      size="xs"
                      leftIcon={<FiPlus />}
                      onClick={onNewSession}
                    >
                      New
                    </Button>
                  )
                }
              >
                {sessions.length + agents.length === 0 && (
                  <Text fontSize="sm" color="ui.dim">
                    No sessions
                  </Text>
                )}
                {sessions.map((session) => (
                  <Flex
                    key={session.id}
                    align="center"
                    gap={2}
                    minH="24px"
                    px={1}
                    borderRadius="md"
                    cursor="pointer"
                    fontWeight={
                      session.id === activeSession ? "semibold" : undefined
                    }
                    _hover={{ bg: hoverBg }}
                    onClick={() => onOpenSession?.(session.id)}
                  >
                    <FiTerminal />
                    <Text fontSize="sm" fontFamily="mono" noOfLines={1}>
                      {session.label}
                    </Text>
                    {session.attached > 0 && (
                      <Tooltip label="Browsers attached">
                        <Badge fontSize="2xs">{session.attached}</Badge>
                      </Tooltip>
                    )}
                  </Flex>
                ))}
                {agents.map((agent) => (
                  <Flex
                    key={agent.pid}
                    align="center"
                    gap={2}
                    minH="24px"
                    px={1}
                    borderRadius="md"
                    cursor="pointer"
                    fontWeight={
                      agent.pid === activeAgent ? "semibold" : undefined
                    }
                    _hover={{ bg: hoverBg }}
                    onClick={() => onViewAgent?.(agent.pid)}
                  >
                    <FiCpu />
                    <Text fontSize="sm" fontFamily="mono" flexShrink={0}>
                      {agent.tool}
                    </Text>
                    {agent.name && (
                      <Text fontSize="sm" noOfLines={1}>
                        {agent.name}
                      </Text>
                    )}
                    <Text fontSize="xs" color="ui.dim" flexShrink={0}>
                      {agent.where === "tmux"
                        ? "in tmux"
                        : agent.app
                          ? `in ${agent.app}`
                          : ""}
                    </Text>
                    {agent.status && (
                      <Badge fontSize="2xs">{agent.status}</Badge>
                    )}
                    {agent.where === "tmux" && onAttachAgent && (
                      <Button
                        size="xs"
                        ml="auto"
                        onClick={(e) => {
                          e.stopPropagation()
                          onAttachAgent(agent.pid)
                        }}
                      >
                        Attach
                      </Button>
                    )}
                  </Flex>
                ))}
              </PanelSection>
            )}
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
          <NewWorkspace
            isOpen={modal === "new_workspace"}
            onClose={() => setModal(undefined)}
            request={request}
            onDone={onChanged}
          />
        </>
      )}
    </Box>
  )
}
