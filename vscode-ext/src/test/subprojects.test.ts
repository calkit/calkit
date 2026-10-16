import assert from "node:assert/strict";
import test from "node:test";
import {
  collectSubprojects,
  envRefParts,
  mergeSubprojectConfigs,
  mergeSubprojectDvcYaml,
  qualifyEnvDescriptions,
  splitQualifiedName,
  splitSubprojectPath,
  stageNameFromDvcAddress,
} from "../subprojects";
import type { CalkitInfo } from "../types";

test("collectSubprojects walks nested subprojects and skips bad entries", async () => {
  const configs: Record<string, CalkitInfo> = {
    analyses: {
      subprojects: [{ path: "nested/" }, { path: ".." }, { path: "." }],
    },
    "analyses/nested": { subprojects: [{ path: "../../analyses" }] },
    other: {},
  };
  const read = async (dir: string) => configs[dir];
  const found = await collectSubprojects(
    {
      subprojects: [
        { path: "analyses" },
        { path: "missing" },
        { description: "no path" },
        "not a mapping" as unknown as { path: string },
        { path: "other\\" },
        { path: "analyses" },
      ],
    },
    read,
  );
  // Parent first, depth first, each once, and a subproject naming its parent
  // or itself doesn't recurse
  assert.deepEqual(
    found.map((sp) => sp.dir),
    ["analyses", "analyses/nested", "other"],
  );
  assert.deepEqual(await collectSubprojects({}, read), []);
  // One reached again through a symlink is the same project
  configs.self = { subprojects: [{ path: "self" }] };
  const realDir = async (dir: string) => dir.replace(/^(self\/)*self$/, ".");
  assert.deepEqual(
    await collectSubprojects(
      { subprojects: [{ path: "self" }, { path: "other" }] },
      read,
      realDir,
    ),
    [{ dir: "other", config: {} }],
  );
});

test("mergeSubprojectConfigs qualifies names and rebases paths", () => {
  const { config, questionOrigins, artifactOrigins } = mergeSubprojectConfigs(
    {
      questions: ["Root question?"],
      environments: { main: { kind: "uv", path: "pyproject.toml" } },
      pipeline: { stages: { build: { kind: "python-script" } } },
      figures: [{ path: "root.png" }],
    },
    [
      {
        dir: "analyses",
        config: {
          questions: [
            "Plain?",
            {
              question: "Structured?",
              evidence: [
                { kind: "figure", path: "figures/a.png" },
                { kind: "result" },
              ],
            },
          ],
          environments: {
            main: { kind: "uv", path: "pyproject.toml" },
            cluster: { kind: "slurm" },
          },
          pipeline: {
            stages: {
              plot: {
                kind: "python-script",
                script_path: "scripts/plot.py",
                environment: "cluster:main",
                scheduler: { log_path: "logs/plot.out" },
                // Calkit also takes an input as a mapping, which the type
                // doesn't say
                inputs: [
                  "data/raw",
                  { path: "params.yaml" },
                  { other: 1 },
                ] as unknown as string[],
                outputs: ["figures/a.png", { path: "results/b.json" }],
              },
              paper: {
                kind: "latex",
                wdir: "paper",
                target_path: "paper.tex",
                environment: "main",
              },
              notes: {
                kind: "markdown",
                target_path: "notes.md",
                pdf: { output_path: "out/notes.pdf" },
              },
              // The built-in environment is the same one everywhere
              sys: { kind: "command", environment: "_system" },
              "sys-outer": {
                kind: "command",
                environment: "_system:main",
              },
            },
          },
          figures: [
            { path: "figures/a.png", stage: "plot" },
            // Declared at the root too, which is where it's edited
            { path: "../root.png" },
          ],
          results: [{ path: "/abs/results.json" }],
          notebooks: [{ path: "nb.ipynb", environment: "main", stage: "plot" }],
          apps: { dash: { path: "app.html", stage: "plot" } },
        },
      },
    ],
  );
  // The root's own entries are untouched
  assert.deepEqual(config.environments?.main, {
    kind: "uv",
    path: "pyproject.toml",
  });
  assert.deepEqual(config.environments?.["analyses:main"], {
    kind: "uv",
    path: "analyses/pyproject.toml",
  });
  assert.deepEqual(config.pipeline?.stages?.["analyses:plot"], {
    kind: "python-script",
    script_path: "analyses/scripts/plot.py",
    environment: "analyses:cluster:analyses:main",
    scheduler: { log_path: "analyses/logs/plot.out" },
    subproject_wdir: "analyses",
    inputs: [
      "analyses/data/raw",
      { path: "analyses/params.yaml" },
      { other: 1 },
    ],
    outputs: ["analyses/figures/a.png", { path: "analyses/results/b.json" }],
  });
  // A wdir is folded into the paths, and each part of a combined environment
  // is qualified
  assert.deepEqual(config.pipeline?.stages?.["analyses:paper"], {
    kind: "latex",
    target_path: "analyses/paper/paper.tex",
    environment: "analyses:main",
    subproject_wdir: "analyses/paper",
  });
  assert.deepEqual(config.pipeline?.stages?.["analyses:notes"], {
    kind: "markdown",
    target_path: "analyses/notes.md",
    pdf: { output_path: "analyses/out/notes.pdf" },
    subproject_wdir: "analyses",
  });
  assert.equal(
    config.pipeline?.stages?.["analyses:sys"]?.environment,
    "_system",
  );
  assert.equal(
    config.pipeline?.stages?.["analyses:sys-outer"]?.environment,
    "_system:analyses:main",
  );
  assert.deepEqual(config.figures, [
    { path: "root.png" },
    { path: "analyses/figures/a.png", stage: "analyses:plot" },
    { path: "root.png" },
  ]);
  assert.deepEqual(
    [...artifactOrigins],
    [
      ["root.png", "."],
      ["analyses/figures/a.png", "analyses"],
      ["/abs/results.json", "analyses"],
    ],
  );
  assert.deepEqual(config.results, [{ path: "/abs/results.json" }]);
  assert.deepEqual(config.notebooks, [
    {
      path: "analyses/nb.ipynb",
      environment: "analyses:main",
      stage: "analyses:plot",
    },
  ]);
  assert.deepEqual(config.apps?.["analyses:dash"], {
    path: "analyses/app.html",
    stage: "analyses:plot",
  });
  assert.deepEqual(config.questions?.[2], {
    question: "Structured?",
    evidence: [
      { kind: "figure", path: "analyses/figures/a.png" },
      { kind: "result" },
    ],
  });
  assert.deepEqual(questionOrigins, [
    { dir: ".", index: 1 },
    { dir: "analyses", index: 1 },
    { dir: "analyses", index: 2 },
  ]);
  // Nothing to merge leaves the root's config as it was
  assert.deepEqual(
    mergeSubprojectConfigs({ name: "x" }, []).config.pipeline?.stages,
    {},
  );
});

test("mergeSubprojectDvcYaml qualifies stages and rebases deps and outs", () => {
  const merged = mergeSubprojectDvcYaml({ stages: { root: { cmd: "a" } } }, [
    {
      dir: "analyses",
      config: {},
      dvcYaml: {
        stages: {
          plot: {
            cmd: "python plot.py",
            deps: ["plot.py"],
            outs: ["figures/a.png", { "results/b.json": { cache: false } }],
          },
          sub: { wdir: "paper", outs: ["paper.pdf"] },
        },
      },
    },
    { dir: "empty", config: {} },
  ]);
  assert.deepEqual(merged.stages, {
    root: { cmd: "a" },
    "analyses:plot": {
      cmd: "python plot.py",
      deps: ["analyses/plot.py"],
      outs: [
        "analyses/figures/a.png",
        { "analyses/results/b.json": { cache: false } },
      ],
    },
    "analyses:sub": { deps: undefined, outs: ["analyses/paper/paper.pdf"] },
  });
});

test("subproject names and paths split back to where they're declared", () => {
  const dirs = ["analyses", "analyses/nested", "other"];
  assert.deepEqual(splitQualifiedName("analyses:plot", dirs), {
    dir: "analyses",
    name: "plot",
  });
  assert.deepEqual(splitQualifiedName("analyses/nested:env", dirs), {
    dir: "analyses/nested",
    name: "env",
  });
  // A root combined environment isn't a subproject's
  assert.deepEqual(splitQualifiedName("slurm:main", dirs), {
    dir: ".",
    name: "slurm:main",
  });
  assert.deepEqual(splitSubprojectPath("analyses/nested/a.png", dirs), {
    dir: "analyses/nested",
    path: "a.png",
  });
  assert.deepEqual(splitSubprojectPath("analyses-old/a.png", dirs), {
    dir: ".",
    path: "analyses-old/a.png",
  });
  assert.equal(
    stageNameFromDvcAddress("analyses/dvc.yaml:download"),
    "analyses:download",
  );
  assert.equal(stageNameFromDvcAddress("dvc.yaml:build"), "build");
  assert.equal(stageNameFromDvcAddress("build@1"), "build@1");
  const envs = new Set(["slurm", "main", "analyses:main", "analyses:cluster"]);
  assert.deepEqual(envRefParts("slurm:main", envs), ["slurm", "main"]);
  assert.deepEqual(envRefParts("analyses:main", envs), ["analyses:main"]);
  assert.deepEqual(envRefParts("analyses:cluster:analyses:main", envs), [
    "analyses:cluster",
    "analyses:main",
  ]);
  assert.deepEqual(envRefParts("slurm:analyses:main", envs), [
    "slurm",
    "analyses:main",
  ]);
  assert.deepEqual(
    qualifyEnvDescriptions("analyses", {
      main: { kind: "uv", spec_path: "pyproject.toml", lock_path: "uv.lock" },
    }),
    {
      "analyses:main": {
        kind: "uv",
        spec_path: "analyses/pyproject.toml",
        lock_path: "analyses/uv.lock",
      },
    },
  );
  assert.deepEqual(qualifyEnvDescriptions(".", { main: { kind: "uv" } }), {
    main: { kind: "uv" },
  });
});

test("a malformed subproject calkit.yaml doesn't break the merge", async () => {
  const sub = {
    subprojects: { path: "nested" },
    environments: { ok: { kind: "uv", path: "pyproject.toml" }, bad: null },
    pipeline: { stages: { ok: { kind: "python-script" }, bad: null } },
    apps: { bad: null },
    notebooks: [{ environment: "ok" }],
    figures: [{ title: "No path" }, { path: "fig.png" }],
    datasets: { path: "not-a-list.csv" },
    questions: [null],
  } as unknown as CalkitInfo;
  const found = await collectSubprojects(
    { subprojects: [{ path: "sub" }] },
    async (dir) => (dir === "sub" ? sub : undefined),
  );
  assert.deepEqual(
    found.map((s) => s.dir),
    ["sub"],
  );
  const { config } = mergeSubprojectConfigs({}, [{ dir: "sub", config: sub }]);
  assert.deepEqual(Object.keys(config.environments ?? {}), ["sub:ok"]);
  assert.deepEqual(Object.keys(config.pipeline?.stages ?? {}), ["sub:ok"]);
  assert.deepEqual(config.apps, {});
  assert.deepEqual(config.notebooks, []);
  assert.deepEqual(config.figures?.map((f) => f.path), ["sub/fig.png"]);
  assert.deepEqual(config.datasets, []);
  const dvc = mergeSubprojectDvcYaml({}, [
    { dir: "sub", config: sub, dvcYaml: { stages: { bad: null } } as never },
  ]);
  assert.deepEqual(dvc.stages, {});
});
