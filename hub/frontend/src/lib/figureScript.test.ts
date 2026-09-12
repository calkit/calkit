import { describe, expect, it } from "vitest"

import type { Environment } from "../client"
import {
  defaultScript,
  envPackages,
  lockPackages,
  pickPythonEnv,
  readDataPaths,
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

describe("readDataPaths", () => {
  it("lists what the script reads, once each, in order", () => {
    const code = [
      'df = pd.read_csv("data/raw/data.csv")',
      "df2 = pd.read_csv('data/other.csv', sep=';')",
      'again = pd.read_csv("data/raw/data.csv")',
      "x = read_csv_like()",
    ].join("\n")
    expect(readDataPaths(code)).toEqual(["data/raw/data.csv", "data/other.csv"])
    expect(readDataPaths("print(1)")).toEqual([])
  })
})

it("inputs that aren't CSVs get a marker line, not a pandas load", () => {
  const paths = ["config.yaml", "data/a.csv", "sims/run-1", "data/b.csv"]
  const script = defaultScript({ datasetPaths: paths, figurePath: "f.png" })
  expect(script).toContain("# Input: config.yaml")
  expect(script).toContain("# Input: sims/run-1")
  // CSVs count from df regardless of where the other inputs sit
  expect(script).toContain('df = pd.read_csv("data/a.csv")')
  expect(script).toContain('df2 = pd.read_csv("data/b.csv")')
  expect(script).not.toContain("df3")
  // No frame at all leaves nothing to plot by default, only the markers
  const h5Only = defaultScript({
    datasetPaths: ["sims/run-1"],
    figurePath: "f.png",
  })
  expect(h5Only).toContain("# Input: sims/run-1")
  expect(h5Only).not.toContain("df.plot")
  expect(h5Only).toContain("Load the inputs named above")
  // Reselecting swaps marker lines along with the load lines
  const swapped = withDatasetLines(h5Only, ["data/a.csv"])
  expect(swapped).not.toContain("# Input:")
  expect(swapped).toContain('df = pd.read_csv("data/a.csv")')
})

it("keeps injected load lines at the depth of the ones they replace", () => {
  const script = [
    "import pandas as pd",
    "",
    "def main():",
    '    df = pd.read_csv("a.csv")',
    "    df.plot()",
    "",
    "main()",
  ].join("\n")
  expect(withDatasetLines(script, ["b.csv", "c.csv", "d.yaml"])).toBe(
    [
      "import pandas as pd",
      "",
      "def main():",
      '    df = pd.read_csv("b.csv")',
      '    df2 = pd.read_csv("c.csv")',
      "    # Input: d.yaml",
      "    df.plot()",
      "",
      "main()",
    ].join("\n"),
  )
  // With no load line to replace, the lines follow the imports at their
  // depth, which at the top of a script is none
  expect(withDatasetLines("import pandas as pd\nprint(1)", ["a.csv"])).toBe(
    'import pandas as pd\n\ndf = pd.read_csv("a.csv")\nprint(1)',
  )
})

it("reads HDF5 inputs with pandas and names pytables from the lock", () => {
  const script = defaultScript({
    datasetPaths: ["data/profiles.h5", "data/a.csv"],
    figurePath: "f.png",
  })
  expect(script).toContain('df = pd.read_hdf("data/profiles.h5")')
  expect(script).toContain('df2 = pd.read_csv("data/a.csv")')
  expect(script).toContain("df.plot(ax=ax)")
  expect(readDataPaths(script)).toEqual(["data/profiles.h5", "data/a.csv"])
  // Reselecting swaps HDF loads the same as CSV ones
  expect(withDatasetLines(script, ["data/b.hdf5"])).toContain(
    'df = pd.read_hdf("data/b.hdf5")',
  )
  expect(withDatasetLines(script, ["data/b.hdf5"])).not.toContain("profiles")
  expect(
    lockPackages(
      'version = 1\n[[package]]\nname = "pandas"\nversion = "2.2"\n[[package]]\nname = "tables"\n',
    ),
  ).toEqual(["pandas", "tables"])
  expect(
    lockPackages(
      "package:\n  - name: numpy\n    version: 1.0\n  - name: python\n",
    ),
  ).toEqual(["numpy"])
  expect(lockPackages("# pip freeze\nh5py==3.10\ntables=3.9=py312\n")).toEqual([
    "h5py",
    "tables",
  ])
  const env = {
    name: "py",
    kind: "uv",
    file_content: '[project]\ndependencies = [\n    "pandas",\n]\n',
    locks: [{ path: "uv.lock", content: '[[package]]\nname = "tables"\n' }],
  } as unknown as Parameters<typeof envPackages>[0]
  expect(envPackages(env)).toEqual(["tables", "pandas"])
})
