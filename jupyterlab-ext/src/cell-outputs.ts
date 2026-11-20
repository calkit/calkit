/**
 * What a notebook's cells are marked to make for documents, i.e., values,
 * figures, and tables Calkit saves when the pipeline runs the notebook, as
 * the server's `notebook/cell/outputs` route lists them, and the labels,
 * choices, and requests for them.
 */

export type CellOutputKind = "value" | "figure" | "table";

export interface ICellOutputMark {
  stage: string;
  kind: CellOutputKind;
  cell_id: string | null;
  cell_index: number | null;
  variable_name: string | null;
  output_path: string | null;
  format: string | null;
  citation: string | null;
  saved_value?: unknown;
}

/** A choice of what a figure or table is saved from. */
export interface IVariableChoice {
  label: string;
  /** The variable, or none for the image a cell shows. */
  variable?: string;
  /** Whether to ask for another variable. */
  isOther?: boolean;
}

export const SHOWN_IMAGE_LABEL = "Image this cell shows";
export const OTHER_VARIABLE_LABEL = "Other variable…";

/** Extensions each kind of file can be saved as, by kind. */
export const MARK_EXTENSIONS: Record<"figure" | "table", string[]> = {
  figure: [".pdf", ".png", ".svg", ".jpg", ".jpeg"],
  table: [".tex", ".csv", ".md", ".json"],
};

/** Marks from the server's response, or none if it isn't a list of them. */
export function filterCellOutputMarks(data: unknown): ICellOutputMark[] {
  return Array.isArray(data)
    ? data.filter(
        (m) =>
          m &&
          typeof m === "object" &&
          ["value", "figure", "table"].includes(m.kind),
      )
    : [];
}

/** What a mark saves: a value's name, or a figure or table's path. */
export function getMarkTarget(mark: ICellOutputMark): string {
  return (mark.kind === "value" ? mark.variable_name : mark.output_path) ?? "";
}

/** A saved value as short text, e.g., `0.03091` or `{3 keys}`. */
export function formatSavedValue(value: unknown): string {
  if (typeof value === "number") {
    if (Number.isInteger(value) || value === 0) {
      return String(value);
    }
    const abs = Math.abs(value);
    return abs >= 1e-3 && abs < 1e6
      ? String(Number(value.toPrecision(4)))
      : value.toExponential(3);
  }
  if (typeof value === "string") {
    return JSON.stringify(value.length > 24 ? value.slice(0, 23) + "…" : value);
  }
  if (Array.isArray(value)) {
    return `[${value.length} item${value.length === 1 ? "" : "s"}]`;
  }
  if (value && typeof value === "object") {
    const n = Object.keys(value).length;
    return `{${n} key${n === 1 ? "" : "s"}}`;
  }
  return String(value);
}

/** The label on a cell for one of its marks, and its tooltip. */
export function getMarkLabel(mark: ICellOutputMark): {
  text: string;
  tooltip: string;
} {
  let text = getMarkTarget(mark);
  if (mark.kind === "value") {
    text +=
      "saved_value" in mark
        ? ` = ${formatSavedValue(mark.saved_value)}`
        : " (not saved yet)";
  } else if (mark.variable_name) {
    text += ` from ${mark.variable_name}`;
  }
  const lines = [
    mark.kind === "value"
      ? `Value saved after this cell when stage '${mark.stage}' runs`
      : `${mark.kind === "figure" ? "Figure" : "Table"} saved ${
          mark.variable_name
            ? `from '${mark.variable_name}'`
            : "from what this cell shows"
        } when stage '${mark.stage}' runs`,
  ];
  if (mark.citation) {
    lines.push(`Show it in a document with ${mark.citation}`);
  }
  return { text, tooltip: lines.join("\n") };
}

/**
 * Names a cell assigns at its top level, last first, since a cell's result
 * is usually what it assigns last, e.g., `fig, ax = plt.subplots()` gives
 * `fig` and `ax`, then what its loops go through, e.g., `rates` in
 * `for t, k in rates.items()`, then loop variables, which only hold the
 * last item. VS Code's extension suggests the same.
 */
export function getAssignedNames(source: string): string[] {
  const assigned: string[] = [];
  const iterated: string[] = [];
  const looped: string[] = [];
  const add = (names: string[], name: string) => {
    const i = names.indexOf(name);
    if (i >= 0) {
      names.splice(i, 1);
    }
    names.push(name);
  };
  const identifier = /^[A-Za-z_][A-Za-z0-9_]*$/;
  const addEach = (names: string[], text: string) => {
    for (const part of text.replace(/[()*]/g, "").split(",")) {
      if (identifier.test(part.trim())) {
        add(names, part.trim());
      }
    }
  };
  for (const line of source.split(/\r?\n/)) {
    // Only the top level, since a value inside a function or loop isn't
    // what the cell leaves
    if (/^\s/.test(line) || line.startsWith("#")) {
      continue;
    }
    const assign =
      /^([A-Za-z_(][A-Za-z0-9_,\s()*]*?)\s*(?::[^=]*)?(?:[+\-*/%@&|^]|\/\/|\*\*|<<|>>)?=(?!=)/.exec(
        line,
      );
    if (assign) {
      addEach(assigned, assign[1]);
      continue;
    }
    const loop = /^for\s+(.+?)\s+in\s+(.+?):?\s*$/.exec(line);
    if (loop) {
      addEach(looped, loop[1]);
      // What's gone through, but not the functions called on it
      const word = /[A-Za-z_][A-Za-z0-9_]*(?![\w(])/g;
      let m: RegExpExecArray | null;
      while ((m = word.exec(loop[2])) !== null) {
        if (loop[2][m.index - 1] !== ".") {
          add(iterated, m[0]);
        }
      }
      continue;
    }
    const withAs = /^with\b.*\bas\s+([A-Za-z_][A-Za-z0-9_]*)\s*:/.exec(line);
    if (withAs) {
      add(assigned, withAs[1]);
    }
  }
  const names = [
    ...assigned.reverse(),
    ...iterated.filter((n) => !looped.includes(n)),
    ...looped.reverse(),
  ];
  return [...new Set(names)];
}

/** Whether text is a Python variable name. */
export function isVariableName(name: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name);
}

/**
 * Names a mark of a kind is most likely saved from first, e.g., `fig` for a
 * figure and `df` for a table, then the rest as the cell assigns them.
 */
export function rankNamesForKind(
  names: string[],
  kind: CellOutputKind,
): string[] {
  const likely: Record<CellOutputKind, RegExp> = {
    value: /^(?!fig|ax|df|plt$)/i,
    figure: /^(fig|figure|plot|chart|g)\b|fig/i,
    table: /^(df|table|tab|summary|results?)\b|df|table/i,
  };
  const first = names.filter((n) => likely[kind].test(n));
  return [...first, ...names.filter((n) => !first.includes(n))];
}

/**
 * What a mark can be saved from, most likely first: for a figure, the image
 * the cell shows if it shows one, then the cell's variables, then another
 * variable, and last, the image, if the cell hasn't shown it yet.
 */
export function getVariableChoices(
  source: string,
  kind: CellOutputKind,
  hasImage: boolean,
): IVariableChoice[] {
  const names = rankNamesForKind(getAssignedNames(source), kind);
  return [
    ...(kind === "figure" && hasImage ? [{ label: SHOWN_IMAGE_LABEL }] : []),
    ...names.map((n) => ({ label: n, variable: n })),
    { label: OTHER_VARIABLE_LABEL, isOther: true },
    ...(kind === "figure" && !hasImage
      ? [{ label: `${SHOWN_IMAGE_LABEL} (run cell first)` }]
      : []),
  ];
}

/**
 * A path to save a figure or table to, from the notebook's name and the
 * variable, e.g., `figures/fit-rates-fig.pdf`, as a PDF for a figure from
 * a variable, which stays sharp in a paper, and otherwise the PNG a cell
 * shows.
 */
export function getDefaultMarkPath(
  kind: "figure" | "table",
  notebookPath: string,
  variable?: string,
): string {
  const stem = (notebookPath.split("/").pop() ?? "notebook")
    .replace(/\.ipynb$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  const name = [stem, variable?.toLowerCase().replace(/_/g, "-")]
    .filter(Boolean)
    .join("-");
  if (kind === "table") {
    return `tables/${name}.tex`;
  }
  return `figures/${name}.${variable ? "pdf" : "png"}`;
}

/** What's wrong with a path to save a figure or table to, if anything. */
export function getMarkPathError(
  kind: "figure" | "table",
  path: string,
): string | null {
  const exts = MARK_EXTENSIONS[kind];
  return exts.some((e) => path.trim().toLowerCase().endsWith(e))
    ? null
    : `Use ${exts.join(", ")}`;
}

/**
 * The body of a request to mark a cell's output: the notebook's path, and
 * the output as calkit.yaml has it, which can save several values at once.
 */
export function getMarkRequestBody(options: {
  notebookPath: string;
  cellId: string;
  kind: CellOutputKind;
  variableNames?: string[];
  outputPath?: string;
  stage?: string;
}): Record<string, unknown> {
  const output: Record<string, unknown> = {
    kind: options.kind,
    cell_id: options.cellId,
  };
  const names = options.variableNames ?? [];
  if (names.length === 1) {
    output.variable_name = names[0];
  } else if (names.length > 1) {
    output.variable_names = names;
  }
  if (options.outputPath && options.kind !== "value") {
    output.output_path = options.outputPath;
  }
  return {
    path: options.notebookPath,
    output,
    ...(options.stage ? { stage: options.stage } : {}),
  };
}

/** The query of a request to unmark a mark. */
export function getUnmarkQuery(
  notebookPath: string,
  mark: ICellOutputMark,
): string {
  return new URLSearchParams({
    path: notebookPath,
    [mark.kind === "value" ? "variable_name" : "output_path"]:
      getMarkTarget(mark),
    stage: mark.stage,
  }).toString();
}

/**
 * Marks on the cell at a position, or with an ID, and for the last cell,
 * those saved after it because they name no cell.
 */
export function getMarksForCell(
  marks: ICellOutputMark[],
  cellIndex: number,
  cellId: string | undefined,
  isLast: boolean,
): ICellOutputMark[] {
  return marks.filter((m) => {
    if (m.cell_id === null) {
      return isLast;
    }
    return cellId ? m.cell_id === cellId : m.cell_index === cellIndex;
  });
}

/** The MIME types of a cell's outputs, as nbformat stores them. */
export function getOutputMimeTypes(outputs: unknown[]): string[] {
  const mimeTypes: string[] = [];
  for (const output of outputs) {
    const data = (output as { data?: unknown } | null)?.data;
    if (data && typeof data === "object") {
      mimeTypes.push(...Object.keys(data));
    }
  }
  return mimeTypes;
}

/** Whether a cell's outputs include an image, which a figure can be saved from. */
export function hasImageOutput(mimeTypes: string[]): boolean {
  return mimeTypes.some((m) =>
    ["image/png", "image/svg+xml", "image/jpeg", "application/pdf"].includes(m),
  );
}
