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

/** Something wrong with what a command shows, as a lint message. */
// Mirrors EXPORTED_EXTENSIONS in calkit/provenance.py: something else
// writes these, e.g., a script or an image editor saving from its own file
const EXPORTED_EXTENSIONS = [".png", ".gif", ".webp", ".bmp", ".pdf", ".eps"];

/** Whether a person can be the origin of a file, as opposed to a tool. */
export function canBeCreatedByPerson(path: string): boolean {
  const lower = path.toLowerCase();
  return !EXPORTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export interface CitationProblem {
  severity: "error" | "warning";
  kind: "value" | "missing" | "origin" | "stale";
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
