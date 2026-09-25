import * as path from "node:path";
import type { CalkitInfo } from "../types";

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

// `calkit latex diff` options that build a document the way its latex stage
// does, mirroring the diff stages calkit/models/pipeline.py writes.
export function latexStageDiffArgs(
  config: CalkitInfo | undefined,
  texFile: string,
): string[] {
  const stage = Object.values(config?.pipeline?.stages ?? {}).find(
    (s) => s.kind === "latex" && s.target_path?.replace(/\\/g, "/") === texFile,
  );
  if (!stage) {
    return [];
  }
  const strings = (value: unknown): string[] =>
    Array.isArray(value) ? value.filter((v) => typeof v === "string") : [];
  return [
    ...(typeof stage.environment === "string" ? ["-e", stage.environment] : []),
    ...(typeof stage.latexmkrc_path === "string"
      ? ["-r", stage.latexmkrc_path]
      : []),
    ...strings(stage.latexmk_args).flatMap((a) => ["--latexmk-arg", a]),
    ...strings(stage.latexdiff_args).flatMap((a) => ["--latexdiff-arg", a]),
    ...(stage.keep_diff_tex === true ? ["--keep-tex"] : []),
  ];
}
