import type { DvcStage, StaleStageDetail } from "../types";

// Pure helpers (no vscode imports) for resolving pipeline stage outputs, so they
// can be unit-tested under plain `node --test` (where the `vscode` module is
// absent). The crux is iterate_over (DVC "matrix") stages: calkit writes their
// deps/outs templated with `${item.*}` placeholders plus a `matrix` of values,
// so the literal templated path never exists on disk and the concrete
// per-iteration files would otherwise go unrecognized as pipeline outputs.

// Expand a DVC `matrix` into the list of concrete `${item.*}` substitution maps,
// one per cartesian-product combination. Mirrors calkit's `_expand_matrix` in
// calkit/pipeline.py, including flattening nested-dict values (produced by
// list-of-lists iterations) into dotted "parent.child" keys.
export function expandDvcMatrix(
  matrix: Record<string, unknown[]>,
): Record<string, string>[] {
  let combos: Record<string, unknown>[] = [{}];
  for (const [key, values] of Object.entries(matrix)) {
    // calkit always writes matrix values as arrays, but a hand-edited dvc.yaml
    // could hold a scalar (which would iterate characters) or a non-iterable
    // (which would throw); skip anything that isn't an array so a malformed
    // file can't break the sidebar render.
    if (!Array.isArray(values)) {
      continue;
    }
    const next: Record<string, unknown>[] = [];
    for (const combo of combos) {
      for (const value of values) {
        next.push({ ...combo, [key]: value });
      }
    }
    combos = next;
  }
  return combos.map((combo) => {
    const flat: Record<string, string> = {};
    for (const [key, value] of Object.entries(combo)) {
      // A nested-dict value substitutes `${item.key.subkey}`; any other value
      // is a scalar substituting `${item.key}`.
      if (value !== null && typeof value === "object") {
        for (const [subKey, subVal] of Object.entries(
          value as Record<string, unknown>,
        )) {
          flat[`${key}.${subKey}`] = String(subVal);
        }
      } else {
        flat[key] = String(value);
      }
    }
    return flat;
  });
}

// Substitute one matrix combination's `${item.*}` placeholders into a template.
function applyMatrixItem(
  template: string,
  item: Record<string, string>,
): string {
  let result = template;
  for (const [variable, value] of Object.entries(item)) {
    result = result.split(`\${item.${variable}}`).join(value);
  }
  return result;
}

// The concrete output paths declared by a DVC stage. A plain stage returns its
// `outs` as written; an iterate_over (matrix) stage has its templated `outs`
// expanded into one concrete path per iteration so the real files---rather than
// a single non-existent templated path---are recognized as pipeline outputs.
export function dvcStageOutputPaths(stage: DvcStage): string[] {
  const rawPaths = (stage.outs ?? []).flatMap((out) =>
    typeof out === "string" ? [out] : Object.keys(out),
  );
  const matrix = stage.matrix as Record<string, unknown[]> | undefined;
  if (!matrix || Object.keys(matrix).length === 0) {
    return rawPaths;
  }
  const items = expandDvcMatrix(matrix);
  return rawPaths.flatMap((p) =>
    p.includes("${item.") ? items.map((item) => applyMatrixItem(p, item)) : [p],
  );
}

// The pieces of a stage's configuration needed to attribute its DVC-reported
// changes to the meaningful categories shown in the sidebar (script, notebook,
// source, environment, declared inputs). Paths are repo-relative, matching how
// `calkit status` reports modified deps/outs.
export interface StageStaleContext {
  scriptPath?: string;
  notebookPath?: string;
  targetPath?: string;
  configuredInputs?: string[];
  // The environment's spec/lock files (e.g. pyproject.toml + uv.lock). When any
  // of these is a modified dep, the stage is stale because its environment
  // changed.
  envFilePaths?: string[];
}

// How a stale stage's changes map onto the categories surfaced in the tree, so
// the sidebar can flag exactly which inputs/outputs/script/environment are out
// of date rather than just marking the whole stage stale.
export interface StaleClassification {
  modifiedInputs: Set<string>;
  modifiedOutputs: Set<string>;
  staleOutputs: Set<string>;
  scriptStale: boolean;
  notebookStale: boolean;
  sourceStale: boolean;
  envStale: boolean;
  commandModified: boolean;
  // Modified deps not attributable to any structured row above (e.g. an
  // auto-added module dependency). Internal `.calkit/` bookkeeping paths are
  // excluded since they mirror the script/notebook rows.
  extraModifiedInputs: string[];
}

// calkit tracks a notebook stage's *cleaned* copy under `.calkit/` as the DVC
// dep, so a source-notebook edit surfaces as a change to this path rather than
// the notebook's own path.
function cleanedNotebookPath(notebookPath: string): string {
  return `.calkit/notebooks/cleaned/${notebookPath}`;
}

// Attribute a stale stage's modified deps/outs to the script, notebook, source,
// environment, and declared inputs/outputs so the sidebar can show what is
// stale about it. Pure (no vscode imports) so it can be unit-tested.
export function classifyStaleStage(
  detail: StaleStageDetail,
  context: StageStaleContext,
): StaleClassification {
  const modifiedInputs = new Set(detail.modified_inputs ?? []);
  const modifiedOutputs = new Set(detail.modified_outputs ?? []);
  const staleOutputs = new Set(detail.stale_outputs ?? []);
  const scriptStale =
    !!context.scriptPath && modifiedInputs.has(context.scriptPath);
  const notebookStale =
    !!context.notebookPath &&
    (modifiedInputs.has(context.notebookPath) ||
      modifiedInputs.has(cleanedNotebookPath(context.notebookPath)));
  const sourceStale =
    !!context.targetPath && modifiedInputs.has(context.targetPath);
  const envFilePaths = context.envFilePaths ?? [];
  const envStale = envFilePaths.some((p) => modifiedInputs.has(p));
  // Deps already represented by a structured row, so they aren't repeated as
  // generic "extra" inputs.
  const covered = new Set<string>(context.configuredInputs ?? []);
  if (context.scriptPath) {
    covered.add(context.scriptPath);
  }
  if (context.notebookPath) {
    covered.add(context.notebookPath);
    covered.add(cleanedNotebookPath(context.notebookPath));
  }
  if (context.targetPath) {
    covered.add(context.targetPath);
  }
  for (const p of envFilePaths) {
    covered.add(p);
  }
  const extraModifiedInputs = [...modifiedInputs].filter(
    (p) => !covered.has(p) && !p.startsWith(".calkit/"),
  );
  return {
    modifiedInputs,
    modifiedOutputs,
    staleOutputs,
    scriptStale,
    notebookStale,
    sourceStale,
    envStale,
    commandModified: !!detail.modified_command,
    extraModifiedInputs,
  };
}
