import { Flex, Text } from "@chakra-ui/react"
import { FaCheck, FaRegSquare } from "react-icons/fa"

import type {
  QuestionEvidence,
  QuestionPublic,
  QuestionSignOff,
} from "../../client"
import Tooltip from "../Common/Tooltip"

const GRAY = "gray.400"
const GREEN = "green.400"
const ORANGE = "orange.300"
const RED = "red.400"

/** Whether what an evidence item cites can be taken at face value.
 *
 * An answer resting on an artifact that isn't there, or that the pipeline
 * considers out of date, is worth flagging: what the reader is looking at
 * isn't what the project would produce now, if it's there to look at at
 * all. The backend works out which of the ways that can happen applies.
 */
export const isEvidenceStale = (evidence: QuestionEvidence) =>
  evidence.stale_reason != null

/** Whether the cited artifact resolves to nothing at all. */
export const isEvidenceMissing = (evidence: QuestionEvidence) =>
  evidence.stale_reason === "missing"

/** The one mark a question's answer gets, worst first.
 *
 * No answer, then an answer with nothing behind it, then evidence that can't
 * be found at all, then evidence that has merely drifted -- staleness that
 * only shows once a question is open is staleness nobody sees.
 */
export const getAnswerMark = (question: QuestionPublic) =>
  !question.answer
    ? {
        icon: FaRegSquare,
        color: GRAY,
        label: "Not yet answered",
      }
    : !question.evidence?.length
      ? {
          icon: FaRegSquare,
          color: ORANGE,
          label: "Answered, but nothing is linked to back it up",
        }
      : question.evidence.some(isEvidenceMissing)
        ? {
            icon: FaCheck,
            color: RED,
            label:
              "Answered, but some of its evidence can't be found -- it may never have been pushed, or it cites a Git ref that doesn't exist.",
          }
        : question.evidence.some(isEvidenceStale)
          ? {
              icon: FaCheck,
              color: ORANGE,
              label:
                "Answered, but some of its evidence is out of date with respect to the pipeline, or comes from a frozen stage without a Git ref pinning it.",
            }
          : {
              icon: FaCheck,
              color: GREEN,
              label: "Answered, and every piece of its evidence is up to date",
            }

/** Stale if any one sign-off is, since each person vouches for what they
 * checked; one that couldn't be checked against history still counts. */
export const getSignOffState = (signOffs: QuestionSignOff[] | undefined) =>
  !signOffs?.length
    ? "none"
    : signOffs.some((s) => s.status === "stale")
      ? "stale"
      : "current"

export type QuestionLetter = {
  letter: string
  name: string
  color: string
  label: string
}

/** The H A V V row: hypothesis, answer, verified, validated. */
export const getQuestionLetters = (
  question: QuestionPublic,
): QuestionLetter[] => {
  const makeSignOffLetter = (
    name: string,
    what: string,
    signOffs: QuestionSignOff[] | undefined,
  ) => {
    const state = getSignOffState(signOffs)
    const who = (signOffs ?? []).map((s) => s.by).join(", ")
    return {
      letter: "V",
      name,
      color: state === "none" ? GRAY : state === "stale" ? ORANGE : GREEN,
      label:
        state === "none"
          ? `Not yet ${name.toLowerCase()}: nobody has signed off that ${what}`
          : state === "stale"
            ? `${name} by ${who}, but what they checked has changed since`
            : `${name} by ${who}: ${what}`,
    }
  }
  const answer = getAnswerMark(question)
  return [
    {
      letter: "H",
      name: "Hypothesis",
      color: question.hypothesis ? GREEN : GRAY,
      label: question.hypothesis ? "Has a hypothesis" : "No hypothesis yet",
    },
    {
      letter: "A",
      name: "Answer",
      color: answer.color,
      label: answer.label,
    },
    makeSignOffLetter(
      "Verified",
      "the pipeline stages behind the evidence implement the approach",
      question.verifications,
    ),
    makeSignOffLetter(
      "Validated",
      "the approach suits the question and the evidence justifies the answer",
      question.validations,
    ),
  ]
}

/** A compact status row for a question, one colored letter per check. */
export default function QuestionStatusLetters({
  question,
  ...props
}: { question: QuestionPublic } & React.ComponentProps<typeof Flex>) {
  const letters = getQuestionLetters(question)
  return (
    <Flex
      role="img"
      aria-label={letters.map((l) => `${l.name}: ${l.label}`).join(". ")}
      flexShrink={0}
      align="center"
      gap={1}
      {...props}
    >
      {letters.map((l) => (
        <Tooltip key={l.name} label={`${l.name}: ${l.label}`}>
          <Text
            as="span"
            aria-hidden
            fontFamily="mono"
            fontSize="xs"
            fontWeight="bold"
            lineHeight={1}
            color={l.color}
          >
            {l.letter}
          </Text>
        </Tooltip>
      ))}
    </Flex>
  )
}
