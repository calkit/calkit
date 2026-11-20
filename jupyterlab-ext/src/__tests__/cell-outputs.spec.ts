import {
  type ICellOutputMark,
  filterCellOutputMarks,
  formatSavedValue,
  getAssignedNames,
  getDefaultMarkPath,
  getMarkLabel,
  getMarkPathError,
  getMarkRequestBody,
  getMarksForCell,
  getOutputMimeTypes,
  getUnmarkQuery,
  getVariableChoices,
  hasImageOutput,
  isVariableName,
  rankNamesForKind,
} from "../cell-outputs";

const value: ICellOutputMark = {
  stage: "fit",
  kind: "value",
  name: "k_25",
  cell: "c0",
  cell_index: 0,
  variable: null,
  format: null,
  citation: "\\ckvalue{fit.ipynb}{k_25}",
  saved_value: 0.030912,
};
const figure: ICellOutputMark = {
  stage: "fit",
  kind: "figure",
  path: "figures/fit.pdf",
  cell: "c2",
  cell_index: 2,
  variable: "fig",
  format: null,
  citation: "\\ckfigure{figures/fit.pdf}",
};

describe("cell outputs", () => {
  it("labels marks with what's saved and how to cite it", () => {
    expect(filterCellOutputMarks([value, figure])).toEqual([value, figure]);
    expect(filterCellOutputMarks([{ kind: "x" }, null])).toEqual([]);
    expect(filterCellOutputMarks({ error: "nope" })).toEqual([]);
    // Saved values are kept short
    expect(formatSavedValue(0.030912)).toBe("0.03091");
    expect(formatSavedValue(25)).toBe("25");
    expect(formatSavedValue(1.5e-7)).toBe("1.500e-7");
    expect(formatSavedValue("done")).toBe('"done"');
    expect(formatSavedValue("x".repeat(30))).toBe(`"${"x".repeat(23)}…"`);
    expect(formatSavedValue({ a: 1, b: 2 })).toBe("{2 keys}");
    expect(formatSavedValue([1])).toBe("[1 item]");
    expect(formatSavedValue(null)).toBe("null");
    expect(getMarkLabel(value)).toEqual({
      text: "k_25 = 0.03091",
      tooltip:
        "Value saved after this cell when stage 'fit' runs\n" +
        "Show it in a document with \\ckvalue{fit.ipynb}{k_25}",
    });
    const unsaved = { ...value };
    delete unsaved.saved_value;
    expect(getMarkLabel(unsaved).text).toBe("k_25 (not saved yet)");
    expect(getMarkLabel(figure).text).toBe("figures/fit.pdf from fig");
    expect(getMarkLabel({ ...figure, variable: null, citation: null })).toEqual(
      {
        text: "figures/fit.pdf",
        tooltip: "Figure saved from what this cell shows when stage 'fit' runs",
      },
    );
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
    ).toEqual(["fig", "f", "n", "b", "a", "t", "rates", "ax"]);
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
      getDefaultMarkPath("figure", "nbs/Fit Rates.ipynb", "decay_fig"),
    ).toBe("figures/fit-rates-decay-fig.pdf");
    expect(getDefaultMarkPath("figure", "fit.ipynb")).toBe("figures/fit.png");
    expect(getDefaultMarkPath("table", "fit.ipynb", "df")).toBe(
      "tables/fit-df.tex",
    );
    expect(getMarkPathError("figure", "figures/fit.PDF")).toBeNull();
    expect(getMarkPathError("table", " tables/rates.csv ")).toBeNull();
    expect(getMarkPathError("table", "tables/rates.pdf")).toBe(
      "Use .tex, .csv, .md, .json",
    );
  });

  it("makes requests to mark and unmark", () => {
    expect(
      getMarkRequestBody({
        notebookPath: "fit.ipynb",
        cellId: "c2",
        kind: "figure",
        target: "figures/fit.pdf",
        variable: "fig",
      }),
    ).toEqual({
      path: "fit.ipynb",
      cell: "c2",
      figure: "figures/fit.pdf",
      variable: "fig",
    });
    // A value is its variable, so it isn't sent twice
    expect(
      getMarkRequestBody({
        notebookPath: "fit.ipynb",
        cellId: "c0",
        kind: "value",
        target: "k",
        variable: "k",
        stage: "fit-2",
      }),
    ).toEqual({ path: "fit.ipynb", cell: "c0", value: "k", stage: "fit-2" });
    expect(getUnmarkQuery("nbs/fit rates.ipynb", figure)).toBe(
      "path=nbs%2Ffit+rates.ipynb&figure=figures%2Ffit.pdf&stage=fit",
    );
    expect(getUnmarkQuery("fit.ipynb", value)).toBe(
      "path=fit.ipynb&value=k_25&stage=fit",
    );
  });

  it("finds a cell's marks by ID or position", () => {
    const atEnd = { ...value, name: "last", cell: null, cell_index: null };
    const marks = [value, figure, atEnd];
    expect(getMarksForCell(marks, 0, "c0", false)).toEqual([value]);
    // An ID wins over a position, e.g., once cells have moved
    expect(getMarksForCell(marks, 0, "c2", false)).toEqual([figure]);
    expect(getMarksForCell(marks, 2, undefined, true)).toEqual([figure, atEnd]);
    expect(getMarksForCell(marks, 1, "x", false)).toEqual([]);
  });
});
