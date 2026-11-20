/**
 * Running, saving, and syncing with Overleaf in one step, apart from VS
 * Code: whether a project syncs with Overleaf, and what to say when a step
 * stops because a file changed in two places.
 */
import type { CalkitInfo } from "../types";

/** A file changed in two places, on Overleaf or the project's remote. */
export interface Clash {
  kind: "overleaf" | "merge";
  files: string[];
}

/**
 * Whether a project syncs a folder with Overleaf, from its calkit.yaml or
 * the sync info kept on this machine.
 */
export function isSyncedWithOverleaf(
  info: CalkitInfo | undefined,
  hasSyncInfo: boolean,
): boolean {
  const synced = (info as { overleaf_sync?: unknown } | undefined)
    ?.overleaf_sync;
  return (
    hasSyncInfo ||
    (typeof synced === "object" &&
      synced !== null &&
      Object.keys(synced).length > 0) ||
    (info?.publications ?? []).some((pub) => Boolean(pub.overleaf))
  );
}

/**
 * What stopped a run, from what Git and an Overleaf sync left behind, or
 * nothing if no file is waiting to be combined.
 */
export function getClash(state: {
  overleafConflict: boolean;
  merging: boolean;
  unmerged: string[];
}): Clash | null {
  if (state.overleafConflict) {
    return { kind: "overleaf", files: state.unmerged };
  }
  if (state.merging) {
    return { kind: "merge", files: state.unmerged };
  }
  return null;
}

/** What to tell someone about a clash, naming where the other copy is. */
export function getClashMessage(clash: Clash, remoteUrl?: string): string {
  const where =
    clash.kind === "overleaf"
      ? "Overleaf"
      : remoteUrl?.includes("github.com")
      ? "GitHub"
      : "the project's remote";
  if (!clash.files.length) {
    return `Changes from ${where} are combined. Select Continue to finish.`;
  }
  const files =
    clash.files.length > 3
      ? `${clash.files.slice(0, 3).join(", ")}, and ` +
        `${clash.files.length - 3} more`
      : clash.files.join(", ");
  return (
    `${files} changed on ${where} and on this machine. ` +
    "Select what to keep in each marked part, then select Continue."
  );
}

/** The Calkit command that finishes combining, before running again. */
export function getContinueArgs(clash: Clash): string[] {
  return clash.kind === "overleaf"
    ? ["overleaf", "sync", "--resolve"]
    : ["merge", "--continue"];
}

/** A file a sync would send to Overleaf or delete there. */
export interface OverleafStatusFile {
  path: string;
  project_path: string;
  state: "new" | "modified" | "deleted";
}

/** What a sync of one folder would do, from `calkit overleaf status --json`. */
export interface OverleafFolderStatus {
  path: string;
  overleaf_url?: string | null;
  commits_from_overleaf: number;
  files_to_push: OverleafStatusFile[];
  files_to_delete: OverleafStatusFile[];
  in_sync: boolean;
}

/** What's known about the folders synced with Overleaf, as last checked. */
export interface OverleafState {
  statuses?: OverleafFolderStatus[];
  checking: boolean;
  error?: string;
  needsLogin?: boolean;
  // The synced folder whose sync stopped on a file changed in both places
  conflict?: string;
}

/** How a synced folder's row shows it: a codicon, short text, and tooltip. */
export interface OverleafRow {
  icon: string;
  description: string;
  tooltip: string;
  needsSync: boolean;
}

/** A synced folder's row, from its status and the state of the last check. */
export function getOverleafRow(
  status: OverleafFolderStatus,
  state: OverleafState,
): OverleafRow {
  const plural = (n: number, word: string) =>
    `${n} ${word}${n === 1 ? "" : "s"}`;
  if (state.conflict === status.path) {
    return {
      icon: "warning",
      description: "conflict",
      tooltip:
        "A file changed on Overleaf and on this machine. Select to resolve.",
      needsSync: true,
    };
  }
  const fromOverleaf = status.commits_from_overleaf;
  const toOverleaf = [...status.files_to_push, ...status.files_to_delete];
  const parts = [
    fromOverleaf ? `${plural(fromOverleaf, "change")} on Overleaf` : "",
    toOverleaf.length ? `${plural(toOverleaf.length, "file")} to push` : "",
  ].filter(Boolean);
  const files = toOverleaf.map(
    (f) =>
      `  ${f.project_path} (${
        status.files_to_delete.includes(f) ? "deleted" : f.state
      })`,
  );
  const tooltip = [
    status.overleaf_url ?? "",
    fromOverleaf
      ? `${plural(fromOverleaf, "change")} on Overleaf since last sync`
      : "",
    files.length ? `To push:\n${files.join("\n")}` : "",
  ]
    .filter(Boolean)
    .join("\n");
  const icon = state.checking
    ? "sync~spin"
    : fromOverleaf
    ? "cloud-download"
    : toOverleaf.length
    ? "cloud-upload"
    : "cloud";
  return {
    icon,
    description: parts.length
      ? parts.join(", ")
      : status.in_sync
      ? "in sync"
      : "not synced",
    tooltip,
    needsSync: !status.in_sync || parts.length > 0,
  };
}

/** Read `calkit overleaf status --json` output into the state it reports. */
export function parseOverleafStatus(stdout: string): OverleafState {
  try {
    const data = JSON.parse(stdout.trim().split("\n").pop() ?? "");
    if (Array.isArray(data.statuses)) {
      return { statuses: data.statuses, checking: false };
    }
    return {
      checking: false,
      error: String(data.error ?? "Couldn't check Overleaf"),
      needsLogin: Boolean(data.needs_login),
    };
  } catch {
    return { checking: false, error: "Couldn't check Overleaf" };
  }
}

/**
 * A commit message for the one file changed, as `calkit save -M` would
 * write it, e.g., "Update fit_rates.ipynb", from `git status --porcelain -z
 * -uall`, or nothing if more than one changed. Ignore rules don't count,
 * since saving touches them either way.
 */
export function getCommitMessageSuggestion(
  porcelain: string,
): string | undefined {
  const entries = porcelain.split("\0");
  const changes: { path: string; status: string }[] = [];
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    if (entry.length < 4) {
      continue;
    }
    const status = entry.slice(0, 2);
    // A rename or copy is followed by where it came from
    if (status[0] === "R" || status[0] === "C") {
      i++;
    }
    const path = entry.slice(3);
    if (path.split("/").pop() !== ".gitignore") {
      changes.push({ path, status });
    }
  }
  if (changes.length !== 1) {
    return undefined;
  }
  const [{ path, status }] = changes;
  const added = status === "??" || status.includes("A");
  return `${added ? "Add" : "Update"} ${path}`;
}

/**
 * Quote an argument so bash, zsh, fish, and PowerShell all read it as one,
 * as it is, e.g., a commit message with `$` or a path with spaces, using a
 * typographic apostrophe for one that can't go in either kind of quote.
 */
export function quoteShellArg(arg: string): string {
  if (/^[\w@%+=:,./-]+$/.test(arg)) {
    return arg;
  }
  if (!arg.includes("'")) {
    return `'${arg}'`;
  }
  if (!/["$`!\\]/.test(arg)) {
    return `"${arg}"`;
  }
  return `'${arg.replace(/'/g, "\u2019")}'`;
}
