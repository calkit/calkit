// Python in the browser, for drafting figures before anything is installed.
//
// Pyodide is loaded once from the CDN on first use (it's tens of megabytes,
// so nothing here runs at page load) and kept for the session. A run writes
// the data files into an in-memory filesystem at the same relative paths
// they have in the repo, runs the script with that as the working
// directory, and reads the figure back out. That way the script that runs
// here is byte for byte the script that gets committed as a stage.

const PYODIDE_VERSION = "0.27.7"
const INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`
const PROJECT_DIR = "/project"

interface PyodideFS {
  mkdirTree: (path: string) => void
  writeFile: (path: string, data: Uint8Array | string) => void
  readFile: (path: string) => Uint8Array
  unlink: (path: string) => void
  analyzePath: (path: string) => { exists: boolean }
}

export interface PyodideInterface {
  FS: PyodideFS
  loadPackage: (names: string | string[]) => Promise<void>
  loadPackagesFromImports: (code: string) => Promise<void>
  runPythonAsync: (code: string) => Promise<unknown>
  setStdout: (opts: { batched: (text: string) => void }) => void
  setStderr: (opts: { batched: (text: string) => void }) => void
  pyimport: (name: string) => any
}

declare global {
  interface Window {
    loadPyodide?: (opts: { indexURL: string }) => Promise<PyodideInterface>
  }
}

let pyodidePromise: Promise<PyodideInterface> | null = null

const loadScript = (src: string) =>
  new Promise<void>((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`)
    if (existing) {
      resolve()
      return
    }
    const script = document.createElement("script")
    script.src = src
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error(`Could not load ${src}`))
    document.head.appendChild(script)
  })

/** The shared runtime, started on first call. */
export function getPyodide(
  onStatus?: (status: string) => void,
): Promise<PyodideInterface> {
  if (!pyodidePromise) {
    pyodidePromise = (async () => {
      onStatus?.("Loading the Python runtime (first time only)")
      await loadScript(`${INDEX_URL}pyodide.js`)
      if (!window.loadPyodide) {
        throw new Error("Pyodide did not initialize")
      }
      const pyodide = await window.loadPyodide({ indexURL: INDEX_URL })
      pyodide.FS.mkdirTree(PROJECT_DIR)
      // No display in here; the Agg backend renders straight to a file,
      // which is all a script that saves a figure needs.
      await pyodide.runPythonAsync(
        ["import os", `os.environ["MPLBACKEND"] = "AGG"`].join("\n"),
      )
      return pyodide
    })().catch((err) => {
      // A failed load shouldn't poison every later attempt.
      pyodidePromise = null
      throw err
    })
  }
  return pyodidePromise
}

// Top-level modules that ship with Python and so never name a package.
const STDLIB = new Set([
  "__future__",
  "abc",
  "argparse",
  "array",
  "asyncio",
  "base64",
  "binascii",
  "bisect",
  "builtins",
  "bz2",
  "calendar",
  "codecs",
  "collections",
  "configparser",
  "contextlib",
  "copy",
  "csv",
  "ctypes",
  "dataclasses",
  "datetime",
  "decimal",
  "difflib",
  "doctest",
  "email",
  "enum",
  "filecmp",
  "fnmatch",
  "fractions",
  "functools",
  "gc",
  "getpass",
  "gettext",
  "glob",
  "gzip",
  "hashlib",
  "heapq",
  "hmac",
  "html",
  "http",
  "inspect",
  "io",
  "itertools",
  "json",
  "linecache",
  "locale",
  "logging",
  "lzma",
  "math",
  "multiprocessing",
  "numbers",
  "operator",
  "os",
  "pathlib",
  "pickle",
  "platform",
  "pprint",
  "queue",
  "random",
  "re",
  "secrets",
  "select",
  "shlex",
  "shutil",
  "signal",
  "socket",
  "ssl",
  "stat",
  "statistics",
  "string",
  "struct",
  "subprocess",
  "sys",
  "sysconfig",
  "tempfile",
  "textwrap",
  "threading",
  "time",
  "tomllib",
  "traceback",
  "types",
  "typing",
  "unicodedata",
  "unittest",
  "urllib",
  "uuid",
  "warnings",
  "weakref",
  "xml",
  "zipfile",
  "zoneinfo",
])

// Import names that differ from the package that provides them.
const MODULE_TO_PACKAGE: Record<string, string> = {
  sklearn: "scikit-learn",
  skimage: "scikit-image",
  PIL: "pillow",
  yaml: "pyyaml",
  cv2: "opencv-python",
  mpl_toolkits: "matplotlib",
  bs4: "beautifulsoup4",
  dateutil: "python-dateutil",
  attr: "attrs",
  Bio: "biopython",
}

/** The PyPI packages a script imports, for an environment spec. */
export function packagesFromImports(code: string): string[] {
  const found = new Set<string>()
  for (const line of code.split("\n")) {
    const match = line.match(/^\s*(?:import|from)\s+([A-Za-z_][\w]*)/)
    if (!match) continue
    const top = match[1]
    if (STDLIB.has(top)) continue
    found.add(MODULE_TO_PACKAGE[top] ?? top)
  }
  return [...found].sort()
}

/** Top-level module for a Pyodide "No module named 'x'" error, if any. */
const missingModule = (message: string): string | null => {
  const match = message.match(/No module named '([A-Za-z_][\w]*)/)
  return match ? match[1] : null
}

export interface RunInput {
  code: string
  /** Repo-relative paths and their contents, written before the run. */
  files: { path: string; data: Uint8Array | string }[]
  /** Repo-relative path the script is expected to write. */
  figurePath: string
  onStatus?: (status: string) => void
}

export interface RunResult {
  image: Blob | null
  stdout: string
  stderr: string
  error: string | null
  durationMs: number
}

const mimeFor = (path: string): string => {
  const lower = path.toLowerCase()
  if (lower.endsWith(".svg")) return "image/svg+xml"
  if (lower.endsWith(".pdf")) return "application/pdf"
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg"
  if (lower.endsWith(".webp")) return "image/webp"
  return "image/png"
}

const dirname = (path: string) => path.split("/").slice(0, -1).join("/")

/**
 * Run a plotting script against the given files and collect the figure.
 *
 * Packages are resolved from the script's imports: anything Pyodide ships
 * (numpy, pandas, matplotlib, scipy, scikit-learn, and more) loads from
 * the CDN; a pure-Python package it doesn't ship is tried through micropip
 * when the script fails to import it.
 */
export async function runFigureScript({
  code,
  files,
  figurePath,
  onStatus,
}: RunInput): Promise<RunResult> {
  const started = performance.now()
  let stdout = ""
  let stderr = ""
  const result = (error: string | null, image: Blob | null): RunResult => ({
    image,
    stdout,
    stderr,
    error,
    durationMs: Math.round(performance.now() - started),
  })
  let pyodide: PyodideInterface
  try {
    pyodide = await getPyodide(onStatus)
  } catch (err) {
    return result((err as Error).message, null)
  }
  pyodide.setStdout({
    batched: (text) => {
      stdout += `${text}\n`
    },
  })
  pyodide.setStderr({
    batched: (text) => {
      stderr += `${text}\n`
    },
  })
  const fs = pyodide.FS
  for (const file of files) {
    const full = `${PROJECT_DIR}/${file.path}`
    const dir = dirname(full)
    if (dir) fs.mkdirTree(dir)
    fs.writeFile(full, file.data)
  }
  const figureFull = `${PROJECT_DIR}/${figurePath}`
  const figureDir = dirname(figureFull)
  if (figureDir) fs.mkdirTree(figureDir)
  // A stale figure from the last run shouldn't pass for this one's.
  if (fs.analyzePath(figureFull).exists) fs.unlink(figureFull)
  onStatus?.("Loading packages")
  try {
    await pyodide.loadPackagesFromImports(code)
  } catch (err) {
    return result(`Could not load packages: ${(err as Error).message}`, null)
  }
  onStatus?.("Running")
  const prelude = [
    "import os",
    `os.chdir(${JSON.stringify(PROJECT_DIR)})`,
    "try:",
    "    import matplotlib",
    "    matplotlib.use('AGG')",
    "    import matplotlib.pyplot as _plt",
    "    _plt.close('all')",
    "except ImportError:",
    "    pass",
  ].join("\n")
  await pyodide.runPythonAsync(prelude)
  let triedMicropip = false
  for (;;) {
    try {
      await pyodide.runPythonAsync(code)
      break
    } catch (err) {
      const message = (err as Error).message ?? String(err)
      const missing = missingModule(message)
      if (missing && !triedMicropip) {
        // One shot at pulling a pure-Python package from PyPI, then give
        // up with the original error so the user sees what's missing.
        triedMicropip = true
        onStatus?.(`Installing ${missing}`)
        try {
          await pyodide.loadPackage("micropip")
          const micropip = pyodide.pyimport("micropip")
          await micropip.install(MODULE_TO_PACKAGE[missing] ?? missing)
          continue
        } catch {
          return result(message, null)
        }
      }
      return result(message, null)
    }
  }
  if (!fs.analyzePath(figureFull).exists) {
    return result(
      `The script finished but did not write ${figurePath}. ` +
        "Save the figure to that path at the end of the script.",
      null,
    )
  }
  const bytes = fs.readFile(figureFull)
  const image = new Blob([new Uint8Array(bytes)], {
    type: mimeFor(figurePath),
  })
  return result(null, image)
}
