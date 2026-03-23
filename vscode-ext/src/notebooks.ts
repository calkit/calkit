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
