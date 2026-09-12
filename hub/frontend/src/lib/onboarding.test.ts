import { describe, expect, it } from "vitest"

import type { ReproCheck } from "../client"
import {
  type OnboardingStep,
  applyFlagLocally,
  buildAccountSteps,
  buildProjectSteps,
  isComplete,
  pipelineHasRun,
  progressPercent,
} from "./onboarding"

const emptyReproCheck = {
  has_pipeline: false,
  has_readme: false,
  instructions_in_readme: false,
  is_dvc_repo: false,
  is_git_repo: true,
  has_calkit_info: false,
  has_dev_container: false,
  n_environments: 0,
  n_stages: 0,
  stages_with_env: [],
  stages_without_env: [],
  n_datasets: 0,
  n_datasets_no_import_or_stage: 0,
  n_figures: 0,
  n_figures_no_import_or_stage: 0,
  n_publications: 0,
  n_publications_no_import_or_stage: 0,
  n_dvc_remotes: 0,
  recommendation: null,
  n_datasets_with_import_or_stage: 0,
  n_figures_with_import_or_stage: 0,
  n_publications_with_import_or_stage: 0,
  n_stages_without_env: 0,
  n_stages_with_env: 0,
} as unknown as ReproCheck

const stepByKey = (steps: OnboardingStep[], key: string) =>
  steps.find((step) => step.key === key)

describe("buildProjectSteps", () => {
  it("derives each step from project state and honors manual marks", () => {
    const emptyProject = buildProjectSteps({
      questionCount: 0,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: [],
    })
    expect(emptyProject.every((step) => !step.done)).toBe(true)
    expect(isComplete(emptyProject)).toBe(false)
    expect(progressPercent(emptyProject)).toBe(0)
    // No step depends on something we can't see: there is no "environment"
    // or "cloned locally" item to sit unchecked forever.
    expect(emptyProject.map((s) => s.key)).toEqual([
      "question",
      "dataset",
      "figure",
      "run",
      "publication",
      "editor",
    ])
    // Each signal ticks off exactly its own step.
    const withQuestion = buildProjectSteps({
      questionCount: 2,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: [],
    })
    expect(stepByKey(withQuestion, "question")?.done).toBe(true)
    expect(stepByKey(withQuestion, "dataset")?.done).toBe(false)
    const withFigure = buildProjectSteps({
      questionCount: 0,
      reproCheck: {
        ...emptyReproCheck,
        n_environments: 1,
        n_figures: 2,
        n_figures_with_import_or_stage: 1,
        n_publications: 1,
      },
      pipelineStatus: "stale",
      stageStatuses: { plot: { status: "stale" } },
      flags: [],
    })
    expect(stepByKey(withFigure, "figure")?.done).toBe(true)
    expect(stepByKey(withFigure, "publication")?.done).toBe(true)
    expect(stepByKey(withFigure, "dataset")?.done).toBe(false)
    // A stale pipeline has run but doesn't reflect the current code, so the
    // "run it" step stays open, worded as "again" since it has run before.
    expect(stepByKey(withFigure, "run")?.done).toBe(false)
    expect(stepByKey(withFigure, "run")?.title).toMatch(/again/)
    const neverRun = buildProjectSteps({
      questionCount: 0,
      reproCheck: emptyReproCheck,
      pipelineStatus: "stale",
      stageStatuses: { plot: { status: "not-run" } },
      flags: [],
    })
    expect(stepByKey(neverRun, "run")?.title).toMatch(/on your machine/)
    const upToDate = buildProjectSteps({
      questionCount: 0,
      reproCheck: emptyReproCheck,
      pipelineStatus: "up-to-date",
      stageStatuses: { plot: { status: "up-to-date" } },
      flags: [],
    })
    expect(stepByKey(upToDate, "run")?.done).toBe(true)
    // A flag marks any step done, which is how steps we can't detect (the
    // editor extensions) get completed at all.
    const flagged = buildProjectSteps({
      questionCount: 0,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: ["editor", "question"],
    })
    expect(stepByKey(flagged, "editor")?.done).toBe(true)
    expect(stepByKey(flagged, "question")?.done).toBe(true)
    expect(stepByKey(flagged, "figure")?.done).toBe(false)
  })

  it("knows whether the pipeline has ever run", () => {
    expect(pipelineHasRun(null)).toBe(false)
    expect(pipelineHasRun({})).toBe(false)
    expect(pipelineHasRun({ a: { status: "not-run" } })).toBe(false)
    expect(
      pipelineHasRun({ a: { status: "not-run" }, b: { status: "stale" } }),
    ).toBe(true)
    expect(pipelineHasRun({ a: { status: "up-to-date" } })).toBe(true)
    expect(pipelineHasRun({ a: { status: "frozen" } })).toBe(true)
  })

  it("distinguishes a mark the user made from something we detected", () => {
    const steps = buildProjectSteps({
      questionCount: 1,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: ["editor"],
    })
    // Detected: nothing to take back, so the mark isn't the user's to undo.
    expect(steps.find((s) => s.key === "question")?.manuallyDone).toBe(false)
    // Marked by hand: un-marking it would actually change something.
    expect(steps.find((s) => s.key === "editor")?.manuallyDone).toBe(true)
    // A step that's neither is undone and unmarked.
    expect(steps.find((s) => s.key === "run")?.manuallyDone).toBe(false)
    const account = buildAccountSteps({
      githubConnected: true,
      zoteroConnected: false,
      overleafConnected: false,
      cliRunning: false,
      projectCount: 0,
      flags: ["cli"],
    })
    expect(account.find((s) => s.key === "github")?.manuallyDone).toBe(false)
    expect(account.find((s) => s.key === "cli")?.manuallyDone).toBe(true)
    // A leftover mark on a step we now detect as done isn't the user's to
    // undo either: un-marking it would leave it done and look broken.
    const markedAndDetected = buildProjectSteps({
      questionCount: 1,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: ["question"],
    })
    const question = markedAndDetected.find((s) => s.key === "question")
    expect(question?.done).toBe(true)
    expect(question?.manuallyDone).toBe(false)
  })

  it("won't let a flag tick off a step our own records answer", () => {
    // Marking "start your first project" done can't make a project exist,
    // and the projects table on the same page would contradict it.
    const steps = buildAccountSteps({
      githubConnected: false,
      zoteroConnected: false,
      overleafConnected: false,
      cliRunning: false,
      projectCount: 0,
      flags: ["project", "github", "zotero", "overleaf", "cli"],
    })
    for (const key of ["project", "github", "zotero", "overleaf"]) {
      const step = steps.find((s) => s.key === key)
      expect(step?.detectedOnly).toBe(true)
      expect(step?.done).toBe(false)
      expect(step?.manuallyDone).toBe(false)
    }
    // The CLI check can be a false negative, so that one still takes a mark.
    expect(steps.find((s) => s.key === "cli")?.done).toBe(true)
  })

  it("treats a missing repro check as nothing done rather than crashing", () => {
    const steps = buildProjectSteps({
      questionCount: 1,
      reproCheck: null,
      flags: [],
    })
    expect(stepByKey(steps, "question")?.done).toBe(true)
    expect(stepByKey(steps, "dataset")?.done).toBe(false)
    expect(stepByKey(steps, "figure")?.done).toBe(false)
  })

  it("completes once every required step is done, optional or not", () => {
    const steps = buildProjectSteps({
      questionCount: 1,
      reproCheck: {
        ...emptyReproCheck,
        n_environments: 1,
        n_datasets: 1,
        n_figures_with_import_or_stage: 1,
        n_publications: 1,
      },
      pipelineStatus: "up-to-date",
      stageStatuses: { plot: { status: "up-to-date" } },
      flags: [],
    })
    // "editor" is optional and still undone, and the list is complete anyway.
    expect(stepByKey(steps, "editor")?.done).toBe(false)
    expect(isComplete(steps)).toBe(true)
    expect(progressPercent(steps)).toBeLessThan(100)
  })
})

describe("buildAccountSteps", () => {
  it("tracks connected accounts, the CLI, and the first project", () => {
    const fresh = buildAccountSteps({
      githubConnected: false,
      zoteroConnected: false,
      overleafConnected: false,
      cliRunning: false,
      projectCount: 0,
      flags: [],
    })
    expect(isComplete(fresh)).toBe(false)
    expect(stepByKey(fresh, "github")?.done).toBe(false)
    const partly = buildAccountSteps({
      githubConnected: true,
      zoteroConnected: true,
      overleafConnected: false,
      cliRunning: false,
      projectCount: 3,
      flags: [],
    })
    expect(stepByKey(partly, "github")?.done).toBe(true)
    expect(stepByKey(partly, "project")?.done).toBe(true)
    expect(stepByKey(partly, "zotero")?.done).toBe(true)
    expect(stepByKey(partly, "cli")?.done).toBe(false)
    // The browser extension can't be detected, so it's manual, and it's
    // optional, so it never holds the checklist open.
    const ext = stepByKey(partly, "browser_extension")
    expect(ext?.manual).toBe(true)
    expect(ext?.optional).toBe(true)
    expect(ext?.done).toBe(false)
    expect(partly.map((s) => s.key)).toEqual([
      "github",
      "project",
      "cli",
      "browser_extension",
      "overleaf",
      "zotero",
    ])
    // Overleaf and Zotero are optional, so the list finishes without them.
    const done = buildAccountSteps({
      githubConnected: true,
      zoteroConnected: false,
      overleafConnected: false,
      cliRunning: true,
      projectCount: 1,
      flags: [],
    })
    expect(isComplete(done)).toBe(true)
    // The CLI check is a local server that's usually down, so marking it by
    // hand has to work.
    const markedCli = buildAccountSteps({
      githubConnected: true,
      zoteroConnected: false,
      overleafConnected: false,
      cliRunning: false,
      projectCount: 1,
      flags: ["cli"],
    })
    expect(stepByKey(markedCli, "cli")?.done).toBe(true)
    expect(isComplete(markedCli)).toBe(true)
    // Marking the extension by hand is the only way it gets done.
    const markedExt = buildAccountSteps({
      githubConnected: true,
      zoteroConnected: false,
      overleafConnected: false,
      cliRunning: true,
      projectCount: 1,
      flags: ["browser_extension"],
    })
    const markedExtStep = stepByKey(markedExt, "browser_extension")
    expect(markedExtStep?.done).toBe(true)
    expect(markedExtStep?.manuallyDone).toBe(true)
  })
})

describe("applyFlagLocally", () => {
  it("adds and removes a step on the right list without touching the rest", () => {
    // Nothing cached yet: both lists start empty.
    const first = applyFlagLocally(undefined, null, "cli", true)
    expect(first).toEqual({ account: ["cli"], projects: {} })
    // Adding the same step twice doesn't duplicate it.
    expect(applyFlagLocally(first, null, "cli", true).account).toEqual(["cli"])
    // A project flag lands under that project and leaves the account alone.
    const withProject = applyFlagLocally(first, "p1", "editor", true)
    expect(withProject).toEqual({
      account: ["cli"],
      projects: { p1: ["editor"] },
    })
    // Another project's list is untouched by a change to this one.
    const twoProjects = applyFlagLocally(withProject, "p2", "question", true)
    expect(twoProjects.projects).toEqual({ p1: ["editor"], p2: ["question"] })
    // Removing takes only that step off only that list.
    const removed = applyFlagLocally(twoProjects, "p1", "editor", false)
    expect(removed.projects).toEqual({ p1: [], p2: ["question"] })
    expect(removed.account).toEqual(["cli"])
    expect(applyFlagLocally(removed, null, "cli", false).account).toEqual([])
    // Removing a step that isn't there is a no-op rather than an error.
    expect(applyFlagLocally(removed, "p3", "editor", false).projects).toEqual({
      p1: [],
      p2: ["question"],
      p3: [],
    })
    // The input isn't mutated, which is what a cache updater has to promise.
    expect(twoProjects.projects?.p1).toEqual(["editor"])
  })
})
