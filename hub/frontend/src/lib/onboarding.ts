// Which onboarding steps a user has left to do, derived from real state.
//
// Nothing here stores progress. A step is done because the project actually
// has an environment, or the pipeline actually ran -- not because someone
// clicked a box. That way a checklist can't congratulate a user for work
// they undid, and a project set up entirely from the CLI shows up complete
// the first time its owner opens the page.
//
// The exception is work we have no way to see, like an editor extension
// installed on the user's laptop. Those steps carry `manual`, and the user
// marks them done; the mark is stored server-side as an onboarding flag.

import type { ReproCheck } from "../client"

export interface OnboardingStep {
  key: string
  title: string
  /** One line on why the step is worth doing. */
  detail: string
  done: boolean
  /**
   * Done because the user said so rather than because we detected it, which
   * is the only case where un-marking would change anything.
   */
  manuallyDone?: boolean
  /** True when only the user can say it's done, so we offer a "Mark done". */
  manual?: boolean
  /**
   * Our own records answer this one, so there's nothing a hand-mark could
   * add. Marking "start your first project" done wouldn't make a project
   * exist, and a checkbox that lies about the thing sitting on the same
   * page is worse than no checkbox.
   */
  detectedOnly?: boolean
  /** Nice to have, but doesn't hold the checklist open. */
  optional?: boolean
}

/** The flag that means "I'm finished with this checklist, hide it." */
export const DISMISSED = "dismissed"

export interface ProjectOnboardingInput {
  /** Research questions declared in calkit.yaml. */
  questionCount: number
  /** The local Calkit server can see this project, so it's cloned locally. */
  localConnected: boolean
  reproCheck?: ReproCheck | null
  pipelineStatus?: "up-to-date" | "stale" | "unknown" | null
  /** Steps this user has marked done or dismissed on this project. */
  flags: string[]
}

/**
 * The path from a fresh project to a reproducible one, as a checklist.
 *
 * Ordered the way the work actually happens: decide what you're asking,
 * get the project onto the machine that will do the computing, describe
 * that machine, make something, run it, and write it up.
 */
export function buildProjectSteps({
  questionCount,
  localConnected,
  reproCheck,
  pipelineStatus,
  flags,
}: ProjectOnboardingInput): OnboardingStep[] {
  const steps: OnboardingStep[] = [
    {
      key: "question",
      title: "Ask a research question",
      detail:
        "Write down what the project is trying to find out, and what you " +
        "expect the answer to be, before the analysis can talk you into one.",
      done: questionCount > 0,
    },
    {
      key: "local",
      title: "Get the project onto your machine",
      detail:
        "Install the CLI and clone it. Everything from here works offline " +
        "and in whatever editor you already use.",
      done: localConnected,
    },
    {
      key: "environment",
      title: "Define a computational environment",
      detail:
        "Pin what your code needs so it runs the same on your laptop, a " +
        "cluster, or a collaborator's machine. The spec lives in your repo, " +
        "not here.",
      done: (reproCheck?.n_environments ?? 0) > 0,
    },
    {
      key: "dataset",
      title: "Declare your data and where it came from",
      detail:
        "Data you collected, downloaded, or pulled from a DOI or repo. " +
        "Recording the source now is what lets anyone trace a figure back " +
        "to it later.",
      done: (reproCheck?.n_datasets ?? 0) > 0,
    },
    {
      key: "figure",
      title: "Produce a figure from a pipeline stage",
      detail:
        "Declare the stage that builds the figure, so the figure always " +
        "traces back to the code and data that made it.",
      done: (reproCheck?.n_figures_with_import_or_stage ?? 0) > 0,
    },
    {
      key: "run",
      title: "Run the pipeline and save the results",
      detail:
        "Run it end to end, then push what it made back here. Your repo " +
        "stays the source of truth; the hub makes it visible to everyone " +
        "else.",
      done: pipelineStatus === "up-to-date",
    },
    {
      key: "publication",
      title: "Link your paper",
      detail:
        "Start from a template or connect the Overleaf project you're " +
        "already writing in, so its figures stop drifting out of date.",
      done: (reproCheck?.n_publications ?? 0) > 0,
    },
    {
      key: "editor",
      title: "Set up your editor",
      detail:
        "The VS Code, JupyterLab, and browser extensions put the pipeline " +
        "and the hub where you're already working.",
      done: false,
      manual: true,
      optional: true,
    },
  ]
  // A user can mark any step done by hand, not just the manual ones -- a
  // project can satisfy a step in a way we don't detect, and arguing with
  // the person who set it up is not a good use of a checklist.
  return steps.map((step) => applyFlags(step, flags))
}

/** Fold a user's marks into a step, recording which ones they made. */
function applyFlags(step: OnboardingStep, flags: string[]): OnboardingStep {
  // A step we can see the answer to ignores flags outright, so a mark left
  // over from before it became detectable can't hold it checked.
  const marked = !step.detectedOnly && flags.includes(step.key)
  return { ...step, done: step.done || marked, manuallyDone: marked }
}

export interface AccountOnboardingInput {
  githubConnected: boolean
  zoteroConnected: boolean
  overleafConnected: boolean
  /** The local Calkit server answered, so the CLI is installed and running. */
  cliRunning: boolean
  projectCount: number
  flags: string[]
}

/** One-time account setup, shared by every project the user creates. */
export function buildAccountSteps({
  githubConnected,
  zoteroConnected,
  overleafConnected,
  cliRunning,
  projectCount,
  flags,
}: AccountOnboardingInput): OnboardingStep[] {
  const steps: OnboardingStep[] = [
    {
      key: "github",
      detectedOnly: true,
      title: "Connect your GitHub account",
      detail: "Calkit keeps a project's code and text in a Git repo there.",
      done: githubConnected,
    },
    {
      key: "project",
      detectedOnly: true,
      title: "Start your first project",
      detail:
        "Clean up something you're already working on, or start fresh from " +
        "a template.",
      done: projectCount > 0,
    },
    {
      key: "cli",
      title: "Install the Calkit CLI",
      detail:
        "The CLI is what runs pipelines and moves results between your " +
        "machine and the hub.",
      done: cliRunning,
      // The local server is usually not running even when the CLI is
      // installed, so an unanswered check is not evidence of absence.
      manual: true,
    },
    {
      key: "overleaf",
      title: "Connect Overleaf",
      detail: "Link papers you're already writing to the projects behind them.",
      done: overleafConnected,
      optional: true,
      detectedOnly: true,
    },
    {
      key: "zotero",
      title: "Connect Zotero",
      detail: "Import a collection and keep the project's .bib file in step.",
      done: zoteroConnected,
      optional: true,
      detectedOnly: true,
    },
  ]
  return steps.map((step) => applyFlags(step, flags))
}

/**
 * Whether a checklist has nothing required left on it.
 *
 * Optional steps are deliberately excluded: a user with no Overleaf paper
 * should still get to see the checklist finish.
 */
export function isComplete(steps: OnboardingStep[]): boolean {
  return steps.every((step) => step.done || step.optional)
}

/** Fraction of steps done, for the progress bar. Optional ones count. */
export function progressPercent(steps: OnboardingStep[]): number {
  if (!steps.length) return 0
  return Math.round(
    (steps.filter((step) => step.done).length / steps.length) * 100,
  )
}
