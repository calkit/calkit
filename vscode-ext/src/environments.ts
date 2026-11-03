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
  | "system"
  | "_system"
  | string;

export interface SlurmLaunchOptions {
  gpus?: string;
  time?: string;
  partition?: string;
  cpus?: string;
  mem?: string;
  extra?: string;
}

type SlurmOptionField = Exclude<keyof SlurmLaunchOptions, "extra">;

// srun flags for the launch options we know, long form first
const SLURM_OPTION_FLAGS: Record<SlurmOptionField, string[]> = {
  gpus: ["--gpus", "-G"],
  time: ["--time", "-t"],
  partition: ["--partition", "-p"],
  cpus: ["--cpus-per-task", "-c"],
  mem: ["--mem"],
};

// Resources a notebook job asks for when its environment doesn't set them, so
// it doesn't silently get the cluster's defaults
export const NOTEBOOK_SLURM_RESOURCES: SlurmOptionField[] = [
  "partition",
  "time",
  "cpus",
  "mem",
];

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
  max_concurrent_jobs?: number;
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
    cpus: options.cpus?.trim() || undefined,
    mem: options.mem?.trim() || undefined,
    extra: options.extra?.trim() || undefined,
  };
}

// Options from base, overridden by whatever override sets
export function mergeSlurmOptions(
  base: SlurmLaunchOptions | undefined,
  override: SlurmLaunchOptions | undefined,
): SlurmLaunchOptions {
  const merged = compactSlurmOptions(base ?? {});
  for (const [key, value] of Object.entries(
    compactSlurmOptions(override ?? {}),
  )) {
    if (value) {
      merged[key as keyof SlurmLaunchOptions] = value;
    }
  }
  return merged;
}

export function getMissingSlurmResources(
  options: SlurmLaunchOptions | undefined,
): SlurmOptionField[] {
  const compact = compactSlurmOptions(options ?? {});
  return NOTEBOOK_SLURM_RESOURCES.filter((key) => {
    if (key === "mem" && /--mem-per-(cpu|gpu)\b/.test(compact.extra ?? "")) {
      return false;
    }
    return !compact[key];
  });
}

export function slurmOptionsToOptionList(
  options: SlurmLaunchOptions,
): string[] {
  const compact = compactSlurmOptions(options);
  const result: string[] = [];
  for (const [key, flags] of Object.entries(SLURM_OPTION_FLAGS)) {
    const value = compact[key as SlurmOptionField];
    if (value) {
      result.push(`${flags[0]}=${value}`);
    }
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
  // One entry can hold several flags, e.g., "--cpus-per-task=8 --mem=32G"
  const tokens = options.flatMap((opt) => opt.trim().split(/\s+/));
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (!token) {
      continue;
    }
    const eq = token.indexOf("=");
    const flag = eq < 0 ? token : token.slice(0, eq);
    const key = (Object.keys(SLURM_OPTION_FLAGS) as SlurmOptionField[]).find(
      (k) => SLURM_OPTION_FLAGS[k].includes(flag),
    );
    if (!key) {
      extraParts.push(token);
      continue;
    }
    const value = eq < 0 ? tokens[++i] : token.slice(eq + 1);
    if (value) {
      result[key] = value;
    }
  }
  if (extraParts.length > 0) {
    result.extra = extraParts.join(" ");
  }
  const compact = compactSlurmOptions(result);
  if (Object.values(compact).every((value) => !value)) {
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

// Printed by the SLURM launch command, since Jupyter bound to 0.0.0.0 doesn't
// report which compute node it's on.
export const SLURM_NODE_MARKER = "CALKIT_SLURM_NODE=";

// Compute node and port of a Jupyter server started in a SLURM job, from its
// output so far. The port can differ from the requested one if it was taken.
// The node only counts once its line ends, since output arrives in chunks.
export function parseSlurmServerOutput(output: string): {
  host?: string;
  port?: number;
} {
  const host = output.match(
    new RegExp(`${SLURM_NODE_MARKER}(\\S+)\\r?\\n`),
  )?.[1];
  const port = output.match(/https?:\/\/[^\s/:]+:(\d+)\/lab\b/)?.[1];
  return { host, port: port ? Number(port) : undefined };
}

// Host a Remote-SSH window connected to, from its workspace URI authority,
// e.g., "ssh-remote+login.hpc.caltech.edu". Remote-SSH hex-encodes the host as
// JSON when it carries more than a name.
export function parseRemoteSshHost(authority: string): string | undefined {
  const prefix = "ssh-remote+";
  if (!authority.startsWith(prefix)) {
    return undefined;
  }
  let host = authority.slice(prefix.length);
  if (/^([0-9a-f]{2})+$/i.test(host)) {
    try {
      const decoded = JSON.parse(Buffer.from(host, "hex").toString("utf8"));
      if (typeof decoded?.hostName === "string") {
        host = decoded.hostName;
      }
    } catch {
      // A plain host name that happens to look like hex
    }
  }
  host = host.replace(/^[^@]*@/, "").replace(/:\d+$/, "");
  return host || undefined;
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
