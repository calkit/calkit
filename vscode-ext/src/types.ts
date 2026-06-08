import type { CalkitEnvironment } from "./environments";

export interface PipelineStage {
  kind?: string;
  notebook_path?: string;
  script_path?: string;
  target_path?: string;
  path?: string;
  environment?: string;
  inputs?: string[];
  outputs?: (
    | string
    | { path: string; storage?: string; [key: string]: unknown }
  )[];
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

export interface FigureEntry {
  path: string;
  stage?: string;
  imported_from?: unknown;
  [key: string]: unknown;
}

export interface DatasetEntry {
  path: string;
  stage?: string;
  imported_from?: unknown;
  [key: string]: unknown;
}

export interface CalkitInfo {
  name?: string;
  environments?: Record<string, CalkitEnvironment>;
  notebooks?: NotebookEntry[];
  figures?: FigureEntry[];
  datasets?: DatasetEntry[];
  pipeline?: {
    stages?: Record<string, PipelineStage>;
  };
}

export interface EnvDescription {
  kind?: string;
  spec_path?: string;
  lock_path?: string;
  prefix?: string;
  python?: string;
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
