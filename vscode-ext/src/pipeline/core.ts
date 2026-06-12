import type { DvcStage } from "../types";

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
    const next: Record<string, unknown>[] = [];
    for (const combo of combos) {
      for (const value of values ?? []) {
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
