import { Box, Text } from "@chakra-ui/react"
import { createFileRoute, useSearch } from "@tanstack/react-router"
import { z } from "zod"

import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import EditQuestion from "../../../../../components/Projects/EditQuestion"
import QuestionModal from "../../../../../components/Projects/QuestionModal"
import useProject, {
  useProjectQuestions,
} from "../../../../../hooks/useProject"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/questions/$questionNumber",
)({
  component: QuestionDetail,
  validateSearch: (search) =>
    z
      .object({
        // Index of the evidence item open within the question, so a link
        // reproduces exactly what's on screen and back steps out of it.
        evidence: z.number().optional(),
        // Whether the editor is open over the question.
        edit: z.boolean().optional(),
      })
      .parse(search),
})

/** One question, on a URL of its own.
 *
 * A question is a thing a project has, not a state the home page is in, so
 * it gets an address that can be linked to, bookmarked, and gone back out
 * of. What's rendered is the same modal the home page used to open; closing
 * it returns there.
 */
function QuestionDetail() {
  const { accountName, projectName, questionNumber } = Route.useParams()
  const navigate = Route.useNavigate()
  const { evidence: evidenceIndex, edit } = Route.useSearch()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const { userHasWriteAccess } = useProject(accountName, projectName, ref)
  const { questionsRequest } = useProjectQuestions(
    accountName,
    projectName,
    ref,
  )
  const number = Number(questionNumber)
  const questions = questionsRequest.data ?? []
  const question = questions.find((q) => q.number === number) ?? null
  // Keep whatever the project layout put in the query -- the ref being
  // browsed, above all -- and drop only what belongs to this page.
  const goToProject = () =>
    navigate({
      to: "/$accountName/$projectName",
      params: { accountName, projectName },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      search: (prev: any) => ({
        ...prev,
        evidence: undefined,
        edit: undefined,
      }),
    })
  // Stepping works off list order rather than number, so a project whose
  // questions aren't numbered contiguously still walks them all.
  const index = question ? questions.indexOf(question) : -1
  const stepQuestion = (delta: number) => {
    const next = questions[index + delta]
    return next
      ? () =>
          navigate({
            to: "/$accountName/$projectName/questions/$questionNumber",
            params: {
              accountName,
              projectName,
              questionNumber: String(next.number),
            },
            // A new question starts at the question itself, not at whichever
            // evidence item the last one was open to.
            search: (prev) => ({ ...prev, evidence: undefined }),
          })
      : undefined
  }
  const setEvidence = (i?: number) =>
    navigate({ search: (prev) => ({ ...prev, evidence: i }) })
  const setEdit = (open: boolean) =>
    navigate({ search: (prev) => ({ ...prev, edit: open || undefined }) })
  if (questionsRequest.isPending) {
    return <LoadingSpinner height="200px" />
  }
  if (!question) {
    return (
      <Box mt={4}>
        <Text fontSize="sm" color="gray.500">
          There's no question {questionNumber} in this project.
        </Text>
      </Box>
    )
  }
  return (
    <>
      <QuestionModal
        question={question}
        isOpen
        onClose={goToProject}
        accountName={accountName}
        projectName={projectName}
        gitRef={ref}
        evidenceIndex={evidenceIndex}
        onEvidenceIndexChange={setEvidence}
        // Stepping is off while the editor is open on top: the arrows it
        // reads are the same ones the editor's own fields see.
        onPrevQuestion={edit ? undefined : stepQuestion(-1)}
        onNextQuestion={edit ? undefined : stepQuestion(1)}
        // The editor opens over the detail view rather than replacing it,
        // so cancelling lands back on the question.
        onEdit={userHasWriteAccess ? () => setEdit(true) : undefined}
      />
      <EditQuestion
        question={question}
        isOpen={!!edit}
        onClose={() => setEdit(false)}
        gitRef={ref}
      />
    </>
  )
}
