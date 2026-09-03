import * as path from "node:path";

// Pure helpers (no vscode imports) for the document components a Calkit
// project injects into a paper, so they can be unit-tested under plain
// `node --test` (where the `vscode` module is absent). The vscode-dependent
// providers live in view.ts.
//
// Everything here works off `calkit describe components --json`, which is the
// same resolver the hub and the browser extension read. Nothing parses LaTeX
// on this side beyond knowing which file the cursor is in.

export type ComponentKind = "value" | "figure" | "text" | "block";
export type ComponentStatus = "ok" | "stale" | "missing" | "unknown";
export type StaleReason =
  | "stage-out-of-date"
  | "changed-since-build"
  | "answer-stale";
export type Provenance =
  | "pipeline"
  | "imported"
  | "attested"
  | "project"
  | "undeclared";

export interface Location {
  source: string;
  line: number;
  column: number;
}

export interface Component {
  kind: ComponentKind;
  path: string;
  key: string | null;
  pages: number[];
  stage: string | null;
  stage_inputs: string[];
  script: string | null;
  provenance: Provenance;
  document_value: string | null;
  build_value: unknown;
  current_value: unknown;
  build_hash: string | null;
  current_hash: string | null;
  status: ComponentStatus;
  stale_reasons: StaleReason[];
  locations: Location[];
}

export interface DocumentComponents {
  /** What the build produced, e.g., the compiled PDF. */
  artifact?: string;
  /** Where a person edits it, for kinds of artifact that have one. */
  source?: string;
  kind?: string;
  built?: boolean;
  components: Component[];
}

// Whether a file is one this feature has anything to say about.
export function isLatexDocument(fsPath: string, languageId?: string): boolean {
  return languageId === "latex" || fsPath.toLowerCase().endsWith(".tex");
}

// Identity of a component within a document, so a positional lookup and a
// whole-document listing can be matched up.
export function componentId(component: Component): string {
  return `${component.kind} ${component.path} ${component.key ?? ""}`;
}

// A positional lookup runs without the pipeline status check, since it happens
// on every hover and that check shells out to DVC. The whole-document listing
// is cached and does run it, so its verdict is folded back in: what is out of
// date is a property of the artifact, not of where it appears in the source,
// and a component the listing checked should not read as unchecked here.
export function withCheckedStatus(
  found: Component[],
  cached: Component[] | undefined,
): Component[] {
  if (!cached || cached.length === 0) {
    return found;
  }
  const byId = new Map(cached.map((c) => [componentId(c), c]));
  return found.map((component) => {
    const known = byId.get(componentId(component));
    if (!known) {
      return component;
    }
    const reasons = [
      ...known.stale_reasons.filter(
        (reason) => !component.stale_reasons.includes(reason),
      ),
      ...component.stale_reasons,
    ];
    let status: ComponentStatus;
    if (component.status === "missing" || known.status === "missing") {
      status = "missing";
    } else if (reasons.length > 0) {
      status = "stale";
    } else if (component.status === "unknown") {
      // The listing checked what the position could not
      status = known.status;
    } else {
      status = component.status;
    }
    return { ...component, status, stale_reasons: reasons };
  });
}

// What a value reads as, for showing someone. The document's own typesetting
// wins, since that is what is on the page; the raw value is the fallback for a
// component the source hasn't been read for.
export function displayValue(component: Component): string | undefined {
  if (component.document_value) {
    return component.document_value;
  }
  if (
    component.current_value === null ||
    component.current_value === undefined
  ) {
    return undefined;
  }
  return typeof component.current_value === "object"
    ? JSON.stringify(component.current_value)
    : String(component.current_value);
}

const STALE_EXPLANATIONS: Record<StaleReason, string> = {
  "stage-out-of-date": "its stage needs a rerun",
  "changed-since-build": "the project has moved on since this was built",
  "answer-stale": "its evidence changed after the answer was written",
};

const PROVENANCE_NOTES: Record<Provenance, string | undefined> = {
  pipeline: undefined,
  project: undefined,
  imported: "Imported from elsewhere",
  attested: "Created by someone in this project",
  undeclared:
    "**No provenance.** Nothing produces this and nobody has said where it " +
    "came from. Running the pipeline will not fix it; it needs an entry in " +
    "`calkit.yaml`.",
};

// The lines of a hover, as Markdown. Kept here rather than in the provider so
// the wording is testable without a running editor.
export function hoverLines(component: Component): string[] {
  const lines: string[] = [];
  const shown = displayValue(component);
  if (component.kind === "value" && shown !== undefined) {
    lines.push(`**${shown}**`);
  } else if (component.kind === "block") {
    lines.push(`**Question ${component.key}**`);
  }
  lines.push(
    component.key
      ? `\`${component.path}\` -> \`${component.key}\``
      : `\`${component.path}\``,
  );
  if (component.stage) {
    lines.push(
      `Stage \`${component.stage}\`` +
        (component.script ? ` (\`${component.script}\`)` : ""),
    );
  }
  const note = PROVENANCE_NOTES[component.provenance];
  if (note) {
    lines.push(note);
  }
  if (component.status === "missing") {
    lines.push("**Missing.** The project no longer has this file.");
  } else if (component.stale_reasons.length > 0) {
    const why = component.stale_reasons
      .map((reason) => STALE_EXPLANATIONS[reason])
      .join(", and ");
    lines.push(`**Out of date** - ${why}.`);
    // Only worth showing the pair when the two actually differ, which is
    // exactly when the document drifted from the project
    if (
      component.stale_reasons.includes("changed-since-build") &&
      component.kind === "value" &&
      component.build_value !== null &&
      component.build_value !== undefined
    ) {
      lines.push(
        `Built with \`${String(component.build_value)}\`, now ` +
          `\`${String(component.current_value)}\`.`,
      );
    }
  }
  if (component.pages.length > 0) {
    const pages = component.pages.join(", ");
    lines.push(
      component.pages.length === 1 ? `Page ${pages}` : `Pages ${pages}`,
    );
  }
  return lines;
}

// The CodeLens title for a line's components: what is there, and whether any
// of it needs attention. Undefined when there is nothing worth a lens.
export function lensTitle(components: Component[]): string | undefined {
  if (components.length === 0) {
    return undefined;
  }
  const attention = components.filter(
    (c) => c.status === "stale" || c.status === "missing",
  );
  if (attention.length > 0) {
    if (attention.some((c) => c.status === "missing")) {
      return "$(error) Missing from the project";
    }
    const reasons = new Set(attention.flatMap((c) => c.stale_reasons));
    if (reasons.has("stage-out-of-date")) {
      const stages = [
        ...new Set(attention.map((c) => c.stage).filter(Boolean)),
      ];
      return `$(warning) Rerun ${stages.join(", ")}`;
    }
    if (reasons.has("answer-stale")) {
      return "$(warning) Evidence changed since the answer";
    }
    return "$(warning) Changed since this was built";
  }
  // Naming the stage, and saying a file has no provenance, are the other
  // lenses' jobs; a line that is fine needs no lens saying so
  return undefined;
}

/** What a line's component is, in the sidebar: an artifact, or a question. */
export interface ObjectLensTarget {
  path?: string;
  question?: string;
}

const OBJECT_ICONS: Record<ComponentKind, string> = {
  figure: "$(file-media)",
  value: "$(symbol-numeric)",
  text: "$(file)",
  block: "$(question)",
};

/**
 * The lens that opens what a line uses, in the sidebar.
 *
 * The stage lens says how a thing is made; this one says what it is. They
 * are different questions, and only the second has an answer for a figure
 * somebody drew or a question somebody wrote. The sidebar entry is also
 * the only place a file's origin can be recorded, so one that nothing
 * accounts for says so here, on the lens that goes where it is fixed.
 */
export function objectLensTitle(components: Component[]): string | undefined {
  const target = components[0];
  if (target === undefined) {
    return undefined;
  }
  if (target.kind === "block") {
    return target.key ? `$(question) Question ${target.key}` : undefined;
  }
  if (target.kind === "figure" && target.provenance === "undeclared") {
    return "$(warning) No provenance";
  }
  const name = target.key ?? target.path.split("/").pop() ?? target.path;
  return `${OBJECT_ICONS[target.kind]} ${name}`;
}

/** What that lens opens: an artifact by path, or a question by number. */
export function objectLensTarget(
  components: Component[],
): ObjectLensTarget | undefined {
  const target = components[0];
  if (target === undefined) {
    return undefined;
  }
  if (target.kind === "block") {
    return target.key ? { question: target.key } : undefined;
  }
  return { path: target.path };
}

/**
 * The lens that opens the stage behind a line, in the sidebar.
 *
 * Which stage made this, and from what, is a question about the pipeline,
 * and the sidebar is where the pipeline is: the script, the inputs and
 * the outputs are all there once the stage is selected. Naming it here
 * and opening it there beats restating any of it on a lens.
 */
export function stageLensTitle(components: Component[]): string | undefined {
  const stages = [...new Set(components.map((c) => c.stage).filter(Boolean))];
  if (stages.length === 0) {
    return undefined;
  }
  return `$(layers) ${stages.join(", ")}`;
}

/** The stages a line's components come from, in the order they appear. */
export function lensStages(components: Component[]): string[] {
  return [
    ...new Set(components.map((c) => c.stage).filter(Boolean)),
  ] as string[];
}

/** A problem with one component, at the place in the source that raised it. */
export interface ComponentDiagnostic {
  line: number;
  column: number;
  /** Editor severities, named so this file needs nothing from `vscode`. */
  severity: "error" | "warning" | "info";
  message: string;
  component: Component;
}

/**
 * What is wrong with a document's components, at the places that say it.
 *
 * A hover answers a question the reader thought to ask, and a lens sits on
 * a line already in view. Neither finds the paragraph on page nine whose
 * number went stale, which is the one worth finding, so the same facts are
 * reported as diagnostics: the editor collects them into Problems and a
 * writer sees the count without going looking.
 *
 * Only what is genuinely wrong. A component with no provenance is reported
 * because nothing else will ever catch it, but as information rather than a
 * warning: it may be perfectly fine and merely undeclared, and a squiggle
 * under every hand-made schematic would train people to ignore all of them.
 */
export function componentDiagnostics(
  components: Component[],
  source: string,
): ComponentDiagnostic[] {
  const diagnostics: ComponentDiagnostic[] = [];
  for (const component of components) {
    const problem = componentProblem(component);
    if (!problem) {
      continue;
    }
    for (const location of component.locations) {
      if (location.source !== source) {
        continue;
      }
      diagnostics.push({
        line: location.line - 1,
        column: Math.max(location.column - 1, 0),
        severity: problem.severity,
        message: problem.message,
        component,
      });
    }
  }
  return diagnostics;
}

/**
 * How much of a line a diagnostic should underline, from its column.
 *
 * The resolver points at where a component starts, which is the backslash
 * of the macro that injected it. Underlining the whole rest of the line
 * would cover the prose around it, so the macro and its arguments are
 * measured; anything else falls back to the rest of the line, which is
 * still better than a caret nobody can see.
 */
export function diagnosticSpan(lineText: string, column: number): number {
  const rest = lineText.slice(column);
  const macro = /^\\[a-zA-Z@]+(\[[^\]]*\])?(\{[^}]*\})?/.exec(rest);
  if (macro) {
    return macro[0].length;
  }
  return Math.max(rest.trimEnd().length, 1);
}

/** The one thing to say about a component, or nothing if it is fine. */
function componentProblem(
  component: Component,
): { severity: ComponentDiagnostic["severity"]; message: string } | undefined {
  const what = component.key
    ? `${component.path}:${component.key}`
    : component.path;
  if (component.status === "missing") {
    return {
      severity: "error",
      message:
        component.kind === "value"
          ? `${what} is no longer in the project, so this value has ` +
            "nothing behind it."
          : `${what} is no longer produced by the project.`,
    };
  }
  if (component.stale_reasons.length > 0) {
    const why = component.stale_reasons
      .map((reason) => STALE_EXPLANATIONS[reason])
      .join(", and ");
    // The pair is the whole point of the warning when the document drifted:
    // it says what the page claims and what the project now says instead
    const drift =
      component.stale_reasons.includes("changed-since-build") &&
      component.kind === "value" &&
      component.build_value !== null &&
      component.build_value !== undefined
        ? ` Built with ${String(component.build_value)}, now ` +
          `${String(component.current_value)}.`
        : "";
    return {
      severity: "warning",
      message: `${what} is out of date: ${why}.${drift}`,
    };
  }
  if (component.provenance === "undeclared") {
    return {
      severity: "warning",
      message:
        `Nothing in the project produces ${what} or says where it came ` +
        "from. Running the pipeline will not fix it; it needs an entry in " +
        "calkit.yaml.",
    };
  }
  return undefined;
}

// The questions half of the same idea: `calkit check questions --json`
// reports what a document cannot, because a broken answer is a fault in
// `calkit.yaml` rather than in the paper that typesets it.

export type QuestionStatus =
  | "ok"
  | "stale"
  | "error"
  | "unanswered"
  | "no-evidence";

export interface QuestionCheck {
  /** 1-based, matching `calkit list questions`. */
  index: number;
  question: string;
  answered: boolean;
  status: QuestionStatus;
  message?: string | null;
}

export interface QuestionsReport {
  questions: QuestionCheck[];
}

/** A problem with one question, at the line in `calkit.yaml` that declares it. */
export interface QuestionDiagnostic {
  line: number;
  severity: "error" | "warning" | "info";
  message: string;
}

const QUESTION_DEFAULT_MESSAGES: Record<QuestionStatus, string | undefined> = {
  ok: undefined,
  unanswered: undefined,
  stale:
    "The evidence has changed since this answer was last edited. Read it " +
    "again and edit the question, even if the answer still holds.",
  error: "This question's evidence could not be read as written.",
  "no-evidence":
    "This question is answered but cites no evidence, so there is nothing " +
    "to check the answer against.",
};

const QUESTION_SEVERITIES: Record<
  QuestionStatus,
  QuestionDiagnostic["severity"] | undefined
> = {
  ok: undefined,
  // Not yet answered is work outstanding, not a fault to report
  unanswered: undefined,
  stale: "warning",
  error: "error",
  "no-evidence": "info",
};

/**
 * Where each question sits in `calkit.yaml`, by its position in the list.
 *
 * Matching on the question's own text would be the obvious way and the
 * wrong one: `calkit.yaml` is written at 80 columns, so a question long
 * enough to be interesting is folded across lines and matches nothing.
 * The check numbers questions in file order, so counting list items finds
 * them whatever the prose does.
 */
export function questionLines(calkitYaml: string): number[] {
  const lines = calkitYaml.split(/\r?\n/);
  const start = lines.findIndex((line) => /^questions:\s*$/.test(line));
  if (start < 0) {
    return [];
  }
  const found: number[] = [];
  let itemIndent: number | undefined;
  for (let i = start + 1; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim() === "" || /^\s*#/.test(line)) {
      continue;
    }
    // A line back at the top level ends the block
    if (!/^\s/.test(line)) {
      break;
    }
    const item = /^(\s*)-\s/.exec(line);
    if (!item) {
      continue;
    }
    if (itemIndent === undefined) {
      itemIndent = item[1].length;
    }
    // Deeper dashes belong to a question's own lists, e.g. its evidence
    if (item[1].length === itemIndent) {
      found.push(i);
    }
  }
  return found;
}

/** What `calkit check questions` found, placed in `calkit.yaml`. */
export function questionDiagnostics(
  report: QuestionsReport,
  calkitYaml: string,
): QuestionDiagnostic[] {
  const lines = questionLines(calkitYaml);
  const diagnostics: QuestionDiagnostic[] = [];
  for (const question of report.questions ?? []) {
    const severity = QUESTION_SEVERITIES[question.status];
    const line = lines[question.index - 1];
    if (!severity || line === undefined) {
      continue;
    }
    diagnostics.push({
      line,
      severity,
      message:
        question.message ??
        QUESTION_DEFAULT_MESSAGES[question.status] ??
        `Question ${question.index} needs attention.`,
    });
  }
  return diagnostics;
}

/**
 * A figure reference in a source Calkit can't resolve fully, as a component.
 *
 * A Quarto or Markdown document has no provenance record and no generated
 * commands, so there is nothing to ask the resolver. What is still knowable
 * is which stage produces the file a figure reference points at, which is
 * enough for a lens that names the stage and offers to run it. Everything a
 * record would add -- pages, values, whether it is current -- is genuinely
 * unknown here, and says so.
 */
export function figureComponent(
  path: string,
  stage: string | undefined,
  source: string,
  line: number,
): Component {
  return {
    kind: "figure",
    path,
    key: null,
    pages: [],
    stage: stage ?? null,
    stage_inputs: [],
    script: null,
    provenance: stage ? "pipeline" : "undeclared",
    document_value: null,
    build_value: null,
    current_value: null,
    build_hash: null,
    current_hash: null,
    status: "unknown",
    stale_reasons: [],
    locations: [{ source, line, column: 1 }],
  };
}

// Group a document's components by the line of one source file they are
// written on, so a lens can be put on each such line from a single listing
// rather than by asking about every line in the document. Lines come back
// 0-based, as the editor counts them; the resolver counts from 1.
export function componentsByLine(
  components: Component[],
  source: string,
): Map<number, Component[]> {
  const byLine = new Map<number, Component[]>();
  for (const component of components) {
    for (const location of component.locations) {
      if (location.source !== source) {
        continue;
      }
      const line = location.line - 1;
      const existing = byLine.get(line);
      if (existing) {
        if (!existing.includes(component)) {
          existing.push(component);
        }
      } else {
        byLine.set(line, [component]);
      }
    }
  }
  return byLine;
}

// Where in a results file a value lives. A JSON or YAML key is found by
// looking for it, which lands the cursor in the right place without parsing
// the file properly; a key that isn't found just opens the file at the top.
export function definitionLine(
  fileText: string,
  key: string | null,
): number | undefined {
  if (!key) {
    return undefined;
  }
  // A key that exists literally wins, so one containing dots keeps working,
  // matching how the resolver looks it up. Otherwise it is walked into
  // nested output, where only the last part appears next to the value;
  // list indices name no key at all.
  const leaf = key
    .split(".")
    .filter((part) => !/^-?\d+$/.test(part))
    .pop();
  const lines = fileText.split(/\r?\n/);
  for (const candidate of leaf && leaf !== key ? [key, leaf] : [key]) {
    const quoted = candidate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(^|[{,\\s])"?${quoted}"?\\s*:`);
    for (let i = 0; i < lines.length; i++) {
      if (re.test(lines[i])) {
        return i;
      }
    }
  }
  return undefined;
}

// Turn a repo-relative path from the CLI into an absolute one.
export function toAbsolute(workspaceRoot: string, relPath: string): string {
  return path.join(workspaceRoot, relPath);
}
