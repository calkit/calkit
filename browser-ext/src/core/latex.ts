import type { Provenance } from "./types";

/**
 * Where a project keeps the marked-up version of a document.
 *
 * A `latex` stage can declare comparisons it wants built, and each lands
 * beside the project's other derived files under a directory named after
 * what it compares, with the document's own path inside it. A pull
 * request's base branch is the usual comparison, so the diff for
 * `pubs/paper-1/main.pdf` against `main` is
 * `.calkit/latex-diffs/main/pubs/paper-1/main.pdf`.
 *
 * Mirrors ``_ref_dirname`` and ``get_diff_path`` in the Python package;
 * the two have to agree, since this is how the extension finds a file it
 * didn't create.
 */
export function refDirName(ref: string): string {
  const name = ref.replace(/^_+/, "").replace(/[_/]/g, "-");
  return name.replace(/[^A-Za-z0-9.-]+/g, "-").replace(/^-+|-+$/g, "");
}

export function latexDiffPath(baseRef: string, outputPath: string): string {
  return `.calkit/latex-diffs/${refDirName(baseRef)}/${outputPath}`;
}

/** Whether an artifact is a document a marked-up diff could exist for. */
export function isDiffableDocument(path: string): boolean {
  return /\.pdf$/i.test(path);
}

/**
 * Project content a document shows, cited with one of calkit.sty's
 * commands or included plainly, e.g., with `\\includegraphics`.
 */
export interface Citation {
  kind: "value" | "figure" | "table" | "file";
  /**
   * Relative to the project root, wherever the document is, except for an
   * included file, which TeX finds relative to the document.
   */
  path: string;
  key?: string;
  /** A value's format spec, or a figure's graphics options. */
  options: string;
  /** Included plainly, so its path may also leave off the extension. */
  included?: boolean;
}

// Mirror _CK_COMMAND_RE in calkit/latex.py, where only \ckvalue takes a
// second brace group
const CK_VALUE_RE =
  /\\ck(value)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}\s*\{([^}]*)\}/g;
const CK_FILE_RE =
  /\\ck(figure|table|include)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}/g;
// The plain commands among _INPUT_COMMANDS in calkit/latex.py that show
// something from the project
const INCLUDE_RE =
  /\\(includegraphics|input|include)\s*((?:\[[^\]]*\])*)\s*\{([^}]*)\}/g;
// What TeX tries after the name as written, as in _INPUT_COMMANDS
const GRAPHICS_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".gif"];

/** A command showing project content, and where it is in its line. */
export interface CitationMatch {
  citation: Citation;
  start: number;
  end: number;
}

/**
 * The commands showing project content in one line of source, in order.
 *
 * A command in a comment doesn't count, the same as when Calkit reads the
 * document to bring in what it cites.
 */
export function citationsIn(line: string): CitationMatch[] {
  const comment = line.search(/(?<!\\)%/);
  const matches = [
    ...line.matchAll(CK_VALUE_RE),
    ...line.matchAll(CK_FILE_RE),
    ...line.matchAll(INCLUDE_RE),
  ];
  const found: CitationMatch[] = [];
  for (const match of matches) {
    const start = match.index ?? 0;
    if (comment >= 0 && start >= comment) {
      continue;
    }
    const [command, kind, options, first, second] = match;
    const citation: Citation = command.startsWith("\\ck")
      ? {
          // \ckinclude inputs any TeX, like a plain \input
          kind: kind === "include" ? "file" : (kind as Citation["kind"]),
          path: first.trim(),
          key: kind === "value" ? second?.trim() : undefined,
          options: (options ?? "").trim(),
        }
      : {
          kind: kind === "includegraphics" ? "figure" : "file",
          path: first.trim(),
          options: (options ?? "").replace(/^\[|\]$/g, "").trim(),
          included: true,
        };
    found.push({ citation, start, end: start + command.length });
  }
  return found.sort((a, b) => a.start - b.start);
}

/** The command showing project content that a position in a line is in. */
export function citationAt(line: string, offset: number): Citation | null {
  return (
    citationsIn(line).find(
      (match) => offset >= match.start && offset <= match.end,
    )?.citation ?? null
  );
}

/**
 * Where in the project a cited or included file could be, in the order TeX
 * tries them, given the folder the Overleaf project syncs with.
 *
 * Mirrors ``component_candidates`` in calkit/latex.py for calkit.sty's
 * commands, and the lookup in ``detect_inputs`` for plain includes.
 */
export function citationCandidates(
  folder: string,
  citation: Citation,
): string[] {
  const exts = citation.kind === "figure" ? GRAPHICS_EXTS : [".tex"];
  if (!citation.included) {
    const path = citation.path.replace(/^\.\//, "");
    if (
      citation.kind === "value" ||
      exts.some((ext) => path.toLowerCase().endsWith(ext))
    ) {
      return [path];
    }
    return [...exts.map((ext) => path + ext), path];
  }
  const parts: string[] = [];
  for (const part of `${folder}/${citation.path}`.split("/")) {
    if (part === "..") {
      parts.pop();
    } else if (part && part !== ".") {
      parts.push(part);
    }
  }
  const path = parts.join("/");
  if (exts.some((ext) => path.toLowerCase().endsWith(ext))) {
    return [path];
  }
  return [path, ...exts.map((ext) => path + ext)];
}

/** The command that cites something, to insert into a document. */
export function citationText(citation: Citation): string {
  const options = citation.options ? `[${citation.options}]` : "";
  if (citation.kind === "value") {
    return `\\ckvalue${options}{${citation.path}}{${citation.key ?? ""}}`;
  }
  const command = citation.kind === "file" ? "include" : citation.kind;
  return `\\ck${command}${options}{${citation.path}}`;
}

// Mirrors EXPORTED_EXTENSIONS in calkit/provenance.py: something else
// writes these, e.g., a script or an image editor saving from its own file
const EXPORTED_EXTENSIONS = [".png", ".gif", ".webp", ".bmp", ".pdf", ".eps"];

/** The app each export stage kind runs, e.g., for "Exported with Inkscape". */
export const EXPORT_APPS: Record<string, string> = {
  "inkscape-export": "Inkscape",
  "gimp-export": "GIMP",
};

/** Whether a person can be the origin of a file, as opposed to a tool. */
export function canBeCreatedByPerson(path: string): boolean {
  const lower = path.toLowerCase();
  return !EXPORTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/** Something wrong with what a command shows, as a lint message. */
export interface CitationProblem {
  severity: "error" | "warning";
  kind: "value" | "missing" | "origin" | "stale" | "typed";
  message: string;
  /** What it's about, e.g., data a figure is made from. */
  path: string;
}

/**
 * What's wrong with what a command shows, worst first.
 *
 * Its origin has to be defined, whether by the pipeline, an import, or a
 * person, and so does the origin of everything it's made from. A plainly
 * included file may be a section only Overleaf has yet, so only a
 * calkit.sty command has to name something in the project.
 */
export function citationProblems(
  citation: Citation,
  provenance: Provenance,
): CitationProblem[] {
  const path = provenance.path;
  const problems: CitationProblem[] = [];
  const missing = !provenance.exists && !provenance.stage;
  if (citation.kind === "value" && provenance.value_error) {
    problems.push({
      severity: "error",
      kind: "value",
      message: provenance.value_error,
      path,
    });
  } else if (missing && !citation.included) {
    problems.push({
      severity: "error",
      kind: "missing",
      message: `${path} isn't in the project`,
      path,
    });
  }
  for (const gap of provenance.gaps ?? []) {
    if (gap.path === path && missing) {
      continue;
    }
    const via = gap.steps.flatMap((step) => (step.stage ? [step.stage] : []));
    const through = via.length ? ` (via ${via.join(", ")})` : "";
    problems.push({
      severity: gap.unchecked ? "warning" : "error",
      kind: "origin",
      message: gap.unchecked
        ? gap.path === path
          ? "Imported from somewhere that can't be checked"
          : `${gap.path}, which it's made from, is imported from ` +
            `somewhere that can't be checked${through}`
        : gap.path === path
        ? "Origin not defined"
        : `Origin not defined for ${gap.path}, which it's made from${through}`,
      path: gap.path,
    });
  }
  if (provenance.stale_reason) {
    problems.push({
      severity: "warning",
      kind: "stale",
      message:
        provenance.stale_reason === "frozen"
          ? "Out of date: its stage is frozen, and what it reads or " +
            "writes has moved since it ran"
          : // Made manually, so someone has to do it again
          provenance.stage_kind === "manual-step"
          ? "Needs a manual step, since what it's made from changed" +
            (provenance.message ? `: ${provenance.message}` : "")
          : "Out of date: what it's made from changed since it last ran",
      path,
    });
  }
  return problems;
}

/** A number typed into a document's text that looks like a result. */
export interface TypedNumber {
  /** As typed, e.g., `-1,234.50`. */
  text: string;
  value: number;
  /** Decimal places typed, which says how far it was rounded. */
  decimals: number;
  /** Typed with commas between thousands. */
  grouped: boolean;
  /** The power of ten typed with it, e.g., 3 for `1.2e3`. */
  exponent: number | null;
}

export interface TypedNumberMatch {
  number: TypedNumber;
  start: number;
  end: number;
}

// Commands whose arguments aren't text, and how many of those arguments
// there are, e.g., \multicolumn's third is the cell's text
//
// siunitx's commands are left out for now, since a number in one can't
// simply be swapped for a \ckvalue
const NOT_TEXT: Record<string, number> = {
  addtocounter: 2,
  addtolength: 2,
  autoref: 1,
  begin: 2,
  bibliography: 1,
  bibliographystyle: 1,
  cite: 1,
  citealp: 1,
  citeauthor: 1,
  citep: 1,
  citet: 1,
  citeyear: 1,
  ckfigure: 1,
  ckinclude: 1,
  cknum: 1,
  cktable: 1,
  ckvalue: 2,
  cline: 1,
  cmidrule: 1,
  colorbox: 1,
  cref: 1,
  Cref: 1,
  definecolor: 3,
  documentclass: 1,
  end: 1,
  eqref: 1,
  graphicspath: 1,
  hspace: 1,
  href: 1,
  include: 1,
  includegraphics: 1,
  input: 1,
  label: 1,
  linespread: 1,
  multicolumn: 2,
  multirow: 2,
  num: 1,
  numrange: 2,
  newcommand: 2,
  nocite: 1,
  pageref: 1,
  qty: 2,
  qtyrange: 3,
  raisebox: 1,
  ref: 1,
  renewcommand: 2,
  RequirePackage: 1,
  resizebox: 2,
  rule: 2,
  scalebox: 1,
  setcounter: 2,
  setlength: 2,
  SI: 2,
  si: 1,
  SIrange: 3,
  textcolor: 1,
  unit: 1,
  url: 1,
  usepackage: 1,
  vspace: 1,
};
// A decimal, or a whole number with commas between thousands, and not part
// of a name, a version like 1.2.3, or a length like 0.5\textwidth
const NUMBER_RE =
  /(?<![\w.\\@])-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w]|\.\d|,\d{3}|\\(?:text|line|column|paper)(?:width|height)|\\baselineskip)/g;

/**
 * The numbers typed into one line of a document that look like results,
 * which a `\\ckvalue` could show instead, in order.
 *
 * Those are decimals, whole numbers grouped with commas, percentages, and
 * either side of a ±. Other whole numbers are too often counts, years,
 * or section numbers to be worth marking. A number in a comment, an
 * option, or an argument that isn't text, e.g., a length, doesn't count.
 */
export function typedNumbersIn(line: string): TypedNumberMatch[] {
  const comment = line.search(/(?<!\\)%/);
  const text = comment >= 0 ? line.slice(0, comment) : line;
  // Where options and arguments that aren't text are
  const skipped: [number, number][] = [];
  for (const command of text.matchAll(/\\([A-Za-z@]+)\*?/g)) {
    let args = NOT_TEXT[command[1]] ?? 0;
    let at = (command.index ?? 0) + command[0].length;
    while (at < text.length) {
      const start = at + (text.slice(at).match(/^\s*/)?.[0].length ?? 0);
      const open = text[start];
      if (open !== "[" && !(open === "{" && args > 0)) {
        break;
      }
      // Options are never text; braces nest, but brackets don't
      let end = start + 1;
      if (open === "[") {
        while (end < text.length && text[end] !== "]") {
          end++;
        }
      } else {
        let depth = 1;
        while (end < text.length && depth) {
          depth += text[end] === "{" ? 1 : text[end] === "}" ? -1 : 0;
          end++;
        }
        args--;
      }
      skipped.push([start, end]);
      at = end + 1;
    }
  }
  const found: TypedNumberMatch[] = [];
  for (const match of text.matchAll(NUMBER_RE)) {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    if (skipped.some(([from, to]) => start >= from && start < to)) {
      continue;
    }
    const raw = match[0];
    const [mantissa, power] = raw.split(/[eE]/);
    const decimals = mantissa.split(".")[1]?.length ?? 0;
    const grouped = mantissa.includes(",");
    const percent = /^(?:\s|~|\\,)*\\%/.test(text.slice(end));
    const plusMinus =
      /^\s*(?:\\pm|±|\\mp)/.test(text.slice(end)) ||
      /(?:\\pm|±|\\mp)\s*$/.test(text.slice(0, start));
    if (!decimals && !grouped && !percent && !plusMinus) {
      continue;
    }
    found.push({
      number: {
        text: raw,
        value: Number(raw.replace(/,/g, "")),
        decimals,
        grouped,
        exponent: power === undefined ? null : Number(power),
      },
      start,
      end,
    });
  }
  return found;
}

/** What a line ends with to say its numbers aren't results. */
export const IGNORE_COMMENT = "% calkit: ignore";

/**
 * Whether a line says its numbers aren't results, e.g., ones quoted from a
 * datasheet, with `% calkit: ignore` in its comment.
 */
export function isIgnored(line: string): boolean {
  const comment = line.search(/(?<!\\)%/);
  return comment >= 0 && /calkit:\s*ignore\b/.test(line.slice(comment));
}

/** A table typed into a document, with the numbers in it. */
export interface TypedTable {
  /** Where `\\begin{tabular}` starts, by 0-based line. */
  start: { line: number; column: number };
  /** Just past `\\end{tabular}`. */
  end: { line: number; column: number };
  /** The environment's name, e.g., `tabular`. */
  env: string;
  numbers: TypedNumber[];
}

const TABLE_RE = /\\begin\s*\{(tabular\*?|tabularx|tabulary|longtable)\}/;

/**
 * The typed numbers in a whole document, by 0-based line, and the tables
 * that hold some, whose numbers are kept together, since a table is better
 * shown from a file a stage writes than number by number.
 *
 * Only the body counts, where there is one, since the preamble sets up
 * the document rather than reporting anything, and neither does code in
 * a verbatim or listing environment, or the bibliography. Nor does a
 * number cited in its sentence with no other number in between, since
 * it's likely quoted from there, or one on a line marked with
 * `% calkit: ignore`, which on a table's `\\begin` line ignores the
 * whole table.
 */
export function typedNumbersInDocument(lines: string[]): {
  numbers: { line: number; match: TypedNumberMatch }[];
  tables: TypedTable[];
} {
  const body = lines.findIndex((line) =>
    /^[^%]*\\begin\s*\{document\}/.test(line),
  );
  const first = body < 0 ? 0 : body + 1;
  const code = (n: number) => {
    const comment = lines[n].search(/(?<!\\)%/);
    return comment >= 0 ? lines[n].slice(0, comment) : lines[n];
  };
  // Whether the sentence a number is in cites something, looking across
  // lines to where it starts and ends, or to a blank line
  const sentenceEnd = /[.!?](?=\s|$)/g;
  const cited = (n: number, match: TypedNumberMatch) => {
    let before = code(n).slice(0, match.start);
    for (let i = n; !before.match(sentenceEnd) && i > first; i--) {
      if (!code(i - 1).trim()) {
        break;
      }
      before = `${code(i - 1)} ${before}`;
    }
    const ends = [...before.matchAll(sentenceEnd)];
    before = before.slice((ends.at(-1)?.index ?? -1) + 1);
    let after = code(n).slice(match.end);
    for (let i = n; !after.match(sentenceEnd) && i + 1 < lines.length; i++) {
      if (!code(i + 1).trim()) {
        break;
      }
      after = `${after} ${code(i + 1)}`;
    }
    after = after.slice(0, after.search(sentenceEnd) + 1 || after.length);
    // Only up to the next number either way, since a citation next to
    // another number is that number's
    const cite = /\\[a-zA-Z]*cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]\s*)*\{/;
    const last = typedNumbersIn(before).at(-1)?.end ?? 0;
    const next = typedNumbersIn(after)[0]?.start ?? after.length;
    return cite.test(before.slice(last)) || cite.test(after.slice(0, next));
  };
  const numbers: { line: number; match: TypedNumberMatch }[] = [];
  const tables: TypedTable[] = [];
  let skipping: string | null = null;
  let table: (TypedTable & { ignored: boolean }) | null = null;
  for (let n = first; n < lines.length; n++) {
    const line = lines[n];
    if (/^[^%]*\\end\s*\{document\}/.test(line)) {
      break;
    }
    if (skipping) {
      if (line.includes(`\\end{${skipping}}`)) {
        skipping = null;
      }
      continue;
    }
    const begin = line.match(
      /\\begin\s*\{(verbatim\*?|Verbatim|lstlisting|minted|comment|thebibliography)\}/,
    );
    if (begin) {
      skipping = line.includes(`\\end{${begin[1]}}`) ? null : begin[1];
      continue;
    }
    const text = code(n);
    const ignored = isIgnored(line);
    let from = 0;
    if (!table) {
      const opened = text.match(TABLE_RE);
      if (opened) {
        from = opened.index ?? 0;
        table = {
          start: { line: n, column: from },
          end: { line: n, column: text.length },
          env: opened[1],
          numbers: [],
          ignored,
        };
      }
    }
    let to = line.length;
    let closed = false;
    if (table) {
      const end = `\\end{${table.env}}`;
      const at = text.indexOf(end, from);
      if (at >= 0) {
        to = at + end.length;
        table.end = { line: n, column: to };
        closed = true;
      }
    }
    for (const match of ignored ? [] : typedNumbersIn(line)) {
      if (table && match.start >= from && match.start < to) {
        table.numbers.push(match.number);
      } else if (!cited(n, match)) {
        numbers.push({ line: n, match });
      }
    }
    if (table && closed) {
      const { ignored, ...typed } = table;
      if (typed.numbers.length && !ignored) {
        tables.push(typed);
      }
      table = null;
    }
  }
  return { numbers, tables };
}

/** A number in a results file, by the key `\\ckvalue` takes for it. */
export interface ResultValue {
  path: string;
  key: string;
  value: number;
}

/** Every number in a results file, by its dotted key. */
export function resultValues(path: string, data: unknown): ResultValue[] {
  const found: ResultValue[] = [];
  const walk = (value: unknown, key: string) => {
    if (typeof value === "number" && Number.isFinite(value)) {
      found.push({ path, key, value });
    } else if (value !== null && typeof value === "object") {
      const entries = Array.isArray(value)
        ? value.map((item, i) => [String(i), item] as const)
        : Object.entries(value as Record<string, unknown>);
      for (const [name, item] of entries) {
        walk(item, key ? `${key}.${name}` : name);
      }
    }
  };
  walk(data, "");
  return found;
}

/** Whether a value rounds to a number the way it was typed. */
function roundsTo(number: TypedNumber, value: number): boolean {
  const half = (0.5 * 10 ** (number.exponent ?? 0)) / 10 ** number.decimals;
  return Math.abs(value - number.value) <= half * (1 + 1e-9) + 1e-12;
}

/**
 * The results a typed number could be, i.e., those that round to it, or
 * failing that, the few nearest it, which may be what it should have said.
 */
export function typedNumberMatches(
  number: TypedNumber,
  values: ResultValue[],
): { exact: ResultValue[]; close: ResultValue[] } {
  const off = (v: ResultValue) => Math.abs(v.value - number.value);
  const exact = values.filter((v) => roundsTo(number, v.value));
  if (exact.length) {
    return { exact, close: [] };
  }
  // Near enough to be a mistyped or outdated copy of it
  const half = (0.5 * 10 ** (number.exponent ?? 0)) / 10 ** number.decimals;
  const near = Math.max(Math.abs(number.value) * 0.25, half * 4);
  const close = values
    .filter((v) => off(v) <= near)
    .sort((a, b) => off(a) - off(b))
    .slice(0, 3);
  return { exact, close };
}

/** The `\\ckvalue` showing a result the way a typed number was written. */
export function typedNumberCitation(
  number: TypedNumber,
  value: ResultValue,
): Citation {
  const options =
    number.exponent !== null
      ? `.${number.decimals}e`
      : `${number.grouped ? "," : ""}.${number.decimals}f`;
  return { kind: "value", path: value.path, key: value.key, options };
}

/** How a result reads once rounded the way a typed number was. */
export function roundedLike(number: TypedNumber, value: number): string {
  if (number.exponent !== null) {
    return value.toExponential(number.decimals);
  }
  const fixed = value.toFixed(number.decimals);
  return number.grouped
    ? Number(fixed).toLocaleString("en-US", {
        minimumFractionDigits: number.decimals,
        maximumFractionDigits: number.decimals,
      })
    : fixed;
}

/** What's wrong with a typed number: the paper can't say where it's from. */
export function typedNumberProblem(
  number: TypedNumber,
  values: ResultValue[],
): CitationProblem {
  const [first] = typedNumberMatches(number, values).exact;
  return {
    severity: "warning",
    kind: "typed",
    message: first
      ? `Typed in, though it matches ${first.key} in ${first.path}`
      : "Typed in, and no result in the project matches it",
    path: first?.path ?? "",
  };
}

/** A table a stage writes as TeX, which `\\cktable` can show. */
export interface TableFile {
  path: string;
  /** Its numbers, the same ones a typed table would have. */
  numbers: TypedNumber[];
}

/**
 * The numbers in a table file, or null if `\\cktable` can't replace a
 * typed table with it, i.e., it has no table, or wraps it in a float.
 */
export function tableFile(path: string, text: string): TableFile | null {
  if (!TABLE_RE.test(text) || /\\begin\s*\{table\*?\}/.test(text)) {
    return null;
  }
  const { numbers, tables } = typedNumbersInDocument(text.split("\n"));
  return {
    path,
    numbers: [
      ...numbers.map(({ match }) => match.number),
      ...tables.flatMap((table) => table.numbers),
    ],
  };
}

/**
 * The table files a typed table could be shown from, best first, with how
 * many of its numbers each has, rounded the way they were typed.
 *
 * A third is enough, since an outdated table may only agree on what it's
 * tabulated over, e.g., the speeds, and not the results.
 */
export function typedTableMatches(
  table: Pick<TypedTable, "numbers">,
  files: TableFile[],
): { path: string; matched: number }[] {
  return files
    .map((file) => ({
      path: file.path,
      matched: table.numbers.filter((number) =>
        file.numbers.some((other) => roundsTo(number, other.value)),
      ).length,
    }))
    .filter(({ matched }) => matched * 3 >= table.numbers.length)
    .sort((a, b) => b.matched - a.matched);
}

/** What's wrong with a typed table: the paper can't say where it's from. */
export function typedTableProblem(
  table: Pick<TypedTable, "numbers">,
  files: TableFile[],
): CitationProblem {
  const [best] = typedTableMatches(table, files);
  return {
    severity: "warning",
    kind: "typed",
    message: best
      ? `Typed in, though ${best.path} has a table like it`
      : "Typed in, and no table in the project matches it",
    path: best?.path ?? "",
  };
}
