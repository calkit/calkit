import { describe, expect, it } from "vitest"

import {
  ENV_KINDS,
  PRESETS,
  buildEnvironment,
  buildSpecFile,
  defaultPathFor,
} from "./environments"

describe("defaultPathFor", () => {
  it("puts each kind's spec where that tool looks for it", () => {
    expect(defaultPathFor("uv", "main")).toBe("pyproject.toml")
    expect(defaultPathFor("pixi", "main")).toBe("pixi.toml")
    expect(defaultPathFor("conda", "main")).toBe("environment.yml")
    expect(defaultPathFor("renv", "main")).toBe("DESCRIPTION")
    expect(defaultPathFor("julia", "main")).toBe("Project.toml")
    expect(defaultPathFor("docker", "main")).toBe("Dockerfile")
    // Venv requirements nest per environment, so two of them in one project
    // don't collide at the repo root.
    expect(defaultPathFor("uv-venv", "analysis")).toBe(
      ".calkit/envs/analysis/requirements.txt",
    )
  })
})

describe("buildSpecFile", () => {
  const packages = ["pandas", "matplotlib"]

  it("writes each kind in the format its tool reads", () => {
    const uv = buildSpecFile({
      name: "main",
      kind: "uv",
      packages,
      pythonVersion: "3.13",
    })
    expect(uv).toContain("[project]")
    expect(uv).toContain('requires-python = ">=3.13"')
    expect(uv).toContain('"pandas",')
    const pixi = buildSpecFile({ name: "main", kind: "pixi", packages })
    expect(pixi).toContain("[dependencies]")
    expect(pixi).toContain('pandas = "*"')
    const conda = buildSpecFile({
      name: "main",
      kind: "conda",
      packages,
      pythonVersion: "3.12",
    })
    expect(conda).toContain("name: main")
    expect(conda).toContain("  - python=3.12")
    expect(conda).toContain("  - pandas")
    // A requirements file is just the names, one per line.
    expect(buildSpecFile({ name: "m", kind: "uv-venv", packages })).toBe(
      "pandas\nmatplotlib\n",
    )
    const renv = buildSpecFile({
      name: "r-analysis",
      kind: "renv",
      packages: ["ggplot2", "dplyr"],
    })
    expect(renv).toContain("Package: r-analysis")
    expect(renv).toContain("Imports:")
    expect(renv).toContain("    ggplot2,")
    const docker = buildSpecFile({
      name: "m",
      kind: "docker",
      packages,
      image: "python:3.13-slim",
    })
    expect(docker).toContain("FROM python:3.13-slim")
    expect(docker).toContain("pip install")
  })

  it("leaves an empty requirements file commented rather than blank", () => {
    const empty = buildSpecFile({ name: "m", kind: "uv-venv", packages: [] })
    expect(empty).toContain("# One package per line")
  })

  it("does not invent UUIDs Julia would reject", () => {
    // Project.toml's [deps] maps names to UUIDs, which can't be produced
    // here, so the names are recorded as a comment for Pkg to resolve.
    const julia = buildSpecFile({
      name: "m",
      kind: "julia",
      packages: ["DataFrames"],
    })
    expect(julia).toContain("[deps]")
    expect(julia).toContain("# Packages to add: DataFrames")
    expect(julia).not.toMatch(/DataFrames\s*=\s*"/)
  })

  it("uses the image as the Docker base even with no packages", () => {
    const docker = buildSpecFile({
      name: "tex",
      kind: "docker",
      packages: [],
      image: "texlive/texlive:latest-full",
    })
    expect(docker).toBe("FROM texlive/texlive:latest-full\n")
  })
})

describe("buildEnvironment", () => {
  it("writes only the keys the chosen kind uses", () => {
    const uv = buildEnvironment({
      name: "main",
      kind: "uv",
      path: "pyproject.toml",
      packages: ["pandas"],
    })
    expect(uv.all_attrs).toEqual({ kind: "uv", path: "pyproject.toml" })
    // No stray image or prefix on a kind that has neither.
    expect(uv.all_attrs).not.toHaveProperty("image")
    expect(uv.all_attrs).not.toHaveProperty("prefix")
    const venv = buildEnvironment({
      name: "analysis",
      kind: "uv-venv",
      path: ".calkit/envs/analysis/requirements.txt",
      packages: [],
      pythonVersion: "3.12",
    })
    // The virtualenv sits beside its requirements file, so removing the
    // environment is removing one directory.
    expect(venv.all_attrs.prefix).toBe(".calkit/envs/analysis/.venv")
    expect(venv.all_attrs.python).toBe("3.12")
    const docker = buildEnvironment({
      name: "tex",
      kind: "docker",
      path: "Dockerfile",
      packages: [],
      image: "texlive/texlive:latest-full",
    })
    expect(docker.all_attrs.image).toBe("texlive/texlive:latest-full")
    const julia = buildEnvironment({
      name: "j",
      kind: "julia",
      path: "Project.toml",
      packages: [],
    })
    // The model requires a version for Julia.
    expect(julia.all_attrs.julia).toBeDefined()
  })

  it("carries a description only when there is one", () => {
    const without = buildEnvironment({
      name: "m",
      kind: "uv",
      path: "pyproject.toml",
      packages: [],
    })
    expect(without.all_attrs).not.toHaveProperty("description")
    const with_ = buildEnvironment({
      name: "m",
      kind: "uv",
      path: "pyproject.toml",
      description: "For analysis",
      packages: [],
    })
    expect(with_.all_attrs.description).toBe("For analysis")
  })
})

describe("presets", () => {
  it("names a kind that exists and carries what that kind needs", () => {
    const kinds = new Set(ENV_KINDS.map((k) => k.kind))
    for (const preset of PRESETS) {
      expect(kinds.has(preset.kind)).toBe(true)
      expect(preset.envName).toBeTruthy()
      // A Docker preset without an image would fail validation on submit.
      if (preset.kind === "docker") {
        expect(preset.image).toBeTruthy()
      } else {
        expect(preset.packages?.length).toBeGreaterThan(0)
      }
    }
  })

  it("defaults Python to uv, with pixi, uv-venv, and conda after it", () => {
    expect(ENV_KINDS[0].kind).toBe("uv")
    const order = ENV_KINDS.map((k) => k.kind)
    expect(order.indexOf("pixi")).toBeLessThan(order.indexOf("uv-venv"))
    expect(order.indexOf("uv-venv")).toBeLessThan(order.indexOf("conda"))
  })
})
