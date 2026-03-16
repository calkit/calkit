import type { CalkitEnvironment } from "./environments";

export interface PipelineStage {
  kind?: string;
  notebook_path?: string;
  script_path?: string;
  path?: string;
  environment?: string;
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
