import assert from "node:assert/strict";
import test from "node:test";
import {
  type CellOutputMark,
  formatSavedValue,
  getAssignedNames,
  getDefaultMarkPath,
  getMarkArgs,
  getMarkLabel,
  getMarksForCell,
  getUnmarkArgs,
  hasImageOutput,
  parseCellOutputs,
  rankNamesForKind,
} from "../cell-outputs/core";

const value: CellOutputMark = {
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
const figure: CellOutputMark = {
  stage: "fit",
  kind: "figure",
  cell_id: "c2",
  cell_index: 2,
  variable_name: "fig",
  output_path: "figures/fit.pdf",
  format: null,
  citation: "\\ckfigure{figures/fit.pdf}",
};

test("parseCellOutputs reads what calkit nb outputs lists", () => {
  assert.deepEqual(parseCellOutputs(JSON.stringify([value, figure])), [
    value,
    figure,
  ]);
  assert.deepEqual(parseCellOutputs(JSON.stringify([{ kind: "x" }])), []);
  assert.deepEqual(parseCellOutputs("Error: nope"), []);
  assert.deepEqual(parseCellOutputs("{}"), []);
});

test("formatSavedValue keeps a value short", () => {
  assert.equal(formatSavedValue(0.030912), "0.03091");
  assert.equal(formatSavedValue(25), "25");
  assert.equal(formatSavedValue(1.5e-7), "1.500e-7");
  assert.equal(formatSavedValue("done"), '"done"');
  assert.equal(formatSavedValue("x".repeat(30)), `"${"x".repeat(23)}…"`);
  assert.equal(formatSavedValue({ a: 1, b: 2 }), "{2 keys}");
  assert.equal(formatSavedValue([1]), "[1 item]");
  assert.equal(formatSavedValue(null), "null");
});

test("getMarkLabel says what's saved, and how to cite it", () => {
  assert.deepEqual(getMarkLabel(value), {
    text: "$(symbol-number) k_25 = 0.03091",
    tooltip:
      "Value saved after this cell when stage 'fit' runs\n" +
      "Show it in a document with \\ckvalue{fit.ipynb}{k_25}",
  });
  const unsaved = { ...value };
  delete unsaved.saved_value;
  assert.equal(
    getMarkLabel(unsaved).text,
    "$(symbol-number) k_25 (not saved yet)",
  );
  assert.equal(getMarkLabel(figure).text, "$(graph) figures/fit.pdf from fig");
  const shown = { ...figure, variable_name: null, citation: null };
  assert.deepEqual(getMarkLabel(shown), {
    text: "$(graph) figures/fit.pdf",
    tooltip: "Figure saved from what this cell shows when stage 'fit' runs",
  });
});

test("getAssignedNames finds what a cell leaves, last first", () => {
  assert.deepEqual(
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
    ["fig", "f", "n", "b", "a", "rates", "ax", "temps", "t"],
  );
  // A loop goes through something more worth saving than its variables
  assert.deepEqual(
    getAssignedNames(
      "for temp, k in rates.items():\n    print(f'{temp}: {k}')",
    ),
    ["rates", "k", "temp"],
  );
  assert.deepEqual(getAssignedNames("for t, k in zip(temps, ks):"), [
    "temps",
    "ks",
    "k",
    "t",
  ]);
  assert.deepEqual(getAssignedNames(""), []);
});

test("rankNamesForKind puts the likely variable first", () => {
  const names = ["k", "ax", "fig", "summary_df", "rates"];
  assert.deepEqual(rankNamesForKind(names, "figure"), [
    "fig",
    "k",
    "ax",
    "summary_df",
    "rates",
  ]);
  assert.deepEqual(rankNamesForKind(names, "table").slice(0, 1), [
    "summary_df",
  ]);
  assert.deepEqual(rankNamesForKind(names, "value"), [
    "k",
    "summary_df",
    "rates",
    "ax",
    "fig",
  ]);
});

test("getDefaultMarkPath names a file after the notebook", () => {
  assert.equal(
    getDefaultMarkPath("figure", "nbs/Fit Rates.ipynb", "decay_fig"),
    "figures/fit-rates-decay-fig.pdf",
  );
  assert.equal(getDefaultMarkPath("figure", "fit.ipynb"), "figures/fit.png");
  assert.equal(
    getDefaultMarkPath("table", "fit.ipynb", "df"),
    "tables/fit-df.tex",
  );
});

test("getMarkArgs and getUnmarkArgs make the CLI's arguments", () => {
  assert.deepEqual(
    getMarkArgs({
      notebookPath: "fit.ipynb",
      cellId: "c2",
      cellIndex: 2,
      kind: "figure",
      variableNames: ["fig"],
      outputPath: "figures/fit.pdf",
    }),
    [
      "nb",
      "add-output",
      "fit.ipynb",
      "figure",
      "--cell-id",
      "c2",
      "--variable-name",
      "fig",
      "--output-path",
      "figures/fit.pdf",
      "--json",
    ],
  );
  // A cell without an ID is named by its position
  assert.deepEqual(
    getMarkArgs({
      notebookPath: "fit.ipynb",
      cellIndex: 0,
      kind: "value",
      variableNames: ["k", "j"],
      stage: "fit-2",
    }),
    [
      "nb",
      "add-output",
      "fit.ipynb",
      "value",
      "--cell-index",
      "0",
      "--variable-name",
      "k",
      "--variable-name",
      "j",
      "--stage",
      "fit-2",
      "--json",
    ],
  );
  assert.deepEqual(getUnmarkArgs("fit.ipynb", figure), [
    "nb",
    "remove-output",
    "fit.ipynb",
    "--output-path",
    "figures/fit.pdf",
    "--stage",
    "fit",
  ]);
});

test("getMarksForCell finds a cell's marks by ID or position", () => {
  const atEnd = {
    ...value,
    variable_name: "last",
    cell_id: null,
    cell_index: null,
  };
  const marks = [value, figure, atEnd];
  assert.deepEqual(getMarksForCell(marks, 0, "c0", false), [value]);
  // An ID wins over a position, e.g., once cells have moved
  assert.deepEqual(getMarksForCell(marks, 0, "c2", false), [figure]);
  assert.deepEqual(getMarksForCell(marks, 2, undefined, true), [figure, atEnd]);
});

test("hasImageOutput spots an image a figure can be saved from", () => {
  assert.equal(hasImageOutput(["text/plain", "image/png"]), true);
  assert.equal(hasImageOutput(["text/plain"]), false);
});
