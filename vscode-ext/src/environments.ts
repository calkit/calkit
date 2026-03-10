export type EnvKind =
  | "conda"
  | "docker"
  | "julia"
  | "matlab"
  | "pixi"
  | "renv"
  | "slurm"
  | "uv"
  | "uv-venv"
  | "venv"
  | "ssh"
  | "_system"
  | string;

export interface SlurmLaunchOptions {
  gpus?: string;
  time?: string;
  partition?: string;
  extra?: string;
}

export interface CalkitEnvironment {
  kind: EnvKind;
  host?: string;
  path?: string;
  julia?: string;
  image?: string;
  platform?: string;
  env_vars?: Record<string, string>;
  gpus?: string;
  ports?: string[];
  user?: string;
  wdir?: string;
  args?: string[];
  default_options?: string[];
  default_slurm_options?: SlurmLaunchOptions;
  [key: string]: unknown;
}

export interface CalkitCandidate {
  label: string;
  description: string;
  detail: string;
  environmentName: string;
  innerEnvironment: string;
  innerKind: EnvKind;
  outerSlurmEnvironment?: string;
  outerKind?: EnvKind;
}

export function compactSlurmOptions(
  options: SlurmLaunchOptions,
): SlurmLaunchOptions {
  return {
    gpus: options.gpus?.trim() || undefined,
    time: options.time?.trim() || undefined,
    partition: options.partition?.trim() || undefined,
    extra: options.extra?.trim() || undefined,
  };
}

export function slurmOptionsToOptionList(
  options: SlurmLaunchOptions,
): string[] {
  const compact = compactSlurmOptions(options);
  const result: string[] = [];
  if (compact.gpus) {
    result.push(`--gpus=${compact.gpus}`);
  }
  if (compact.time) {
    result.push(`--time=${compact.time}`);
  }
  if (compact.partition) {
    result.push(`--partition=${compact.partition}`);
  }
  if (compact.extra) {
    result.push(compact.extra);
  }
  return result;
}

export function parseSlurmOptionList(
  options: string[],
): SlurmLaunchOptions | undefined {
  const result: SlurmLaunchOptions = {};
  const extraParts: string[] = [];

  for (const raw of options) {
    const opt = raw.trim();
    if (!opt) {
      continue;
    }
    const gpusMatch = opt.match(/^--gpus(?:=|\s+)(.+)$/);
    if (gpusMatch) {
      result.gpus = gpusMatch[1].trim();
      continue;
    }
    const timeMatch = opt.match(/^--time(?:=|\s+)(.+)$/);
    if (timeMatch) {
      result.time = timeMatch[1].trim();
      continue;
    }
    const partitionMatch = opt.match(/^--partition(?:=|\s+)(.+)$/);
    if (partitionMatch) {
      result.partition = partitionMatch[1].trim();
      continue;
    }
    extraParts.push(opt);
  }

  if (extraParts.length > 0) {
    result.extra = extraParts.join(" ");
  }

  const compact = compactSlurmOptions(result);
  if (!compact.gpus && !compact.time && !compact.partition && !compact.extra) {
    return undefined;
  }
  return compact;
}

export function getDefaultSlurmOptions(
  env: CalkitEnvironment | undefined,
): SlurmLaunchOptions | undefined {
  if (!env) {
    return undefined;
  }

  if (Array.isArray(env.default_options)) {
    const parsed = parseSlurmOptionList(env.default_options);
    if (parsed) {
      return parsed;
    }
  }

  // Backward compatibility for early extension versions.
  const fromLegacy = env.default_slurm_options;
  if (fromLegacy) {
    return compactSlurmOptions(fromLegacy);
  }

  return undefined;
}

export function makeEnvironmentCandidates(
  environments: Record<string, CalkitEnvironment>,
): CalkitCandidate[] {
  const notebookKinds = new Set<EnvKind>([
    "conda",
    "docker",
    "julia",
    "matlab",
    "pixi",
    "renv",
    "uv",
    "uv-venv",
    "venv",
  ]);

  const standalone: CalkitCandidate[] = [];
  const allNonSlurmInners: CalkitCandidate[] = [];
  const slurmOuterNames: string[] = [];

  for (const [name, env] of Object.entries(environments)) {
    if (env.kind === "slurm") {
      slurmOuterNames.push(name);
      continue;
    }

    allNonSlurmInners.push({
      label: name,
      description: env.kind,
      detail: "Run in this environment under a slurm outer environment",
      environmentName: name,
      innerEnvironment: name,
      innerKind: env.kind,
    });

    if (!notebookKinds.has(env.kind)) {
      continue;
    }

    standalone.push({
      label: name,
      description: env.kind,
      detail: "Run Jupyter server in this environment",
      environmentName: name,
      innerEnvironment: name,
      innerKind: env.kind,
    });
  }

  const nested: CalkitCandidate[] = [];
  for (const slurmOuter of slurmOuterNames) {
    for (const inner of allNonSlurmInners) {
      nested.push({
        label: `${slurmOuter}:${inner.environmentName}`,
        description: `slurm + ${inner.description}`,
        detail: "Run server with srun, then enter inner environment",
        environmentName: `${slurmOuter}:${inner.environmentName}`,
        innerEnvironment: inner.environmentName,
        innerKind: inner.innerKind,
        outerSlurmEnvironment: slurmOuter,
        outerKind: "slurm",
      });
    }
  }

  return [...standalone, ...nested];
}
