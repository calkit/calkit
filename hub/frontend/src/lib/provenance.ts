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
 * A stage's inputs as its author declared them in calkit.yaml, with
 * another stage's outputs expanded to the paths they are.
 *
 * This is the list to show a person. dvc.yaml's deps also carry what
 * Calkit adds for itself (environment locks, the script), which is why
 * they aren't used here. Empty when the stage hasn't loaded or declares
 * none.
 */
interface StageIteration {
  arg_name: string | string[]
  values: unknown[]
}

interface CalkitStage {
  iterate_over?: StageIteration[] | null
  outputs?: (string | { path?: string })[] | null
}

/** The stages of a calkit.yaml, and its parameters, from its text. */
function parseCalkitYaml(text: string | null | undefined): {
  stages: Record<string, CalkitStage>
  parameters: Record<string, unknown>
} {
  if (!text) return { stages: {}, parameters: {} }
  try {
    const doc = (yamlLoad(text) ?? {}) as {
      pipeline?: { stages?: Record<string, CalkitStage> }
      parameters?: Record<string, unknown>
    }
    return {
      stages: doc.pipeline?.stages ?? {},
      parameters: doc.parameters ?? {},
    }
  } catch {
    return { stages: {}, parameters: {} }
  }
}

/** The values one `iterate_over` entry runs through, as Calkit expands them:
 * literals, `{range: {start, stop, step}}`, and `{parameter: name}` lists. */
function iterationValues(
  values: unknown[],
  parameters: Record<string, unknown>,
): unknown[] {
  const out: unknown[] = []
  const expandRange = (r: { start: number; stop: number; step: number }) => {
    const decimals = Math.max(
      ...[r.start, r.stop, r.step].map(
        (n) => (String(n).split(".")[1] ?? "").length,
      ),
    )
    for (let v = r.start; v < r.stop; v += r.step) {
      out.push(Number(v.toFixed(decimals)))
    }
  }
  for (const v of values) {
    if (v && typeof v === "object" && "range" in v) {
      expandRange(
        (v as { range: { start: number; stop: number; step: number } }).range,
      )
    } else if (v && typeof v === "object" && "parameter" in v) {
      const param = parameters[(v as { parameter: string }).parameter]
      for (const pv of Array.isArray(param) ? param : []) {
        if (pv && typeof pv === "object" && "range" in pv) {
          expandRange(
            (pv as { range: { start: number; stop: number; step: number } })
              .range,
          )
        } else {
          out.push(pv)
        }
      }
    } else {
      out.push(v)
    }
  }
  return out
}

/**
 * Every concrete path a templated one stands for, over a stage's
 * `iterate_over`.
 *
 * A stage that runs once per case writes its outputs with the case in the
 * path: `cases/{model}/postProcessing` in calkit.yaml, which DVC sees as
 * `cases/${item.model}/postProcessing`. Neither is a path that exists; the
 * combinations of the iterated arguments are. A path with no template, or
 * a stage with nothing to iterate, comes back as is.
 */
export function expandIteratedPaths(
  paths: string[],
  stage: CalkitStage | undefined,
  parameters: Record<string, unknown> = {},
): string[] {
  const iterations = stage?.iterate_over ?? []
  if (!iterations.length) return paths
  // Each iteration contributes a list of partial bindings; the stage runs
  // over their product.
  let combos: Record<string, unknown>[] = [{}]
  for (const it of iterations) {
    const names = Array.isArray(it.arg_name) ? it.arg_name : [it.arg_name]
    const bindings = iterationValues(it.values ?? [], parameters).map((v) => {
      const vals = Array.isArray(it.arg_name) ? (v as unknown[]) : [v]
      return Object.fromEntries(names.map((n, i) => [n, vals[i]]))
    })
    combos = combos.flatMap((c) => bindings.map((b) => ({ ...c, ...b })))
  }
  const single =
    iterations.length === 1 && !Array.isArray(iterations[0].arg_name)
      ? iterations[0].arg_name
      : null
  const fill = (path: string, combo: Record<string, unknown>) =>
    path
      .replace(/\$\{item\.([A-Za-z_][A-Za-z0-9_]*)\}/g, (m, name) =>
        name in combo ? String(combo[name]) : m,
      )
      .replace(/\$\{item\}/g, (m) => (single ? String(combo[single]) : m))
      .replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (m, name) =>
        name in combo ? String(combo[name]) : m,
      )
  const out: string[] = []
  for (const path of paths) {
    if (!/\$?\{/.test(path)) {
      out.push(path)
      continue
    }
    for (const combo of combos) {
      const filled = fill(path, combo)
      if (!out.includes(filled)) out.push(filled)
    }
  }
  return out
}

/**
 * A stage's inputs as declared in calkit.yaml, as concrete paths.
 *
 * `from_stage_outputs` is resolved through the other stage's declared
 * outputs, and the outputs of a stage that iterates are expanded to one
 * path per case, so what comes back can be fetched. calkit.yaml is the
 * source; the compiled dvc.yaml only stands in for a stage it lacks, and
 * without calkit.yaml, templated paths are left as they are.
 */
export function declaredInputs(
  stageYaml: string | undefined | null,
  dvcStages: Record<string, unknown> | undefined | null,
  calkitYaml?: string | null,
): string[] {
  if (!stageYaml) return []
  let parsed: { inputs?: unknown } = {}
  try {
    parsed = (yamlLoad(stageYaml) as { inputs?: unknown }) ?? {}
  } catch {
    return []
  }
  if (!Array.isArray(parsed.inputs)) return []
  const ck = parseCalkitYaml(calkitYaml)
  const paths: string[] = []
  for (const input of parsed.inputs) {
    if (typeof input === "string") {
      paths.push(input)
    } else if (input && typeof input === "object") {
      const item = input as { path?: string; from_stage_outputs?: string }
      if (item.from_stage_outputs) {
        // The other stage's outputs as calkit.yaml declares them; dvc.yaml
        // is only a fallback, for a stage calkit.yaml doesn't know.
        const name = item.from_stage_outputs
        const ckStage = ck.stages[name]
        const outs = ckStage
          ? (ckStage.outputs ?? []).flatMap((o) =>
              typeof o === "string" ? [o] : o?.path ? [o.path] : [],
            )
          : getStageOuts((dvcStages ?? {})[name] as DvcStage | undefined)
        paths.push(...expandIteratedPaths(outs, ckStage, ck.parameters))
      } else if (item.path) {
        paths.push(item.path)
      }
    }
  }
  return paths.filter((p) => Boolean(p)).map(normalizePath)
}
