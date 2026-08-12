// Load the files a publication needs to compile in the browser. Driven by the
// publication's pipeline-stage deps when available (the authoritative list,
// including figures outside the .tex's own directory and DVC-tracked outputs),
// plus a scan of the .tex's own directory. Files are seeded at their full repo
// paths so relative refs like \includegraphics{../figures/x.png} resolve.
import jsYaml from "js-yaml"

import {
  type GetProjectContentsResponse,
  ProjectsService,
  type Publication,
} from "../client"
import { decodeBase64Utf8 } from "./strings"

// Resolve the LaTeX source path for a publication. Prefer the Calkit pipeline
// stage definition: a latex stage's target_path is the file to edit, relative
// to the stage's wdir (which defaults to the project root). A publication
// built by a non-latex stage has no LaTeX source to edit. Publications
// without a stage definition fall back to the output-path heuristic,
// e.g., paper.pdf -> paper.tex.
export function getLatexSourcePath(publication: Publication): string | null {
  const stage = publication.calkit_stage as
    | { kind?: string; target_path?: string; wdir?: string }
    | null
    | undefined
  if (stage) {
    if (stage.kind !== "latex" || !stage.target_path) {
      return null
    }
    const wdir = stage.wdir?.replace(/\/+$/, "")
    return wdir && wdir !== "."
      ? `${wdir}/${stage.target_path}`
      : stage.target_path
  }
  return publication.path ? publication.path.replace(/\.[^/.]+$/, ".tex") : null
}

const TEXT_EXT = new Set([
  "tex",
  "bib",
  "cls",
  "sty",
  "bst",
  "bbl",
  "ltx",
  "def",
  "clo",
  "cfg",
])
const IMG_EXT = new Set(["png", "jpg", "jpeg", "pdf", "eps", "gif"])
const SKIP_PREFIXES = [".calkit/", ".git/", ".dvc/"]
const MAX_FILES = 150
const MAX_DEPTH = 5

export interface ProjectFile {
  path: string
  kind: "text" | "binary"
  text?: string
  bytes?: Uint8Array
  // True when the pipeline writes this path (it was read from somewhere else),
  // so the editor must not offer to commit edits to it.
  generated?: boolean
}

// A path a map-paths stage produces, and where its content comes from. The
// destination of such a stage is written when the pipeline runs and is neither
// in Git nor in DVC storage (its DVC out is uncached), so reading it directly
// gets nothing — the source is the only place the content exists.
export interface MapPathsRule {
  src: string
  dest: string
  // Whether this maps a whole directory tree rather than a single file.
  isDir: boolean
}

function ext(p: string): string {
  const i = p.lastIndexOf(".")
  return i < 0 ? "" : p.slice(i + 1).toLowerCase()
}

function relevant(name: string): boolean {
  const e = ext(name)
  return TEXT_EXT.has(e) || IMG_EXT.has(e)
}

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) {
    out[i] = bin.charCodeAt(i)
  }
  return out
}

function trimSlashes(p: string): string {
  return p.replace(/^\/+|\/+$/g, "")
}

// Read every map-paths stage out of calkit.yaml as a destination -> source
// rule. Exported for unit testing.
export function parseMapPathsRules(calkitYaml: string): MapPathsRule[] {
  let doc: unknown
  try {
    doc = jsYaml.load(calkitYaml)
  } catch {
    return []
  }
  const stages = (doc as any)?.pipeline?.stages
  if (!stages || typeof stages !== "object") {
    return []
  }
  const rules: MapPathsRule[] = []
  for (const stage of Object.values(stages as Record<string, any>)) {
    if (stage?.kind !== "map-paths" || !Array.isArray(stage.paths)) {
      continue
    }
    for (const p of stage.paths) {
      const src = typeof p?.src === "string" ? trimSlashes(p.src) : ""
      const dest = typeof p?.dest === "string" ? trimSlashes(p.dest) : ""
      if (!src || !dest) {
        continue
      }
      if (p.kind === "file-to-file") {
        rules.push({ src, dest, isDir: false })
      } else if (p.kind === "file-to-dir") {
        // The copy keeps the source's filename inside the destination dir.
        rules.push({
          src,
          dest: `${dest}/${src.split("/").pop()}`,
          isDir: false,
        })
      } else {
        // dir-to-dir-merge and dir-to-dir-replace both mirror the tree.
        rules.push({ src, dest, isDir: true })
      }
    }
  }
  return rules
}

// Where to actually read a path whose content a map-paths stage produces, or
// null when nothing maps to it.
function mapToSource(path: string, rules: MapPathsRule[]): string | null {
  for (const rule of rules) {
    if (!rule.isDir) {
      if (path === rule.dest) {
        return rule.src
      }
    } else if (path === rule.dest) {
      return rule.src
    } else if (path.startsWith(`${rule.dest}/`)) {
      return rule.src + path.slice(rule.dest.length)
    }
  }
  return null
}

async function getContents(
  ownerName: string,
  projectName: string,
  path: string,
): Promise<GetProjectContentsResponse | null> {
  try {
    return await ProjectsService.getProjectContents({
      owner_name: ownerName,
      project_name: projectName,
      path: path || undefined,
    }).then((response) => response.data)
  } catch {
    return null
  }
}

// Walk a directory, accumulating repo path -> path to read its content from.
// The two differ only under a map-paths destination, where `virtualDir` is
// where the files belong for the compile and `dir` is where they really live.
async function listDir(
  ownerName: string,
  projectName: string,
  dir: string,
  depth: number,
  acc: Map<string, string>,
  virtualDir: string = dir,
): Promise<void> {
  if (depth > MAX_DEPTH || acc.size >= MAX_FILES) {
    return
  }
  const res = await getContents(ownerName, projectName, dir)
  if (!res) {
    return
  }
  for (const item of res.dir_items ?? []) {
    if (acc.size >= MAX_FILES) {
      break
    }
    const virtualPath =
      virtualDir === dir
        ? item.path
        : `${virtualDir}/${item.path.slice(dir.length + 1)}`
    if (item.type === "dir") {
      await listDir(
        ownerName,
        projectName,
        item.path,
        depth + 1,
        acc,
        virtualPath,
      )
    } else if (relevant(item.name)) {
      acc.set(virtualPath, item.path)
    }
  }
}

// Expand a pipeline-stage dep (a file or a directory) into concrete file paths.
async function expandDep(
  ownerName: string,
  projectName: string,
  dep: string,
  acc: Map<string, string>,
  rules: MapPathsRule[],
): Promise<void> {
  if (SKIP_PREFIXES.some((p) => dep.startsWith(p)) || dep.startsWith(".")) {
    return
  }
  let readPath = dep
  let res = await getContents(ownerName, projectName, dep)
  if (!res) {
    // A dep that isn't readable is often a map-paths destination, which only
    // exists after the pipeline has run — read the source it's copied from.
    const src = mapToSource(dep, rules)
    if (!src) {
      return
    }
    readPath = src
    res = await getContents(ownerName, projectName, src)
    if (!res) {
      return
    }
  }
  if (res.type === "dir") {
    await listDir(ownerName, projectName, readPath, 0, acc, dep)
  } else if (relevant(dep)) {
    acc.set(dep, readPath)
  }
}

async function fetchOne(
  ownerName: string,
  projectName: string,
  path: string,
  readPath: string = path,
): Promise<ProjectFile | null> {
  const res = await getContents(ownerName, projectName, readPath)
  if (!res) {
    return null
  }
  const generated = readPath !== path
  if (TEXT_EXT.has(ext(path))) {
    // Files over the API's inline-content size limit come back as a signed
    // URL with no `content` — fetch the text so large sources aren't empty.
    let text = ""
    if (res.content) {
      text = decodeBase64Utf8(res.content)
    } else if (res.url) {
      text = await (await fetch(res.url)).text()
    }
    return { path, kind: "text", text, generated }
  }
  let bytes: Uint8Array | null = null
  if (res.content) {
    bytes = base64ToBytes(res.content)
  } else if (res.url) {
    bytes = new Uint8Array(await (await fetch(res.url)).arrayBuffer())
  }
  if (!bytes) {
    return null
  }
  return { path, kind: "binary", bytes, generated }
}

export async function loadLatexProject(
  ownerName: string,
  projectName: string,
  texPath: string,
  deps?: string[] | null,
  opts?: { fresh?: boolean },
): Promise<ProjectFile[]> {
  // The content endpoint serves a cached server-side clone (default TTL), so a
  // plain load can miss others' just-pushed commits. When refreshing (the
  // editor's "Pull updates"), force one ttl=0 read first to make the server
  // re-pull from origin; that warms the cache so the reads below see the latest
  // without each re-pulling.
  if (opts?.fresh) {
    try {
      await ProjectsService.getProjectContents({
        owner_name: ownerName,
        project_name: projectName,
        ttl: 0,
      }).then((response) => response.data)
    } catch {
      // Best effort: if the refresh call fails, fall through to normal reads.
    }
  }
  // Repo path -> the path to read its content from; the same except under a
  // map-paths destination.
  const paths = new Map<string, string>([[texPath, texPath]])
  // Always read the pipeline, even with no deps to expand: a map-paths
  // destination inside the paper directory (example-basic copies `figures`
  // to `paper/figures`) is gitignored, so it appears in neither the deps nor
  // the directory scan, and the sweep below is the only thing that finds it.
  let rules: MapPathsRule[] = []
  try {
    const pipeline = await ProjectsService.getProjectPipeline({
      owner_name: ownerName,
      project_name: projectName,
    }).then((response) => response.data)
    if (pipeline?.calkit_yaml) {
      rules = parseMapPathsRules(pipeline.calkit_yaml)
    }
  } catch {
    // Best effort: without the pipeline, map-paths paths just don't resolve.
  }
  // Deps first (authoritative, and they can point outside the paper
  // directory), so they're never crowded out of the MAX_FILES budget by the
  // scans below.
  for (const dep of deps ?? []) {
    await expandDep(ownerName, projectName, dep, paths, rules)
  }
  const dir = texPath.includes("/")
    ? texPath.slice(0, texPath.lastIndexOf("/"))
    : ""
  // Map-paths destinations that land beside the document. The pipeline writes
  // these, so they're absent from Git and from the listing below, but the
  // document references them as if they were there.
  for (const rule of rules) {
    const underDir =
      dir === "" || rule.dest === dir || rule.dest.startsWith(`${dir}/`)
    if (underDir && !paths.has(rule.dest)) {
      await expandDep(ownerName, projectName, rule.dest, paths, rules)
    }
  }
  // Then always scan the .tex's own directory. A latex stage's deps are usually
  // just the target .tex, but a paper directory routinely also holds the class,
  // style, and bib-style files it needs (e.g. a journal's jfm.cls). Those aren't
  // pipeline deps, and without them the in-browser compile dies with
  // "File `jfm.cls' not found".
  await listDir(ownerName, projectName, dir, 0, paths)
  const files = await Promise.all(
    [...paths].map(([path, readPath]) =>
      fetchOne(ownerName, projectName, path, readPath).catch(() => null),
    ),
  )
  // Only the project's own files go here. Anything missing from the in-browser
  // TeX bundle (e.g. revtex4-1.cls for AASTeX) is fetched on demand by the
  // engine's kpathsea hook into an in-memory dir, so it never appears in the
  // editor's working folder. See texmf-proxy/ and VITE_TEXMF_PROXY.
  return files.filter((f): f is ProjectFile => f !== null)
}
