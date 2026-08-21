/**
 * Provenance helpers: what went into an artifact, read off its pipeline
 * stage's concrete inputs (the deps compiled into dvc.yaml) rather than
 * anything the artifact declares about itself.
 */
import { load as yamlLoad } from "js-yaml"
import type {
  Dataset,
  DvcForeachStage,
  DvcPipelineStage,
  Figure,
} from "../client"

export type DvcStage = DvcPipelineStage | DvcForeachStage

const DATA_SUFFIXES = new Set([
  "csv",
  "parquet",
  "h5",
  "hdf5",
  "nc",
  "json",
  "xlsx",
  "npz",
  "mat",
])

const FIGURE_SUFFIXES = new Set([
  "png",
  "jpg",
  "jpeg",
  "svg",
  "pdf",
  "gif",
  "webp",
  "eps",
  "tif",
  "tiff",
])

// LaTeX sources that are inputs to a build but never worth listing as
// "what went into" a publication.
const LATEX_SOURCE_SUFFIXES = new Set(["tex", "cls", "sty", "bst"])

/** Strips a leading "./" and any trailing slashes so paths compare cleanly. */
export function normalizePath(path: string): string {
  let p = path.trim()
  while (p.startsWith("./")) p = p.slice(2)
  while (p.length > 1 && p.endsWith("/")) p = p.slice(0, -1)
  return p
}

function getSuffix(path: string): string {
  const name = path.split("/").pop() ?? ""
  const dot = name.lastIndexOf(".")
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase()
}

/** True when `path` is `folder` itself or lives somewhere beneath it. */
export function isPathUnder(path: string, folder: string): boolean {
  const p = normalizePath(path)
  const f = normalizePath(folder)
  if (!f || f === ".") return false
  return p === f || p.startsWith(`${f}/`)
}

/** A stage's deps, whether it's a plain stage or a foreach one. */
export function getStageDeps(stage: DvcStage | null | undefined): string[] {
  if (!stage) return []
  const inner = "do" in stage ? stage.do : stage
  return (inner.deps ?? []).map(normalizePath)
}

/** A stage's out paths; outs may be bare strings or `{path: {flags}}`. */
export function getStageOuts(stage: DvcStage | null | undefined): string[] {
  if (!stage) return []
  const inner = "do" in stage ? stage.do : stage
  const outs: string[] = []
  for (const out of inner.outs ?? []) {
    if (typeof out === "string") outs.push(normalizePath(out))
    else for (const key of Object.keys(out)) outs.push(normalizePath(key))
  }
  return outs
}

export interface DatasetMatch {
  dataset: Dataset
  /** The dep that tied the stage to this dataset. */
  dep: string
}

export interface DataInputs {
  /** Deps that are (or live inside, or contain) a declared dataset. */
  declared: DatasetMatch[]
  /** Deps that look like data files but aren't declared datasets. */
  other: string[]
}

/**
 * Splits a stage's deps into declared datasets and other data-looking files.
 * A dep equal to a dataset path, under a dataset folder, or a folder that
 * contains a dataset, maps to that dataset; the most specific dataset wins
 * and each dataset is listed once.
 */
export function matchDepsToDatasets(
  deps: string[],
  datasets: Dataset[],
): DataInputs {
  const declared: DatasetMatch[] = []
  const seenDatasets = new Set<string>()
  const other: string[] = []
  const seenOther = new Set<string>()
  for (const rawDep of deps) {
    const dep = normalizePath(rawDep)
    if (!dep || dep === ".") continue
    // Prefer the dataset whose path is longest, i.e., most specific.
    const matches = datasets
      .filter((ds) => isPathUnder(dep, ds.path) || isPathUnder(ds.path, dep))
      .sort((a, b) => b.path.length - a.path.length)
    if (matches.length > 0) {
      for (const ds of matches) {
        // A folder dep can contain several datasets; list them all, but a
        // file dep under one dataset should only name that one.
        const key = normalizePath(ds.path)
        if (seenDatasets.has(key)) continue
        seenDatasets.add(key)
        declared.push({ dataset: ds, dep })
        if (isPathUnder(dep, ds.path)) break
      }
      continue
    }
    if (DATA_SUFFIXES.has(getSuffix(dep)) && !seenOther.has(dep)) {
      seenOther.add(dep)
      other.push(dep)
    }
  }
  return { declared, other }
}

export interface FigureInput {
  path: string
  /** Set when the dep is a figure declared in calkit.yaml. */
  figure?: Figure
}

export interface PublicationInputs {
  figures: FigureInput[]
  references: string[]
  other: string[]
}

/**
 * Sorts a publication stage's deps into figures, bibliography files, and
 * other inputs. LaTeX sources (.tex, .cls, .sty, .bst) are dropped since
 * they're the document itself rather than something that went into it.
 */
export function classifyPublicationDeps(
  deps: string[],
  figures: Figure[],
): PublicationInputs {
  const byPath = new Map(figures.map((f) => [normalizePath(f.path), f]))
  const result: PublicationInputs = { figures: [], references: [], other: [] }
  const seen = new Set<string>()
  for (const rawDep of deps) {
    const dep = normalizePath(rawDep)
    if (!dep || dep === "." || seen.has(dep)) continue
    seen.add(dep)
    const suffix = getSuffix(dep)
    const declared = byPath.get(dep)
    const folders = dep.split("/").slice(0, -1)
    const inFiguresFolder =
      folders.includes("figures") && FIGURE_SUFFIXES.has(suffix)
    if (declared || inFiguresFolder) {
      result.figures.push(
        declared ? { path: dep, figure: declared } : { path: dep },
      )
    } else if (suffix === "bib") {
      result.references.push(dep)
    } else if (!LATEX_SOURCE_SUFFIXES.has(suffix)) {
      result.other.push(dep)
    }
  }
  return result
}

/**
 * Names the stages that copy inputs into a publication's folder, e.g., a
 * `map-paths` stage like `figs-to-paper`. A stage counts when one of its
 * outs is a dep of the publication's stage and either its name contains
 * "to-paper" or its outs land under the publication's folder.
 */
export function findFeederStages(
  stageName: string,
  dvcStages: { [name: string]: DvcStage },
  publicationPath: string,
): string[] {
  const deps = getStageDeps(dvcStages[stageName])
  if (deps.length === 0) return []
  const pubFolder = normalizePath(publicationPath)
    .split("/")
    .slice(0, -1)
    .join("/")
  const feeders: string[] = []
  for (const [name, stage] of Object.entries(dvcStages)) {
    if (name === stageName) continue
    const outs = getStageOuts(stage)
    const feeds = outs.some((out) =>
      deps.some((dep) => isPathUnder(dep, out) || isPathUnder(out, dep)),
    )
    if (!feeds) continue
    const looksLikeCopy =
      name.includes("to-paper") ||
      (pubFolder !== "" && outs.some((out) => isPathUnder(out, pubFolder)))
    if (looksLikeCopy) feeders.push(name)
  }
  return feeders.sort()
}

/**
 * A stage's inputs as its author declared them in calkit.yaml, with
 * another stage's outputs expanded to the paths they are.
 *
 * This is the list to show a person. dvc.yaml's deps also carry what
 * Calkit adds for itself (environment locks, the script), which is why
 * they aren't used here. Empty when the stage hasn't loaded or declares
 * none.
 */
export function declaredInputs(
  stageYaml: string | undefined | null,
  dvcStages: Record<string, unknown> | undefined | null,
): string[] {
  if (!stageYaml) return []
  let parsed: { inputs?: unknown } = {}
  try {
    parsed = (yamlLoad(stageYaml) as { inputs?: unknown }) ?? {}
  } catch {
    return []
  }
  if (!Array.isArray(parsed.inputs)) return []
  const paths: string[] = []
  for (const input of parsed.inputs) {
    if (typeof input === "string") {
      paths.push(input)
    } else if (input && typeof input === "object") {
      const item = input as { path?: string; from_stage_outputs?: string }
      if (item.from_stage_outputs) {
        paths.push(
          ...getStageOuts(
            (dvcStages ?? {})[item.from_stage_outputs] as DvcStage | undefined,
          ),
        )
      } else if (item.path) {
        paths.push(item.path)
      }
    }
  }
  return paths.filter((p) => Boolean(p)).map(normalizePath)
}
