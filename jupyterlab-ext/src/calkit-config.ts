import { requestAPI } from "./request";

/**
 * Interface for environment information from calkit.yaml
 */
export interface CalkitEnvironment {
  kind:
    | "conda"
    | "docker"
    | "poetry"
    | "npm"
    | "yarn"
    | "ssh"
    | "uv"
    | "pixi"
    | "venv"
    | "uv-venv"
    | "renv";
  path?: string;
  description?: string;
  stage?: string;
  default?: boolean;
}

/**
 * Interface for pipeline stage information
 */
export interface PipelineStage {
  description?: string;
  environment?: string;
  steps?: Array<{
    cmd?: string;
  }>;
}

/**
 * Interface for calkit.yaml project info
 */
export interface CalkitProjectInfo {
  title?: string;
  environments?: Record<string, CalkitEnvironment>;
  pipeline?: {
    stages?: Record<string, PipelineStage>;
  };
}

/**
 * Fetch the project's calkit.yaml configuration
 */
export async function getCalkitConfig(): Promise<CalkitProjectInfo | null> {
  try {
    const config = await requestAPI<CalkitProjectInfo>("config");
    return config;
  } catch (error) {
    console.warn("Failed to fetch calkit config:", error);
    return null;
  }
}

/**
 * Extract kernel names from the project's environments and pipeline
 * Maps environment types to jupyter kernel names
 */
export function extractKernelsFromConfig(config: CalkitProjectInfo): string[] {
  const kernels = new Set<string>();

  if (!config.environments) {
    return Array.from(kernels);
  }

  // Map environment kinds to common Jupyter kernel names
  const kindToKernels: Record<string, string[]> = {
    conda: [
      "python3",
      "python",
      "python3.9",
      "python3.10",
      "python3.11",
      "python3.12",
    ],
    "uv-venv": ["python3", "python"],
    venv: ["python3", "python"],
    uv: ["python3", "python"],
    pixi: ["python3", "python"],
    renv: ["ir"],
    docker: ["python3", "python"],
    poetry: ["python3", "python"],
  };

  // Extract kernels from each environment
  for (const [, env] of Object.entries(config.environments)) {
    const possibleKernels = kindToKernels[env.kind] || [];
    for (const kernel of possibleKernels) {
      kernels.add(kernel);
    }
  }

  return Array.from(kernels);
}

/**
 * Get all available kernel names from the project
 */
export async function getProjectKernels(): Promise<string[]> {
  const config = await getCalkitConfig();
  if (!config) {
    return [];
  }
  return extractKernelsFromConfig(config);
}

/**
 * Get filtered kernel specs from the Python server
 * This will return only the kernels that are available in the current project
 *
 * TODO: Implement server endpoint to return filtered kernel specs
 */
export async function getFilteredKernelSpecs(): Promise<string[]> {
  try {
    // Placeholder: Will request filtered kernel specs from Python server
    // const kernels = await requestAPI<string[]>('kernelspecs');
    // return kernels;

    console.log("getFilteredKernelSpecs: Server endpoint not yet implemented");
    return [];
  } catch (error) {
    console.warn("Failed to fetch filtered kernel specs:", error);
    return [];
  }
}
