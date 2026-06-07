import assert from "node:assert/strict";
import test from "node:test";
import * as path from "node:path";
import {
  getConfiguredCandidateForNotebookPath,
  getExecutedNotebookHtmlPath,
  resolveNotebookEnvironmentName,
  type CalkitInfo,
} from "../notebooks";

test("getExecutedNotebookHtmlPath mirrors calkit's executed HTML location", () => {
  // Notebook in a subdirectory keeps its directory under the html dir.
  assert.equal(
    getExecutedNotebookHtmlPath("notebooks/analysis.ipynb"),
    path.join(".calkit", "notebooks", "html", "notebooks", "analysis.html"),
  );
  // Bare filename has no leading "./" segment.
  assert.equal(
    getExecutedNotebookHtmlPath("analysis.ipynb"),
    path.join(".calkit", "notebooks", "html", "analysis.html"),
  );
});

test("resolveNotebookEnvironmentName uses jupyter pipeline stages directly", () => {
  const config: CalkitInfo = {
    environments: {
      clima: { kind: "slurm", host: "clima.gps.caltech.edu" },
      main: { kind: "julia", path: ".calkit/envs/main/Project.toml" },
    },
    pipeline: {
      stages: {
        "benchmark-notebook-tr": {
          kind: "jupyter-notebook",
          notebook_path: "notebooks/benchmark-localgeom-tr.ipynb",
          environment: "clima:main",
        },
      },
    },
    notebooks: [
      {
        path: "notebooks/benchmark-localgeom-tr.ipynb",
      },
    ],
  };

  assert.equal(
    resolveNotebookEnvironmentName(
      config,
      "notebooks/benchmark-localgeom-tr.ipynb",
    ),
    "clima:main",
  );
});

test("resolveNotebookEnvironmentName resolves the notebooks-section sources", () => {
  const config: CalkitInfo = {
    environments: {
      analyze: { kind: "uv-venv", path: "envs/analyze.txt" },
      main: { kind: "uv-venv", path: "envs/main.txt" },
    },
    pipeline: {
      stages: {
        // A non-jupyter kind that still references the notebook by name.
        analyze: {
          kind: "python-script",
          notebook_path: "notebooks/analyze.ipynb",
          environment: "analyze",
        },
      },
    },
    notebooks: [
      // References a stage by name, with no explicit environment of its own.
      { path: "notebooks/analyze.ipynb", stage: "analyze" },
      // Carries an explicit environment.
      { path: "notebooks/main.ipynb", environment: "main" },
    ],
  };
  // Resolved via the referenced stage's environment, even though the stage's
  // kind isn't "jupyter-notebook".
  assert.equal(
    resolveNotebookEnvironmentName(config, "notebooks/analyze.ipynb"),
    "analyze",
  );
  // Resolved via the notebook entry's explicit environment.
  assert.equal(
    resolveNotebookEnvironmentName(config, "notebooks/main.ipynb"),
    "main",
  );
  // Unknown notebook resolves to nothing.
  assert.equal(
    resolveNotebookEnvironmentName(config, "notebooks/missing.ipynb"),
    undefined,
  );
});

test("getConfiguredCandidateForNotebookPath resolves nested slurm notebook envs from pipeline stages", () => {
  const config: CalkitInfo = {
    environments: {
      clima: { kind: "slurm", host: "clima.gps.caltech.edu" },
      main: {
        kind: "julia",
        path: ".calkit/envs/main/Project.toml",
        julia: "1.11",
      },
    },
    pipeline: {
      stages: {
        "benchmark-notebook-tr": {
          kind: "jupyter-notebook",
          notebook_path: "notebooks/benchmark-localgeom-tr.ipynb",
          environment: "clima:main",
        },
      },
    },
  };

  const candidate = getConfiguredCandidateForNotebookPath(
    config,
    "notebooks/benchmark-localgeom-tr.ipynb",
  );

  assert.equal(candidate?.environmentName, "clima:main");
  assert.equal(candidate?.outerSlurmEnvironment, "clima");
  assert.equal(candidate?.innerEnvironment, "main");
  assert.equal(candidate?.innerKind, "julia");
});
