import * as path from "node:path";
import {
  findCalkitEnvKernelSourceCandidate,
  type CalkitEnvNotebookKernelSource,
} from "./environments";
import type { CalkitInfo, PipelineStage } from "./types";

export type { CalkitInfo, PipelineStage } from "./types";
export type { NotebookEntry } from "./types";

function normalizeNotebookPath(notebookPath: string): string {
  return notebookPath.replace(/\\/g, "/");
}

// Repo-relative path of a notebook's executed HTML, mirroring
// calkit.notebooks.get_executed_notebook_path (the no-parameters case). A
// subproject's goes under its own .calkit, since it runs from there.
export function getExecutedNotebookHtmlPath(
  notebookRelPath: string,
  projectDir = ".",
): string {
  if (projectDir !== ".") {
    return path.join(
      projectDir,
      getExecutedNotebookHtmlPath(
        path.posix.relative(projectDir, normalizeNotebookPath(notebookRelPath)),
      ),
    );
  }
  const dir = path.dirname(notebookRelPath);
  const htmlName =
    path.basename(notebookRelPath).replace(/\.ipynb$/, "") + ".html";
  // path.dirname returns "." for a bare filename; drop it so the result is
  // ".calkit/notebooks/html/<name>.html", not ".../html/./<name>.html".
  const rel = dir === "." ? htmlName : path.join(dir, htmlName);
  return path.join(".calkit", "notebooks", "html", rel);
}

// Environment of the pipeline stage that runs this notebook, i.e., a
// notebook stage, or a quarto stage rendering it, by its path relative to the
// stage's wdir. Any stage referencing the notebook counts, since the path is
// what ties the stage to it.
function getNotebookEnvironmentFromPipelineStages(
  stages: Record<string, PipelineStage>,
  normalizedPath: string,
): string | undefined {
  for (const stage of Object.values(stages)) {
    const stagePath =
      stage.notebook_path ??
      stage.script_path ??
      stage.path ??
      (stage.kind === "quarto" ? stage.target_path : undefined);
    if (typeof stagePath !== "string" || !stage.environment) {
      continue;
    }
    const wdir = typeof stage.wdir === "string" ? stage.wdir : "";
    const projectPath = path.posix.normalize(
      path.posix.join(
        normalizeNotebookPath(wdir),
        normalizeNotebookPath(stagePath),
      ),
    );
    if (projectPath === normalizedPath) {
      return stage.environment;
    }
  }
  return undefined;
}

export function resolveNotebookEnvironmentName(
  info: CalkitInfo,
  notebookRelativePath: string,
): string | undefined {
  const normalizedPath = normalizeNotebookPath(notebookRelativePath);
  const stages = info.pipeline?.stages ?? {};

  // 1. From the notebooks section: an explicit environment, or the environment
  //    of the pipeline stage the entry references by name.
  for (const notebook of info.notebooks ?? []) {
    if (normalizeNotebookPath(notebook.path) !== normalizedPath) {
      continue;
    }
    if (notebook.environment) {
      return notebook.environment;
    }
    if (notebook.stage && stages[notebook.stage]?.environment) {
      return stages[notebook.stage].environment;
    }
  }

  // 2. From the pipeline stage that runs this notebook.
  return getNotebookEnvironmentFromPipelineStages(stages, normalizedPath);
}

export function getConfiguredCandidateForNotebookPath(
  info: CalkitInfo,
  notebookRelativePath: string,
): CalkitEnvNotebookKernelSource | undefined {
  const environmentName = resolveNotebookEnvironmentName(
    info,
    notebookRelativePath,
  );
  if (!environmentName) {
    return undefined;
  }

  return findCalkitEnvKernelSourceCandidate(
    info.environments ?? {},
    environmentName,
  );
}
