// The figure editor's pure parts: what a script saves, what it reads, how
// a starting script is written, and which project environment it runs in.
// Kept apart from the component so they can be tested without rendering
// (and without pulling in the PDF renderer the component uses).

import type { Environment } from "../client"

// Kinds a Python script can run in, most preferred first. Mirrors the
// backend's choice, so what the studio shows is what the stage gets.
const PYTHON_ENV_KINDS = ["uv", "uv-venv", "pixi", "conda", "venv"]

/** The project's Python environment the stage would run in, if any. */
export function pickPythonEnv(envs: Environment[]): Environment | null {
  for (const kind of PYTHON_ENV_KINDS) {
    const match = envs.find((e) => e.kind === kind)
    if (match) return match
  }
  return null
}

/**
 * Package names declared in an environment's spec file.
 *
 * Good enough to mirror the environment in the browser: one name per line
 * for requirements files, quoted entries for pyproject and pixi, dashed
 * entries for conda. Version pins and extras are dropped, since Pyodide
 * ships one version of each.
 */
export function envPackages(env: Environment | null): string[] {
  const text = env?.file_content ?? ""
  const names = new Set<string>()
  // YAML specs (conda) list channels and dependencies as sibling lists;
  // only the dependencies are packages.
  let section = ""
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    if (!line || line.startsWith("#") || line.startsWith("[")) continue
    if (/^[A-Za-z_-]+:\s*$/.test(line)) {
      section = line.slice(0, -1)
      continue
    }
    if (line.startsWith("-") && section && section !== "dependencies") continue
    const match = line.match(
      /^(?:-\s*)?["']?([A-Za-z0-9][A-Za-z0-9._-]*)["']?\s*(?:[<>=!~\[;, ]|$)/,
    )
    if (!match) continue
    const name = match[1].toLowerCase()
    if (
      ["python", "pip", "name", "version", "channels", "dependencies"].includes(
        name,
      )
    ) {
      continue
    }
    names.add(name)
  }
  return [...names]
}

/**
 * The path the script saves its figure to, read from the last save call.
 *
 * The script is the source of truth for where the figure lands, since that
 * is what the stage will run; the form only reflects it. Matplotlib's
 * savefig and plotly's write_json / write_html / write_image all count.
 */
export function savefigPath(code: string): string | null {
  const matches = [
    ...code.matchAll(
      /\.(?:savefig|write_json|write_html|write_image)\(\s*(?:(?:fname|file)\s*=\s*)?[rf]?(["'])([^"'\n]+)\1/g,
    ),
  ]
  const last = matches.at(-1)
  return last ? last[2] : null
}

export const stem = (path: string) =>
  (path.split("/").pop() ?? path).replace(/\.[^.]+$/, "")

export const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "figure"

export const isCsvPath = (path: string) => path.toLowerCase().endsWith(".csv")

// The lines the studio owns: a pandas load per CSV, and a marker naming
// every other input, since what opens an HDF5 file or a results folder is
// the script's business, not something to guess at.
const isLoadLine = (line: string) =>
  /^\s*df\d*\s*=\s*pd\.read_csv\(/.test(line) || /^\s*# Input: /.test(line)

const loadLines = (paths: string[]) => {
  const csvs = paths.filter(isCsvPath)
  return paths.map((path) => {
    if (!isCsvPath(path)) return `# Input: ${path}`
    const i = csvs.indexOf(path)
    return `${i === 0 ? "df" : `df${i + 1}`} = pd.read_csv(${JSON.stringify(path)})`
  })
}

/**
 * The script with its `df = pd.read_csv(...)` lines replaced for a new
 * dataset selection, everything else left as the user wrote it.
 *
 * The new lines go where the old ones were; a script with none yet gets
 * them after its imports.
 */
export function withDatasetLines(code: string, paths: string[]): string {
  const lines = code.split("\n")
  const first = lines.findIndex(isLoadLine)
  const kept = lines.filter((line) => !isLoadLine(line))
  const fresh = loadLines(paths)
  if (first !== -1) {
    kept.splice(first, 0, ...fresh)
    return kept.join("\n")
  }
  let lastImport = -1
  kept.forEach((line, i) => {
    if (/^\s*(import|from)\s/.test(line)) lastImport = i
  })
  kept.splice(lastImport + 1, 0, "", ...fresh)
  return kept.join("\n")
}

/** The files a script reads with pandas, from its read_csv calls. */
export function readCsvPaths(code: string): string[] {
  const found: string[] = []
  for (const match of code.matchAll(
    /\.read_csv\(\s*[rf]?(["'])([^"'\n]+)\1/g,
  )) {
    if (!found.includes(match[2])) found.push(match[2])
  }
  return found
}

/** A plotting script for the chosen datasets, as the starting point to edit. */
export function defaultScript({
  datasetPaths,
  figurePath,
  x,
  y,
}: {
  datasetPaths: string[]
  figurePath: string
  x?: string
  y?: string
}): string {
  const [first] = datasetPaths
  const lines = ["import matplotlib.pyplot as plt", "import pandas as pd", ""]
  // The first CSV is `df`; the rest count up from df2.
  lines.push(...loadLines(datasetPaths))
  lines.push("", "fig, ax = plt.subplots(figsize=(5, 3.5))")
  if (first && isCsvPath(first) && x && y) {
    lines.push(
      `ax.plot(df[${JSON.stringify(x)}], df[${JSON.stringify(y)}], "o")`,
      `ax.set_xlabel(${JSON.stringify(x)})`,
      `ax.set_ylabel(${JSON.stringify(y)})`,
    )
  } else if (first && isCsvPath(first)) {
    lines.push(
      "# Pick the columns to plot; df.columns lists them.",
      "df.plot(ax=ax)",
    )
  } else if (first) {
    lines.push("# Load the inputs named above and plot them here.")
  } else {
    lines.push("# Choose a dataset above, or load one here.")
  }
  lines.push(
    "fig.tight_layout()",
    `fig.savefig(${JSON.stringify(figurePath)}, dpi=150)`,
    "",
  )
  return lines.join("\n")
}
