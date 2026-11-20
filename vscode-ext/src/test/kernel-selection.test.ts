import assert from "node:assert/strict";
import test from "node:test";
import {
  getKernelMatchRank,
  getPythonEnvDir,
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

const SERVER_KINDS: EnvKind[] = ["docker", "slurm", "system", "_system"];

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

test("getKernelMatchRank prefers the kernel registered for the environment", () => {
  const name = "test-dye-2.py";
  const display = "test-dye-2: py";
  // The project's own .venv, whose name starts the same
  const projectVenv = {
    id: "ms-toolsai.jupyter/.jvsc74a57bd0f4./Users/me/dye-fading/.venv/python./Users/me/dye-fading/.venv/python.-m#ipykernel_launcher",
    label: "test-dye-2 (Python 3.14.0)",
  };
  const registered = {
    id: "ms-toolsai.jupyter/.jvsc74a57bd0a1./Users/me/Library/Jupyter/kernels/test-dye-2.py",
    label: "test-dye-2: py",
  };
  assert.equal(getKernelMatchRank(projectVenv, name, display), 1);
  assert.equal(getKernelMatchRank(registered, name, display), 4);
  assert.equal(
    getKernelMatchRank({ id: "x/abc", label: display }, name, display),
    3,
  );
  assert.equal(
    getKernelMatchRank({ id: `ms-toolsai.jupyter/${name}` }, name, display),
    4,
  );
  assert.equal(
    getKernelMatchRank({ id: "x/other", label: "Other" }, name, display),
    0,
  );
});

test("getKernelMatchRank knows the environment by its Python", () => {
  const venv = "/Users/me/dye-fading/.calkit/envs/py/.venv";
  assert.equal(getPythonEnvDir(`${venv}/bin/python`), venv);
  assert.equal(
    getPythonEnvDir("C:\\proj\\.venv\\Scripts\\python.exe"),
    "C:/proj/.venv",
  );
  assert.equal(getPythonEnvDir("C:\\envs\\py\\python.exe"), "C:/envs/py");
  const envController = {
    id: `ms-toolsai.jupyter/.undefined.-xfrozen_modules=off.${venv}/python.${venv}/python.-xfrozen_modules=off#-m#ipykernel_launcher`,
    label: "test-dye-2-py (Python 3.14.0)",
  };
  const projectVenv = {
    id: "ms-toolsai.jupyter/.jvsc74a57bd0f4./Users/me/dye-fading/.venv/python./Users/me/dye-fading/.venv/python.-m#ipykernel_launcher",
    label: "test-dye-2 (Python 3.14.0)",
  };
  assert.equal(
    getKernelMatchRank(envController, "test-dye-2.py", "test-dye-2: py", venv),
    5,
  );
  assert.equal(
    getKernelMatchRank(projectVenv, "test-dye-2.py", "test-dye-2: py", venv),
    1,
  );
});
