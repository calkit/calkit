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
  "answer-stale": "the answer no longer matches its evidence",
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
      return "$(warning) Answer no longer matches its evidence";
    }
    return "$(warning) Changed since this was built";
  }
  if (components.some((c) => c.provenance === "undeclared")) {
    return "$(question) No provenance";
  }
  const stages = [...new Set(components.map((c) => c.stage).filter(Boolean))];
  if (stages.length === 0) {
    return undefined;
  }
  return `$(go-to-file) ${stages.join(", ")}`;
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
