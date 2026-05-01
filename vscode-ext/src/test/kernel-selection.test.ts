import assert from "node:assert/strict";
import test from "node:test";
import {
  kernelRegistrationKinds,
  makeCalkitEnvKernelSourceCandidates,
  type EnvKind,
} from "../environments";

const REGISTRATION_KINDS: EnvKind[] = [
  "uv",
  "uv-venv",
  "venv",
  "conda",
  "pixi",
  "julia",
];

const SERVER_KINDS: EnvKind[] = ["docker", "slurm", "ssh", "_system"];

test("kernelRegistrationKinds includes all local env types", () => {
  for (const kind of REGISTRATION_KINDS) {
    assert.ok(
      kernelRegistrationKinds.has(kind),
      `expected '${kind}' to be in kernelRegistrationKinds`,
    );
  }
});

test("kernelRegistrationKinds excludes server-launch env types", () => {
  for (const kind of SERVER_KINDS) {
    assert.ok(
      !kernelRegistrationKinds.has(kind),
      `expected '${kind}' to NOT be in kernelRegistrationKinds`,
    );
  }
});

test("non-nested local env candidate has no outerSlurmEnvironment", () => {
  // A standalone uv-venv env should produce a candidate with no outer
  // SLURM environment, which is the signal that no server launch is needed.
  const candidates = makeCalkitEnvKernelSourceCandidates({
    main: { kind: "uv-venv", path: "pyproject.toml" },
  });
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].innerKind, "uv-venv");
  assert.equal(candidates[0].outerSlurmEnvironment, undefined);
  assert.ok(kernelRegistrationKinds.has(candidates[0].innerKind));
});

test("nested slurm+uv-venv candidate has outerSlurmEnvironment set", () => {
  // A SLURM-wrapped uv-venv env must still launch a server — the outer
  // SLURM environment is what triggers that path. The guard in extension.ts
  // is: !outerSlurmEnvironment && needsKernelRegistration(innerKind)
  const candidates = makeCalkitEnvKernelSourceCandidates({
    cluster: { kind: "slurm", host: "cluster.example.edu" },
    main: { kind: "uv-venv", path: "pyproject.toml" },
  });
  const nested = candidates.find((c) => c.outerSlurmEnvironment === "cluster");
  assert.ok(nested, "expected a nested slurm:uv-venv candidate");
  assert.equal(nested.innerKind, "uv-venv");
  assert.equal(nested.outerSlurmEnvironment, "cluster");
  assert.ok(kernelRegistrationKinds.has(nested.innerKind));
  assert.ok(nested.outerSlurmEnvironment !== undefined);
});

test("nested slurm+docker candidate has outerSlurmEnvironment set and docker does not use kernel registration", () => {
  const candidates = makeCalkitEnvKernelSourceCandidates({
    cluster: { kind: "slurm", host: "cluster.example.edu" },
    myContainer: { kind: "docker", image: "jupyter/minimal-notebook:latest" },
  });
  const nested = candidates.find((c) => c.outerSlurmEnvironment === "cluster");
  assert.ok(nested);
  assert.equal(nested.innerKind, "docker");
  assert.ok(!kernelRegistrationKinds.has(nested.innerKind));
});

test("all standalone registration-kind envs produce candidates with no outer env", () => {
  const envs: Record<string, { kind: EnvKind }> = {};
  for (const kind of REGISTRATION_KINDS) {
    envs[kind] = { kind };
  }
  const candidates = makeCalkitEnvKernelSourceCandidates(envs);
  for (const kind of REGISTRATION_KINDS) {
    const c = candidates.find((x) => x.environmentName === kind);
    assert.ok(c, `expected standalone candidate for kind '${kind}'`);
    assert.equal(c.outerSlurmEnvironment, undefined);
  }
});
