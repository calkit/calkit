import { describe, expect, it } from "vitest"

import type { ReproCheck } from "../../client"
import { auditFindings } from "./ReproAudit"

const empty = {
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
} as unknown as ReproCheck

const byKey = (check: ReproCheck) =>
  Object.fromEntries(auditFindings(check).map((f) => [f.key, f]))

describe("auditFindings", () => {
  it("reads an untouched repo as all gaps, in working order", () => {
    const findings = auditFindings(empty)
    expect(findings.map((f) => f.key)).toEqual([
      "pipeline",
      "environment",
      "dataset",
      "figure",
      "publication",
      "readme",
    ])
    expect(findings.every((f) => !f.ok)).toBe(true)
    expect(findings[0].title).toBe("No pipeline yet")
  })

  it("distinguishes partial from complete", () => {
    const partial = byKey({
      ...empty,
      has_pipeline: true,
      n_stages: 3,
      n_environments: 1,
      stages_without_env: ["plot"],
      n_datasets: 2,
      n_datasets_no_import_or_stage: 1,
      n_figures: 2,
      n_figures_no_import_or_stage: 0,
      n_publications: 1,
      has_readme: true,
      instructions_in_readme: false,
    })
    expect(partial.pipeline.ok).toBe(true)
    expect(partial.pipeline.title).toBe("A pipeline with 3 stages")
    // An environment exists, but a stage runs outside it: still a gap,
    // and the detail names the stage.
    expect(partial.environment.ok).toBe(false)
    expect(partial.environment.detail).toContain("plot")
    expect(partial.dataset.ok).toBe(false)
    expect(partial.dataset.title).toBe("1 of 2 datasets with no stated origin")
    expect(partial.figure.ok).toBe(true)
    expect(partial.figure.title).toBe("2 figures, all produced by the pipeline")
    expect(partial.publication.ok).toBe(true)
    expect(partial.readme.ok).toBe(false)
    const done = byKey({
      ...empty,
      has_pipeline: true,
      n_stages: 1,
      n_environments: 1,
      n_datasets: 1,
      n_figures: 1,
      n_publications: 1,
      has_readme: true,
      instructions_in_readme: true,
    })
    expect(Object.values(done).every((f) => f.ok)).toBe(true)
    expect(done.pipeline.title).toBe("A pipeline with 1 stage")
  })
})
