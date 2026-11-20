/**
 * What a notebook's cells are marked to make for documents, i.e., values,
 * figures, and tables Calkit saves when the pipeline runs the notebook, as
 * `calkit nb outputs --json` lists them, and the labels and commands for
 * them.
 */

export type CellOutputKind = "value" | "figure" | "table";

export interface CellOutputMark {
  stage: string;
  kind: CellOutputKind;
  name?: string;
  path?: string;
  cell: string | null;
  cell_index: number | null;
  variable: string | null;
  format: string | null;
  citation: string | null;
  saved_value?: unknown;
}

/** Marks from `calkit nb outputs --json`, or none if it can't be read. */
export function parseCellOutputs(stdout: string): CellOutputMark[] {
  try {
    const parsed = JSON.parse(stdout);
    return Array.isArray(parsed)
      ? parsed.filter(
          (m) =>
            m &&
            typeof m === "object" &&
            ["value", "figure", "table"].includes(m.kind),
        )
      : [];
  } catch {
    return [];
  }
}

/** What a mark saves: a value's name, or a figure or table's path. */
export function getMarkTarget(mark: CellOutputMark): string {
  return (mark.kind === "value" ? mark.name : mark.path) ?? "";
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
export function getMarkLabel(mark: CellOutputMark): {
  text: string;
  tooltip: string;
} {
  const icon = { value: "symbol-number", figure: "graph", table: "table" }[
    mark.kind
  ];
  const target = getMarkTarget(mark);
  let text = `$(${icon}) ${target}`;
  if (mark.kind === "value") {
    text +=
      "saved_value" in mark
        ? ` = ${formatSavedValue(mark.saved_value)}`
        : " (not saved yet)";
  } else if (mark.variable) {
    text += ` from ${mark.variable}`;
  }
  const lines = [
    mark.kind === "value"
      ? `Value saved after this cell when stage '${mark.stage}' runs`
      : `${mark.kind === "figure" ? "Figure" : "Table"} saved ${
          mark.variable
            ? `from '${mark.variable}'`
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
 * `fig` and `ax`.
 */
export function getAssignedNames(source: string): string[] {
  const names: string[] = [];
  const add = (name: string) => {
    const i = names.indexOf(name);
    if (i >= 0) {
      names.splice(i, 1);
    }
    names.push(name);
  };
  const identifier = /^[A-Za-z_][A-Za-z0-9_]*$/;
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
      for (const part of assign[1].replace(/[()*]/g, "").split(",")) {
        const name = part.trim();
        if (identifier.test(name)) {
          add(name);
        }
      }
      continue;
    }
    const loop = /^for\s+(.+?)\s+in\b/.exec(line);
    const withAs = /^with\b.*\bas\s+([A-Za-z_][A-Za-z0-9_]*)\s*:/.exec(line);
    for (const part of (loop?.[1] ?? withAs?.[1] ?? "")
      .replace(/[()]/g, "")
      .split(",")) {
      if (identifier.test(part.trim())) {
        add(part.trim());
      }
    }
  }
  return names.reverse();
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

/** The arguments to `calkit nb mark` for a mark. */
export function getMarkArgs(options: {
  notebookPath: string;
  cellId?: string;
  cellIndex: number;
  kind: CellOutputKind;
  target: string;
  variable?: string;
  stage?: string;
}): string[] {
  const args = ["nb", "mark", options.notebookPath];
  args.push(
    ...(options.cellId
      ? ["--cell", options.cellId]
      : ["--cell-index", String(options.cellIndex)]),
  );
  args.push(`--${options.kind}`, options.target);
  if (options.variable) {
    args.push("--variable", options.variable);
  }
  if (options.stage) {
    args.push("--stage", options.stage);
  }
  return [...args, "--json"];
}

/** The arguments to `calkit nb unmark` for a mark. */
export function getUnmarkArgs(
  notebookPath: string,
  mark: CellOutputMark,
): string[] {
  return [
    "nb",
    "unmark",
    notebookPath,
    `--${mark.kind}`,
    getMarkTarget(mark),
    "--stage",
    mark.stage,
  ];
}

/**
 * Marks on the cell at a position, or with an ID, and for the last cell,
 * those saved after it because they name no cell.
 */
export function getMarksForCell(
  marks: CellOutputMark[],
  cellIndex: number,
  cellId: string | undefined,
  isLast: boolean,
): CellOutputMark[] {
  return marks.filter((m) => {
    if (m.cell === null) {
      return isLast;
    }
    return cellId ? m.cell === cellId : m.cell_index === cellIndex;
  });
}

/** Whether a cell's outputs include an image, which a figure can be saved from. */
export function hasImageOutput(mimeTypes: string[]): boolean {
  return mimeTypes.some((m) =>
    ["image/png", "image/svg+xml", "image/jpeg", "application/pdf"].includes(m),
  );
}
