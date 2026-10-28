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

/**
 * The command showing project content that a position in one line of
 * source falls in.
 *
 * A command in a comment doesn't count, the same as when Calkit reads the
 * document to bring in what it cites.
 */
export function citationAt(line: string, offset: number): Citation | null {
  const comment = line.search(/(?<!\\)%/);
  const matches = [
    ...line.matchAll(CK_VALUE_RE),
    ...line.matchAll(CK_FILE_RE),
    ...line.matchAll(INCLUDE_RE),
  ];
  for (const match of matches) {
    const start = match.index ?? 0;
    if (comment >= 0 && start >= comment) {
      continue;
    }
    if (offset < start || offset > start + match[0].length) {
      continue;
    }
    const [command, kind, options, first, second] = match;
    if (!command.startsWith("\\ck")) {
      return {
        kind: kind === "includegraphics" ? "figure" : "file",
        path: first.trim(),
        options: (options ?? "").replace(/^\[|\]$/g, "").trim(),
        included: true,
      };
    }
    return {
      // \ckinclude inputs any TeX, like a plain \input
      kind: kind === "include" ? "file" : (kind as Citation["kind"]),
      path: first.trim(),
      key: kind === "value" ? second?.trim() : undefined,
      options: (options ?? "").trim(),
    };
  }
  return null;
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
