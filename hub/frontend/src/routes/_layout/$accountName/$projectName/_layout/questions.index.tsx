import { createFileRoute, useSearch } from "@tanstack/react-router"

import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import { QuestionsModal } from "../../../../../components/Projects/QuestionModal"
import { useProjectQuestions } from "../../../../../hooks/useProject"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/questions/",
)({
  component: Questions,
})

/** All of a project's questions, on a URL of their own like each one is. */
function Questions() {
  const { accountName, projectName } = Route.useParams()
  const navigate = Route.useNavigate()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const { questionsRequest } = useProjectQuestions(
    accountName,
    projectName,
    ref,
  )
  if (questionsRequest.isPending) {
    return <LoadingSpinner height="200px" />
  }
  return (
    <QuestionsModal
      questions={questionsRequest.data ?? []}
      isOpen
      onClose={() =>
        navigate({
          to: "/$accountName/$projectName",
          params: { accountName, projectName },
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          search: (prev: any) => prev,
        })
      }
      accountName={accountName}
      projectName={projectName}
      gitRef={ref}
      onOpenQuestion={(questionNumber, evidenceIndex) =>
        navigate({
          to: "/$accountName/$projectName/questions/$questionNumber",
          params: {
            accountName,
            projectName,
            questionNumber: String(questionNumber),
          },
          // Closing the question comes back here rather than to the home page.
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          search: (prev: any) => ({
            ...prev,
            evidence: evidenceIndex,
            list: true,
          }),
        })
      }
    />
  )
}
