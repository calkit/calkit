import { ChakraProvider } from "@chakra-ui/react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { QuestionPublic, QuestionSignOff } from "../../client"
import QuestionStatusLetters, {
  getQuestionLetters,
  getSignOffState,
} from "./QuestionStatus"

const base: QuestionPublic = {
  id: "q",
  project_id: "p",
  number: 1,
  question: "Does it work?",
}

const signOff = (status: QuestionSignOff["status"]): QuestionSignOff => ({
  by: "Ada",
  status,
})

const colors = (question: QuestionPublic) =>
  getQuestionLetters(question).map((l) => l.color)

describe("question status letters", () => {
  it("reads H A V V, gray until there's something to show", () => {
    const letters = getQuestionLetters(base)
    expect(letters.map((l) => l.letter).join(" ")).toBe("H A V V")
    expect(letters.map((l) => l.name)).toEqual([
      "Hypothesis",
      "Answer",
      "Verified",
      "Validated",
    ])
    expect(colors(base)).toEqual(Array(4).fill("gray.400"))
  })

  it("colors the answer by its evidence, worst first", () => {
    const answered = { ...base, hypothesis: "Yes.", answer: "Yes." }
    expect(colors(answered).slice(0, 2)).toEqual(["green.400", "orange.300"])
    const evidence = (stale_reason?: "missing" | "pipeline") => ({
      ...answered,
      evidence: [
        { kind: "figure" as const, path: "a.png" },
        { kind: "figure" as const, path: "b.png", stale_reason },
      ],
    })
    expect(colors(evidence())[1]).toBe("green.400")
    expect(colors(evidence("pipeline"))[1]).toBe("orange.300")
    expect(colors(evidence("missing"))[1]).toBe("red.400")
  })

  it("marks sign-offs stale if any one is, and unchecked as current", () => {
    expect(getSignOffState(undefined)).toBe("none")
    expect(getSignOffState([signOff("current"), signOff("unchecked")])).toBe(
      "current",
    )
    expect(getSignOffState([signOff("current"), signOff("stale")])).toBe(
      "stale",
    )
    const signed = {
      ...base,
      verifications: [signOff("current")],
      validations: [signOff("stale")],
    }
    const [, , verified, validated] = getQuestionLetters(signed)
    expect(verified.color).toBe("green.400")
    expect(verified.label).toContain("Verified by Ada")
    expect(validated.color).toBe("orange.300")
    expect(validated.label).toContain("has changed since")
  })

  it("renders one labeled row", () => {
    const html = renderToStaticMarkup(
      <ChakraProvider>
        <QuestionStatusLetters question={base} />
      </ChakraProvider>,
    )
    expect(html).toContain('role="img"')
    expect(html).toContain("Hypothesis: No hypothesis yet")
    expect(html.match(/>V</g)).toHaveLength(2)
  })
})
