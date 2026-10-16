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

/** Project content a document cites with one of calkit.sty's commands. */
export interface Citation {
  kind: "value" | "figure" | "table";
  /** Relative to the project root, wherever the document is. */
  path: string;
  key?: string;
  /** A value's format spec, or a figure's graphics options. */
  options: string;
}

// Mirrors _CITE_RE in calkit/latex.py
const CITE_RE =
  /\\ck(value|figure|table)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}(?:\s*\{([^}]*)\})?/g;

/**
 * The calkit.sty command a position in one line of source falls in.
 *
 * A command in a comment doesn't count, the same as when Calkit reads the
 * document to bring in what it cites.
 */
export function citationAt(line: string, offset: number): Citation | null {
  const comment = line.search(/(?<!\\)%/);
  for (const match of line.matchAll(CITE_RE)) {
    const start = match.index ?? 0;
    if (comment >= 0 && start >= comment) {
      break;
    }
    if (offset < start || offset > start + match[0].length) {
      continue;
    }
    const [, kind, options, first, second] = match;
    return {
      kind: kind as Citation["kind"],
      path: first.trim(),
      key: kind === "value" ? second?.trim() : undefined,
      options: (options ?? "").trim(),
    };
  }
  return null;
}

/** The command that cites something, to insert into a document. */
export function citationText(citation: Citation): string {
  const options = citation.options ? `[${citation.options}]` : "";
  if (citation.kind === "value") {
    return `\\ckvalue${options}{${citation.path}}{${citation.key ?? ""}}`;
  }
  return `\\ck${citation.kind}${options}{${citation.path}}`;
}
