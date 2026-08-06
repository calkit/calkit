// Load the files a publication needs to compile in the browser. Driven by the
// publication's pipeline-stage deps when available (the authoritative list,
// including figures outside the .tex's own directory and DVC-tracked outputs),
// falling back to scanning the .tex's directory. Files are seeded at their full
// repo paths so relative refs like \includegraphics{../figures/x.png} resolve.
import { ProjectsService } from "../client"
import { decodeBase64Utf8 } from "./strings"

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

async function listDir(
  ownerName: string,
  projectName: string,
  dir: string,
  depth: number,
  acc: Set<string>,
): Promise<void> {
  if (depth > MAX_DEPTH || acc.size >= MAX_FILES) {
    return
  }
  let res: Awaited<ReturnType<typeof ProjectsService.getProjectContents>>
  try {
    res = await ProjectsService.getProjectContents({
      ownerName,
      projectName,
      path: dir || undefined,
    })
  } catch {
    return
  }
  for (const item of res.dir_items ?? []) {
    if (acc.size >= MAX_FILES) {
      break
    }
    if (item.type === "dir") {
      await listDir(ownerName, projectName, item.path, depth + 1, acc)
    } else if (relevant(item.name)) {
      acc.add(item.path)
    }
  }
}

// Expand a pipeline-stage dep (a file or a directory) into concrete file paths.
async function expandDep(
  ownerName: string,
  projectName: string,
  dep: string,
  acc: Set<string>,
): Promise<void> {
  if (SKIP_PREFIXES.some((p) => dep.startsWith(p)) || dep.startsWith(".")) {
    return
  }
  let res: Awaited<ReturnType<typeof ProjectsService.getProjectContents>>
  try {
    res = await ProjectsService.getProjectContents({
      ownerName,
      projectName,
      path: dep,
    })
  } catch {
    return
  }
  if (res.type === "dir") {
    await listDir(ownerName, projectName, dep, 0, acc)
  } else if (relevant(dep)) {
    acc.add(dep)
  }
}

async function fetchOne(
  ownerName: string,
  projectName: string,
  path: string,
): Promise<ProjectFile | null> {
  let res: Awaited<ReturnType<typeof ProjectsService.getProjectContents>>
  try {
    res = await ProjectsService.getProjectContents({
      ownerName,
      projectName,
      path,
    })
  } catch {
    return null
  }
  if (TEXT_EXT.has(ext(path))) {
    // Files over the API's inline-content size limit come back as a signed
    // URL with no `content` — fetch the text so large sources aren't empty.
    let text = ""
    if (res.content) {
      text = decodeBase64Utf8(res.content)
    } else if (res.url) {
      text = await (await fetch(res.url)).text()
    }
    return { path, kind: "text", text }
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
  return { path, kind: "binary", bytes }
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
        ownerName,
        projectName,
        ttl: 0,
      })
    } catch {
      // Best effort: if the refresh call fails, fall through to normal reads.
    }
  }
  const paths = new Set<string>([texPath])
  if (deps && deps.length > 0) {
    for (const dep of deps) {
      await expandDep(ownerName, projectName, dep, paths)
    }
  } else {
    const dir = texPath.includes("/")
      ? texPath.slice(0, texPath.lastIndexOf("/"))
      : ""
    await listDir(ownerName, projectName, dir, 0, paths)
  }
  const files = await Promise.all(
    [...paths].map((p) =>
      fetchOne(ownerName, projectName, p).catch(() => null),
    ),
  )
  // Only the project's own files go here. Anything missing from the in-browser
  // TeX bundle (e.g. revtex4-1.cls for AASTeX) is fetched on demand by the
  // engine's kpathsea hook into an in-memory dir, so it never appears in the
  // editor's working folder. See texmf-proxy/ and VITE_TEXMF_PROXY.
  return files.filter((f): f is ProjectFile => f !== null)
}
