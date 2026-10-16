import * as path from "node:path";
import type {
  ArtifactEntry,
  CalkitInfo,
  DvcStage,
  DvcYaml,
  EnvDescription,
  PipelineStage,
  QuestionEntry,
} from "./types";

// Folding subprojects into one view of the project, the way `calkit run` and
// `calkit status` treat them from the parent. Kept free of vscode imports so
// it can be unit-tested under plain `node --test`.

export interface Subproject {
  // Relative to the workspace root, with forward slashes
  dir: string;
  config: CalkitInfo;
  dvcYaml?: DvcYaml;
}

// Where each merged question came from, so removing one can go to the
// calkit.yaml that declares it, by its index there.
export interface QuestionOrigin {
  dir: string;
  index: number;
}

/**
 * Read a project's subprojects, and theirs, parent first and depth first.
 *
 * Mirrors `calkit.iter_projects`: entries without a path, or pointing at a
 * directory without a calkit.yaml (`readConfig` returns undefined), are
 * skipped, and a subproject naming its parent or itself doesn't recurse.
 */
export async function collectSubprojects(
  config: CalkitInfo,
  readConfig: (dir: string) => Promise<CalkitInfo | undefined>,
  // Where a directory really is, so one reached again through a symlink
  // counts as seen
  realDir: (dir: string) => Promise<string> = async (dir) => dir,
  base = ".",
  seen?: Set<string>,
): Promise<{ dir: string; config: CalkitInfo }[]> {
  seen ??= new Set([await realDir(".")]);
  const found: { dir: string; config: CalkitInfo }[] = [];
  for (const entry of config.subprojects ?? []) {
    const rawPath =
      entry && typeof entry === "object" && typeof entry.path === "string"
        ? entry.path
        : undefined;
    if (!rawPath) {
      continue;
    }
    const dir = path.posix
      .normalize(path.posix.join(base, rawPath.replace(/\\/g, "/")))
      .replace(/\/+$/, "");
    const real = await realDir(dir);
    if (seen.has(real)) {
      continue;
    }
    const subConfig = await readConfig(dir);
    if (subConfig === undefined) {
      continue;
    }
    seen.add(real);
    found.push({ dir, config: subConfig });
    found.push(
      ...(await collectSubprojects(subConfig, readConfig, realDir, dir, seen)),
    );
  }
  return found;
}

/** Name something in a subproject the way `calkit status` names its stages. */
export function qualifyName(dir: string, name: string): string {
  return dir === "." ? name : `${dir}:${name}`;
}

function rebasePath(dir: string, p: string): string {
  return path.posix.isAbsolute(p) ? p : path.posix.join(dir, p);
}

// An environment reference may combine an outer and inner environment as
// "outer:inner", so each part is qualified on its own.
function qualifyEnvRef(dir: string, ref: string): string {
  return ref
    .split(":")
    .map((part) => qualifyName(dir, part))
    .join(":");
}

/**
 * Split an environment reference into the environments it names.
 *
 * A reference combines environments as "outer:inner", and a subproject's
 * environment is itself named "sub:env", so a part is joined to the next
 * whenever that names a known environment.
 */
export function envRefParts(ref: string, envNames: Set<string>): string[] {
  const tokens = ref.split(":");
  const parts: string[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const joined = `${tokens[i]}:${tokens[i + 1]}`;
    if (i + 1 < tokens.length && envNames.has(joined)) {
      parts.push(joined);
      i++;
    } else {
      parts.push(tokens[i]);
    }
  }
  return parts;
}

// A stage's paths are relative to its wdir, which is relative to its
// project, so rebasing onto the wdir puts them all in the root's frame and
// the wdir can go.
function rebaseStage(dir: string, stage: PipelineStage): PipelineStage {
  const base =
    typeof stage.wdir === "string" ? path.posix.join(dir, stage.wdir) : dir;
  const rebased: PipelineStage = { ...stage, subproject_wdir: base };
  delete rebased.wdir;
  for (const [key, value] of Object.entries(stage)) {
    if (
      (key === "path" || key.endsWith("_path")) &&
      typeof value === "string"
    ) {
      rebased[key] = rebasePath(base, value);
    }
  }
  if (typeof stage.environment === "string") {
    rebased.environment = qualifyEnvRef(dir, stage.environment);
  }
  if (Array.isArray(stage.inputs)) {
    rebased.inputs = (stage.inputs as unknown[]).map((input) =>
      typeof input === "string"
        ? rebasePath(base, input)
        : input &&
          typeof input === "object" &&
          typeof (input as { path?: unknown }).path === "string"
        ? {
            ...(input as object),
            path: rebasePath(base, (input as { path: string }).path),
          }
        : input,
    ) as string[];
  }
  if (Array.isArray(stage.outputs)) {
    rebased.outputs = stage.outputs.map((output) =>
      typeof output === "string"
        ? rebasePath(base, output)
        : { ...output, path: rebasePath(base, output.path) },
    );
  }
  if (typeof stage.scheduler?.log_path === "string") {
    rebased.scheduler = {
      ...stage.scheduler,
      log_path: rebasePath(base, stage.scheduler.log_path),
    };
  }
  const pdf = stage.pdf as { output_path?: unknown } | null | undefined;
  if (typeof pdf?.output_path === "string") {
    rebased.pdf = { ...pdf, output_path: rebasePath(base, pdf.output_path) };
  }
  return rebased;
}

function rebaseArtifact<T extends ArtifactEntry>(dir: string, entry: T): T {
  const rebased = { ...entry, path: rebasePath(dir, entry.path) };
  if (typeof entry.stage === "string") {
    rebased.stage = qualifyName(dir, entry.stage);
  }
  return rebased;
}

/**
 * Fold subprojects' configs into the root's.
 *
 * Stages, environments, and apps are named "sub:name", as `calkit status`
 * reports them and `calkit run` accepts them, and every path is made
 * relative to the root, so the result reads like one project's config.
 */
export function mergeSubprojectConfigs(
  root: CalkitInfo,
  subprojects: Subproject[],
): {
  config: CalkitInfo;
  questionOrigins: QuestionOrigin[];
  // The project declaring each artifact path, which needn't be the one its
  // file is in
  artifactOrigins: Map<string, string>;
} {
  const merged: CalkitInfo = {
    ...root,
    environments: { ...(root.environments ?? {}) },
    pipeline: {
      ...(root.pipeline ?? {}),
      stages: { ...(root.pipeline?.stages ?? {}) },
    },
    apps: { ...(root.apps ?? {}) },
    notebooks: [...(root.notebooks ?? [])],
    questions: [...(root.questions ?? [])],
    figures: [...(root.figures ?? [])],
    datasets: [...(root.datasets ?? [])],
    results: [...(root.results ?? [])],
    publications: [...(root.publications ?? [])],
    presentations: [...(root.presentations ?? [])],
  };
  const questionOrigins: QuestionOrigin[] = (root.questions ?? []).map(
    (_, i) => ({ dir: ".", index: i + 1 }),
  );
  const artifactOrigins = new Map<string, string>();
  const artifactKinds = [
    "figures",
    "datasets",
    "results",
    "publications",
    "presentations",
  ] as const;
  for (const kind of artifactKinds) {
    for (const entry of root[kind] ?? []) {
      artifactOrigins.set(entry.path, ".");
    }
  }
  for (const { dir, config } of subprojects) {
    for (const [name, env] of Object.entries(config.environments ?? {})) {
      merged.environments![qualifyName(dir, name)] =
        typeof env.path === "string"
          ? { ...env, path: rebasePath(dir, env.path) }
          : env;
    }
    for (const [name, stage] of Object.entries(config.pipeline?.stages ?? {})) {
      merged.pipeline!.stages![qualifyName(dir, name)] = rebaseStage(
        dir,
        stage,
      );
    }
    for (const [name, app] of Object.entries(config.apps ?? {})) {
      merged.apps![qualifyName(dir, name)] = {
        ...app,
        ...(typeof app.path === "string"
          ? { path: rebasePath(dir, app.path) }
          : {}),
        ...(typeof app.stage === "string"
          ? { stage: qualifyName(dir, app.stage) }
          : {}),
      };
    }
    for (const notebook of config.notebooks ?? []) {
      merged.notebooks!.push({
        ...notebook,
        path: rebasePath(dir, notebook.path),
        ...(typeof notebook.environment === "string"
          ? { environment: qualifyEnvRef(dir, notebook.environment) }
          : {}),
        ...(typeof notebook.stage === "string"
          ? { stage: qualifyName(dir, notebook.stage) }
          : {}),
      });
    }
    for (const kind of artifactKinds) {
      for (const entry of config[kind] ?? []) {
        const rebased = rebaseArtifact(dir, entry);
        (merged[kind] as ArtifactEntry[]).push(rebased);
        if (!artifactOrigins.has(rebased.path)) {
          artifactOrigins.set(rebased.path, dir);
        }
      }
    }
    (config.questions ?? []).forEach((question, i) => {
      merged.questions!.push(
        typeof question === "string"
          ? question
          : ({
              ...question,
              evidence: question.evidence?.map((ev) =>
                typeof ev.path === "string"
                  ? { ...ev, path: rebasePath(dir, ev.path) }
                  : ev,
              ),
            } as QuestionEntry),
      );
      questionOrigins.push({ dir, index: i + 1 });
    });
  }
  return { config: merged, questionOrigins, artifactOrigins };
}

function rebaseDvcPaths(
  base: string,
  entries: DvcStage["deps"],
): DvcStage["deps"] {
  return entries?.map((entry) =>
    typeof entry === "string"
      ? rebasePath(base, entry)
      : Object.fromEntries(
          Object.entries(entry).map(([p, opts]) => [rebasePath(base, p), opts]),
        ),
  );
}

/** Fold subprojects' dvc.yaml stages into the root's, named as above. */
export function mergeSubprojectDvcYaml(
  root: DvcYaml,
  subprojects: Subproject[],
): DvcYaml {
  const stages: Record<string, DvcStage> = { ...(root.stages ?? {}) };
  for (const { dir, dvcYaml } of subprojects) {
    for (const [name, stage] of Object.entries(dvcYaml?.stages ?? {})) {
      const base =
        typeof stage.wdir === "string" ? path.posix.join(dir, stage.wdir) : dir;
      const rebased: DvcStage = {
        ...stage,
        deps: rebaseDvcPaths(base, stage.deps),
        outs: rebaseDvcPaths(base, stage.outs),
      };
      delete rebased.wdir;
      stages[qualifyName(dir, name)] = rebased;
    }
  }
  return { ...root, stages };
}

/** Qualify a subproject's `calkit describe envs` output the same way. */
export function qualifyEnvDescriptions(
  dir: string,
  descriptions: Record<string, EnvDescription>,
): Record<string, EnvDescription> {
  const result: Record<string, EnvDescription> = {};
  for (const [name, desc] of Object.entries(descriptions)) {
    result[qualifyName(dir, name)] = {
      ...desc,
      ...(desc.spec_path ? { spec_path: rebasePath(dir, desc.spec_path) } : {}),
      ...(desc.lock_path ? { lock_path: rebasePath(dir, desc.lock_path) } : {}),
    };
  }
  return result;
}

/**
 * The stage name `calkit status` uses for a DVC stage address.
 *
 * Running stages come back as DVC addresses ("sub/dvc.yaml:stage"), while
 * stale ones already carry the "sub:stage" name.
 */
export function stageNameFromDvcAddress(address: string): string {
  const marker = "dvc.yaml:";
  const at = address.indexOf(marker);
  if (at < 0) {
    return address;
  }
  const dir = address.slice(0, at).replace(/\/+$/, "");
  return qualifyName(dir || ".", address.slice(at + marker.length));
}

// The subproject a qualified name or a root-relative path belongs to, the
// deepest one winning, and what it's called there.
function deepestSubproject(
  dirs: string[],
  matches: (dir: string) => boolean,
): string | undefined {
  return dirs.filter(matches).sort((a, b) => b.length - a.length)[0];
}

/** The subproject and local name a qualified name refers to. */
export function splitQualifiedName(
  name: string,
  dirs: string[],
): { dir: string; name: string } {
  const dir = deepestSubproject(dirs, (d) => name.startsWith(`${d}:`));
  return dir ? { dir, name: name.slice(dir.length + 1) } : { dir: ".", name };
}

/** The subproject a root-relative path is in, and the path from there. */
export function splitSubprojectPath(
  relPath: string,
  dirs: string[],
): { dir: string; path: string } {
  const dir = deepestSubproject(dirs, (d) => relPath.startsWith(`${d}/`));
  return dir
    ? { dir, path: relPath.slice(dir.length + 1) }
    : { dir: ".", path: relPath };
}
