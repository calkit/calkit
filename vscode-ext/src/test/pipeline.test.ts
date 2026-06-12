import assert from "node:assert/strict";
import test from "node:test";
import { dvcStageOutputPaths, expandDvcMatrix } from "../pipeline/core";

test("expandDvcMatrix produces the cartesian product, flattening nested values", () => {
  // Single arg (the common iterate_over case): one map per value.
  assert.deepEqual(expandDvcMatrix({ problem: ["zdt1", "zdt2"] }), [
    { problem: "zdt1" },
    { problem: "zdt2" },
  ]);
  // Multiple args: every combination, values stringified.
  assert.deepEqual(expandDvcMatrix({ problem: ["a"], seed: [1, 2] }), [
    { problem: "a", seed: "1" },
    { problem: "a", seed: "2" },
  ]);
  // Nested-dict values flatten to dotted keys.
  assert.deepEqual(expandDvcMatrix({ _arg0: [{ a: 1, b: 2 }] }), [
    { "_arg0.a": "1", "_arg0.b": "2" },
  ]);
  // An empty matrix yields a single empty combination.
  assert.deepEqual(expandDvcMatrix({}), [{}]);
});

test("dvcStageOutputPaths expands matrix-templated outs into concrete files", () => {
  // Plain stage: outs returned as written, including object-form outs.
  assert.deepEqual(
    dvcStageOutputPaths({
      outs: ["results/summary.json", { "data/out.csv": { cache: false } }],
    }),
    ["results/summary.json", "data/out.csv"],
  );
  // iterate_over stage (mirrors xfo's benchmark): the ${item.*} template is
  // expanded once per matrix value.
  assert.deepEqual(
    dvcStageOutputPaths({
      outs: ["docs/paper/results/runs/${item.problem}.json"],
      matrix: { problem: ["zdt1", "zdt2", "vawt"] },
    }),
    [
      "docs/paper/results/runs/zdt1.json",
      "docs/paper/results/runs/zdt2.json",
      "docs/paper/results/runs/vawt.json",
    ],
  );
  // A non-templated out in a matrix stage is left untouched (no duplication).
  assert.deepEqual(
    dvcStageOutputPaths({
      outs: ["static/legend.json", "runs/${item.problem}.json"],
      matrix: { problem: ["a", "b"] },
    }),
    ["static/legend.json", "runs/a.json", "runs/b.json"],
  );
  // No outs: empty list.
  assert.deepEqual(dvcStageOutputPaths({}), []);
});
