// Helpers for the releases feature.

import type { ReleaseListItem } from "../client"

// Validate a release name as a Git tag name (a release becomes a Git tag and a
// calkit.yaml key), following Git's check-ref-format rules. Returns an error
// message, or undefined when valid, matching react-hook-form's validate API.
// Keep in sync with validate_release_name on the backend.
// biome-ignore lint/suspicious/noControlCharactersInRegex: matching Git's rule
const GIT_REF_FORBIDDEN = /[\s~^:?*[\\\x00-\x1f\x7f]/
export const validateReleaseName = (name: string): string | undefined => {
  const n = name.trim()
  if (!n) return "Name is required."
  if (GIT_REF_FORBIDDEN.test(n))
    return "Can't contain spaces or any of: ~ ^ : ? * [ \\"
  if (n === "@") return "Can't be '@'."
  if (n.startsWith("-")) return "Can't start with '-'."
  if (n.startsWith("/") || n.endsWith("/") || n.includes("//"))
    return "Can't start or end with '/' or contain '//'."
  if (n.endsWith(".")) return "Can't end with '.'."
  if (n.includes("..") || n.includes("@{")) return "Can't contain '..' or '@{'."
  for (const part of n.split("/")) {
    if (part.startsWith(".") || part.endsWith(".lock"))
      return "No part can start with '.' or end with '.lock'."
  }
  return undefined
}

// Build the in-app path to a release's page. Project members open it directly;
// a share recipient appends their ?token=... to view (and maybe comment)
// without signing up.
export const releasePagePath = (
  ownerName: string,
  projectName: string,
  releaseName: string,
  token?: string | null,
): string => {
  const base = `/${ownerName}/${projectName}/releases/${encodeURIComponent(
    releaseName,
  )}`
  return token ? `${base}?token=${encodeURIComponent(token)}` : base
}

// Absolute URL for a release page, using the current origin so it works across
// local/staging/prod without extra config.
export const releasePageUrl = (
  ownerName: string,
  projectName: string,
  releaseName: string,
  token?: string | null,
): string =>
  `${window.location.origin}${releasePagePath(
    ownerName,
    projectName,
    releaseName,
    token,
  )}`

// Pretty labels for known release locations (archival services / venues).
const LOCATION_LABELS: Record<string, string> = {
  zenodo: "Zenodo",
  caltechdata: "CaltechDATA",
  github: "GitHub",
  arxiv: "arXiv",
  osf: "OSF",
  figshare: "figshare",
  dryad: "Dryad",
}

// Where a release lives: "Calkit" (hosted for review) or the external venue it
// was published to (Zenodo, CaltechDATA, arXiv, …), with the off-site link when
// there is one.
export const releaseLocation = (
  r: ReleaseListItem,
): { label: string; internal: boolean; href: string | null } => {
  // Cloud (hosted) releases always carry internal=true, so the flag alone
  // decides this -- no need to special-case the source.
  if (r.internal) return { label: "Calkit", internal: true, href: null }
  const label = r.publisher
    ? LOCATION_LABELS[r.publisher.toLowerCase()] ?? r.publisher
    : "External"
  const href = r.url ?? (r.doi ? `https://doi.org/${r.doi}` : null)
  return { label, internal: false, href }
}

// The openable link for a release, if any: the Calkit-hosted page for a cloud
// release, otherwise the declared external URL or a DOI resolver. ``internal``
// marks the in-app page (same origin) vs an off-site link. Returns null when
// the release has no openable link.
export const releaseExternalLink = (
  r: ReleaseListItem,
  ownerName?: string,
  projectName?: string,
): { href: string; label: string; internal: boolean } | null => {
  if (r.source === "cloud" && ownerName && projectName)
    return {
      href: releasePagePath(ownerName, projectName, r.name),
      label: "release page",
      internal: true,
    }
  if (r.url)
    return {
      href: r.url,
      label: r.publisher === "github" ? "GitHub release" : "external release",
      internal: false,
    }
  if (r.doi)
    return { href: `https://doi.org/${r.doi}`, label: "DOI", internal: false }
  return null
}

// Format a release date for display, rounded to the nearest minute. Cloud
// releases carry a full timestamp (created.isoformat()); calkit.yaml releases
// carry a plain YYYY-MM-DD, which is shown as a date only.
export const formatReleaseDate = (date?: string | null): string => {
  if (!date) return "—"
  const hasTime = /[T ]\d{2}:\d{2}/.test(date)
  // A plain YYYY-MM-DD carries no time or zone; parse it as a local calendar
  // date so it isn't shifted a day for users west of UTC. (new Date("2026-06-24")
  // is UTC midnight, which toLocaleDateString() would render as the prior day.)
  // Match the date portion of the timestamped case below (dateStyle: "medium")
  // so tag/calkit.yaml releases and cloud releases read the same, just without
  // a time.
  if (!hasTime) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date.trim())
    if (m) {
      return new Date(
        Number(m[1]),
        Number(m[2]) - 1,
        Number(m[3]),
      ).toLocaleDateString(undefined, { dateStyle: "medium" })
    }
    const dateOnly = new Date(date)
    return Number.isNaN(dateOnly.getTime())
      ? date
      : dateOnly.toLocaleDateString(undefined, { dateStyle: "medium" })
  }
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) return date
  const rounded = new Date(Math.round(d.getTime() / 60000) * 60000)
  return rounded.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  })
}

// Build the download filename for a released artifact, matching the calkit CLI
// convention so a downloaded file traces back to its project and release:
// {project}-{stem}-{release}{ext} (e.g. adani-swarm-assessment-slides-v0.pdf).
export const releaseDownloadName = (
  projectName: string,
  releaseName: string,
  path: string,
): string => {
  const base = path.split("/").pop() ?? path
  const dot = base.lastIndexOf(".")
  const stem = dot > 0 ? base.slice(0, dot) : base
  const ext = dot > 0 ? base.slice(dot) : ""
  return `${projectName}-${stem}-${releaseName}${ext}`
}
