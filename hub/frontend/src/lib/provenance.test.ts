import { describe, expect, it } from "vitest"

import type { Dataset, Figure } from "../client"
import {
  classifyPublicationDeps,
  getStageDeps,
  getStageOuts,
  isPathUnder,
  matchDepsToDatasets,
  normalizePath,
  declaredInputs,
  expandIteratedPaths,
} from "./provenance"

const datasets = [
  { path: "data/raw", title: "Raw measurements" },
  { path: "data/raw/special.csv", title: "Special run" },
  { path: "data/processed.parquet" },
] as Dataset[]

describe("path helpers", () => {
  it("normalizes and compares paths", () => {
    expect(normalizePath("./data/raw/")).toBe("data/raw")
    expect(normalizePath("data/raw")).toBe("data/raw")
    expect(normalizePath("/")).toBe("/")
    expect(isPathUnder("data/raw/a.csv", "data/raw")).toBe(true)
    expect(isPathUnder("data/raw", "data/raw")).toBe(true)
    // A shared prefix that isn't a folder boundary doesn't count
    expect(isPathUnder("data/rawer/a.csv", "data/raw")).toBe(false)
    // Neither does the repo root, which would match everything
    expect(isPathUnder("data/raw", "")).toBe(false)
    expect(isPathUnder("data/raw", ".")).toBe(false)
  })

  it("reads deps and outs from plain and foreach stages", () => {
    expect(getStageDeps(undefined)).toEqual([])
    expect(getStageOuts(null)).toEqual([])
    expect(
      getStageDeps({ cmd: "x", deps: ["./a.csv", "b/"], outs: null }),
    ).toEqual(["a.csv", "b"])
    expect(
      getStageDeps({
        foreach: ["1", "2"],
        do: { cmd: "x", deps: ["in/${item}.csv"] },
      }),
    ).toEqual(["in/${item}.csv"])
    // Outs may be bare strings or flag maps keyed by path
    expect(
      getStageOuts({
        cmd: "x",
        outs: ["figures/a.png", { "paper/figures/b.png": { cache: false } }],
      }),
    ).toEqual(["figures/a.png", "paper/figures/b.png"])
  })
})

describe("matchDepsToDatasets", () => {
  it("maps deps onto declared datasets and keeps other data files", () => {
    const result = matchDepsToDatasets(
      [
        "scripts/plot.py",
        "data/raw/run1.csv",
        "data/raw/run2.csv",
        "data/processed.parquet",
        "results/summary.json",
        "results/summary.json",
        "config.yaml",
      ],
      datasets,
    )
    // Two files under one dataset folder collapse into one entry
    expect(result.declared.map((m) => m.dataset.path)).toEqual([
      "data/raw",
      "data/processed.parquet",
    ])
    expect(result.declared[0].dep).toBe("data/raw/run1.csv")
    // Scripts and config aren't data; duplicates are listed once
    expect(result.other).toEqual(["results/summary.json"])
  })

  it("prefers the most specific dataset and expands folder deps", () => {
    // A file inside a nested dataset maps to the inner one only
    const nested = matchDepsToDatasets(["data/raw/special.csv"], datasets)
    expect(nested.declared.map((m) => m.dataset.path)).toEqual([
      "data/raw/special.csv",
    ])
    // A folder dep that contains datasets lists all of them, most specific
    // (longest path) first
    const folder = matchDepsToDatasets(["data"], datasets)
    expect(folder.declared.map((m) => m.dataset.path)).toEqual([
      "data/processed.parquet",
      "data/raw/special.csv",
      "data/raw",
    ])
    // The repo root and empty deps are ignored rather than matching all
    expect(matchDepsToDatasets(["", ".", "./"], datasets)).toEqual({
      declared: [],
      other: [],
    })
    expect(matchDepsToDatasets([], [])).toEqual({ declared: [], other: [] })
  })
})

describe("classifyPublicationDeps", () => {
  const figures: Figure[] = [
    { path: "figures/plot.png", title: "Plot", stage: "plot" },
  ]

  it("sorts deps into figures, references, and other inputs", () => {
    const result = classifyPublicationDeps(
      [
        "paper/paper.tex",
        "paper/template.cls",
        "paper/style.sty",
        "paper/refs.bst",
        "paper/refs.bib",
        "./figures/plot.png",
        "paper/figures/copied.pdf",
        "paper/figures/notes.txt",
        "results/table.csv",
        "results/table.csv",
      ],
      figures,
    )
    expect(result.figures).toEqual([
      { path: "figures/plot.png", figure: figures[0] },
      { path: "paper/figures/copied.pdf" },
    ])
    expect(result.references).toEqual(["paper/refs.bib"])
    // LaTeX sources are dropped; a non-image under figures/ is just an input
    expect(result.other).toEqual([
      "paper/figures/notes.txt",
      "results/table.csv",
    ])
  })

  it("handles no deps and no declared figures", () => {
    expect(classifyPublicationDeps([], [])).toEqual({
      figures: [],
      references: [],
      other: [],
    })
    // An image outside any figures/ folder is an input, not a figure
    expect(classifyPublicationDeps(["logo.png"], []).other).toEqual([
      "logo.png",
    ])
  })
})

describe("declaredInputs", () => {
  it("reads calkit.yaml inputs and expands another stage's outputs", () => {
    const dvcStages = {
      "figs-to-paper": { cmd: "x", outs: ["paper/figures/a.png"] },
    }
    const yaml = [
      "kind: latex",
      "inputs:",
      "  - paper/references.bib",
      "  - from_stage_outputs: figs-to-paper",
      "  - path: data/raw.csv",
      "outputs:",
      "  - paper/paper.pdf",
    ].join("\n")
    expect(declaredInputs(yaml, dvcStages)).toEqual([
      "paper/references.bib",
      "paper/figures/a.png",
      "data/raw.csv",
    ])
    // Nothing declared, not loaded, or unparseable: nothing listed
    expect(declaredInputs("kind: latex\n", dvcStages)).toEqual([])
    expect(declaredInputs(undefined, dvcStages)).toEqual([])
    expect(declaredInputs("::not yaml", dvcStages)).toEqual([])
  })
})

describe("expandIteratedPaths / declaredInputs with iterate_over", () => {
  const calkitYaml = `
parameters:
  models: [laminar, k-epsilon]
  res:
    - 1
    - range: {start: 2, stop: 4, step: 1}
pipeline:
  stages:
    run-sim:
      kind: python-script
      script_path: run.py
      iterate_over:
        - arg_name: model
          values: [{parameter: models}]
      outputs:
        - cases/{model}/postProcessing
    sweep:
      kind: python-script
      script_path: sweep.py
      iterate_over:
        - arg_name: [a, b]
          values: [[x, 1], [y, 2]]
        - arg_name: n
          values: [{range: {start: 0.5, stop: 1.5, step: 0.5}}]
      outputs:
        - out/{a}-{b}-{n}.csv
    plot:
      kind: python-script
      script_path: plot.py
      inputs:
        - from_stage_outputs: run-sim
        - from_stage_outputs: sweep
        - data/profiles.h5
`
  const dvcStages = {
    "run-sim": { outs: ["cases/${item.model}/postProcessing"] },
    sweep: { outs: ["out/${item.a}-${item.b}-${item.n}.csv"] },
  }
  it("expands every template form over the iterated values", () => {
    const stageYaml = `
kind: python-script
inputs:
  - from_stage_outputs: run-sim
  - from_stage_outputs: sweep
  - data/profiles.h5
`
    expect(declaredInputs(stageYaml, dvcStages, calkitYaml)).toEqual([
      "cases/laminar/postProcessing",
      "cases/k-epsilon/postProcessing",
      "out/x-1-0.5.csv",
      "out/x-1-1.csv",
      "out/y-2-0.5.csv",
      "out/y-2-1.csv",
      "data/profiles.h5",
    ])
    // Without the calkit.yaml text there is nothing to expand with, so the
    // template is left rather than guessed at
    expect(declaredInputs(stageYaml, dvcStages)).toEqual([
      "cases/${item.model}/postProcessing",
      "out/${item.a}-${item.b}-${item.n}.csv",
      "data/profiles.h5",
    ])
    // Plain paths pass through an iterating stage untouched, and a stage
    // with nothing to iterate returns its paths as they are
    expect(
      expandIteratedPaths(["fixed.txt", "${item}.txt"], {
        iterate_over: [{ arg_name: "k", values: ["p", "q"] }],
      }),
    ).toEqual(["fixed.txt", "p.txt", "q.txt"])
    expect(expandIteratedPaths(["a/{x}"], undefined)).toEqual(["a/{x}"])
  })
})
