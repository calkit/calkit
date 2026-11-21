import type {
  QuestionCheck,
  QuestionEntry,
  SignOffCheck,
  SignOffStatus,
} from "./types";
import { qualifyName, type QuestionOrigin } from "./subprojects";

// The hub's colors for a question's status: gray for not there yet, green for
// present or current, orange for stale, red for missing or broken
export type LetterState = "none" | "ok" | "stale" | "error";

export interface QuestionLetter {
  letter: string;
  name: string;
  state: LetterState;
  // What the state means, and for a sign-off, who signed off
  detail: string;
}

// Theme colors matching the hub's green/orange/red, and gray for absent
export const LETTER_COLORS: Record<LetterState, string> = {
  none: "disabledForeground",
  ok: "charts.green",
  stale: "charts.orange",
  error: "charts.red",
};

const SEVERITY: LetterState[] = ["none", "ok", "stale", "error"];

// Subproject paths as both sides write them, e.g., "./sub/" and "sub"
function normalizeDir(dir: string | null | undefined): string {
  const trimmed = (dir ?? ".").replace(/^(\.\/)+/, "").replace(/\/+$/, "");
  return trimmed === "" ? "." : trimmed;
}

/**
 * Read `calkit check questions --json` output. The check exits nonzero when
 * any question fails, so the output is parsed either way, and anything that
 * isn't the report, e.g., from a CLI too old to have the command, reads as
 * no checks.
 */
export function parseQuestionChecks(stdout: string): QuestionCheck[] {
  try {
    const parsed = JSON.parse(stdout) as { questions?: unknown };
    return Array.isArray(parsed?.questions)
      ? (parsed.questions as QuestionCheck[])
      : [];
  } catch {
    return [];
  }
}

// Each merged question's check, in the merged order the sidebar numbers them
export function alignQuestionChecks(
  checks: QuestionCheck[],
  origins: QuestionOrigin[],
): (QuestionCheck | undefined)[] {
  const byOrigin = new Map<string, QuestionCheck>();
  for (const check of checks) {
    byOrigin.set(`${normalizeDir(check.project)}#${check.index}`, check);
  }
  return origins.map((o) => byOrigin.get(`${normalizeDir(o.dir)}#${o.index}`));
}

function signOffLetter(
  name: string,
  status: SignOffStatus | undefined,
  signOffs: SignOffCheck[] | undefined,
): QuestionLetter {
  const people = (signOffs ?? [])
    .map((s) => {
      const when = s.date ? ` on ${s.date}` : "";
      const ai = s.with_ai?.length ? ` with ${s.with_ai.join(", ")}` : "";
      const stale = s.status === "stale" ? ` (stale: ${s.message ?? ""})` : "";
      return `${s.by}${when}${ai}${stale}`;
    })
    .join("; ");
  if (status === "stale") {
    return { letter: "V", name, state: "stale", detail: `stale: ${people}` };
  }
  if (status === "current") {
    return { letter: "V", name, state: "ok", detail: people };
  }
  return { letter: "V", name, state: "none", detail: "not yet" };
}

/**
 * The "H A V V" row for a question: hypothesis, answer, verified, validated.
 *
 * The check is run without asking DVC which stages are stale, since the
 * extension already knows, so an answer citing a stage in `staleStageNames`
 * (qualified with its subproject, as the sidebar names stages) is stale too.
 */
export function questionLetters(
  question: string | QuestionEntry,
  check: QuestionCheck,
  staleStageNames: Set<string>,
): QuestionLetter[] {
  const entry = typeof question === "string" ? undefined : question;
  const hasHypothesis = check.hypothesis ?? !!entry?.hypothesis;
  const hypothesis: QuestionLetter = {
    letter: "H",
    name: "Hypothesis",
    state: hasHypothesis ? "ok" : "none",
    detail: hasHypothesis ? "stated" : "not yet",
  };
  const dir = normalizeDir(check.project);
  const staleStage = (check.evidence ?? [])
    .map((ev) => ev.stage)
    .find((stage) => !!stage && staleStageNames.has(qualifyName(dir, stage)));
  let answer: Pick<QuestionLetter, "state" | "detail">;
  switch (check.status) {
    case "unanswered":
      answer = { state: "none", detail: "not yet answered" };
      break;
    case "no-evidence":
      answer = { state: "stale", detail: "nothing is linked to back it up" };
      break;
    case "missing":
    case "error":
      answer = {
        state: "error",
        detail: check.message ?? `evidence is ${check.status}`,
      };
      break;
    case "stale":
    case "frozen":
      answer = {
        state: "stale",
        detail: check.message ?? `evidence is ${check.status}`,
      };
      break;
    default:
      answer = staleStage
        ? { state: "stale", detail: `stage ${staleStage} is out of date` }
        : { state: "ok", detail: "backed by current evidence" };
  }
  return [
    hypothesis,
    { letter: "A", name: "Answer", ...answer },
    signOffLetter("Verified", check.verification_status, check.verifications),
    signOffLetter("Validated", check.validation_status, check.validations),
  ];
}

// The worst state in the row, which colors the question's icon
export function worstLetterState(letters: QuestionLetter[]): LetterState {
  return letters.reduce<LetterState>(
    (worst, l) =>
      SEVERITY.indexOf(l.state) > SEVERITY.indexOf(worst) ? l.state : worst,
    "none",
  );
}

// Plain text for the tree item's description, which can't be colored: a
// letter for what's there, "·" for what isn't, and "!" after what's stale or
// broken
export function lettersDescription(letters: QuestionLetter[]): string {
  return letters
    .map((l) =>
      l.state === "none" ? "·" : l.state === "ok" ? l.letter : `${l.letter}!`,
    )
    .join(" ");
}

function escapeMarkdown(text: string): string {
  return text.replace(/[\\`*_{}[\]()#+\-.!|<>&]/g, (c) => `\\${c}`);
}

// Markdown with colored letters, for a tooltip that allows HTML spans
export function lettersTooltip(
  questionText: string,
  letters: QuestionLetter[],
): string {
  const row = letters
    .map(
      (l) =>
        `<span style="color:var(--vscode-${LETTER_COLORS[l.state].replace(
          ".",
          "-",
        )});">**${l.letter}**</span>`,
    )
    .join("&nbsp;");
  const lines = letters.map(
    (l) => `- **${l.name}**: ${escapeMarkdown(l.detail)}`,
  );
  return [escapeMarkdown(questionText), "", row, "", ...lines].join("\n");
}
