import { describe, expect, it } from "vitest"

import {
  extractEnvRefs,
  extractFilePaths,
  findStageLineRange,
  looksLikePath,
} from "./pipelineYaml"

const CALKIT_YAML = `pipeline:
  stages:
    collect-data:
      kind: python-script
      script_path: scripts/collect.py
      environment: main
      outputs:
        - data/raw.csv
    run-on-cluster:
      kind: shell-command
      command: "python run.py"
      environment: slurm-env:py
    process-data:
      kind: python-script
      script_path: scripts/process.py
      environment: main
`

const DVC_YAML = `stages:
  collect-data:
    cmd: python scripts/collect.py
    deps:
      - scripts/collect.py
    outs:
      - data/raw.csv
`

describe("looksLikePath", () => {
  it("treats paths with slashes and file extensions as paths", () => {
    expect(looksLikePath("scripts/collect.py")).toBe(true)
    expect(looksLikePath("data/raw.csv")).toBe(true)
    expect(looksLikePath("Dockerfile.txt")).toBe(true)
  })

  it("rejects URLs, git remotes, names with spaces, and bare words", () => {
    expect(looksLikePath("https://example.com/x")).toBe(false)
    expect(looksLikePath("git@github.com:org/repo.git")).toBe(false)
    expect(looksLikePath("some thing")).toBe(false)
    expect(looksLikePath("main")).toBe(false)
    expect(looksLikePath("")).toBe(false)
  })
})

describe("extractFilePaths", () => {
  it("collects file-path-looking strings and keys", () => {
    const paths = extractFilePaths(CALKIT_YAML)
    expect(paths.has("scripts/collect.py")).toBe(true)
    expect(paths.has("data/raw.csv")).toBe(true)
    expect(paths.has("scripts/process.py")).toBe(true)
    // Plain env names / words are not paths.
    expect(paths.has("main")).toBe(false)
  })

  it("returns an empty set for invalid YAML", () => {
    expect(extractFilePaths(":\n  - [unbalanced").size).toBe(0)
  })
})

describe("extractEnvRefs", () => {
  it("collects every environment value, keeping composites whole", () => {
    const refs = extractEnvRefs(CALKIT_YAML)
    expect(refs.has("main")).toBe(true)
    expect(refs.has("slurm-env:py")).toBe(true)
    expect(refs.size).toBe(2)
  })

  it("does not collect non-environment keys", () => {
    const refs = extractEnvRefs(CALKIT_YAML)
    expect(refs.has("python-script")).toBe(false)
    expect(refs.has("scripts/collect.py")).toBe(false)
  })

  it("returns an empty set when there are no environment keys (dvc.yaml)", () => {
    expect(extractEnvRefs(DVC_YAML).size).toBe(0)
  })

  it("returns an empty set for invalid YAML", () => {
    expect(extractEnvRefs(":\n  - [unbalanced").size).toBe(0)
  })
})

describe("findStageLineRange", () => {
  it("returns the [start, end) line range covering the stage block", () => {
    const range = findStageLineRange(CALKIT_YAML, "collect-data")
    expect(range).not.toBeNull()
    const [start, end] = range!
    const lines = CALKIT_YAML.split("\n")
    expect(lines[start].trim()).toBe("collect-data:")
    // The block ends at the next sibling stage key.
    expect(lines[end].trim()).toBe("run-on-cluster:")
    // It contains the stage's environment line.
    const block = lines.slice(start, end)
    expect(block.some((l) => l.includes("environment: main"))).toBe(true)
  })

  it("works for dvc.yaml stages", () => {
    const range = findStageLineRange(DVC_YAML, "collect-data")
    expect(range).not.toBeNull()
    const [start] = range!
    expect(DVC_YAML.split("\n")[start].trim()).toBe("collect-data:")
  })

  it("returns null for an unknown stage", () => {
    expect(findStageLineRange(CALKIT_YAML, "does-not-exist")).toBeNull()
  })

  it("does not match a stage name that is only a substring of another", () => {
    // "data" should not match "collect-data" / "process-data".
    expect(findStageLineRange(CALKIT_YAML, "data")).toBeNull()
  })
})
