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
