import { describe, expect, it } from "vitest"

import type { ReproCheck } from "../client"
import {
  buildAccountSteps,
  buildProjectSteps,
  isComplete,
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
} as ReproCheck

const stepByKey = (steps: { key: string; done: boolean }[], key: string) =>
  steps.find((step) => step.key === key)

describe("buildProjectSteps", () => {
  it("derives each step from project state and honors manual marks", () => {
    const emptyProject = buildProjectSteps({
      questionCount: 0,
      localConnected: false,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: [],
    })
    expect(emptyProject.every((step) => !step.done)).toBe(true)
    expect(isComplete(emptyProject)).toBe(false)
    expect(progressPercent(emptyProject)).toBe(0)
    // Each signal ticks off exactly its own step.
    const withQuestion = buildProjectSteps({
      questionCount: 2,
      localConnected: false,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: [],
    })
    expect(stepByKey(withQuestion, "question")?.done).toBe(true)
    expect(stepByKey(withQuestion, "environment")?.done).toBe(false)
    const withEnvAndFigure = buildProjectSteps({
      questionCount: 0,
      localConnected: true,
      reproCheck: {
        ...emptyReproCheck,
        n_environments: 1,
        n_figures: 2,
        n_figures_with_import_or_stage: 1,
        n_publications: 1,
      },
      pipelineStatus: "stale",
      flags: [],
    })
    expect(stepByKey(withEnvAndFigure, "local")?.done).toBe(true)
    expect(stepByKey(withEnvAndFigure, "environment")?.done).toBe(true)
    expect(stepByKey(withEnvAndFigure, "figure")?.done).toBe(true)
    expect(stepByKey(withEnvAndFigure, "publication")?.done).toBe(true)
    // A stale pipeline has run but doesn't reflect the current code, so the
    // "run it" step stays open.
    expect(stepByKey(withEnvAndFigure, "run")?.done).toBe(false)
    const upToDate = buildProjectSteps({
      questionCount: 0,
      localConnected: false,
      reproCheck: emptyReproCheck,
      pipelineStatus: "up-to-date",
      flags: [],
    })
    expect(stepByKey(upToDate, "run")?.done).toBe(true)
    // A flag marks any step done, which is how steps we can't detect (the
    // editor extensions) get completed at all.
    const flagged = buildProjectSteps({
      questionCount: 0,
      localConnected: false,
      reproCheck: emptyReproCheck,
      pipelineStatus: null,
      flags: ["editor", "question"],
    })
    expect(stepByKey(flagged, "editor")?.done).toBe(true)
    expect(stepByKey(flagged, "question")?.done).toBe(true)
    expect(stepByKey(flagged, "environment")?.done).toBe(false)
  })

  it("treats a missing repro check as nothing done rather than crashing", () => {
    const steps = buildProjectSteps({
      questionCount: 1,
      localConnected: false,
      reproCheck: null,
      flags: [],
    })
    expect(stepByKey(steps, "question")?.done).toBe(true)
    expect(stepByKey(steps, "environment")?.done).toBe(false)
    expect(stepByKey(steps, "figure")?.done).toBe(false)
  })

  it("completes once every required step is done, optional or not", () => {
    const steps = buildProjectSteps({
      questionCount: 1,
      localConnected: true,
      reproCheck: {
        ...emptyReproCheck,
        n_environments: 1,
        n_figures_with_import_or_stage: 1,
        n_publications: 1,
      },
      pipelineStatus: "up-to-date",
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
  })
})
