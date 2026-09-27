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

// A diff a latex stage keeps, mirroring `get_pipeline_diffs` in
// calkit/latex.py. `toRef` is undefined for a bare revision, which is
// compared with the working tree.
export interface PipelineLatexDiff {
  path: string;
  document: string;
  latexStage: string;
  stage: string;
  fromRef: string;
  toRef?: string;
}

export function pipelineLatexDiffs(
  stages: Record<string, unknown>,
): PipelineLatexDiff[] {
  const diffs: PipelineLatexDiff[] = [];
  for (const [name, raw] of Object.entries(stages)) {
    const stage = raw as {
      kind?: string;
      wdir?: string;
      target_path?: string;
      diffs?: (string | string[])[];
    };
    if (stage?.kind !== "latex" || !stage.target_path) {
      continue;
    }
    const wdir = stage.wdir ?? "";
    const target = stage.target_path;
    for (const entry of stage.diffs ?? []) {
      const [fromRef, toRef] =
        typeof entry === "string" ? [entry, "HEAD"] : [entry[0], entry[1]];
      let dir = refDirname(fromRef);
      let suffix = refDirname(fromRef);
      if (toRef !== "HEAD") {
        dir += `..${refDirname(toRef)}`;
        suffix += `-${refDirname(toRef)}`;
      }
      diffs.push({
        path: path.posix.join(
          wdir,
          ".calkit/latex-diffs",
          dir,
          path.posix.dirname(target),
          `${path.posix.basename(target, path.posix.extname(target))}.pdf`,
        ),
        document: path.posix.join(wdir, target),
        latexStage: name,
        stage: `${name}-diff-${suffix}`,
        fromRef,
        toRef: typeof entry === "string" ? undefined : toRef,
      });
    }
  }
  return diffs;
}

interface LatexStageFields {
  kind?: string;
  wdir?: string;
  target_path?: string;
}

// The PDF a latex stage builds from `texFile`, if one does.
export function latexStagePdf(
  stages: Record<string, unknown>,
  texFile: string,
): string | undefined {
  for (const raw of Object.values(stages)) {
    const stage = raw as LatexStageFields;
    if (stage?.kind !== "latex" || typeof stage.target_path !== "string") {
      continue;
    }
    const target = path.posix.join(stage.wdir ?? "", stage.target_path);
    if (target === texFile) {
      return target.replace(/\.tex$/, ".pdf");
    }
  }
  return undefined;
}

// The document a latex stage builds `pdfFile` from, if one does.
export function latexStageSource(
  stages: Record<string, unknown>,
  pdfFile: string,
): string | undefined {
  for (const raw of Object.values(stages)) {
    const stage = raw as LatexStageFields;
    if (stage?.kind !== "latex" || typeof stage.target_path !== "string") {
      continue;
    }
    const target = path.posix.join(stage.wdir ?? "", stage.target_path);
    if (target.replace(/\.tex$/, ".pdf") === pdfFile) {
      return target;
    }
  }
  return undefined;
}
