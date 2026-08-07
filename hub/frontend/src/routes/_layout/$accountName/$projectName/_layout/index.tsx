import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import {
  Box,
  Flex,
  Heading,
  Text,
  Accordion,
  AccordionItem,
  AccordionButton,
  AccordionPanel,
  AccordionIcon,
  Image,
  useColorModeValue,
  Checkbox,
  FormControl,
  FormLabel,
  Switch,
  Spacer,
  useDisclosure,
  IconButton,
  Link,
  Icon,
  Table,
  Thead,
  Tbody,
  Tr,
  Th,
  Td,
} from "@chakra-ui/react"
import {
  createFileRoute,
  Link as RouterLink,
  useSearch,
} from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { z } from "zod"
import { FaPlus, FaRegFileAlt } from "react-icons/fa"
import { MdEdit } from "react-icons/md"
import { ExternalLinkIcon } from "@chakra-ui/icons"

import Markdown from "../../../../../components/Common/Markdown"
import FigureView from "../../../../../components/Figures/FigureView"
import { ReleasesService, type QuestionEvidence } from "../../../../../client"
import { decodeBase64Utf8 } from "../../../../../lib/strings"
import {
  formatReleaseDate,
  releaseLocation,
  releasePagePath,
} from "../../../../../lib/releases"
import CreateIssue from "../../../../../components/Projects/CreateIssue"
import CreateQuestion from "../../../../../components/Projects/CreateQuestion"
import EditQuestion from "../../../../../components/Projects/EditQuestion"
import NewPublication from "../../../../../components/Publications/NewPublication"
import NewRelease from "../../../../../components/Releases/NewRelease"
import useProject, {
  useProjectIssues,
  useProjectQuestions,
  useProjectReadme,
} from "../../../../../hooks/useProject"
import ProjectShowcase from "../../../../../components/Projects/ProjectShowcase"
import ImportOverleaf from "../../../../../components/Publications/ImportOverleaf"
import LatexEditor from "../../../../../components/Publications/LatexEditor"

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
        // Number of the question whose details are expanded, so the back
        // button and links restore the expanded state.
        expanded_question: z.number().optional(),
        // LaTeX editor open state (from a showcase publication), so a link
        // reopens it. editor_tex is the .tex source path.
        editor_open: z.boolean().optional(),
        editor_tex: z.string().optional(),
      })
      .parse(search),
})

/** Compact display of a single piece of question evidence. */
function EvidenceItem({
  evidence,
  accountName,
  projectName,
  gitRef,
}: {
  evidence: QuestionEvidence
  accountName: string
  projectName: string
  gitRef?: string
}) {
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const bg = useColorModeValue("white", "gray.800")
  if (evidence.kind === "figure") {
    const fig = evidence.figure
    const ext = evidence.path.toLowerCase().split(".").pop() ?? ""
    const imgMime: Record<string, string> = {
      png: "image/png",
      jpg: "image/jpeg",
      jpeg: "image/jpeg",
      gif: "image/gif",
      svg: "image/svg+xml",
    }
    const imgSrc =
      fig && ext in imgMime
        ? fig.content
          ? `data:${imgMime[ext]};base64,${fig.content}`
          : fig.url ?? undefined
        : undefined
    let thumb
    if (imgSrc) {
      // Raster/SVG images render directly for reliable, cheap thumbnails.
      thumb = (
        <Image
          src={imgSrc}
          alt={fig?.title ?? evidence.path}
          width="100%"
          height="100%"
          objectFit="contain"
        />
      )
    } else if (fig && (fig.content || fig.url)) {
      // Plotly JSON, PDFs, etc. go through the shared figure renderer.
      thumb = <FigureView figure={fig} fillHeight />
    } else {
      thumb = (
        <Flex height="100%" align="center" justify="center" color="gray.400">
          <Icon as={ExternalLinkIcon} />
        </Flex>
      )
    }
    return (
      <Link
        as={RouterLink}
        to={`/${accountName}/${projectName}/figures`}
        // Preserve the global ref so the figure opens at the same git ref the
        // project is being browsed at.
        search={{ path: evidence.path, ref: gitRef } as any}
        _hover={{ textDecoration: "none" }}
      >
        <Box
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="md"
          overflow="hidden"
          bg={bg}
          width="150px"
          _hover={{ shadow: "md" }}
        >
          {/* pointerEvents off so a click hits the link, not the Plotly plot */}
          <Box height="90px" overflow="hidden" pointerEvents="none">
            {thumb}
          </Box>
          <Text fontSize="xs" noOfLines={1} px={2} py={1}>
            {fig?.title ?? evidence.path}
          </Text>
        </Box>
      </Link>
    )
  }
  if (evidence.kind === "publication") {
    const pub = evidence.publication
    return (
      <Link
        as={RouterLink}
        to={`/${accountName}/${projectName}/publications`}
        search={{ path: evidence.path, ref: gitRef } as any}
        _hover={{ textDecoration: "none" }}
      >
        <Box
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="md"
          bg={bg}
          px={3}
          py={2}
          minW="130px"
          maxW="100%"
          _hover={{ shadow: "md" }}
        >
          <Flex align="center" gap={1.5}>
            <Icon as={FaRegFileAlt} color="gray.500" flexShrink={0} />
            <Text fontSize="sm" fontWeight="semibold" noOfLines={1}>
              {pub?.title ?? evidence.path}
            </Text>
          </Flex>
          <Text fontSize="xs" color="gray.500" noOfLines={1}>
            {evidence.path}
          </Text>
          {evidence.explanation ? (
            <Text fontSize="xs" color="gray.500" noOfLines={2} mt={0.5}>
              {evidence.explanation}
            </Text>
          ) : null}
        </Box>
      </Link>
    )
  }
  return (
    <Box
      borderWidth={1}
      borderColor={borderColor}
      borderRadius="md"
      bg={bg}
      px={3}
      py={2}
      minW="130px"
      maxW="100%"
    >
      {/* `path:key` at the top links to the file and identifies the result. */}
      <Link
        as={RouterLink}
        to={`/${accountName}/${projectName}/files`}
        search={{ path: evidence.path, ref: gitRef } as any}
        fontSize="xs"
        fontWeight="semibold"
        noOfLines={1}
        display="block"
      >
        {evidence.path}
        {evidence.key ? `:${evidence.key}` : ""}
      </Link>
      {evidence.value != null ? (
        <Text
          fontSize="xl"
          fontWeight="bold"
          lineHeight="1.1"
          noOfLines={1}
          my={0.5}
        >
          {evidence.value}
        </Text>
      ) : null}
      {evidence.explanation ? (
        <Text fontSize="xs" color="gray.500" noOfLines={2} mt={0.5}>
          {evidence.explanation}
        </Text>
      ) : null}
    </Box>
  )
}

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
        ownerName: accountName,
        projectName,
      }),
  })
  // Newest first (ISO dates sort lexically); show only the latest few on the
  // home page and link to the full list on the History page.
  const HOME_RELEASES_LIMIT = 5
  const sortedReleases = [...(releasesRequest.data ?? [])].sort((a, b) =>
    (b.date ?? "").localeCompare(a.date ?? ""),
  )
  const topReleases = sortedReleases.slice(0, HOME_RELEASES_LIMIT)
  const gitRepoUrl = projectRequest.data?.git_repo_url
  const codespacesUrl =
    String(gitRepoUrl).replace("://github.com/", "://codespaces.new/") +
    "?quickstart=1"
  const githubDevUrl = String(gitRepoUrl).replace(
    "://github.com/",
    "://github.dev/",
  )
  const removeFirstLine = (txt: any) => {
    let lines = String(txt).split("\n")
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
  const newPubTemplateModal = useDisclosure()
  const overleafImportModal = useDisclosure()
  // New release modal open state lives in the URL so a link can reopen it.
  const navigate = Route.useNavigate()
  const {
    new_release: newReleaseOpen,
    edit_question: editQuestionNumber,
    expanded_question: expandedQuestion,
    editor_open: editorOpen,
    editor_tex: editorTexPath,
  } = Route.useSearch()
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
  // Which question is expanded lives in the URL so the back button restores
  // it. The Accordion works in list positions; translate to/from the question
  // number, which is stable across reorders.
  const questions = questionsRequest.data ?? []
  const expandedIndex = questions.findIndex(
    (q) => q.number === expandedQuestion,
  )
  const setExpandedIndex = (index: number) =>
    navigate({
      search: (prev) => ({
        ...prev,
        expanded_question: index >= 0 ? questions[index]?.number : undefined,
      }),
    })

  return (
    <>
      <Flex mt={1}>
        <Box width="65%" mr={8}>
          {/* Showcase */}
          <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
            <Flex alignItems="center">
              <Heading size="md">Showcase</Heading>
              {userHasWriteAccess ? (
                <>
                  <Link
                    href={`https://github.dev/${accountName}/${projectName}/blob/main/calkit.yaml`}
                    isExternal
                  >
                    <IconButton
                      aria-label="Edit calkit.yaml"
                      height="25px"
                      width="28px"
                      ml={1.5}
                      icon={<MdEdit />}
                      size={"xs"}
                    />
                  </Link>
                </>
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
              {userHasWriteAccess ? (
                <>
                  <Link
                    href={`https://github.dev/${accountName}/${projectName}/blob/main/README.md`}
                    isExternal
                  >
                    <IconButton
                      aria-label="Edit README"
                      height="25px"
                      width="28px"
                      ml={1.5}
                      icon={<MdEdit />}
                      size={"xs"}
                    />
                  </Link>
                </>
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
            ) : questionsRequest.data?.length ? (
              <Accordion
                allowToggle
                index={expandedIndex}
                onChange={(idx) =>
                  setExpandedIndex(Array.isArray(idx) ? idx[0] ?? -1 : idx)
                }
              >
                {questionsRequest.data.map((question) => {
                  const hasDetails =
                    !!question.hypothesis ||
                    !!question.answer ||
                    (question.evidence?.length ?? 0) > 0
                  return (
                    <AccordionItem key={question.id} border="none">
                      <Flex align="center">
                        {hasDetails ? (
                          <AccordionButton
                            flex="1"
                            px={0}
                            py={1}
                            _hover={{ bg: "transparent" }}
                          >
                            <Box
                              flex="1"
                              textAlign="left"
                              sx={{ "& p": { my: 0 } }}
                            >
                              <Markdown>
                                {`${question.number}. ${question.question}`}
                              </Markdown>
                            </Box>
                            <AccordionIcon />
                          </AccordionButton>
                        ) : (
                          <Box flex="1" py={1} sx={{ "& p": { my: 0 } }}>
                            <Markdown>
                              {`${question.number}. ${question.question}`}
                            </Markdown>
                          </Box>
                        )}
                        {userHasWriteAccess ? (
                          <IconButton
                            aria-label="Edit question"
                            icon={<MdEdit />}
                            size="xs"
                            variant="ghost"
                            ml={1}
                            onClick={() => setEditQuestion(question.number)}
                          />
                        ) : null}
                      </Flex>
                      {hasDetails ? (
                        <AccordionPanel px={0} pt={0}>
                          {question.hypothesis ? (
                            <Box mb={2}>
                              <Text
                                fontSize="xs"
                                fontWeight="bold"
                                color="gray.500"
                              >
                                Hypothesis
                              </Text>
                              <Box mt={0.5} sx={{ "& p": { my: 0 } }}>
                                <Markdown>{question.hypothesis}</Markdown>
                              </Box>
                            </Box>
                          ) : null}
                          {question.answer ? (
                            <Box mb={2}>
                              <Text
                                fontSize="xs"
                                fontWeight="bold"
                                color="gray.500"
                              >
                                Answer
                              </Text>
                              <Box mt={0.5} sx={{ "& p": { my: 0 } }}>
                                <Markdown>{question.answer}</Markdown>
                              </Box>
                            </Box>
                          ) : null}
                          {question.evidence?.length ? (
                            <Box>
                              <Text
                                fontSize="xs"
                                fontWeight="bold"
                                color="gray.500"
                              >
                                Evidence
                              </Text>
                              <Flex wrap="wrap" gap={2} mt={1}>
                                {question.evidence.map((evidence, i) => (
                                  <EvidenceItem
                                    key={`${evidence.kind}:${evidence.path}:${i}`}
                                    evidence={evidence}
                                    accountName={accountName}
                                    projectName={projectName}
                                    gitRef={ref}
                                  />
                                ))}
                              </Flex>
                            </Box>
                          ) : null}
                        </AccordionPanel>
                      ) : null}
                    </AccordionItem>
                  )
                })}
              </Accordion>
            ) : (
              <Text fontSize="sm" color="gray.500">
                No research questions defined yet.
              </Text>
            )}
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
                {visibleIssues?.map((issue) => {
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
              </>
            )}
          </Box>
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
          {/* Quick actions */}
          {userHasWriteAccess ? (
            <>
              <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
                <Heading size="md" mb={2}>
                  Quick actions
                </Heading>
                <Text>
                  📜{" "}
                  <Link onClick={newPubTemplateModal.onOpen}>
                    Create a new publication from a template
                  </Link>
                </Text>
                <Text>
                  🍃{" "}
                  <Link onClick={overleafImportModal.onOpen}>
                    Import/link a publication from Overleaf
                  </Link>
                </Text>
                <Text>
                  🚀{" "}
                  <Link isExternal href={codespacesUrl}>
                    Open in GitHub Codespace (edit and run){" "}
                    <Icon height={"40%"} as={ExternalLinkIcon} pb={0.5} />
                  </Link>
                </Text>
                <Text>
                  ✏️{" "}
                  <Link isExternal href={githubDevUrl}>
                    Open in GitHub.dev (edit only){" "}
                    <Icon height={"40%"} as={ExternalLinkIcon} pb={0.5} />
                  </Link>
                </Text>
                <Text>
                  🔒{" "}
                  <Link
                    as={RouterLink}
                    to={"/settings"}
                    search={{ tab: "tokens" } as any}
                  >
                    Manage Calkit personal access tokens
                  </Link>
                </Text>
              </Box>
              <NewPublication
                isOpen={newPubTemplateModal.isOpen}
                onClose={newPubTemplateModal.onClose}
                variant="template"
              />
              <ImportOverleaf
                isOpen={overleafImportModal.isOpen}
                onClose={overleafImportModal.onClose}
              />
            </>
          ) : (
            ""
          )}
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
    </>
  )
}

function Project() {
  return <ProjectView />
}
