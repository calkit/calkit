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
// calkit.notebooks.get_executed_notebook_path (the no-parameters case).
export function getExecutedNotebookHtmlPath(notebookRelPath: string): string {
  const dir = path.dirname(notebookRelPath);
  const htmlName =
    path.basename(notebookRelPath).replace(/\.ipynb$/, "") + ".html";
  // path.dirname returns "." for a bare filename; drop it so the result is
  // ".calkit/notebooks/html/<name>.html", not ".../html/./<name>.html".
  const rel = dir === "." ? htmlName : path.join(dir, htmlName);
  return path.join(".calkit", "notebooks", "html", rel);
}

function getNotebookEnvironmentFromPipelineStages(
  stages: Record<string, PipelineStage> | undefined,
  normalizedPath: string,
): string | undefined {
  if (!stages) {
    return undefined;
  }
  for (const stage of Object.values(stages)) {
    if (stage.kind !== "jupyter-notebook") {
      continue;
    }
    const stagePath = stage.notebook_path ?? stage.script_path ?? stage.path;
    if (
      typeof stagePath === "string" &&
      normalizeNotebookPath(stagePath) === normalizedPath &&
      stage.environment
    ) {
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

  const pipelineEnvironment = getNotebookEnvironmentFromPipelineStages(
    info.pipeline?.stages,
    normalizedPath,
  );
  if (pipelineEnvironment) {
    return pipelineEnvironment;
  }

  for (const notebook of info.notebooks ?? []) {
    if (normalizeNotebookPath(notebook.path) !== normalizedPath) {
      continue;
    }
    if (notebook.environment) {
      return notebook.environment;
    }
  }

  return undefined;
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
