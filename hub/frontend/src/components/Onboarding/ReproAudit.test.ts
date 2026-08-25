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
  scripts_not_in_pipeline: [],
  n_scripts_not_in_pipeline: 0,
  misc_needing_provenance: [],
  n_misc_needing_provenance: 0,
  n_dvc_remotes: 0,
} as unknown as ReproCheck

const byKey = (check: ReproCheck) =>
  Object.fromEntries(auditFindings(check).map((f) => [f.key, f]))

describe("auditFindings", () => {
  it("reads an untouched repo as all gaps, in working order", () => {
    const findings = auditFindings(empty)
    expect(findings.map((f) => f.key)).toEqual([
      "pipeline",
      "scripts",
      "environment",
      "dataset",
      "figure",
      "misc",
      "publication",
      "readme",
    ])
    // Nothing to run and nothing generated is not a gap on its own; the
    // rest is.
    expect(findings.filter((f) => !f.ok).map((f) => f.key)).toEqual([
      "pipeline",
      "environment",
      "dataset",
      "figure",
      "publication",
      "readme",
    ])
    expect(findings[0].title).toBe("No pipeline yet")
  })

  it("names the files that a stage or a person should account for", () => {
    const found = byKey({
      ...empty,
      scripts_not_in_pipeline: ["scripts/plot.py"],
      n_scripts_not_in_pipeline: 1,
      misc_needing_provenance: ["figures/a.png", "report.pdf"],
      n_misc_needing_provenance: 2,
    })
    expect(found.scripts.ok).toBe(false)
    expect(found.scripts.title).toBe("1 script no stage runs")
    expect(found.scripts.paths).toEqual(["scripts/plot.py"])
    expect(found.misc.ok).toBe(false)
    expect(found.misc.title).toBe("2 generated files with no stated origin")
    expect(found.misc.paths).toEqual(["figures/a.png", "report.pdf"])
    // Older backends may send the list without the count
    const counted = byKey({
      ...empty,
      scripts_not_in_pipeline: ["a.py", "b.py"],
      n_scripts_not_in_pipeline: undefined,
    } as unknown as ReproCheck)
    expect(counted.scripts.title).toBe("2 scripts no stage runs")
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
