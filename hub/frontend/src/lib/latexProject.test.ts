import { describe, expect, it } from "vitest"

import { getLatexSourcePath, parseMapPathsRules } from "./latexProject"

const CALKIT_YAML = `pipeline:
  stages:
    figs-to-paper:
      kind: map-paths
      paths:
        - kind: dir-to-dir-replace
          src: figures
          dest: paper/figures/
        - kind: file-to-dir
          src: results/summary.pdf
          dest: paper/
        - kind: file-to-file
          src: assets/logo.png
          dest: paper/logo.png
    analyze:
      kind: python-script
      script_path: scripts/analyze.py
      environment: py
    build-paper:
      kind: latex
      target_path: paper/paper.tex
      environment: tex
`

describe("parseMapPathsRules", () => {
  it("reads every map-paths mapping and ignores other stages", () => {
    expect(parseMapPathsRules(CALKIT_YAML)).toEqual([
      { src: "figures", dest: "paper/figures", isDir: true },
      { src: "results/summary.pdf", dest: "paper/summary.pdf", isDir: false },
      { src: "assets/logo.png", dest: "paper/logo.png", isDir: false },
    ])
  })

  it("returns nothing for YAML without a pipeline, or invalid YAML", () => {
    expect(parseMapPathsRules("owner: calkit\nname: example\n")).toEqual([])
    expect(parseMapPathsRules("pipeline:\n  stages:\n    a: [oops\n")).toEqual(
      [],
    )
    expect(parseMapPathsRules("")).toEqual([])
  })

  it("skips mappings missing a src or dest", () => {
    const yaml = `pipeline:
  stages:
    s:
      kind: map-paths
      paths:
        - kind: file-to-file
          src: a.png
        - kind: file-to-file
          src: b.png
          dest: paper/b.png
`
    expect(parseMapPathsRules(yaml)).toEqual([
      { src: "b.png", dest: "paper/b.png", isDir: false },
    ])
  })
})

describe("getLatexSourcePath", () => {
  it("prefers the stage's target, resolved against its wdir", () => {
    expect(
      getLatexSourcePath({
        path: "paper/paper.pdf",
        calkit_stage: { kind: "latex", target_path: "paper.tex", wdir: "docs" },
      } as any),
    ).toBe("docs/paper.tex")
    expect(
      getLatexSourcePath({
        path: "paper/paper.pdf",
        calkit_stage: { kind: "latex", target_path: "paper/paper.tex" },
      } as any),
    ).toBe("paper/paper.tex")
    // A publication built by something other than LaTeX has no source to edit
    expect(
      getLatexSourcePath({
        path: "paper/paper.pdf",
        calkit_stage: { kind: "docx", target_path: "paper.docx" },
      } as any),
    ).toBeNull()
    // Without a stage, fall back to the output path's stem
    expect(
      getLatexSourcePath({
        path: "paper/paper.pdf",
        calkit_stage: null,
      } as any),
    ).toBe("paper/paper.tex")
  })
})
