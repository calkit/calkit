import { describe, expect, it } from "vitest"

import { packagesFromImports } from "./pyodide"

describe("packagesFromImports", () => {
  it("maps imports to PyPI names and skips the standard library", () => {
    const code = [
      "import os",
      "import json, sys",
      "import numpy as np",
      "import matplotlib.pyplot as plt",
      "from sklearn.linear_model import LinearRegression",
      "from PIL import Image",
      "  import pandas  # indented, still counts",
      "# import fake_commented_out",
      "x = 'import notreal'",
      "from . import local",
    ].join("\n")
    expect(packagesFromImports(code)).toEqual([
      "matplotlib",
      "numpy",
      "pandas",
      "pillow",
      "scikit-learn",
    ])
    expect(packagesFromImports("")).toEqual([])
  })
})
