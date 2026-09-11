import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Box,
  Checkbox,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  Icon,
  IconButton,
  Link,
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
import { useRef, useState } from "react"
import { FaCheck, FaPlus, FaRegSquare } from "react-icons/fa"
import { MdEdit } from "react-icons/md"
import { z } from "zod"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"

import { ReleasesService } from "../../../../../client"
import Markdown from "../../../../../components/Common/Markdown"
import Tooltip from "../../../../../components/Common/Tooltip"
import FileEditorModal from "../../../../../components/Files/FileEditorModal"
import ProjectChecklist from "../../../../../components/Onboarding/ProjectChecklist"
import CreateIssue from "../../../../../components/Projects/CreateIssue"
import CreateQuestion from "../../../../../components/Projects/CreateQuestion"
import EditQuestion from "../../../../../components/Projects/EditQuestion"
import QuestionModal, {
  isEvidenceMissing,
  isEvidenceStale,
} from "../../../../../components/Projects/QuestionModal"
import ProjectShowcase from "../../../../../components/Projects/ProjectShowcase"
import RecentChanges from "../../../../../components/Projects/RecentChanges"
import LatexEditor from "../../../../../components/Publications/LatexEditor"
import NewRelease from "../../../../../components/Releases/NewRelease"
import useProject, {
  useProjectIssues,
  useProjectQuestions,
  useProjectReadme,
} from "../../../../../hooks/useProject"
import {
  formatReleaseDate,
  releaseLocation,
  releasePagePath,
} from "../../../../../lib/releases"
import { decodeBase64Utf8 } from "../../../../../lib/strings"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/",
)({
  component: Project,
  validateSearch: (search) =>
    z
      .object({
        // Whole-project "New release" modal open state, so a link reopens it.
        new_release: z.boolean().optional(),
        // Number of the question whose edit modal is open, so a link reopens it.
        edit_question: z.number().optional(),
        // Number of the question whose detail modal is open, and the index of
        // the evidence item open within it, so a link reproduces exactly what
        // is on screen and the back button steps out of it.
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
  const { projectRequest, userHasWriteAccess } = useProject(
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
  const removeFirstLine = (txt: any) => {
    const lines = String(txt).split("\n")
    lines.splice(0, 1)
    return lines.join("\n")
  }
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
  // Which question's edit modal is open also lives in the URL.
  const setEditQuestion = (number?: number) =>
    navigate({
      search: (prev) => ({ ...prev, edit_question: number }),
    })
  const editingQuestion =
    questionsRequest.data?.find((q) => q.number === editQuestionNumber) ?? null
  // Which question's detail modal is open, and which of its evidence items,
  // both live in the URL. Closing the question drops the evidence with it, so
  // a stale index can't outlive the question it indexed into.
  const questions = questionsRequest.data ?? []
  const openQuestion =
    questions.find((q) => q.number === openQuestionNumber) ?? null
  const setOpenQuestion = (number?: number) =>
    navigate({
      search: (prev) => ({ ...prev, question: number, evidence: undefined }),
    })
  const setOpenEvidence = (index?: number) =>
    navigate({ search: (prev) => ({ ...prev, evidence: index }) })
  // Stepping between questions works off list order rather than number, so a
  // project whose questions aren't numbered contiguously still walks them all.
  const openQuestionIdx = openQuestion ? questions.indexOf(openQuestion) : -1
  const stepQuestion = (delta: number) => {
    const next = questions[openQuestionIdx + delta]
    return next ? () => setOpenQuestion(next.number) : undefined
  }

  return (
    <>
      <Flex mt={1}>
        <Box width="65%" mr={8}>
          {/* What's left to set up, until it's done or dismissed */}
          {userHasWriteAccess && !ref && projectRequest.data ? (
            <ProjectChecklist
              accountName={accountName}
              projectName={projectName}
              projectId={projectRequest.data.id}
            />
          ) : null}
          {/* Showcase */}
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
            {readmeRequest.isPending ? (
              <LoadingSpinner height="100vh" />
            ) : readmeRequest.data ? (
              <Markdown>
                {removeFirstLine(
                  decodeBase64Utf8(String(readmeRequest?.data?.content)),
                )}
              </Markdown>
            ) : (
              ""
            )}
          </Box>
        </Box>
        <Box width={"35%"}>
          {/* Questions  */}
          <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
            <Flex>
              <Heading size="md" mb={2}>
                Questions
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
              <LoadingSpinner height="100px" />
            ) : questions.length ? (
              <Box>
                {questions.map((question) => {
                  // One mark per row, worst first: no answer, then an answer
                  // with nothing behind it, then evidence that can't be found
                  // at all, then evidence that has merely drifted --
                  // staleness that only shows once a question is open is
                  // staleness nobody sees. All four are icons of the same
                  // size, so they land on one line down the list.
                  const mark = !question.answer
                    ? {
                        icon: FaRegSquare,
                        color: "red.400",
                        label: "Not yet answered",
                      }
                    : !question.evidence?.length
                      ? {
                          icon: FaRegSquare,
                          color: "orange.300",
                          label:
                            "Answered, but nothing is linked to back it up",
                        }
                      : question.evidence.some(isEvidenceMissing)
                        ? {
                            icon: FaCheck,
                            color: "red.400",
                            label:
                              "Answered, but some of its evidence can't be found -- it may never have been pushed, or it cites a Git ref that doesn't exist.",
                          }
                        : question.evidence.some(isEvidenceStale)
                          ? {
                              icon: FaCheck,
                              color: "orange.300",
                              label:
                                "Answered, but some of its evidence is out of date with respect to the pipeline, or comes from a frozen stage without a Git ref pinning it.",
                            }
                          : {
                              icon: FaCheck,
                              color: "green.400",
                              label:
                                "Answered, and every piece of its evidence is up to date",
                            }
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
                      onClick={() => setOpenQuestion(question.number)}
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
                      <Tooltip label={mark.label}>
                        <Flex ml={2} flexShrink={0} align="center">
                          <Icon as={mark.icon} color={mark.color} />
                        </Flex>
                      </Tooltip>
                    </Flex>
                  )
                })}
              </Box>
            ) : (
              <Text fontSize="sm" color="gray.500">
                No research questions defined yet.
              </Text>
            )}
            <QuestionModal
              question={openQuestion}
              // Only open once the target question has resolved, so a
              // deep-linked ?question= can't render an empty modal.
              isOpen={openQuestion !== null}
              onClose={() => setOpenQuestion(undefined)}
              accountName={accountName}
              projectName={projectName}
              gitRef={ref}
              evidenceIndex={openEvidenceIndex}
              onEvidenceIndexChange={setOpenEvidence}
              // Stepping is off while the editor is open on top: the arrows
              // it reads are the same ones the editor's own fields see.
              onPrevQuestion={editingQuestion ? undefined : stepQuestion(-1)}
              onNextQuestion={editingQuestion ? undefined : stepQuestion(1)}
              // The editor opens over the detail view rather than replacing
              // it, so cancelling lands back on the question.
              onEdit={
                userHasWriteAccess && openQuestion
                  ? () => setEditQuestion(openQuestion.number)
                  : undefined
              }
            />
            <EditQuestion
              question={editingQuestion}
              // Only open once the target question has actually resolved, so a
              // deep-linked ?edit_question= can't render a null-question modal.
              isOpen={editingQuestion !== null}
              onClose={() => setEditQuestion(undefined)}
              gitRef={ref}
            />
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
              <LoadingSpinner />
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
                  return (
                    <Flex key={issue.number} alignItems={"flex-start"}>
                      <Checkbox
                        isChecked={issue.state === "closed"}
                        onChange={onTodoCheckbox}
                        id={String(issue.number)}
                        isDisabled={!userHasWriteAccess}
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
                        <Link isExternal href={issue.url}>
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
                    href={issuesUrl}
                    fontSize="sm"
                    display="inline-block"
                    mt={2}
                  >
                    {(visibleIssues?.length ?? 0) > HOME_TODOS_LIMIT
                      ? `See all ${visibleIssues?.length} on GitHub`
                      : "See all on GitHub"}{" "}
                    <Icon as={ExternalLinkIcon} mb={0.5} />
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
              <LoadingSpinner height="100px" />
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
      {editorOpen && editorTexPath && (
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
