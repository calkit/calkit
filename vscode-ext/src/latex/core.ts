/**
 * Where a project's LaTeX documents, their PDFs, and their diffs are, from
 * its pipeline. No vscode imports, so it can be tested with `node --test`.
 */
import * as path from "node:path";

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
      subproject_wdir?: string;
      target_path?: string;
      diffs?: (string | string[])[];
    };
    if (stage?.kind !== "latex" || !stage.target_path) {
      continue;
    }
    // Diffs are built under the directory the stage runs in, which for a
    // subproject's is its own, though its target is relative to the root
    const wdir = stage.subproject_wdir ?? stage.wdir ?? "";
    const target =
      stage.subproject_wdir === undefined
        ? stage.target_path
        : path.posix.relative(stage.subproject_wdir, stage.target_path);
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

interface DocumentStageFields {
  kind?: string;
  wdir?: string;
  target_path?: string;
  pdf?: { output_path?: string } | null;
}

// Each document a stage builds into a PDF, i.e., a latex stage's or a
// markdown stage's with `pdf` set
function stageDocuments(
  stages: Record<string, unknown>,
): { kind: string; source: string; pdf: string }[] {
  const out = [];
  for (const raw of Object.values(stages)) {
    const stage = raw as DocumentStageFields;
    if (typeof stage?.target_path !== "string") {
      continue;
    }
    if (stage.kind === "latex") {
      const source = path.posix.join(stage.wdir ?? "", stage.target_path);
      out.push({
        kind: stage.kind,
        source,
        pdf: source.replace(/\.tex$/, ".pdf"),
      });
    } else if (stage.kind === "markdown" && stage.pdf) {
      const source = path.posix.normalize(stage.target_path);
      out.push({
        kind: stage.kind,
        source,
        pdf: path.posix.normalize(
          stage.pdf.output_path ?? source.replace(/\.(md|markdown)$/i, ".pdf"),
        ),
      });
    }
  }
  return out;
}

// The PDF a latex stage builds from `texFile`, if one does.
export function latexStagePdf(
  stages: Record<string, unknown>,
  texFile: string,
): string | undefined {
  return stageDocuments(stages).find(
    (d) => d.kind === "latex" && d.source === texFile,
  )?.pdf;
}

// The document a latex stage builds `pdfFile` from, if one does.
export function latexStageSource(
  stages: Record<string, unknown>,
  pdfFile: string,
): string | undefined {
  return stageDocuments(stages).find(
    (d) => d.kind === "latex" && d.pdf === pdfFile,
  )?.source;
}

// The latex stage that builds `texFile`, if one does, and the directory its
// build runs in, which for a subproject's is its own, though its target is
// relative to the root.
export function findLatexStage(
  stages: Record<string, unknown>,
  texFile: string,
): { name: string; wdir: string } | undefined {
  for (const [name, raw] of Object.entries(stages)) {
    const stage = raw as DocumentStageFields & { subproject_wdir?: string };
    if (
      stage?.kind === "latex" &&
      typeof stage.target_path === "string" &&
      path.posix.join(stage.wdir ?? "", stage.target_path) === texFile
    ) {
      return { name, wdir: stage.subproject_wdir ?? stage.wdir ?? "" };
    }
  }
  return undefined;
}

// How to preview a latex stage's document without running the pipeline:
// the build the pipeline compiled for it (its dvc.yaml `cmd`), run from
// `dir`, its working directory, and checking the environment first, since
// no `calkit run` did. Undefined if the stage isn't compiled to one.
export function latexPreviewCommand(
  cmd: unknown,
  dir: string,
): string | undefined {
  const prefix = "calkit latex build ";
  if (typeof cmd !== "string" || !cmd.startsWith(prefix)) {
    return undefined;
  }
  const quoted = `'${dir.replace(/'/g, `'\\''`)}'`;
  const args = cmd.slice(prefix.length).replace(/(^| )--no-check(?= )/, "");
  return `calkit -C ${quoted} latex build ${args.trim()}`;
}

// Whether LaTeX Workshop builds each document as its stage does, as
// `calkit update vscode-config` sets it up to for a project with a TeX Live
// environment, given its `latex.tools` setting.
export function latexWorkshopBuildsWithCalkit(tools: unknown): boolean {
  return (
    Array.isArray(tools) &&
    tools.some((raw) => {
      const tool = raw as { command?: unknown; args?: unknown };
      return (
        tool?.command === "calkit" &&
        Array.isArray(tool.args) &&
        tool.args.includes("--as-stage")
      );
    })
  );
}

// The PDF any stage builds from a document, LaTeX or Markdown.
export function documentStagePdf(
  stages: Record<string, unknown>,
  file: string,
): string | undefined {
  return stageDocuments(stages).find((d) => d.source === file)?.pdf;
}

// The document, LaTeX or Markdown, any stage builds `pdfFile` from.
export function documentStageSource(
  stages: Record<string, unknown>,
  pdfFile: string,
): string | undefined {
  return stageDocuments(stages).find((d) => d.pdf === pdfFile)?.source;
}

// The review file the publication at `pdfFile` lists first, if any, where
// comments on a PDF with no source go, as `calkit new comment` keeps them.
export function reviewPath(
  publications: unknown[],
  pdfFile: string,
): string | undefined {
  const want = path.posix.normalize(pdfFile);
  for (const pub of publications) {
    const p = pub as { path?: unknown; reviews?: unknown };
    if (typeof p?.path !== "string" || path.posix.normalize(p.path) !== want) {
      continue;
    }
    for (const r of Array.isArray(p.reviews) ? p.reviews : []) {
      if (typeof r?.path === "string" && r.path) {
        return r.path;
      }
    }
  }
  return undefined;
}
