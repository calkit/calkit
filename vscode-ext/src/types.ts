import type { CalkitEnvironment } from "./environments";

export interface PipelineStage {
  kind?: string;
  notebook_path?: string;
  script_path?: string;
  path?: string;
  environment?: string;
  inputs?: string[];
  outputs?: string[];
  slurm?: {
    setup?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface NotebookEntry {
  path: string;
  environment?: string;
  stage?: string;
}

export interface CalkitInfo {
  name?: string;
  environments?: Record<string, CalkitEnvironment>;
  notebooks?: NotebookEntry[];
  pipeline?: {
    stages?: Record<string, PipelineStage>;
  };
}

export interface DvcStage {
  cmd?: string;
  deps?: (string | Record<string, unknown>)[];
  outs?: (string | Record<string, unknown>)[];
  params?: unknown[];
  desc?: string;
  [key: string]: unknown;
}

export interface DvcYaml {
  stages?: Record<string, DvcStage>;
}
