import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Badge,
  Box,
  Checkbox,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  Icon,
  IconButton,
  Link,
  SkeletonText,
  Spacer,
  Switch,
  Table,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  useSearch,
} from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { FaPlus } from "react-icons/fa"
import {
  GoGitPullRequest,
  GoGitPullRequestClosed,
  GoIssueClosed,
  GoIssueOpened,
} from "react-icons/go"
import { MdEdit } from "react-icons/md"
import { z } from "zod"

import { ReleasesService } from "../../../../../client"
import Markdown from "../../../../../components/Common/Markdown"
import Tooltip from "../../../../../components/Common/Tooltip"
import FileEditorModal from "../../../../../components/Files/FileEditorModal"
import ProjectChecklist from "../../../../../components/Onboarding/ProjectChecklist"
import CreateIssue from "../../../../../components/Projects/CreateIssue"
import CreateQuestion from "../../../../../components/Projects/CreateQuestion"
import ProjectShowcase from "../../../../../components/Projects/ProjectShowcase"
import QuestionStatusLetters from "../../../../../components/Projects/QuestionStatus"
import RecentChanges from "../../../../../components/Projects/RecentChanges"
import LatexEditor from "../../../../../components/Publications/LatexEditor"
import NewRelease from "../../../../../components/Releases/NewRelease"
import useProject, {
  useProjectIssues,
  useProjectQuestions,
  useProjectReadme,
  useProjectResults,
} from "../../../../../hooks/useProject"
import {
  formatReleaseDate,
  releaseLocation,
  releasePagePath,
} from "../../../../../lib/releases"
import {
  decodeBase64Utf8,
  removeLeadingHeading,
  safeHref,
} from "../../../../../lib/strings"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/",
)({
  component: Project,
  validateSearch: (search) =>
    z
      .object({
        // Whole-project "New release" modal open state, so a link reopens it.
        new_release: z.boolean().optional(),
        // Questions have their own URLs; these are kept so links made before
        // they did still land on the right one, and are forwarded on arrival.
        edit_question: z.number().optional(),
        question: z.number().optional(),
        evidence: z.number().optional(),
        // LaTeX editor open state (from a showcase publication), so a link
        // reopens it. editor_tex is the .tex source path.
        editor_open: z.boolean().optional(),
        editor_tex: z.string().optional(),
        // Path of the file open in the text editor (README.md or
        // calkit.yaml from the cards here), so a refresh keeps it open.
        edit_file: z.string().optional(),
      })
      .parse(search),
})

function ProjectView() {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const [showClosedTodos, setShowClosedTodos] = useState(false)
  const [checklistSettled, setChecklistSettled] = useState(false)
  const { projectRequest, userHasWriteAccess, showcaseRequest } = useProject(
    accountName,
    projectName,
    ref,
  )
  const { issuesRequest, issueStateMutation, registerCreatedIssue } =
    useProjectIssues(accountName, projectName)
  const visibleIssues = issuesRequest.data?.filter(
    (issue) => showClosedTodos || issue.state === "open",
  )
  // The home page shows the top of the list; the full list, with labels,
  // milestones, and search, is GitHub's own issues page.
  const HOME_TODOS_LIMIT = 5
  const topIssues = visibleIssues?.slice(0, HOME_TODOS_LIMIT)
  const issuesUrl = projectRequest.data?.git_repo_url
    ? `${projectRequest.data.git_repo_url}/issues${
        showClosedTodos ? "?q=is%3Aissue" : ""
      }`
    : null
  const { readmeRequest } = useProjectReadme(accountName, projectName, ref)
  const { questionsRequest } = useProjectQuestions(
    accountName,
    projectName,
    ref,
  )
  const { resultsRequest } = useProjectResults(accountName, projectName, ref)
  // One row per file, since several results can be keys into the same one
  const HOME_RESULTS_LIMIT = 5
  const resultFiles = (resultsRequest.data ?? []).filter(
    (result, index, all) =>
      all.findIndex((other) => other.path === result.path) === index,
  )
  // Shares its cache with the History page's Releases tab (same query key), so
  // creating a release refreshes both.
  const releasesRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "releases", undefined],
    queryFn: () =>
      ReleasesService.getProjectReleases({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
  })
  // Newest first (ISO dates sort lexically); show only the latest few on the
  // home page and link to the full list on the History page.
  const HOME_RELEASES_LIMIT = 5
  const sortedReleases = [...(releasesRequest.data ?? [])].sort((a, b) =>
    (b.date ?? "").localeCompare(a.date ?? ""),
  )
  const topReleases = sortedReleases.slice(0, HOME_RELEASES_LIMIT)
  const removeTitle = (txt: any) => removeLeadingHeading(String(txt))
  const onClosedTodosSwitch = (e: any) => {
    setShowClosedTodos(e.target.checked)
  }
  const onTodoCheckbox = (e: any) => {
    issueStateMutation.mutate({
      // e.target.id is the DOM id string; coerce it to a number so it
      // matches issue.number when updating the cache.
      issueNumber: Number(e.target.id),
      state: e.target.checked ? "closed" : "open",
    })
  }
  const newIssueModal = useDisclosure()
  const newQuestionModal = useDisclosure()
  // New release modal open state lives in the URL so a link can reopen it.
  const navigate = Route.useNavigate()
  const {
    new_release: newReleaseOpen,
    edit_question: editQuestionNumber,
    question: openQuestionNumber,
    evidence: openEvidenceIndex,
    editor_open: editorOpen,
    editor_tex: editorTexPath,
    edit_file: editFile,
  } = Route.useSearch()
  const setEditFile = (path?: string) =>
    navigate({ search: (prev) => ({ ...prev, edit_file: path }) })
  // The editor open state (which .tex) lives in the URL; deps are a best-effort
  // optimization captured when the button is clicked (absent on a cold link).
  const latexDepsRef = useRef<string[] | null | undefined>(undefined)
  const openLatexEditor = (texPath: string, deps?: string[] | null) => {
    latexDepsRef.current = deps
    navigate({
      search: (prev) => ({ ...prev, editor_open: true, editor_tex: texPath }),
    })
  }
  const closeLatexEditor = () =>
    navigate({
      search: (prev) => ({
        ...prev,
        editor_open: undefined,
        editor_tex: undefined,
      }),
    })
  const setNewReleaseOpen = (open: boolean) =>
    navigate({
      search: (prev) => ({ ...prev, new_release: open || undefined }),
    })
  const questions = questionsRequest.data ?? []
  // A question has its own URL now. Links made before it did -- a comment
  // notification, a bookmark -- arrive here with the number in the query,
  // so send them on rather than dropping them.
  const legacyQuestion = openQuestionNumber ?? editQuestionNumber
  useEffect(() => {
    if (legacyQuestion === undefined) {
      return
    }
    navigate({
      to: "/$accountName/$projectName/questions/$questionNumber",
      params: {
        accountName,
        projectName,
        questionNumber: String(legacyQuestion),
      },
      search: {
        evidence: openEvidenceIndex,
        edit: editQuestionNumber !== undefined || undefined,
      },
      replace: true,
    })
  }, [
    legacyQuestion,
    editQuestionNumber,
    openEvidenceIndex,
    accountName,
    projectName,
    navigate,
  ])

  const checklistProject =
    userHasWriteAccess && !ref ? projectRequest.data : undefined
  return (
    <>
      <Flex mt={1}>
        <Box width="65%" mr={8}>
          {/* What's left to set up, until it's done or dismissed */}
          {checklistProject ? (
            <ProjectChecklist
              accountName={accountName}
              projectName={projectName}
              projectId={checklistProject.id}
              onSettledChange={setChecklistSettled}
            />
          ) : null}
          {/* Each of these sits above the next, so hold them all until all
              have landed rather than shoving the README down mid-read; the
              project says whether there's a checklist to wait for */}
          {projectRequest.isPending ||
          (checklistProject && !checklistSettled) ||
          showcaseRequest.isPending ||
          readmeRequest.isPending ? (
            <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
              <SkeletonText noOfLines={12} spacing={3} skeletonHeight="14px" />
            </Box>
          ) : (
            <>
              {/* Showcase, only once there's one to show, so a project
                  without one doesn't open on an empty card */}
              {showcaseRequest.data?.elements.length ? (
                <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
                  <Flex alignItems="center">
                    <Heading size="md">Showcase</Heading>
                    {userHasWriteAccess && !ref ? (
                      <IconButton
                        aria-label="Edit calkit.yaml"
                        height="25px"
                        width="28px"
                        ml={1.5}
                        icon={<MdEdit />}
                        size={"xs"}
                        onClick={() => setEditFile("calkit.yaml")}
                      />
                    ) : (
                      ""
                    )}
                  </Flex>
                  <ProjectShowcase
                    ownerName={accountName}
                    projectName={projectName}
                    gitRef={ref}
                    onEditLatex={
                      userHasWriteAccess && !ref ? openLatexEditor : undefined
                    }
                  />
                </Box>
              ) : null}
              {/* README */}
              <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
                <Flex alignItems="center">
                  <Heading size="md">README</Heading>
                  {userHasWriteAccess && !ref ? (
                    <IconButton
                      aria-label="Edit README"
                      height="25px"
                      width="28px"
                      ml={1.5}
                      icon={<MdEdit />}
                      size={"xs"}
                      onClick={() => setEditFile("README.md")}
                    />
                  ) : (
                    ""
                  )}
                </Flex>
                {readmeRequest.data ? (
                  <Markdown repo={{ accountName, projectName, ref }}>
                    {removeTitle(
                      decodeBase64Utf8(String(readmeRequest?.data?.content)),
                    )}
                  </Markdown>
                ) : (
                  ""
                )}
              </Box>
            </>
          )}
        </Box>
        <Box width={"35%"}>
          {/* Questions  */}
          <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
            <Flex>
              <Heading size="md" mb={2}>
                <Link
                  as={RouterLink}
                  to={`/${accountName}/${projectName}/questions`}
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  search={{ ref } as any}
                >
                  Questions
                </Link>
              </Heading>
              {userHasWriteAccess ? (
                <>
                  <IconButton
                    aria-label="Add question"
                    height="25px"
                    width="28px"
                    ml={1.5}
                    icon={<FaPlus />}
                    size={"xs"}
                    onClick={newQuestionModal.onOpen}
                  />
                  <CreateQuestion
                    isOpen={newQuestionModal.isOpen}
                    onClose={newQuestionModal.onClose}
                  />
                </>
              ) : (
                ""
              )}
            </Flex>
            {questionsRequest.isPending ? (
              <SkeletonText noOfLines={3} spacing={2} skeletonHeight="14px" />
            ) : questions.length ? (
              <Box>
                {questions.map((question) => {
                  return (
                    // The whole row opens the question, mark included, since
                    // the answer and its evidence are the point of listing it
                    // -- editing included, which is why there's no edit
                    // button here.
                    <Flex
                      key={question.id}
                      as="button"
                      type="button"
                      role="group"
                      align="center"
                      w="100%"
                      textAlign="left"
                      py={1}
                      // A <button> doesn't get one on its own, and this one
                      // reads as a link to the question.
                      cursor="pointer"
                      sx={{ "& p": { my: 0 } }}
                      onClick={() =>
                        navigate({
                          to: "/$accountName/$projectName/questions/$questionNumber",
                          params: {
                            accountName,
                            projectName,
                            questionNumber: String(question.number),
                          },
                          // Keeps the ref being browsed; drops what was only
                          // ever here to forward an old link.
                          search: (prev) => ({
                            ...prev,
                            question: undefined,
                            evidence: undefined,
                            edit_question: undefined,
                          }),
                        })
                      }
                    >
                      <Box
                        minW={0}
                        flex="1"
                        _groupHover={{ textDecoration: "underline" }}
                      >
                        <Markdown>
                          {`${question.number}. ${question.question}`}
                        </Markdown>
                      </Box>
                      <QuestionStatusLetters question={question} ml={2} />
                    </Flex>
                  )
                })}
              </Box>
            ) : (
              <Text fontSize="sm" color="gray.500">
                No research questions defined yet.
              </Text>
            )}
          </Box>
          {/* Results, with whether each is out of date */}
          <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
            <Heading size="md" mb={2}>
              <Link
                as={RouterLink}
                to={`/${accountName}/${projectName}/results`}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                search={{ ref } as any}
              >
                Results
              </Link>
            </Heading>
            {resultsRequest.isPending ? (
              <SkeletonText noOfLines={3} spacing={2} skeletonHeight="14px" />
            ) : resultFiles.length ? (
              <Box>
                {resultFiles.slice(0, HOME_RESULTS_LIMIT).map((result) => (
                  <Flex key={result.path} align="center" py={1} gap={2}>
                    <Link
                      as={RouterLink}
                      to={`/${accountName}/${projectName}/results`}
                      // eslint-disable-next-line @typescript-eslint/no-explicit-any
                      search={{ ref, path: result.path } as any}
                      noOfLines={1}
                    >
                      {result.title}
                    </Link>
                    {result.stage_status?.status === "stale" ? (
                      <Badge colorScheme="orange" fontSize="2xs">
                        Stale
                      </Badge>
                    ) : null}
                  </Flex>
                ))}
                {resultFiles.length > HOME_RESULTS_LIMIT ? (
                  <Text fontSize="sm" color="gray.500">
                    and {resultFiles.length - HOME_RESULTS_LIMIT} more
                  </Text>
                ) : null}
              </Box>
            ) : (
              <Text fontSize="sm" color="gray.500">
                No results yet.
              </Text>
            )}
          </Box>
          {/* To-dos (issues) */}
          <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
            <Flex width="full" alignItems="center" mb={2}>
              <Box>
                <Flex>
                  <Heading size="md">To-do</Heading>
                  {userHasWriteAccess ? (
                    <>
                      <IconButton
                        aria-label="Add to-do"
                        height="25px"
                        width="28px"
                        ml={1.5}
                        icon={<FaPlus />}
                        size={"xs"}
                        onClick={newIssueModal.onOpen}
                      />
                      <CreateIssue
                        isOpen={newIssueModal.isOpen}
                        onClose={newIssueModal.onClose}
                        onCreated={registerCreatedIssue}
                      />
                    </>
                  ) : (
                    ""
                  )}
                </Flex>
              </Box>
              <Spacer />
              <Box>
                <FormControl display="flex" alignItems="center">
                  <FormLabel htmlFor="show-closed" mb="0">
                    Show closed
                  </FormLabel>
                  <Switch
                    id="show-closed"
                    isChecked={showClosedTodos}
                    onChange={onClosedTodosSwitch}
                  />
                </FormControl>
              </Box>
            </Flex>
            {issuesRequest.isPending ? (
              <SkeletonText noOfLines={3} spacing={2} skeletonHeight="14px" />
            ) : (
              <>
                {topIssues?.map((issue) => {
                  const routeMap: Record<string, string> = {
                    figure: "figures",
                    publication: "publications",
                    notebook: "notebooks",
                    file: "files",
                  }
                  const artifactRoute = issue.artifact_type
                    ? routeMap[issue.artifact_type] ?? "files"
                    : null
                  const artifactHref =
                    artifactRoute && issue.artifact_path
                      ? `/${accountName}/${projectName}/${artifactRoute}?path=${encodeURIComponent(issue.artifact_path)}`
                      : null
                  const isOpen = issue.state === "open"
                  // GitHub's icons and colors, though closed pull requests
                  // are grey since this doesn't know if they were merged
                  const kindIcon = issue.is_pull_request
                    ? isOpen
                      ? GoGitPullRequest
                      : GoGitPullRequestClosed
                    : isOpen
                      ? GoIssueOpened
                      : GoIssueClosed
                  const kindColor = isOpen
                    ? "green.500"
                    : issue.is_pull_request
                      ? "gray.500"
                      : "purple.500"
                  return (
                    <Flex key={issue.number} alignItems={"flex-start"}>
                      {/* Checking off a pull request would close it without
                          merging it, so its checkbox is disabled */}
                      <Checkbox
                        isChecked={!isOpen}
                        onChange={onTodoCheckbox}
                        id={String(issue.number)}
                        isDisabled={
                          !userHasWriteAccess || issue.is_pull_request
                        }
                        mt={1}
                      />
                      <Text ml={2}>
                        {" "}
                        {artifactHref ? (
                          <Link as={RouterLink} to={artifactHref as any}>
                            {issue.title}
                          </Link>
                        ) : (
                          issue.title
                        )}{" "}
                        (
                        <Link isExternal href={safeHref(issue.url)}>
                          <Tooltip
                            label={
                              issue.is_pull_request ? "Pull request" : "Issue"
                            }
                          >
                            <span>
                              <Icon
                                as={kindIcon}
                                color={kindColor}
                                verticalAlign="-0.125em"
                                mr={0.5}
                              />
                            </span>
                          </Tooltip>
                          #{issue.number}
                        </Link>
                        )
                      </Text>
                    </Flex>
                  )
                })}
                {issuesUrl && (visibleIssues?.length ?? 0) > 0 ? (
                  <Link
                    isExternal
                    href={safeHref(issuesUrl)}
                    fontSize="sm"
                    display="inline-block"
                    mt={2}
                  >
                    {/* No count: this is GitHub's first page, not all */}
                    See all on GitHub <Icon as={ExternalLinkIcon} mb={0.5} />
                  </Link>
                ) : null}
              </>
            )}
          </Box>
          {/* What moved since the last visit: pushes from the CLI, a
              collaborator's commits, an Overleaf sync */}
          {!ref ? (
            <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
              <RecentChanges
                accountName={accountName}
                projectName={projectName}
              />
            </Box>
          ) : null}
          {/* Releases */}
          <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
            <Flex>
              <Heading size="md" mb={2}>
                <Link
                  as={RouterLink}
                  to={`/${accountName}/${projectName}/releases`}
                >
                  Releases
                </Link>
              </Heading>
              {userHasWriteAccess ? (
                <>
                  <IconButton
                    aria-label="Add release"
                    height="25px"
                    width="28px"
                    ml={1.5}
                    icon={<FaPlus />}
                    size={"xs"}
                    onClick={() => setNewReleaseOpen(true)}
                  />
                  <NewRelease
                    isOpen={Boolean(newReleaseOpen)}
                    onClose={() => setNewReleaseOpen(false)}
                    ownerName={accountName}
                    projectName={projectName}
                    kind="project"
                  />
                </>
              ) : (
                ""
              )}
            </Flex>
            {releasesRequest.isPending ? (
              <SkeletonText noOfLines={3} spacing={2} skeletonHeight="14px" />
            ) : releasesRequest.isError ? (
              <Text fontSize="sm" color="red.500">
                Failed to load releases.
              </Text>
            ) : topReleases.length > 0 ? (
              <>
                <Table size="sm" variant="simple">
                  <Thead>
                    <Tr>
                      <Th px={2}>Name</Th>
                      <Th px={2}>Path</Th>
                      <Th px={2}>Date</Th>
                      <Th px={2}>Location</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {topReleases.map((release) => {
                      const dest = releaseLocation(release)
                      const pathLabel = release.path || "."
                      return (
                        <Tr key={`${release.source}-${release.name}`}>
                          <Td px={2}>
                            <Link
                              as={RouterLink}
                              to={
                                releasePagePath(
                                  accountName,
                                  projectName,
                                  release.name,
                                ) as any
                              }
                              color="blue.500"
                            >
                              {release.name}
                            </Link>
                          </Td>
                          <Td px={2} fontSize="sm">
                            <Link
                              as={RouterLink}
                              to={
                                releasePagePath(
                                  accountName,
                                  projectName,
                                  release.name,
                                ) as any
                              }
                              color="blue.500"
                            >
                              {pathLabel}
                            </Link>
                          </Td>
                          <Td px={2} fontSize="sm" color="gray.500">
                            {formatReleaseDate(release.date)}
                          </Td>
                          <Td px={2} fontSize="sm">
                            {dest.href ? (
                              <Link
                                href={dest.href}
                                isExternal
                                color="blue.500"
                                display="inline-flex"
                                alignItems="center"
                                gap={1}
                                aria-label={`Open ${dest.label}`}
                              >
                                {dest.label}
                                <Icon as={ExternalLinkIcon} />
                              </Link>
                            ) : (
                              <Text as="span" color="gray.500">
                                {dest.label}
                              </Text>
                            )}
                          </Td>
                        </Tr>
                      )
                    })}
                  </Tbody>
                </Table>
                {sortedReleases.length > topReleases.length ? (
                  <Link
                    as={RouterLink}
                    to={`/${accountName}/${projectName}/releases`}
                    fontSize="sm"
                  >
                    View all {sortedReleases.length} releases →
                  </Link>
                ) : (
                  ""
                )}
              </>
            ) : (
              <Text fontSize="sm" color="gray.500">
                No releases yet.
              </Text>
            )}
          </Box>
        </Box>
      </Flex>
      {editorOpen && editorTexPath && userHasWriteAccess && !ref && (
        <LatexEditor
          isOpen={Boolean(editorOpen)}
          onClose={closeLatexEditor}
          ownerName={accountName}
          projectName={projectName}
          texPath={editorTexPath}
          deps={latexDepsRef.current}
        />
      )}
      {editFile && userHasWriteAccess && !ref ? (
        <FileEditorModal
          isOpen
          onClose={() => setEditFile(undefined)}
          ownerName={accountName}
          projectName={projectName}
          path={editFile}
        />
      ) : null}
    </>
  )
}

function Project() {
  return <ProjectView />
}
