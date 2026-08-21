import { describe, expect, it } from "vitest"

import type { Dataset, Figure } from "../client"
import {
  classifyPublicationDeps,
  findFeederStages,
  getStageDeps,
  getStageOuts,
  isPathUnder,
  matchDepsToDatasets,
  normalizePath,
  declaredInputs,
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

describe("findFeederStages", () => {
  const dvcStages = {
    plot: { cmd: "python plot.py", outs: ["figures/plot.png"] },
    "figs-to-paper": {
      cmd: "calkit map-paths",
      deps: ["figures/plot.png"],
      outs: [{ "paper/figures/plot.png": { cache: false } }],
    },
    "data-to-paper": {
      cmd: "calkit map-paths",
      deps: ["results/table.csv"],
      outs: ["shared/table.csv"],
    },
    "copy-refs": { cmd: "cp", outs: ["paper/refs.bib"] },
    "build-paper": {
      cmd: "latexmk",
      deps: [
        "paper/paper.tex",
        "paper/figures/plot.png",
        "shared/table.csv",
        "paper/refs.bib",
        "figures/plot.png",
      ],
      outs: ["paper/paper.pdf"],
    },
  }

  it("names stages that copy inputs into the publication", () => {
    // figs-to-paper by name and by outs under paper/; copy-refs by outs
    // under paper/; data-to-paper by name only; plot feeds the build
    // directly but is neither named nor copying, so it isn't a feeder
    expect(
      findFeederStages("build-paper", dvcStages, "paper/paper.pdf"),
    ).toEqual(["copy-refs", "data-to-paper", "figs-to-paper"])
    // A publication at the repo root only matches by name
    expect(findFeederStages("build-paper", dvcStages, "paper.pdf")).toEqual([
      "data-to-paper",
      "figs-to-paper",
    ])
    // A stage without deps, or an unknown stage, has no feeders
    expect(findFeederStages("plot", dvcStages, "paper/paper.pdf")).toEqual([])
    expect(findFeederStages("missing", dvcStages, "paper/paper.pdf")).toEqual(
      [],
    )
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
