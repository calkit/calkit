import assert from "node:assert/strict";
import test from "node:test";
import {
  getConfiguredCandidateForNotebookPath,
  resolveNotebookEnvironmentName,
  type CalkitInfo,
} from "../notebooks";

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
