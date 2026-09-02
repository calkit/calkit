import type { PublicationComponent } from "./types";

// Pure helpers for the project content a document shows on the page, so
// they can be unit-tested without a page or an extension around them. The
// panel that renders them lives in content/overleaf.ts.
//
// Everything comes from the hub's publication components endpoint, which is
// the same resolver the CLI and the VS Code extension read, so a number in
// a paper has one account of where it came from wherever you ask.

// Worst first, since that's what needs doing; a component nothing could be
// checked about is not a problem, but it isn't a clean bill of health
// either, so it sits between.
const STATUS_RANK: Record<string, number> = {
  missing: 0,
  stale: 1,
  unknown: 2,
  ok: 3,
};

/** Sort components worst first, then by the file they came from. */
export function sortComponents(
  items: PublicationComponent[],
): PublicationComponent[] {
  const rank = (item: PublicationComponent) =>
    STATUS_RANK[item.status ?? "unknown"] ?? STATUS_RANK.unknown;
  return [...items].sort(
    (a, b) =>
      rank(a) - rank(b) ||
      a.path.localeCompare(b.path) ||
      (a.key ?? "").localeCompare(b.key ?? ""),
  );
}

/** How to name a component: the file, and the key within it. */
export function componentLabel(item: PublicationComponent): string {
  return item.key ? `${item.path}: ${item.key}` : item.path;
}

const STALE_EXPLANATIONS: Record<string, string> = {
  "stage-out-of-date": "its stage needs a rerun",
  "changed-since-build": "the project has moved on since this was built",
  "answer-stale": "its evidence changed after the answer was written",
};

/**
 * What is wrong with a component, in terms someone editing a paper can act
 * on, or an empty string when nothing is.
 */
export function componentProblem(item: PublicationComponent): string {
  if (item.status === "missing") {
    return "the project no longer has this file";
  }
  const reasons = item.stale_reasons ?? [];
  if (reasons.length > 0) {
    return reasons
      .map((reason) => STALE_EXPLANATIONS[reason] ?? reason)
      .join(", and ");
  }
  if (item.provenance === "undeclared") {
    return "nothing produces this and nobody has said where it came from";
  }
  return "";
}

/**
 * The badge a component gets: what it is, in one word, and how loudly to
 * say it. Nothing for a component that is fine, since a panel listing
 * what needs attention shouldn't shout about what doesn't.
 */
export function componentBadge(
  item: PublicationComponent,
): { text: string; level: "danger" | "warn" | "dim" } | null {
  if (item.status === "missing") return { text: "missing", level: "danger" };
  if (item.status === "stale") return { text: "out of date", level: "warn" };
  if (item.provenance === "undeclared")
    return { text: "no provenance", level: "warn" };
  if (item.status === "unknown") return { text: "unchecked", level: "dim" };
  return null;
}

/**
 * A line summarizing what a document's components need, for the panel
 * header. Empty when there is nothing to say.
 */
export function componentsSummary(items: PublicationComponent[]): string {
  const stale = items.filter(
    (item) => item.status === "stale" || item.status === "missing",
  ).length;
  const undeclared = items.filter(
    (item) => item.provenance === "undeclared" && item.status !== "missing",
  ).length;
  const parts: string[] = [];
  if (stale) parts.push(`${stale} out of date`);
  if (undeclared) parts.push(`${undeclared} with no provenance`);
  return parts.join(", ");
}

/**
 * Where in the hub to go to change a component: the script that produces
 * it when there is one, otherwise the file itself. This is the "jump into
 * a mode to edit it" step -- Overleaf can't run the pipeline, so the
 * project is where the change is made.
 */
export function editUrl(
  hubWebUrl: string,
  owner: string,
  project: string,
  item: PublicationComponent,
): string {
  const base = `${hubWebUrl}/${owner}/${project}`;
  if (item.script) {
    return `${base}/files?path=${encodeURIComponent(item.script)}`;
  }
  if (item.stage) {
    return `${base}/pipeline?stage=${encodeURIComponent(item.stage)}`;
  }
  return `${base}/files?path=${encodeURIComponent(item.path)}`;
}

/** What a value reads as, for a panel row. */
export function valueText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
