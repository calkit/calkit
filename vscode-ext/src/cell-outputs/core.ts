/**
 * What a notebook's cells save for documents, i.e., values,
 * figures, and tables Calkit saves when the pipeline runs the notebook, as
 * `calkit nb outputs --json` lists them, and the labels and commands for
 * them.
 */
import * as path from "node:path";

export type CellOutputKind = "value" | "figure" | "table";

export interface CellOutput {
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

/** Cell outputs from `calkit nb outputs --json`, or none if it can't be read. */
export function parseCellOutputs(stdout: string): CellOutput[] {
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

/** What an output saves: a value's variable, or a figure or table's path. */
export function getCellOutputTarget(output: CellOutput): string {
  return (
    (output.kind === "value" ? output.variable_name : output.output_path) ?? ""
  );
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

/** The label on a cell for one of its outputs, and its tooltip. */
export function getCellOutputLabel(output: CellOutput): {
  text: string;
  tooltip: string;
} {
  const icon = { value: "symbol-number", figure: "graph", table: "table" }[
    output.kind
  ];
  const target = getCellOutputTarget(output);
  let text = `$(${icon}) ${target}`;
  if (output.kind === "value") {
    text +=
      "saved_value" in output
        ? ` = ${formatSavedValue(output.saved_value)}`
        : " (not saved yet)";
  } else if (output.variable_name) {
    text += ` from ${output.variable_name}`;
  }
  const lines = [
    output.kind === "value"
      ? `Saved after this cell by stage '${output.stage}'`
      : `Saved from ${
          output.variable_name ? `'${output.variable_name}'` : "cell display"
        } by stage '${output.stage}'`,
  ];
  if (output.citation) {
    lines.push(`Cite with ${output.citation}`);
  }
  return { text, tooltip: lines.join("\n") };
}

/**
 * Names a cell assigns at its top level, last first, since a cell's result
 * is usually what it assigns last, e.g., `fig, ax = plt.subplots()` gives
 * `fig` and `ax`, then what its loops go through, e.g., `rates` in
 * `for t, k in rates.items()`, then loop variables, which only hold the
 * last item. JupyterLab's extension suggests the same.
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
      for (const m of loop[2].matchAll(/[A-Za-z_][A-Za-z0-9_]*(?![\w(])/g)) {
        const before = loop[2][(m.index ?? 0) - 1];
        if (before !== ".") {
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

/**
 * Names an output of a kind is most likely saved from first, e.g., `fig` for a
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
export function getDefaultOutputPath(
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

/**
 * The arguments to `calkit nb add-output` for an output, which can save
 * several values at once.
 */
export function getAddOutputArgs(options: {
  notebookPath: string;
  cellId?: string;
  cellIndex: number;
  kind: CellOutputKind;
  variableNames?: string[];
  outputPath?: string;
  stage?: string;
}): string[] {
  const args = ["nb", "add-output", options.notebookPath, options.kind];
  args.push(
    ...(options.cellId
      ? ["--cell-id", options.cellId]
      : ["--cell-index", String(options.cellIndex)]),
  );
  for (const name of options.variableNames ?? []) {
    args.push("--variable-name", name);
  }
  if (options.outputPath) {
    args.push("--output-path", options.outputPath);
  }
  if (options.stage) {
    args.push("--stage", options.stage);
  }
  return [...args, "--json"];
}

/** The arguments to `calkit nb remove-output` for an output. */
export function getRemoveOutputArgs(
  notebookPath: string,
  output: CellOutput,
): string[] {
  return [
    "nb",
    "remove-output",
    notebookPath,
    output.kind === "value" ? "--variable-name" : "--output-path",
    getCellOutputTarget(output),
    "--stage",
    output.stage,
  ];
}

/**
 * Outputs saved from the cell at a position, or with an ID, and for the last cell,
 * those saved after it because they name no cell.
 */
export function getCellOutputsForCell(
  cellOutputs: CellOutput[],
  cellIndex: number,
  cellId: string | undefined,
  isLast: boolean,
): CellOutput[] {
  return cellOutputs.filter((m) => {
    if (m.cell_id === null) {
      return isLast;
    }
    return cellId ? m.cell_id === cellId : m.cell_index === cellIndex;
  });
}

/** Whether a cell's outputs include an image, which a figure can be saved from. */
export function hasImageOutput(mimeTypes: string[]): boolean {
  return mimeTypes.some((m) =>
    ["image/png", "image/svg+xml", "image/jpeg", "application/pdf"].includes(m),
  );
}

/**
 * How a document at a project path shows an output, from its LaTeX
 * citation, or null if it can't, e.g., a CSV table. Values are named from
 * the project, as in LaTeX, and Markdown paths from the document.
 */
export function getCellOutputInsertText(
  output: CellOutput,
  documentPath: string,
): string | null {
  const ext = path.posix.extname(documentPath).toLowerCase();
  if (ext === ".tex") {
    return output.citation;
  }
  const quarto = ext === ".qmd";
  if (!quarto && ext !== ".md" && ext !== ".markdown") {
    return null;
  }
  const cited = output.citation?.match(/^\\ck\w+\{([^}]*)\}(?:\{([^}]*)\})?$/);
  if (output.kind === "value") {
    if (!cited?.[2]) {
      return null;
    }
    return quarto
      ? `{{< ckvalue ${cited[1]} ${cited[2]} >}}`
      : `<!-- ckvalue ${cited[1]} ${cited[2]} -->`;
  }
  const target = cited?.[1] ?? output.output_path;
  if (!target) {
    return null;
  }
  // Relative to the document, as Markdown and Quarto read paths
  const rel = path.posix.relative(path.posix.dirname(documentPath), target);
  if (output.kind === "figure") {
    return `![](${rel})`;
  }
  return quarto && /\.md$/i.test(rel) ? `{{< include ${rel} >}}` : null;
}
