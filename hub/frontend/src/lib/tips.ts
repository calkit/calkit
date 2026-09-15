/**
 * First-project tips: little bubbles over the things worth trying once a
 * project exists.
 *
 * Tips are tracked as onboarding flags on the project they belong to, so
 * what's been seen and done survives a new browser. One tip shows at a
 * time, in an order that follows the work: read the data, make a figure,
 * write it up, share it.
 */

export type TipId =
  | "view-dataset"
  | "edit-figure"
  | "edit-latex"
  | "publication"
  | "release"

export interface Tip {
  id: TipId
  /** Route suffix of the page where the tip's action lives. */
  page: string
  /** Sidebar item the tip points at from other pages. */
  nav: string
  title: string
  body: string
}

export const TIPS: Tip[] = [
  {
    id: "view-dataset",
    page: "/datasets",
    nav: "Datasets",
    title: "Try viewing a dataset",
    body: "Click a dataset's path to look through it right here, with no download.",
  },
  {
    id: "edit-figure",
    page: "/figures",
    nav: "Figures",
    title: "Try editing a figure",
    body: "Open a figure and click Edit figure to change its script and re-plot in your browser.",
  },
  {
    id: "edit-latex",
    page: "/publications",
    nav: "Publications",
    title: "Try the built-in LaTeX editor",
    body: "Click Edit LaTeX to change the source and rebuild the PDF right here, no TeX install needed.",
  },
  {
    id: "publication",
    page: "/publications",
    nav: "Publications",
    title: "Try creating or editing a publication",
    body: "Start a paper from a template, or edit the one that's here. It builds from the same pipeline as the figures.",
  },
  {
    id: "release",
    page: "/releases",
    nav: "Releases",
    title: "Ready to share? Create a release",
    body: "A release snapshots the project, or part of it, so others can cite exactly what you shared.",
  },
]

/** Every tip at once has been hidden for this project. */
export const TIPS_DISMISSED = "tips-dismissed"
/** One tip was acted on or waved away. */
export const tipDoneFlag = (id: TipId) => `tip-done:${id}`
/** Account-level: tips were reset on this project, which overrides the
 * first-project rule so a reset shows them where it was asked for. */
export const TIPS_PROJECT_PREFIX = "tips-project:"

/** The project tips belong on: where they were last reset, else the first. */
export function tipsProjectId(
  accountFlags: string[],
  firstProjectId: string | null | undefined,
): string | null {
  const reset = accountFlags.find((f) => f.startsWith(TIPS_PROJECT_PREFIX))
  if (reset) return reset.slice(TIPS_PROJECT_PREFIX.length)
  return firstProjectId ?? null
}

/** The tip to show on a project, given its flags; null when none is due. */
export function activeTip(projectFlags: string[]): Tip | null {
  if (projectFlags.includes(TIPS_DISMISSED)) return null
  return TIPS.find((t) => !projectFlags.includes(tipDoneFlag(t.id))) ?? null
}

/** Whether a page path is the one a tip's action lives on. */
export const onTipPage = (tip: Tip, pathname: string): boolean =>
  pathname.replace(/\/+$/, "").endsWith(tip.page)
