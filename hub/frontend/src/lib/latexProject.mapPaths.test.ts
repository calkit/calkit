// Regression test for issue #1084, built from calkit/example-basic's real API
// responses: its `figs-to-paper` map-paths stage copies `figures` to
// `paper/figures`, which is gitignored. The document does
// \includegraphics{figures/x-vs-y.png}, so without resolving the mapping the
// preview compiles with a missing figure.
import { beforeEach, describe, expect, it, vi } from "vitest"

const getProjectContents = vi.fn()
const getProjectPipeline = vi.fn()

vi.mock("../client", () => ({
  ProjectsService: {
    getProjectContents: (...args: unknown[]) => getProjectContents(...args),
    getProjectPipeline: (...args: unknown[]) => getProjectPipeline(...args),
  },
}))

const { loadLatexProject } = await import("./latexProject")

// The `pipeline` section as the pipeline endpoint returns it.
const CALKIT_YAML = `pipeline:
  stages:
    analyze:
      kind: python-script
      script_path: scripts/analyze.py
      environment: py
      outputs:
        - figures/x-vs-y.png
    figs-to-paper:
      kind: map-paths
      paths:
        - kind: dir-to-dir-replace
          src: figures
          dest: paper/figures
    build-paper:
      kind: latex
      target_path: paper/paper.tex
      environment: tex
      outputs:
        - paper/paper.pdf
`

const b64 = (s: string) => Buffer.from(s, "utf-8").toString("base64")

const PAPER_TEX =
  "\\documentclass{article}\n\\includegraphics{figures/x-vs-y.png}\n"

// Only what's really readable: paper/figures is absent, exactly as the live
// API has it (404), and the figure lives at its source path, DVC-backed so it
// comes back as a signed URL rather than inline content.
const FILES: Record<string, any> = {
  paper: {
    name: "paper",
    path: "paper",
    type: "dir",
    dir_items: [
      { name: ".gitignore", path: "paper/.gitignore", type: "file" },
      { name: "paper.pdf", path: "paper/paper.pdf", type: "file" },
      { name: "paper.tex", path: "paper/paper.tex", type: "file" },
      { name: "references.bib", path: "paper/references.bib", type: "file" },
      { name: "results.tex", path: "paper/results.tex", type: "file" },
    ],
  },
  "paper/paper.tex": { type: "file", content: b64(PAPER_TEX) },
  "paper/references.bib": { type: "file", content: b64("@article{a}\n") },
  "paper/results.tex": { type: "file", content: b64("\\newcommand{\\r}{1}\n") },
  "paper/paper.pdf": { type: "file", content: b64("%PDF-1.4") },
  figures: {
    name: "figures",
    path: "figures",
    type: "dir",
    dir_items: [
      { name: ".gitignore", path: "figures/.gitignore", type: "file" },
      { name: "x-vs-y.png", path: "figures/x-vs-y.png", type: "file" },
    ],
  },
  "figures/x-vs-y.png": {
    type: "file",
    content: null,
    url: "https://storage.example/x-vs-y.png",
  },
}

describe("loadLatexProject with a map-paths stage (issue #1084)", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    getProjectPipeline.mockResolvedValue({ data: { calkit_yaml: CALKIT_YAML } })
    getProjectContents.mockImplementation(
      async ({ path }: { path?: string }) => {
        const entry = FILES[path ?? ""]
        if (!entry) {
          throw new Error(`404 ${path}`)
        }
        return { data: entry }
      },
    )
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        arrayBuffer: async () => new TextEncoder().encode("PNGDATA").buffer,
        text: async () => "PNGDATA",
      })),
    )
  })

  // Opened from the publications page, where the stage's deps are known.
  it("resolves a map-paths dep to its source", async () => {
    const files = await loadLatexProject(
      "calkit",
      "example-basic",
      "paper/paper.tex",
      [
        "paper/paper.tex",
        "paper/references.bib",
        ".calkit/env-locks/tex",
        "paper/figures",
        "paper/results.tex",
      ],
    )
    const fig = files.find((f) => f.path === "paper/figures/x-vs-y.png")
    // Seeded where the document expects it, with the source's bytes, and
    // flagged generated so the editor won't offer to commit to that path.
    expect(fig).toBeDefined()
    expect(fig?.kind).toBe("binary")
    expect(fig?.generated).toBe(true)
    expect(fig?.bytes?.length).toBeGreaterThan(0)
  })

  // Opened from the files page, which has no deps to go on. This is the case
  // the first fix missed: paper/figures is in neither the deps nor the
  // paper/ listing, so only the map-paths sweep finds it.
  it("finds a map-paths destination beside the document with no deps", async () => {
    const files = await loadLatexProject(
      "calkit",
      "example-basic",
      "paper/paper.tex",
    )
    expect(files.map((f) => f.path)).toContain("paper/figures/x-vs-y.png")
    // The document itself and its siblings still load
    expect(files.map((f) => f.path)).toContain("paper/paper.tex")
    expect(files.map((f) => f.path)).toContain("paper/references.bib")
    // Nothing is invented for the path that 404s
    expect(files.map((f) => f.path)).not.toContain("paper/figures")
  })

  it("still loads the project when there is no pipeline", async () => {
    getProjectPipeline.mockRejectedValue(new Error("no pipeline"))
    const files = await loadLatexProject(
      "calkit",
      "example-basic",
      "paper/paper.tex",
    )
    expect(files.map((f) => f.path)).toContain("paper/paper.tex")
    expect(files.map((f) => f.path)).not.toContain("paper/figures/x-vs-y.png")
  })
})
