import { describe, expect, it } from "vitest"

import type { Environment } from "../client"
import {
  defaultScript,
  envPackages,
  pickPythonEnv,
  readCsvPaths,
  savefigPath,
  withDatasetLines,
} from "./figureScript"

describe("savefigPath", () => {
  it("reads the path from the last savefig call, in any quoting", () => {
    expect(savefigPath('fig.savefig("figures/a.png", dpi=150)')).toBe(
      "figures/a.png",
    )
    expect(savefigPath("plt.savefig('figures/b.svg')")).toBe("figures/b.svg")
    expect(savefigPath('fig.savefig(fname="figures/c.pdf")')).toBe(
      "figures/c.pdf",
    )
    // Two calls: the last one is the figure the stage produces.
    expect(
      savefigPath('fig.savefig("draft.png")\nfig.savefig("figures/d.png")'),
    ).toBe("figures/d.png")
    // plotly writes JSON or HTML rather than pixels
    expect(savefigPath('fig.write_json("figures/e.json")')).toBe(
      "figures/e.json",
    )
    expect(savefigPath("fig.write_html(file='figures/f.html')")).toBe(
      "figures/f.html",
    )
    expect(savefigPath("plt.show()")).toBeNull()
    expect(savefigPath("")).toBeNull()
  })

  it("round-trips with the generated script", () => {
    const code = defaultScript({
      datasetPaths: ["data/raw.csv", "data/more.csv"],
      figurePath: "figures/raw.png",
      x: "x",
      y: "y",
    })
    expect(savefigPath(code)).toBe("figures/raw.png")
    expect(code).toContain('df = pd.read_csv("data/raw.csv")')
    expect(code).toContain('df2 = pd.read_csv("data/more.csv")')
  })
})

describe("withDatasetLines", () => {
  it("swaps the loading lines and leaves the rest of the script alone", () => {
    const code = [
      "import pandas as pd",
      "",
      'df = pd.read_csv("data/a.csv")',
      'df2 = pd.read_csv("data/b.csv")',
      "",
      "ax.plot(df.x, df.y)  # my edit",
    ].join("\n")
    expect(withDatasetLines(code, ["data/b.csv"])).toBe(
      [
        "import pandas as pd",
        "",
        'df = pd.read_csv("data/b.csv")',
        "",
        "ax.plot(df.x, df.y)  # my edit",
      ].join("\n"),
    )
    expect(
      withDatasetLines(code, ["data/a.csv", "data/b.csv", "data/c.csv"]),
    ).toContain('df3 = pd.read_csv("data/c.csv")')
    // No loading lines yet: they go after the imports.
    expect(
      withDatasetLines("import pandas as pd\nprint(1)", ["data/z.csv"]),
    ).toBe('import pandas as pd\n\ndf = pd.read_csv("data/z.csv")\nprint(1)')
    // Deselecting everything leaves no loading lines behind.
    expect(withDatasetLines(code, [])).not.toContain("read_csv")
  })
})

describe("environment mirroring", () => {
  const env = (name: string, kind: string, file_content: string | null) =>
    ({ name, kind, path: null, all_attrs: {}, file_content }) as Environment

  it("prefers uv, then uv-venv, pixi, conda, venv, and skips the rest", () => {
    expect(pickPythonEnv([])).toBeNull()
    expect(
      pickPythonEnv([env("tex", "docker", null), env("r", "renv", null)]),
    ).toBeNull()
    // example-basic: a uv-venv env and a docker env
    expect(
      pickPythonEnv([
        env("tex", "docker", null),
        env("py", "uv-venv", "pandas\n"),
      ])?.name,
    ).toBe("py")
    expect(
      pickPythonEnv([env("c", "conda", ""), env("u", "uv", "")])?.name,
    ).toBe("u")
  })

  it("reads package names out of each spec format", () => {
    expect(
      envPackages(env("py", "uv-venv", "pandas\nmatplotlib>=3.8\nnumpy\n")),
    ).toEqual(["pandas", "matplotlib", "numpy"])
    expect(
      envPackages(
        env(
          "py",
          "uv",
          '[project]\nname = "py"\ndependencies = [\n    "pandas",\n    "scipy[extra]>=1",\n]\n',
        ),
      ),
    ).toEqual(["pandas", "scipy"])
    expect(
      envPackages(
        env(
          "c",
          "conda",
          "name: c\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.12\n  - seaborn\n  - pip\n",
        ),
      ),
    ).toEqual(["seaborn"])
    expect(envPackages(null)).toEqual([])
  })
})

describe("readCsvPaths", () => {
  it("lists what the script reads, once each, in order", () => {
    const code = [
      'df = pd.read_csv("data/raw/data.csv")',
      "df2 = pd.read_csv('data/other.csv', sep=';')",
      'again = pd.read_csv("data/raw/data.csv")',
      "x = read_csv_like()",
    ].join("\n")
    expect(readCsvPaths(code)).toEqual(["data/raw/data.csv", "data/other.csv"])
    expect(readCsvPaths("print(1)")).toEqual([])
  })
})
