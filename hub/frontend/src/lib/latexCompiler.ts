// Thin client-side wrapper around the (MIT) busytex WASM worker for in-browser
// LaTeX compilation. The engine binaries are served from VITE_TEX_ENGINE_URL
// (default same-origin /tex). Compilation is preview-only.

export interface LatexFile {
  path: string
  contents: string | Uint8Array | null
}

export interface CompileResult {
  pdf: Uint8Array | null
  log: string
  exitCode: number
}

// busytex drivers: pdftex_bibtex8 | xetex_bibtex8_dvipdfmx | luahbtex_bibtex8
const DRIVER = "pdftex_bibtex8"
// Eagerly loaded base filesystem.
const PRELOAD_PACKAGES = ["texlive-basic.js"]
// All available bundles; the engine resolves \usepackage names against these
// and loads the needed .data on demand. Bundles are a subset of full TeX Live;
// anything absent (e.g. sectsty, revtex) is fetched on demand from the texmf
// proxy by the patched engine when VITE_TEXMF_PROXY is set. See texmf-proxy/.
const DATA_PACKAGES = [
  "texlive-basic.js",
  "ubuntu-texlive-latex-base.js",
  "ubuntu-texlive-latex-recommended.js",
  "ubuntu-texlive-latex-extra.js",
  "ubuntu-texlive-science.js",
  "ubuntu-texlive-fonts-recommended.js",
]

const ENGINE_BASE = (import.meta.env.VITE_TEX_ENGINE_URL || "/tex").replace(
  /\/$/,
  "",
)

// Bump when the engine binaries or worker glue change. The ~30 MB busytex.wasm
// is aggressively cached by the browser; without a version query, a rebuilt
// engine (e.g. the remote-fetch/font patches) won't be picked up until a hard
// refresh. Appended to the worker + engine URLs to bust the HTTP cache.
const ENGINE_VERSION = "2026-07-09-fixed-point-2"
const V = `?v=${ENGINE_VERSION}`

// Self-hosted texmf proxy. When set, the patched busytex engine fetches any TeX
// file missing from the bundled subset on demand (one compile, exact filenames),
// giving full TeX Live coverage. Empty => engine falls back to stock behaviour
// (missing package => friendly error). See texmf-proxy/.
const TEXMF_PROXY = (import.meta.env.VITE_TEXMF_PROXY || "").replace(/\/$/, "")

type Pending = {
  resolve: (r: CompileResult) => void
  reject: (e: Error) => void
}

// Pull "File `foo.sty' not found" package names out of a TeX log so the UI can
// explain that a package isn't in the in-browser bundle.
export function findMissingPackages(log: string): string[] {
  const out = new Set<string>()
  const re = /File `([^']+\.(?:sty|cls))' not found/g
  let m = re.exec(log)
  while (m !== null) {
    out.add(m[1])
    m = re.exec(log)
  }
  return [...out]
}

// Return the index of the first match of `re` that isn't commented out (i.e.
// not preceded by an unescaped % earlier on its line). `re` must be global.
function firstActiveMatch(tex: string, re: RegExp): RegExpExecArray | null {
  let m: RegExpExecArray | null
  // biome-ignore lint/suspicious/noAssignInExpressions: standard exec loop
  while ((m = re.exec(tex)) !== null) {
    const lineStart = tex.lastIndexOf("\n", m.index) + 1
    if (!/(^|[^\\])%/.test(tex.slice(lineStart, m.index))) {
      return m
    }
  }
  return null
}

// The in-browser engine can't generate bitmap (PK) fonts: mktexpk shells out
// via fork(), which the WASM runtime doesn't implement, so a document that
// pulls in the TS1 text-companion CM fonts (tcrm*, e.g. via textcomp symbols)
// dies with "Font tcrm1095 not found". Latin Modern ships scalable Type1 T1+TS1
// fonts, so loading lmodern sidesteps bitmap generation. This is a preview-only
// transform (LM renders ~identically to Computer Modern); the real pipeline PDF
// is built server-side and unaffected.
//
// Placement matters and drives the fallbacks below:
//   1. Right after the real \documentclass (skipping commented-out ones, a
//      common pattern is a disabled variant on the line above). Early in the
//      preamble means a document's own explicit font package still overrides
//      us, and such documents don't hit the bitmap issue anyway.
//   2. If there's no parseable \documentclass in the main file (e.g. a wrapper
//      that \inputs the real root), inject just before \begin{document} so it
//      still lands in the preamble.
//   3. As a last resort, \RequirePackage before everything, which is legal even
//      ahead of \documentclass.
// A misplaced \usepackage (above \documentclass) makes pdflatex fail with
// "\usepackage before \documentclass", so we never inject blindly.
function ensureScalableFonts(tex: string): string {
  if (/\\usepackage(\[[^\]]*\])?\{[^}]*\blmodern\b[^}]*\}/.test(tex)) {
    return tex
  }
  const docClass = firstActiveMatch(
    tex,
    /\\documentclass(\[[^\]]*\])?\{[^}]*\}/g,
  )
  if (docClass) {
    const at = docClass.index + docClass[0].length
    return `${tex.slice(0, at)}\n\\usepackage{lmodern}${tex.slice(at)}`
  }
  const beginDoc = firstActiveMatch(tex, /\\begin\{document\}/g)
  if (beginDoc) {
    const at = beginDoc.index
    return `${tex.slice(0, at)}\\usepackage{lmodern}\n${tex.slice(at)}`
  }
  return `\\RequirePackage{lmodern}\n${tex}`
}

// A stable content key for a set of compile inputs. latexmk does no work when
// nothing changed; likewise a byte-identical source can reuse the last result
// instead of re-running the whole multi-pass typeset. FNV-1a with two
// accumulators plus file count and total length, so a collision (which would
// return a stale but identical-looking PDF) is astronomically unlikely.
function hashFiles(files: LatexFile[]): string {
  let h1 = 0x811c9dc5
  let h2 = 0x811c9dc5 ^ 0x1234
  let total = 0
  const mix = (b: number) => {
    h1 = Math.imul(h1 ^ b, 0x01000193)
    h2 = Math.imul(h2 ^ b, 0x01000193)
  }
  for (const f of [...files].sort((a, b) => (a.path < b.path ? -1 : 1))) {
    for (let i = 0; i < f.path.length; i++) mix(f.path.charCodeAt(i) & 0xff)
    mix(0)
    const c = f.contents
    if (typeof c === "string") {
      for (let i = 0; i < c.length; i++) {
        const cc = c.charCodeAt(i)
        mix(cc & 0xff)
        mix((cc >> 8) & 0xff)
      }
      total += c.length
    } else if (c) {
      for (let i = 0; i < c.length; i++) mix(c[i])
      total += c.length
    }
    mix(0)
  }
  return `${files.length}:${total}:${(h1 >>> 0).toString(36)}:${(h2 >>> 0).toString(36)}`
}

export class LatexCompiler {
  private worker: Worker | null = null
  private ready: Promise<void> | null = null
  private pending: Pending | null = null
  private onLog?: (line: string) => void
  // Content key + result of the last successful compile, for the no-op fast path.
  private lastKey: string | null = null
  private lastResult: CompileResult | null = null
  private pendingKey: string | null = null

  constructor(opts: { onLog?: (line: string) => void } = {}) {
    this.onLog = opts.onLog
  }

  // Lazily spin up the worker and wait for the engine to initialize.
  init(): Promise<void> {
    if (this.ready) {
      return this.ready
    }
    this.ready = new Promise<void>((resolve, reject) => {
      const worker = new Worker(`${ENGINE_BASE}/busytex_worker.js${V}`)
      this.worker = worker
      worker.onmessage = ({ data }) => {
        if (data.print !== undefined) {
          this.onLog?.(data.print)
          return
        }
        if (data.initialized !== undefined) {
          resolve()
          return
        }
        if (data.exception !== undefined) {
          const err = new Error(data.exception)
          if (this.pending) {
            this.pending.reject(err)
            this.pending = null
          } else {
            reject(err)
          }
          return
        }
        // Otherwise: a compile result.
        if (this.pending) {
          const result: CompileResult = {
            pdf: data.pdf ?? null,
            log: data.log ?? "",
            exitCode: data.exit_code ?? -1,
          }
          // Cache only a genuinely successful compile, so the no-op fast path
          // never serves a stale failure or blank PDF.
          if (
            result.exitCode === 0 &&
            result.pdf &&
            result.pdf.byteLength > 0
          ) {
            this.lastKey = this.pendingKey
            this.lastResult = result
          } else {
            this.lastKey = null
          }
          this.pending.resolve(result)
          this.pending = null
        }
      }
      worker.onerror = (e) => {
        const err = new Error(`Engine worker error: ${e.message}`)
        if (this.pending) {
          this.pending.reject(err)
          this.pending = null
        } else {
          reject(err)
        }
      }
      // Data-package and wasm paths are resolved relative to the worker's
      // location unless absolute, so pass absolute engine URLs.
      worker.postMessage({
        busytex_wasm: `${ENGINE_BASE}/busytex.wasm${V}`,
        busytex_js: `${ENGINE_BASE}/busytex.js${V}`,
        preload_data_packages_js: PRELOAD_PACKAGES.map(
          (p) => `${ENGINE_BASE}/${p}`,
        ),
        data_packages_js: DATA_PACKAGES.map((p) => `${ENGINE_BASE}/${p}`),
        texmf_local: [],
        preload: true,
        calkit_texmf_endpoint: TEXMF_PROXY,
      })
    })
    return this.ready
  }

  async compile(
    files: LatexFile[],
    mainTexPath: string,
  ): Promise<CompileResult> {
    await this.init()
    if (this.pending) {
      throw new Error("A compilation is already in progress")
    }
    // No-op fast path: identical source since the last successful compile, so
    // the output can't differ. Skip the whole multi-pass typeset.
    const key = hashFiles(files)
    if (key === this.lastKey && this.lastResult) {
      this.onLog?.("Source unchanged since last compile; reusing result.\n")
      return this.lastResult
    }
    this.pendingKey = key
    // With the texmf proxy configured, missing bitmap fonts (and any other
    // absent TeX file) are fetched/generated on demand, so we leave the source
    // untouched. Only when there's no proxy do we fall back to rewriting the
    // main file to load lmodern, so TS1/text-companion glyphs resolve to
    // scalable fonts instead of triggering (unsupported) bitmap generation.
    const patchedFiles = TEXMF_PROXY
      ? files
      : files.map((f) =>
          f.path === mainTexPath && typeof f.contents === "string"
            ? { ...f, contents: ensureScalableFonts(f.contents) }
            : f,
        )
    return new Promise<CompileResult>((resolve, reject) => {
      this.pending = { resolve, reject }
      this.worker?.postMessage({
        files: patchedFiles,
        main_tex_path: mainTexPath,
        // null => auto-detect a bibliography and run the full latexmk-style
        // cycle. Docs with \bibliography run bibtex + rerun pdflatex; docs
        // without just rerun pdflatex until cross-references stabilise. Both
        // resolve \ref/\cite instead of leaving "??"/"[?]". (The old forced
        // single pass avoided a multi-pass crash that turned out to be an
        // argv-mutation bug in the worker glue, now fixed — see
        // busytex_pipeline.js callMainWithRedirects.)
        bibtex: null,
        verbose: "silent",
        driver: DRIVER,
        data_packages_js: DATA_PACKAGES.map((p) => `${ENGINE_BASE}/${p}`),
      })
    })
  }

  terminate(): void {
    this.worker?.terminate()
    this.worker = null
    this.ready = null
    this.pending = null
  }
}
