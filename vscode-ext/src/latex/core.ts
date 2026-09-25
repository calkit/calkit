import * as path from "node:path";

// Pure helpers (no vscode imports) for diffing LaTeX documents, so they can be
// unit-tested under plain `node --test`.

// Turn a Git ref into one path component, mirroring `_ref_dirname` in
// calkit/latex.py.
function refDirname(ref: string): string {
  const name = ref.replace(/^_+/, "").replace(/_/g, "-").replace(/\//g, "-");
  return name.replace(/[^A-Za-z0-9.-]+/g, "-").replace(/^-+|-+$/g, "");
}

// Where `calkit latex diff` keeps a comparison against the working tree,
// mirroring `get_diff_path` in calkit/latex.py. An undefined `fromRef` means
// the CLI's default, the merge base with the default branch.
export function latexWorkingDiffPath(
  texFile: string,
  fromRef?: string,
): string {
  const name = refDirname(fromRef ?? "default-branch");
  return path.posix.join(
    ".calkit/local/latex-diffs",
    `${name}..working`,
    path.posix.dirname(texFile),
    `${path.posix.basename(texFile, path.posix.extname(texFile))}.pdf`,
  );
}
