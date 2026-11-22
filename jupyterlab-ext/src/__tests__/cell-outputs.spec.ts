import {
  type ICellOutput,
  filterCellOutputs,
  formatSavedValue,
  getAssignedNames,
  getDefaultOutputPath,
  getCellOutputLabel,
  getOutputPathError,
  getAddOutputRequestBody,
  getCellOutputsForCell,
  getOutputMimeTypes,
  getRemoveOutputQuery,
  getVariableChoices,
  hasImageOutput,
  hasResultOutput,
  isVariableName,
  rankNamesForKind,
} from "../cell-outputs";

const value: ICellOutput = {
  stage: "fit",
  kind: "value",
  cell_id: "c0",
  cell_index: 0,
  variable_name: "k_25",
  output_path: null,
  format: null,
  citation: "\\ckvalue{fit.ipynb}{k_25}",
  saved_value: 0.030912,
};
const figure: ICellOutput = {
  stage: "fit",
  kind: "figure",
  cell_id: "c2",
  cell_index: 2,
  variable_name: "fig",
  output_path: "figures/fit.pdf",
  format: null,
  citation: "\\ckfigure{figures/fit.pdf}",
};

describe("cell outputs", () => {
  it("labels cellOutputs with what's saved and how to cite it", () => {
    expect(filterCellOutputs([value, figure])).toEqual([value, figure]);
    expect(filterCellOutputs([{ kind: "x" }, null])).toEqual([]);
    expect(filterCellOutputs({ error: "nope" })).toEqual([]);
    // Saved values are kept short
    expect(formatSavedValue(0.030912)).toBe("0.03091");
    expect(formatSavedValue(25)).toBe("25");
    expect(formatSavedValue(1.5e-7)).toBe("1.500e-7");
    expect(formatSavedValue("done")).toBe('"done"');
    expect(formatSavedValue("x".repeat(30))).toBe(`"${"x".repeat(23)}…"`);
    expect(formatSavedValue({ a: 1, b: 2 })).toBe("{2 keys}");
    expect(formatSavedValue([1])).toBe("[1 item]");
    expect(formatSavedValue(null)).toBe("null");
    expect(getCellOutputLabel(value)).toEqual({
      text: "k_25 = 0.03091",
      tooltip:
        "Saved after this cell by stage 'fit'\n" +
        "Cite with \\ckvalue{fit.ipynb}{k_25}",
    });
    const unsaved = { ...value };
    delete unsaved.saved_value;
    expect(getCellOutputLabel(unsaved).text).toBe("k_25 (not saved yet)");
    expect(getCellOutputLabel(figure).text).toBe("figures/fit.pdf from fig");
    expect(
      getCellOutputLabel({ ...figure, variable_name: null, citation: null }),
    ).toEqual({
      text: "figures/fit.pdf",
      tooltip: "Saved from cell display by stage 'fit'",
    });
  });

  it("offers the variables a cell assigns, likely ones first", () => {
    expect(
      getAssignedNames(
        [
          "import numpy as np",
          "fig, ax = plt.subplots()",
          "rates: dict = {}",
          "for t in temps:",
          "    k = fit(t)",
          "    rates[t] = k",
          "(a, b) = 1, 2",
          "n += 1",
          "if x == 2:",
          "    pass",
          "with open('f') as f:",
          "# c = 3",
          "df.loc[0] = 1",
          "fig = plt.figure()",
        ].join("\n"),
      ),
    ).toEqual(["fig", "f", "n", "b", "a", "rates", "ax", "temps", "t"]);
    // A loop goes through something more worth saving than its variables
    expect(
      getAssignedNames(
        "for temp, k in rates.items():\n    print(f'{temp}: {k}')",
      ),
    ).toEqual(["rates", "k", "temp"]);
    expect(getAssignedNames("for t, k in zip(temps, ks):")).toEqual([
      "temps",
      "ks",
      "k",
      "t",
    ]);
    expect(getAssignedNames("")).toEqual([]);
    const names = ["k", "ax", "fig", "summary_df", "rates"];
    expect(rankNamesForKind(names, "figure")).toEqual([
      "fig",
      "k",
      "ax",
      "summary_df",
      "rates",
    ]);
    expect(rankNamesForKind(names, "table")[0]).toBe("summary_df");
    expect(rankNamesForKind(names, "value")).toEqual([
      "k",
      "summary_df",
      "rates",
      "ax",
      "fig",
    ]);
    // A figure can be the image the cell shows, which comes last until the
    // cell has shown one
    const source = "fig, ax = plt.subplots()\nk = 2";
    expect(getVariableChoices(source, "figure", true)).toEqual([
      { label: "Image this cell shows" },
      { label: "fig", variable: "fig" },
      { label: "k", variable: "k" },
      { label: "ax", variable: "ax" },
      { label: "Other variable…", isOther: true },
    ]);
    expect(
      getVariableChoices(source, "figure", false).map((c) => c.label),
    ).toEqual([
      "fig",
      "k",
      "ax",
      "Other variable…",
      "Image this cell shows (run cell first)",
    ]);
    // A table can be the result the cell's last line shows
    expect(getVariableChoices("df = load()\ndf.head()", "table", true)).toEqual(
      [
        { label: "Result this cell shows" },
        { label: "df", variable: "df" },
        { label: "Other variable…", isOther: true },
      ],
    );
    expect(
      getVariableChoices("df = load()", "table", false).map((c) => c.label),
    ).toEqual([
      "df",
      "Other variable…",
      "Result this cell shows (run cell first)",
    ]);
    expect(
      hasResultOutput([
        { output_type: "stream", text: "hi" },
        { output_type: "execute_result", data: { "text/html": "<table>" } },
      ]),
    ).toBe(true);
    expect(hasResultOutput([{ output_type: "display_data" }, null])).toBe(
      false,
    );
    expect(getVariableChoices("", "value", true)).toEqual([
      { label: "Other variable…", isOther: true },
    ]);
    // Even a variable named "other" is a variable
    expect(getVariableChoices("other = 1", "table", false)[0]).toEqual({
      label: "other",
      variable: "other",
    });
    expect(isVariableName("k_25")).toBe(true);
    expect(isVariableName("2k")).toBe(false);
    expect(isVariableName("df.T")).toBe(false);
    expect(
      hasImageOutput(
        getOutputMimeTypes([
          { output_type: "stream", text: "hi" },
          { output_type: "display_data", data: { "image/png": "..." } },
        ]),
      ),
    ).toBe(true);
    expect(
      getOutputMimeTypes([
        { output_type: "execute_result", data: { "text/plain": "1" } },
        null,
      ]),
    ).toEqual(["text/plain"]);
    expect(hasImageOutput(["text/plain"])).toBe(false);
  });

  it("suggests and checks paths to save figures and tables to", () => {
    expect(
      getDefaultOutputPath("figure", "nbs/Fit Rates.ipynb", "decay_fig"),
    ).toBe("figures/fit-rates-decay-fig.pdf");
    expect(getDefaultOutputPath("figure", "fit.ipynb")).toBe("figures/fit.png");
    expect(getDefaultOutputPath("table", "fit.ipynb", "df")).toBe(
      "tables/fit-df.tex",
    );
    expect(getOutputPathError("figure", "figures/fit.PDF")).toBeNull();
    expect(getOutputPathError("table", " tables/rates.csv ")).toBeNull();
    expect(getOutputPathError("table", "tables/rates.pdf")).toBe(
      "Use .tex, .csv, .md, .json",
    );
  });

  it("makes requests to add and remove outputs", () => {
    expect(
      getAddOutputRequestBody({
        notebookPath: "fit.ipynb",
        cellId: "c2",
        kind: "figure",
        variableNames: ["fig"],
        outputPath: "figures/fit.pdf",
      }),
    ).toEqual({
      path: "fit.ipynb",
      output: {
        kind: "figure",
        cell_id: "c2",
        variable_name: "fig",
        output_path: "figures/fit.pdf",
      },
    });
    // A value has no path of its own
    expect(
      getAddOutputRequestBody({
        notebookPath: "fit.ipynb",
        cellId: "c0",
        kind: "value",
        variableNames: ["k"],
        outputPath: "ignored",
        stage: "fit-2",
      }),
    ).toEqual({
      path: "fit.ipynb",
      output: { kind: "value", cell_id: "c0", variable_name: "k" },
      stage: "fit-2",
    });
    // Several values at once
    expect(
      getAddOutputRequestBody({
        notebookPath: "fit.ipynb",
        cellId: "c0",
        kind: "value",
        variableNames: ["k", "j"],
      }).output,
    ).toEqual({ kind: "value", cell_id: "c0", variable_names: ["k", "j"] });
    expect(getRemoveOutputQuery("nbs/fit rates.ipynb", figure)).toBe(
      "path=nbs%2Ffit+rates.ipynb&output_path=figures%2Ffit.pdf&stage=fit",
    );
    expect(getRemoveOutputQuery("fit.ipynb", value)).toBe(
      "path=fit.ipynb&variable_name=k_25&stage=fit",
    );
  });

  it("finds a cell's cellOutputs by ID or position", () => {
    const atEnd = {
      ...value,
      variable_name: "last",
      cell_id: null,
      cell_index: null,
    };
    const cellOutputs = [value, figure, atEnd];
    expect(getCellOutputsForCell(cellOutputs, 0, "c0", false)).toEqual([value]);
    // An ID wins over a position, e.g., once cells have moved
    expect(getCellOutputsForCell(cellOutputs, 0, "c2", false)).toEqual([
      figure,
    ]);
    expect(getCellOutputsForCell(cellOutputs, 2, undefined, true)).toEqual([
      figure,
      atEnd,
    ]);
    expect(getCellOutputsForCell(cellOutputs, 1, "x", false)).toEqual([]);
  });
});
