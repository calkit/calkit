import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import {
  Code,
  Box,
  Text,
  Heading,
  Button,
  Flex,
  Icon,
  Link,
  IconButton,
  ListItem,
  UnorderedList,
  Badge,
  useDisclosure,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import axios from "axios"
import { FiExternalLink } from "react-icons/fi"
import { FaCheck, FaPlus, FaSync } from "react-icons/fa"
import mixpanel from "mixpanel-browser"

import { type ProjectPublic } from "../../../../../client"
import NewStage from "../../../../../components/Local/NewStage"
import AddPath from "../../../../../components/Local/AddPath"
import IgnorePath from "../../../../../components/Local/IgnorePath"
import useCustomToast from "../../../../../hooks/useCustomToast"
import SaveFiles from "../../../../../components/Local/SaveFiles"
import DiscardChanges from "../../../../../components/Local/DiscardChanges"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/local",
)({
  component: LocalServer,
})

function LocalServer() {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const queryClient = useQueryClient()
  const { accountName, projectName } = Route.useParams()
  const project = queryClient.getQueryData<ProjectPublic>([
    "projects",
    accountName,
    projectName,
  ])
  const localServerRunningQuery = useQuery({
    queryKey: ["local-server-main"],
    queryFn: () => axios.get("http://localhost:8866/health"),
    retry: false,
  })
  const localServerRunning = localServerRunningQuery.data?.data === "All good!"
  const localServerQuery = useQuery({
    queryKey: ["local-server-main", accountName, projectName],
    queryFn: () =>
      axios.get(`http://localhost:8866/projects/${accountName}/${projectName}`),
    retry: 2,
  })
  const jupyterServerQuery = useQuery({
    queryKey: ["jupyter-server", accountName, projectName],
    queryFn: () =>
      axios.get(
        `http://localhost:8866/projects/${accountName}/${projectName}/jupyter-server`,
      ),
    retry: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  })
  const openVSCode = () => {
    axios.post(
      `http://localhost:8866/projects/${accountName}/${projectName}/open/vscode`,
    )
  }
  const openFolder = () => {
    axios.post(
      `http://localhost:8866/projects/${accountName}/${projectName}/open/folder`,
    )
  }
  const jupyterServerMutation = useMutation({
    mutationFn: () => {
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/jupyter-server`
      if (!jupyterServerQuery.data?.data?.url) {
        return axios.get(url, { params: { autostart: true, no_browser: true } })
      }
      return axios.delete(url)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server", accountName, projectName],
      })
      queryClient.invalidateQueries({
        queryKey: ["jupyter-server", accountName, projectName],
      })
      jupyterServerQuery.refetch()
      queryClient.refetchQueries({
        queryKey: ["local-server", accountName, projectName],
      })
    },
  })
  const localWorkingDir = localServerQuery.data?.data?.wdir
  const statusQuery = useQuery({
    queryKey: ["local-server-main", accountName, projectName, "status"],
    queryFn: () =>
      axios.get(
        `http://localhost:8866/projects/${accountName}/${projectName}/status`,
      ),
    retry: 2,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  })
  const commitsAhead = statusQuery.data?.data?.git?.commits_ahead
  const commitsBehind = statusQuery.data?.data?.git?.commits_behind
  const untrackedFiles = statusQuery.data?.data?.git?.untracked ?? []
  const gitChangedFiles = statusQuery.data?.data?.git?.changed ?? []
  const dvcChangedFiles = statusQuery.data?.data?.dvc?.data?.changed ?? []
  const changedFiles = gitChangedFiles.concat(dvcChangedFiles)
  const gitStagedFiles = statusQuery.data?.data?.git?.staged ?? []
  const dvcStagedFiles = statusQuery.data?.data?.dvc?.data?.staged ?? []
  const stagedFiles = gitStagedFiles.concat(dvcStagedFiles)
  const pipelineUpToDate =
    JSON.stringify(statusQuery.data?.data?.dvc?.pipeline) === "{}"
  const stagesOutOfDate = Object.keys(
    Object(statusQuery.data?.data?.dvc?.pipeline),
  )
  const dvcNeedsPull =
    statusQuery.data?.data?.dvc?.data?.not_in_cache?.length > 0
  const dvcNeedsPush =
    statusQuery.data?.data?.dvc?.data?.not_in_remote?.length > 0
  const gitPushMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked git push on local machine page")
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/git/push`
      return axios.post(url)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
    },
  })
  const gitPullMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked git pull on local machine page")
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/git/pull`
      return axios.post(url)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
    },
  })
  const dvcPushMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked DVC push on local machine page")
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/dvc/push`
      return axios.post(url)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
    },
  })
  const dvcPullMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked DVC pull on local machine page")
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/dvc/pull`
      return axios.post(url)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
    },
  })
  const showToast = useCustomToast()
  const runPipelineMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked run pipeline on local machine page")
      const url = `http://localhost:8866/projects/${accountName}/${projectName}/pipeline/runs`
      return axios.post(url)
    },
    onError: (err: any) => {
      showToast("Error", String(err.response.data.detail), "error")
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
    },
  })
  const pipelineQuery = useQuery({
    queryKey: ["local-server-main", accountName, projectName, "pipeline"],
    queryFn: () =>
      axios.get(
        `http://localhost:8866/projects/${accountName}/${projectName}/pipeline`,
      ),
    retry: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  })
  const cloneMutation = useMutation({
    mutationFn: () => {
      mixpanel.track("Clicked clone on local machine page")
      const url = "http://localhost:8866/calkit/clone"
      const data = { git_repo_url: project?.git_repo_url }
      return axios.post(url, data)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "status"],
      })
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName, "pipeline"],
      })
      queryClient.invalidateQueries({
        queryKey: ["local-server", accountName, projectName],
      })
      queryClient.invalidateQueries({
        queryKey: ["local-server-main", accountName, projectName],
      })
    },
  })
  const newStageModal = useDisclosure()
  const saveFilesModal = useDisclosure()
  const discardAlertDialog = useDisclosure()

  return (
    <>
      <Box mr={4}>
        <Heading size="md" mb={1}>
          Local machine
        </Heading>
        {localServerQuery.isPending ? (
          <LoadingSpinner height="100vh" />
        ) : (
          <Flex>
            {localServerRunning ? (
              <Box mr={12} width="60%">
                <Text>The local server is running.</Text>
                {/* Actions that are only possible if repo has been cloned */}
                {localWorkingDir ? (
                  <>
                    <Box bg={secBgColor} p={4} borderRadius="lg" mt={4}>
                      <Heading size="md" mb={2}>
                        Actions
                      </Heading>
                      <Button m={2} variant="primary" onClick={openVSCode}>
                        Open in VSCode <Icon ml={1} as={FiExternalLink} />
                      </Button>
                      <Button
                        m={2}
                        variant="primary"
                        onClick={() => jupyterServerMutation.mutate()}
                        isLoading={
                          jupyterServerQuery.isPending ||
                          jupyterServerMutation.isPending ||
                          jupyterServerQuery.isRefetching
                        }
                      >
                        {!jupyterServerQuery.data?.data?.url
                          ? "Start Jupyter server"
                          : "Stop Jupyter server"}
                      </Button>
                      {jupyterServerQuery.data?.data?.url ? (
                        <Link
                          isExternal
                          href={jupyterServerQuery.data?.data.url}
                        >
                          <Button variant="primary" m={2}>
                            Open JupyterLab <Icon ml={1} as={FiExternalLink} />
                          </Button>
                        </Link>
                      ) : (
                        ""
                      )}
                    </Box>
                  </>
                ) : (
                  ""
                )}
              </Box>
            ) : (
              <Box>
                <Text>
                  Local server not connected. To connect your local machine, run{" "}
                  <Code>calkit local-server</Code> in a terminal.
                </Text>
              </Box>
            )}
            {/* Right hand side status box */}
            {localServerRunning ? (
              <>
                <Box
                  borderRadius="lg"
                  width="40%"
                  p={4}
                  height="75vh"
                  bg={secBgColor}
                >
                  <Flex>
                    <Heading size="md" mb={2} mr={1}>
                      Status
                    </Heading>
                    <IconButton
                      aria-label="refresh"
                      height="25px"
                      icon={<FaSync />}
                      onClick={() => {
                        statusQuery.refetch()
                        pipelineQuery.refetch()
                      }}
                      isLoading={statusQuery.isRefetching}
                    />
                  </Flex>
                  {statusQuery.isPending ||
                  statusQuery.isRefetching ||
                  pipelineQuery.isPending ||
                  pipelineQuery.isRefetching ? (
                    <LoadingSpinner />
                  ) : (
                    <>
                      {localWorkingDir ? (
                        <Text>
                          The repo is cloned locally in{" "}
                          <Link onClick={openFolder}>{localWorkingDir}</Link>.
                        </Text>
                      ) : (
                        <Flex alignItems="center">
                          <Text>
                            The repo has not yet been cloned to this machine.
                          </Text>
                          <Button
                            ml={1}
                            size="xs"
                            variant="primary"
                            onClick={() => cloneMutation.mutate()}
                            isLoading={cloneMutation.isPending}
                          >
                            Clone
                          </Button>
                        </Flex>
                      )}
                      {!statusQuery.isPending && !statusQuery.error ? (
                        <>
                          <Heading size="sm" mb={1} mt={4}>
                            Cloud sync
                          </Heading>
                          {commitsAhead ? (
                            <Flex alignItems="center">
                              <Text mr={1} color="yellow.500">
                                There are {commitsAhead} commits to push to Git
                                remote.
                              </Text>
                              <Button
                                variant="primary"
                                size="xs"
                                aria-label="push"
                                onClick={() => gitPushMutation.mutate()}
                                isLoading={gitPushMutation.isPending}
                              >
                                Push
                              </Button>
                            </Flex>
                          ) : (
                            ""
                          )}
                          {commitsBehind ? (
                            <Flex alignItems="center">
                              <Text mr={1} color="yellow.500">
                                There are {commitsBehind} commits to pull from
                                Git remote.
                              </Text>
                              <Button
                                variant="primary"
                                size="xs"
                                aria-label="pull"
                                onClick={() => gitPullMutation.mutate()}
                                isLoading={gitPullMutation.isPending}
                              >
                                Pull
                              </Button>
                            </Flex>
                          ) : (
                            ""
                          )}
                          {commitsAhead === 0 && commitsBehind === 0 ? (
                            <Text>
                              Repo is synced with Git remote
                              <Icon
                                ml={0.5}
                                height="13px"
                                color="green.500"
                                as={FaCheck}
                              />
                            </Text>
                          ) : (
                            ""
                          )}
                          {dvcNeedsPull ? (
                            <Flex alignItems="center" mt={1}>
                              <Text color="yellow.500" mr={1}>
                                There are changes to pull from DVC remote.
                              </Text>
                              <Button
                                variant="primary"
                                size="xs"
                                aria-label="dvc-pull"
                                onClick={() => dvcPullMutation.mutate()}
                                isLoading={dvcPullMutation.isPending}
                              >
                                Pull
                              </Button>
                            </Flex>
                          ) : (
                            ""
                          )}
                          {dvcNeedsPush ? (
                            <Flex alignItems="center" mt={1}>
                              <Text color="yellow.500" mr={1}>
                                There are changes to push to DVC remote.
                              </Text>
                              <Button
                                variant="primary"
                                size="xs"
                                aria-label="dvc-push"
                                onClick={() => dvcPushMutation.mutate()}
                                isLoading={dvcPushMutation.isPending}
                              >
                                Push
                              </Button>
                            </Flex>
                          ) : (
                            ""
                          )}
                          {!dvcNeedsPull && !dvcNeedsPush ? (
                            <Text>
                              Repo is synced with DVC remote
                              <Icon
                                ml={0.5}
                                height="13px"
                                color="green.500"
                                as={FaCheck}
                              />
                            </Text>
                          ) : (
                            ""
                          )}
                        </>
                      ) : (
                        ""
                      )}
                      {/* Untracked files */}
                      {untrackedFiles && untrackedFiles.length > 0 ? (
                        <>
                          <Heading size="sm" mb={1} mt={4}>
                            Untracked files
                          </Heading>
                          {untrackedFiles.map((fpath: string) => (
                            <Flex key={fpath} alignItems="center" mb={1}>
                              <Text color="red.500" mr={1}>
                                {fpath}
                              </Text>
                              <AddPath path={fpath} />
                              <IgnorePath path={fpath} />
                            </Flex>
                          ))}
                        </>
                      ) : (
                        ""
                      )}
                      {/* Changed files */}
                      {localWorkingDir ? (
                        <>
                          <Flex alignItems="center" mb={1} mt={4}>
                            <Heading size="sm">Uncommitted changes</Heading>
                            {(stagedFiles && stagedFiles.length > 0) ||
                            (changedFiles && changedFiles.length > 0) ? (
                              <>
                                <Button
                                  size="xs"
                                  variant="primary"
                                  ml={1}
                                  onClick={saveFilesModal.onOpen}
                                >
                                  Commit
                                </Button>
                                <SaveFiles
                                  isOpen={saveFilesModal.isOpen}
                                  onClose={saveFilesModal.onClose}
                                  changedFiles={changedFiles}
                                  stagedFiles={stagedFiles}
                                />
                                <Button
                                  size="xs"
                                  variant="danger"
                                  ml={1}
                                  onClick={discardAlertDialog.onOpen}
                                >
                                  Discard
                                </Button>
                                <DiscardChanges
                                  onClose={discardAlertDialog.onClose}
                                  isOpen={discardAlertDialog.isOpen}
                                />
                              </>
                            ) : (
                              ""
                            )}
                          </Flex>
                          {stagedFiles ? (
                            <>
                              {stagedFiles.map((fpath: string) => (
                                <Flex key={fpath} alignItems="center">
                                  <Text color="green.500" mr={1}>
                                    {fpath}
                                  </Text>
                                </Flex>
                              ))}
                            </>
                          ) : (
                            ""
                          )}
                          {changedFiles ? (
                            <>
                              {changedFiles.map((fpath: string) => (
                                <Flex key={fpath} alignItems="center">
                                  <Text color="red.500" mr={1}>
                                    {fpath}
                                  </Text>
                                </Flex>
                              ))}
                            </>
                          ) : (
                            ""
                          )}
                          {stagedFiles.length === 0 &&
                          changedFiles.length === 0 ? (
                            <Text>
                              Repo is clean
                              <Icon
                                ml={0.5}
                                height="13px"
                                color="green.500"
                                as={FaCheck}
                              />
                            </Text>
                          ) : (
                            ""
                          )}
                          {/* Pipeline section of status */}
                          <Flex mb={1} mt={4} alignItems="center">
                            <Heading size="sm" mr={1}>
                              Pipeline
                            </Heading>
                            {!pipelineUpToDate ? (
                              <Flex alignItems="center">
                                <Badge mr={1} color="yellow.500">
                                  Out-of-date
                                </Badge>
                                <Button
                                  size="xs"
                                  variant="primary"
                                  onClick={() => runPipelineMutation.mutate()}
                                  isLoading={runPipelineMutation.isPending}
                                >
                                  Run
                                </Button>
                              </Flex>
                            ) : (
                              <Badge color="green.500">Up-to-date</Badge>
                            )}
                            <Button
                              ml={1}
                              variant="primary"
                              size="xs"
                              onClick={newStageModal.onOpen}
                            >
                              <Icon mr={0.5} as={FaPlus} /> New stage
                            </Button>
                            <NewStage
                              isOpen={newStageModal.isOpen}
                              onClose={newStageModal.onClose}
                            />
                          </Flex>
                          {!pipelineQuery.error && pipelineQuery.data?.data ? (
                            <>
                              <Heading size="xs">Stages</Heading>
                              <UnorderedList>
                                {Object.entries(
                                  pipelineQuery.data.data.stages,
                                ).map(([k, _]) => (
                                  <ListItem key={k}>
                                    <Code
                                      fontSize="small"
                                      color={
                                        stagesOutOfDate.includes(k)
                                          ? "yellow.500"
                                          : ""
                                      }
                                    >
                                      {k}
                                    </Code>
                                  </ListItem>
                                ))}
                              </UnorderedList>
                            </>
                          ) : (
                            ""
                          )}
                        </>
                      ) : (
                        ""
                      )}
                    </>
                  )}
                </Box>
              </>
            ) : (
              ""
            )}
          </Flex>
        )}
      </Box>
    </>
  )
}
