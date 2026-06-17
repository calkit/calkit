import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyStaleStage,
  dvcStageOutputPaths,
  expandDvcMatrix,
} from "../pipeline/core";

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
  // A malformed (non-array) matrix value is skipped rather than throwing or
  // iterating a scalar's characters.
  assert.deepEqual(
    expandDvcMatrix({ bad: 5 as unknown as unknown[], problem: ["a"] }),
    [{ problem: "a" }],
  );
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

test("classifyStaleStage attributes a script edit to the script row", () => {
  // Mirrors the adani plot-met-tower-wind-rose stage: editing its script makes
  // the script the modified dep and its outputs stale.
  const cls = classifyStaleStage(
    {
      modified_inputs: ["scripts/plot-met-tower-wind-rose.py"],
      modified_outputs: [],
      stale_outputs: [
        "figures/met-tower-wind-rose.png",
        "results/met-tower-wind-rose-stats.json",
      ],
      modified_command: false,
    },
    {
      scriptPath: "scripts/plot-met-tower-wind-rose.py",
      configuredInputs: ["data/met-tower/mast.xlsx"],
      envFilePaths: ["pyproject.toml", "uv.lock"],
    },
  );
  assert.equal(cls.scriptStale, true);
  assert.equal(cls.envStale, false);
  assert.equal(cls.commandModified, false);
  assert.equal(cls.staleOutputs.has("figures/met-tower-wind-rose.png"), true);
  // The declared input wasn't touched, and nothing falls through to "extra".
  assert.deepEqual(cls.extraModifiedInputs, []);
});

test("classifyStaleStage flags the environment when a lock file changed", () => {
  const cls = classifyStaleStage(
    { modified_inputs: ["uv.lock"], modified_command: false },
    {
      scriptPath: "scripts/run.py",
      envFilePaths: ["pyproject.toml", "uv.lock"],
    },
  );
  assert.equal(cls.envStale, true);
  assert.equal(cls.scriptStale, false);
  // The lock file is attributed to the environment, not surfaced as an input.
  assert.deepEqual(cls.extraModifiedInputs, []);
});

test("classifyStaleStage maps a notebook edit via its cleaned copy", () => {
  // calkit tracks the cleaned copy under .calkit/ as the DVC dep.
  const cls = classifyStaleStage(
    {
      modified_inputs: [".calkit/notebooks/cleaned/notebooks/explore.ipynb"],
    },
    { notebookPath: "notebooks/explore.ipynb" },
  );
  assert.equal(cls.notebookStale, true);
  // The internal cleaned path isn't surfaced as a stray "extra" input.
  assert.deepEqual(cls.extraModifiedInputs, []);
});

test("classifyStaleStage surfaces modified declared inputs and extra deps", () => {
  const cls = classifyStaleStage(
    {
      modified_inputs: [
        "data/in.csv", // a declared input
        "assessment/utils.py", // an auto-added module dep, not declared
      ],
      modified_outputs: ["data/out.parquet"],
      stale_outputs: ["data/out.parquet"],
    },
    {
      scriptPath: "scripts/process.py",
      configuredInputs: ["data/in.csv", "data/other.csv"],
      envFilePaths: ["pyproject.toml", "uv.lock"],
    },
  );
  assert.equal(cls.modifiedInputs.has("data/in.csv"), true);
  assert.equal(cls.modifiedInputs.has("data/other.csv"), false);
  assert.deepEqual(cls.extraModifiedInputs, ["assessment/utils.py"]);
  assert.equal(cls.modifiedOutputs.has("data/out.parquet"), true);
});

test("classifyStaleStage reports a changed command", () => {
  const cls = classifyStaleStage(
    { modified_command: true, modified_inputs: [] },
    { scriptPath: "scripts/run.py" },
  );
  assert.equal(cls.commandModified, true);
  assert.equal(cls.scriptStale, false);
});
