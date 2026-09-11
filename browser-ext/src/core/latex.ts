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
