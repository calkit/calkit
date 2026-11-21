import assert from "node:assert/strict";
import test from "node:test";
import {
  alignQuestionChecks,
  lettersDescription,
  lettersTooltip,
  parseQuestionChecks,
  questionLetters,
  worstLetterState,
} from "../questions";
import type { QuestionCheck } from "../types";

function check(overrides: Partial<QuestionCheck> = {}): QuestionCheck {
  return {
    index: 1,
    question: "Does it work?",
    answered: true,
    status: "ok",
    evidence: [{ path: "results/fit.json", stage: "fit" }],
    hypothesis: true,
    approach: true,
    verifications: [],
    validations: [],
    verification_status: "none",
    validation_status: "none",
    ...overrides,
  };
}

test("parseQuestionChecks reads the report and nothing else", () => {
  // A failing check still prints the report; anything else is no checks
  assert.deepEqual(
    parseQuestionChecks(JSON.stringify({ questions: [check()] })),
    [check()],
  );
  for (const stdout of ["", "Usage: calkit check [OPTIONS]", "{}", "[]"]) {
    assert.deepEqual(parseQuestionChecks(stdout), [], stdout);
  }
});

test("alignQuestionChecks follows each merged question to its project", () => {
  const checks = [
    check({ index: 1 }),
    check({ index: 2, question: "Why?" }),
    check({ index: 1, project: "sub", question: "Sub?" }),
  ];
  // Origins are in merged order, and a subproject's path may be written
  // either way; a question with no check, e.g., a new one, gets none
  const aligned = alignQuestionChecks(checks, [
    { dir: ".", index: 2 },
    { dir: ".", index: 1 },
    { dir: "./sub/", index: 1 },
    { dir: "sub", index: 2 },
  ]);
  assert.deepEqual(
    aligned.map((c) => c?.question),
    ["Why?", "Does it work?", "Sub?", undefined],
  );
});

test("questionLetters gives each of H A V V the hub's state", () => {
  const states = (c: QuestionCheck, stale = new Set<string>()) =>
    questionLetters({ question: c.question }, c, stale).map((l) => l.state);
  // Nothing yet, then everything current
  assert.deepEqual(
    states(
      check({
        status: "unanswered",
        answered: false,
        hypothesis: false,
        evidence: [],
      }),
    ),
    ["none", "none", "none", "none"],
  );
  const signedOff = check({
    verification_status: "current",
    validation_status: "current",
    verifications: [{ by: "Ada", date: "2026-10-04", status: "current" }],
    validations: [
      {
        by: "Ada",
        date: "2026-10-04",
        status: "current",
        with_ai: ["Claude Opus 5"],
      },
    ],
  });
  assert.deepEqual(states(signedOff), ["ok", "ok", "ok", "ok"]);
  // Each kind of answer trouble, worst in red
  for (const [status, state] of [
    ["no-evidence", "stale"],
    ["stale", "stale"],
    ["frozen", "stale"],
    ["missing", "error"],
    ["error", "error"],
  ] as const) {
    assert.equal(states(check({ status }))[1], state, status);
  }
  // The check skips the pipeline, so a stage the sidebar knows is stale
  // makes the answer stale, qualified by subproject as the sidebar names it
  assert.equal(states(check(), new Set(["fit"]))[1], "stale");
  assert.equal(states(check({ project: "sub" }), new Set(["fit"]))[1], "ok");
  assert.equal(
    states(check({ project: "sub" }), new Set(["sub:fit"]))[1],
    "stale",
  );
  // A stale sign-off, with who and why in the detail
  const stale = check({
    validation_status: "stale",
    validations: [
      {
        by: "Ada",
        date: "2026-10-04",
        status: "stale",
        message: "the question was edited after it",
      },
    ],
  });
  const letters = questionLetters({ question: "Q?" }, stale, new Set());
  assert.equal(letters[3].state, "stale");
  assert.match(letters[3].detail, /Ada on 2026-10-04 \(stale: the question/);
  assert.equal(worstLetterState(letters), "stale");
  assert.equal(lettersDescription(letters), "H A · V!");
  const tooltip = lettersTooltip("Does x > 1?", letters);
  assert.match(tooltip, /^Does x \\> 1\?/);
  assert.match(
    tooltip,
    /<span style="color:var\(--vscode-charts-orange\);">\*\*V\*\*<\/span>/,
  );
  assert.match(tooltip, /- \*\*Validated\*\*: stale: Ada/);
  // Signed off with AI says so
  assert.match(
    questionLetters({ question: "Q?" }, signedOff, new Set())[3].detail,
    /with Claude Opus 5/,
  );
  // An older CLI reports neither the declared fields nor sign-offs, so the
  // hypothesis comes from calkit.yaml and the sign-offs read as not yet
  const old = check({
    hypothesis: undefined,
    verification_status: undefined,
    validation_status: undefined,
  });
  assert.deepEqual(
    questionLetters({ question: "Q?", hypothesis: "Yes." }, old, new Set()).map(
      (l) => l.state,
    ),
    ["ok", "ok", "none", "none"],
  );
});
