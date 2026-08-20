// What each kind of computational environment needs, and how to write one.
//
// The spec file is generated here rather than left to the user, because the
// gap between "I want pandas" and "a pyproject.toml with a dependencies
// array under [project]" is most of what makes setting up a reproducible
// environment feel like a chore.

import type { Environment } from "../client"

export type EnvKind =
  | "uv"
  | "pixi"
  | "uv-venv"
  | "conda"
  | "renv"
  | "julia"
  | "docker"

/** Named package sets, offered as one-click additions. */
export const PACKAGE_GROUPS: Record<string, string[]> = {
  // The same list the JupyterLab extension offers, so the two agree on what
  // "PyData" means.
  PyData: [
    "numpy",
    "scipy",
    "pandas",
    "polars",
    "pyarrow",
    "matplotlib",
    "statsmodels",
    "scikit-learn",
    "seaborn",
    "duckdb",
    "plotly",
    "altair",
    "bokeh",
  ],
  Notebooks: ["jupyterlab", "ipykernel"],
  Tidyverse: ["tidyverse", "ggplot2", "dplyr", "readr", "tidyr"],
  RMarkdown: ["knitr", "rmarkdown"],
  JuliaData: ["DataFrames", "CSV", "Plots", "Statistics"],
}

interface KindSpec {
  kind: EnvKind
  label: string
  hint: string
  /** Null when the kind has no spec file of its own. */
  defaultPath: string | null
  hasPath: boolean
  packageLabel?: string
  packagePlaceholder?: string
  packageGroups?: string[]
  needsImage?: boolean
  pythonVersion?: boolean
}

/**
 * Ordered by what to reach for first.
 *
 * uv leads because it's the fastest and needs the least explaining, then
 * pixi for anything beyond Python packages, then the older venv and conda
 * routes for projects that already use them.
 */
export const ENV_KINDS: KindSpec[] = [
  {
    kind: "uv",
    label: "Python (uv project)",
    hint: "Fastest, and locks to a uv.lock committed with the project.",
    defaultPath: "pyproject.toml",
    hasPath: true,
    packageLabel: "Python packages",
    packagePlaceholder: "Ex: pandas",
    packageGroups: ["PyData", "Notebooks"],
    pythonVersion: true,
  },
  {
    kind: "pixi",
    label: "Pixi (Python plus conda packages)",
    hint: "For dependencies that aren't only Python, e.g. compilers or GDAL.",
    defaultPath: "pixi.toml",
    hasPath: true,
    packageLabel: "Packages",
    packagePlaceholder: "Ex: gdal",
    packageGroups: ["PyData", "Notebooks"],
    pythonVersion: true,
  },
  {
    kind: "uv-venv",
    label: "Python (uv virtualenv from requirements.txt)",
    hint: "A plain requirements file, created with uv.",
    defaultPath: null,
    hasPath: true,
    packageLabel: "Python packages",
    packagePlaceholder: "Ex: pandas",
    packageGroups: ["PyData", "Notebooks"],
    pythonVersion: true,
  },
  {
    kind: "conda",
    label: "Conda",
    hint: "For projects already built around a conda environment file.",
    defaultPath: "environment.yml",
    hasPath: true,
    packageLabel: "Packages",
    packagePlaceholder: "Ex: scipy",
    packageGroups: ["PyData", "Notebooks"],
    pythonVersion: true,
  },
  {
    kind: "renv",
    label: "R (renv)",
    hint: "Packages are declared in DESCRIPTION and pinned in renv.lock.",
    defaultPath: "DESCRIPTION",
    hasPath: true,
    packageLabel: "R packages",
    packagePlaceholder: "Ex: ggplot2",
    packageGroups: ["Tidyverse", "RMarkdown"],
  },
  {
    kind: "julia",
    label: "Julia",
    hint: "Packages are resolved by Pkg the first time it runs.",
    defaultPath: "Project.toml",
    hasPath: true,
    packageLabel: "Julia packages",
    packagePlaceholder: "Ex: DataFrames",
    packageGroups: ["JuliaData"],
  },
  {
    kind: "docker",
    label: "Docker",
    hint: "A full image, for anything that isn't just a set of packages.",
    defaultPath: "Dockerfile",
    hasPath: true,
    needsImage: true,
    packageLabel: "Python packages to add to the image",
    packagePlaceholder: "Ex: pandas",
    packageGroups: ["PyData"],
  },
]

export interface Preset {
  name: string
  label: string
  kind: EnvKind
  envName: string
  packages?: string[]
  image?: string
}

/** Ready-made setups covering what most projects actually need. */
export const PRESETS: Preset[] = [
  {
    name: "pydata",
    label: "🐍 PyData—pandas, matplotlib, scikit-learn",
    kind: "uv",
    envName: "py",
    packages: [...PACKAGE_GROUPS.PyData],
  },
  {
    name: "pydata-notebooks",
    label: "📓 PyData with notebooks",
    kind: "uv",
    envName: "py",
    packages: [...PACKAGE_GROUPS.PyData, ...PACKAGE_GROUPS.Notebooks],
  },
  {
    name: "tidyverse",
    label: "📊 R analysis—tidyverse, knitr",
    kind: "renv",
    envName: "r",
    packages: [...PACKAGE_GROUPS.Tidyverse, ...PACKAGE_GROUPS.RMarkdown],
  },
  {
    name: "latex",
    label: "📄 LaTeX—full TeX Live in Docker",
    kind: "docker",
    envName: "latex",
    image: "texlive/texlive:latest-full",
  },
  {
    name: "julia",
    label: "🔬 Julia—DataFrames, Plots",
    kind: "julia",
    envName: "jl",
    packages: [...PACKAGE_GROUPS.JuliaData],
  },
]

/**
 * Where a kind's spec file goes by default.
 *
 * The venv kinds nest under .calkit/envs/{name}/ so several can coexist
 * without their requirements files colliding at the repo root.
 */
export function defaultPathFor(kind: EnvKind, envName: string): string {
  if (kind === "uv-venv") {
    return `.calkit/envs/${envName}/requirements.txt`
  }
  return ENV_KINDS.find((k) => k.kind === kind)?.defaultPath ?? ""
}

export interface BuildEnvironmentInput {
  name: string
  kind: EnvKind
  path: string
  description?: string
  packages: string[]
  image?: string
  pythonVersion?: string
}

/**
 * Turn the form's answers into the calkit.yaml entry and its spec file.
 *
 * `all_attrs` is written into calkit.yaml verbatim, so it carries exactly
 * the keys the chosen kind uses and nothing else.
 */
export function buildEnvironment({
  name,
  kind,
  path,
  description,
  packages,
  image,
  pythonVersion,
}: BuildEnvironmentInput): Environment {
  const attrs: Record<string, unknown> = { kind }
  if (path) {
    attrs.path = path
  }
  if (description) {
    attrs.description = description
  }
  if (kind === "uv-venv") {
    // Keeping the virtualenv beside its requirements file means removing
    // the environment is removing one directory.
    attrs.prefix = `.calkit/envs/${name}/.venv`
  }
  if (kind === "docker") {
    attrs.image = image
  }
  if (pythonVersion && (kind === "uv-venv" || kind === "conda")) {
    attrs.python = pythonVersion
  }
  if (kind === "julia") {
    // The model requires a version, and Pkg resolves against it.
    attrs.julia = "1"
  }
  return {
    name,
    kind,
    path: path || null,
    description: description || null,
    all_attrs: attrs,
    file_content: buildSpecFile({
      name,
      kind,
      packages,
      image,
      pythonVersion,
    }),
  }
}

/** The contents of the spec file for a kind, or null when it has none. */
export function buildSpecFile({
  name,
  kind,
  packages,
  image,
  pythonVersion,
}: {
  name: string
  kind: EnvKind
  packages: string[]
  image?: string
  pythonVersion?: string
}): string | null {
  const python = pythonVersion || "3.13"
  switch (kind) {
    case "uv":
      return [
        "[project]",
        `name = "${name}"`,
        'version = "0.1.0"',
        `requires-python = ">=${python}"`,
        `dependencies = [${packages.map((p) => `\n    "${p}",`).join("")}${
          packages.length ? "\n" : ""
        }]`,
        "",
      ].join("\n")
    case "pixi":
      return [
        "[project]",
        `name = "${name}"`,
        'channels = ["conda-forge"]',
        'platforms = ["linux-64", "osx-64", "osx-arm64", "win-64"]',
        "",
        "[dependencies]",
        `python = ">=${python}"`,
        ...packages.map((p) => `${p} = "*"`),
        "",
      ].join("\n")
    case "uv-venv":
      return packages.length
        ? `${packages.join("\n")}\n`
        : "# One package per line, e.g.\n# pandas\n# matplotlib\n"
    case "conda":
      return [
        `name: ${name}`,
        "channels:",
        "  - conda-forge",
        "dependencies:",
        `  - python=${python}`,
        ...packages.map((p) => `  - ${p}`),
        "",
      ].join("\n")
    case "renv":
      return [
        `Package: ${name}`,
        "Type: Project",
        `Title: Environment for ${name}`,
        "Version: 0.1.0",
        ...(packages.length
          ? [`Imports:\n${packages.map((p) => `    ${p}`).join(",\n")}`]
          : []),
        "",
      ].join("\n")
    case "julia":
      // Pkg fills in [deps] with UUIDs when it resolves, which can't be
      // done from here; the names are recorded as a comment so the intent
      // survives until then.
      return [
        ...(packages.length
          ? [`# Packages to add: ${packages.join(", ")}`]
          : []),
        "[deps]",
        "",
      ].join("\n")
    case "docker":
      return [
        `FROM ${image || "python:3.13-slim"}`,
        ...(packages.length
          ? [
              "",
              `RUN pip install --no-cache-dir \\\n    ${packages.join(
                " \\\n    ",
              )}`,
            ]
          : []),
        "",
      ].join("\n")
    default:
      return null
  }
}
