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
  default_setup?: string[];
  [key: string]: unknown;
}

// An environment candidate for the notebook, which shows up in
// the kernel source list in the Calkit Environments section
export interface CalkitEnvNotebookKernelSource {
  label: string;
  description: string;
  detail?: string;
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

  return undefined;
}

export function makeCalkitEnvKernelSourceCandidates(
  environments: Record<string, CalkitEnvironment>,
): CalkitEnvNotebookKernelSource[] {
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

  const standalone: CalkitEnvNotebookKernelSource[] = [];
  const allNonSlurmInners: CalkitEnvNotebookKernelSource[] = [];
  const slurmOuterNames: string[] = [];

  const isNotebookCapableDocker = (env: CalkitEnvironment): boolean => {
    if (env.kind !== "docker") {
      return true;
    }
    const image = String(env.image ?? "").toLowerCase();
    return !image.includes("texlive");
  };

  for (const [name, env] of Object.entries(environments)) {
    if (env.kind === "slurm") {
      slurmOuterNames.push(name);
      continue;
    }

    if (!isNotebookCapableDocker(env)) {
      continue;
    }

    allNonSlurmInners.push({
      label: name,
      description: env.kind,
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
      environmentName: name,
      innerEnvironment: name,
      innerKind: env.kind,
    });
  }

  const nested: CalkitEnvNotebookKernelSource[] = [];
  for (const slurmOuter of slurmOuterNames) {
    for (const inner of allNonSlurmInners) {
      nested.push({
        label: `${slurmOuter}:${inner.environmentName}`,
        description: `slurm + ${inner.description}`,
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

export function findCalkitEnvKernelSourceCandidate(
  environments: Record<string, CalkitEnvironment>,
  environmentName: string,
): CalkitEnvNotebookKernelSource | undefined {
  return makeCalkitEnvKernelSourceCandidates(environments).find(
    (candidate) => candidate.environmentName === environmentName,
  );
}

// Environment kinds that can have their Jupyter kernel registered and selected
// natively in VS Code — no Jupyter server launch required.
export const kernelRegistrationKinds: ReadonlySet<EnvKind> = new Set<EnvKind>([
  "uv",
  "uv-venv",
  "venv",
  "conda",
  "pixi",
  "julia",
]);

// --- Environment spec-file parsers ---------------------------------------
// Pure helpers (no vscode imports) for reading package lists out of the spec
// files backing uv and pixi environments.

// Collect the keys (package names) of a single TOML table identified by its
// header line, e.g. "[feature.main.dependencies]". Reads until the next table
// header. Handles bare and quoted keys.
function tomlTableKeys(raw: string, header: string): string[] {
  // Match the header only at the start of a line so it isn't found inside a
  // longer header (e.g. "[dependencies]" within "[feature.x.dependencies]").
  const lines = raw.split(/\r?\n/);
  const i = lines.findIndex((l) => l.trim() === header);
  if (i === -1) {
    return [];
  }
  const keys: string[] = [];
  for (let j = i + 1; j < lines.length; j++) {
    if (/^\s*\[/.test(lines[j])) {
      break;
    }
    const match = lines[j].match(/^\s*(?:"([^"]+)"|([A-Za-z0-9._-]+))\s*=/);
    if (match) {
      keys.push(match[1] ?? match[2]);
    }
  }
  return keys;
}

// Package requirements from a pyproject.toml's [project] dependencies array.
// Walks the [project] table line-by-line so arrays in other fields (e.g.
// authors/classifiers, which contain "[") don't trip up the scan.
export function parseProjectDependencies(raw: string): string[] {
  const lines = raw.split(/\r?\n/);
  let i = 0;
  while (i < lines.length && lines[i].trim() !== "[project]") {
    i++;
  }
  for (i += 1; i < lines.length; i++) {
    // Stop at the next table header (dependencies live directly under [project]).
    if (/^\s*\[/.test(lines[i])) {
      break;
    }
    const match = lines[i].match(/^\s*dependencies\s*=\s*\[(.*)$/);
    if (!match) {
      continue;
    }
    let buf = match[1];
    while (!buf.includes("]") && i + 1 < lines.length) {
      i++;
      buf += "\n" + lines[i];
    }
    const inner = buf.slice(0, buf.lastIndexOf("]"));
    return Array.from(inner.matchAll(/"([^"]+)"|'([^']+)'/g)).map(
      (m) => m[1] ?? m[2],
    );
  }
  return [];
}

// Package specs from a requirements.txt-style file: one per line, ignoring
// blank lines, comments, and option lines (those starting with "-").
export function parseRequirementsTxt(raw: string): string[] {
  const pkgs: string[] = [];
  for (let line of raw.split(/\r?\n/)) {
    const hash = line.indexOf("#");
    if (hash !== -1) {
      line = line.slice(0, hash);
    }
    line = line.trim();
    if (line && !line.startsWith("-")) {
      pkgs.push(line);
    }
  }
  return pkgs;
}

// Packages for a uv environment. A calkit-managed uv env uses a pyproject.toml
// ([project] dependencies); a uv-venv may instead point at a requirements.txt.
export function parseUvPackages(raw: string): string[] {
  return raw.includes("[project]")
    ? parseProjectDependencies(raw)
    : parseRequirementsTxt(raw);
}

// Conda and PyPI package names for a pixi environment, read from pixi.toml.
// Packages may live in the default [dependencies]/[pypi-dependencies] tables or
// under a feature named after the environment; include both.
export function parsePixiPackages(
  raw: string,
  featureName: string,
): { conda: string[]; pip: string[] } {
  const dedupe = (items: string[]): string[] => [...new Set(items)];
  return {
    conda: dedupe([
      ...tomlTableKeys(raw, "[dependencies]"),
      ...tomlTableKeys(raw, `[feature.${featureName}.dependencies]`),
    ]),
    pip: dedupe([
      ...tomlTableKeys(raw, "[pypi-dependencies]"),
      ...tomlTableKeys(raw, `[feature.${featureName}.pypi-dependencies]`),
    ]),
  };
}
