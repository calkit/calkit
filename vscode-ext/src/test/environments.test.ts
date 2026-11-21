import assert from "node:assert/strict";
import test from "node:test";
import {
  findCalkitEnvKernelSourceCandidate,
  getDefaultSlurmOptions,
  getMissingSlurmResources,
  makeCalkitEnvKernelSourceCandidates,
  mergeSlurmOptions,
  parsePixiPackages,
  parseProjectDependencies,
  parseRemoteSshHost,
  parseRequirementsTxt,
  parseSlurmServerOutput,
  parseSlurmOptionList,
  parseUvPackages,
  slurmOptionsToOptionList,
} from "../environments";

test("slurmOptionsToOptionList serializes well-known fields", () => {
  const options = slurmOptionsToOptionList({
    gpus: "1",
    time: "120",
    partition: "gpu",
    extra: "--cpus-per-task=8 --mem=32G",
  });

  assert.deepEqual(options, [
    "--gpus=1",
    "--time=120",
    "--partition=gpu",
    "--cpus-per-task=8 --mem=32G",
  ]);
});

test("parseSlurmOptionList parses equals and spaced options", () => {
  const parsed = parseSlurmOptionList([
    "--gpus=1",
    "--time 02:00:00",
    "--partition gpu",
    "--cpus-per-task=8",
    "--mem=32G",
  ]);

  assert.deepEqual(parsed, {
    gpus: "1",
    time: "02:00:00",
    partition: "gpu",
    cpus: "8",
    mem: "32G",
    extra: undefined,
  });
  // Short flags, several flags per entry, and unknown flags kept as extra
  assert.deepEqual(
    parseSlurmOptionList(["-p short -t 60", "-c 4 --mem-per-cpu=2G -A lab"]),
    {
      gpus: undefined,
      time: "60",
      partition: "short",
      cpus: "4",
      mem: undefined,
      extra: "--mem-per-cpu=2G -A lab",
    },
  );
  assert.equal(parseSlurmOptionList([" "]), undefined);
  // Flag-like text in a quoted value stays in that value
  assert.deepEqual(
    parseSlurmOptionList(['--comment="notebook -p gpu"', "-p short"]),
    {
      gpus: undefined,
      time: undefined,
      partition: "short",
      cpus: undefined,
      mem: undefined,
      extra: '--comment="notebook -p gpu"',
    },
  );
});

test("missing SLURM resources are found and filled from other options", () => {
  assert.deepEqual(getMissingSlurmResources(undefined), [
    "partition",
    "time",
    "cpus",
    "mem",
  ]);
  // Memory per CPU or GPU counts as memory
  assert.deepEqual(
    getMissingSlurmResources({
      partition: "short",
      cpus: "4",
      extra: "--mem-per-cpu=2G",
    }),
    ["time"],
  );
  // Only what the override sets replaces the base
  assert.deepEqual(
    mergeSlurmOptions(
      { time: "120", cpus: "4", gpus: "1" },
      { time: "60", cpus: " ", partition: "short" },
    ),
    {
      gpus: "1",
      time: "60",
      partition: "short",
      cpus: "4",
      mem: undefined,
      extra: undefined,
    },
  );
  // Flags saved in extra by older versions don't survive a newer value
  assert.deepEqual(
    mergeSlurmOptions(
      { extra: "--mem=32G -A lab --qos=low" },
      { mem: "64G", extra: "--qos=high" },
    ),
    {
      gpus: undefined,
      time: undefined,
      partition: undefined,
      cpus: undefined,
      mem: "64G",
      extra: "-A lab --qos=high",
    },
  );
  // Memory flags override each other, since SLURM takes only one
  assert.deepEqual(
    mergeSlurmOptions({ mem: "32G" }, { extra: "--mem-per-cpu=2G" }),
    {
      gpus: undefined,
      time: undefined,
      partition: undefined,
      cpus: undefined,
      mem: undefined,
      extra: "--mem-per-cpu=2G",
    },
  );
  assert.equal(
    mergeSlurmOptions({ extra: "--mem-per-gpu 8G -A lab" }, { mem: "64G" })
      .extra,
    "-A lab",
  );
});

test("getDefaultSlurmOptions prefers default_options in calkit.yaml format", () => {
  const parsed = getDefaultSlurmOptions({
    kind: "slurm",
    host: "cluster.school.edu",
    default_options: ["--gpus=1", "--time=120"],
  });

  assert.equal(parsed?.gpus, "1");
  assert.equal(parsed?.time, "120");
  assert.equal(parsed?.partition, undefined);
  assert.equal(parsed?.extra, undefined);
});

test("getDefaultSlurmOptions ignores legacy object format", () => {
  const parsed = getDefaultSlurmOptions({
    kind: "slurm",
    default_slurm_options: {
      gpus: "2",
      time: "240",
    },
  });

  assert.equal(parsed, undefined);
});

test("parseRemoteSshHost finds the host a Remote-SSH window connected to", () => {
  assert.equal(
    parseRemoteSshHost("ssh-remote+login.hpc.caltech.edu"),
    "login.hpc.caltech.edu",
  );
  assert.equal(
    parseRemoteSshHost("ssh-remote+pete@login.hpc.caltech.edu:2222"),
    "login.hpc.caltech.edu",
  );
  // Hex-encoded JSON form
  const encoded = Buffer.from(
    JSON.stringify({ hostName: "login.hpc.caltech.edu", user: "pete" }),
  ).toString("hex");
  assert.equal(
    parseRemoteSshHost(`ssh-remote+${encoded}`),
    "login.hpc.caltech.edu",
  );
  // A host name that only looks like hex
  assert.equal(parseRemoteSshHost("ssh-remote+deadbeef"), "deadbeef");
  // Not Remote-SSH
  assert.equal(parseRemoteSshHost(""), undefined);
  assert.equal(parseRemoteSshHost("wsl+Ubuntu"), undefined);
});

test("parseSlurmServerOutput finds the compute node and Jupyter port", () => {
  // Nothing printed yet
  assert.deepEqual(parseSlurmServerOutput(""), {
    host: undefined,
    port: undefined,
  });
  // Job started, Jupyter not up yet
  assert.deepEqual(parseSlurmServerOutput("CALKIT_SLURM_NODE=node042\n"), {
    host: "node042",
    port: undefined,
  });
  // Jupyter up on a fallback port since the requested one was taken
  const output = [
    "CALKIT_SLURM_NODE=node042.cluster.edu",
    "Environment is up to date",
    "[I ServerApp] Jupyter Server 2.21.1 is running at:",
    "[I ServerApp] http://0.0.0.0:8889/lab?token=abc",
    "[I ServerApp]     http://127.0.0.1:8889/lab?token=abc",
  ].join("\n");
  assert.deepEqual(parseSlurmServerOutput(output), {
    host: "node042.cluster.edu",
    port: 8889,
  });
  // Node name cut off mid-chunk isn't used until its line ends
  assert.equal(
    parseSlurmServerOutput("CALKIT_SLURM_NODE=node042.cl").host,
    undefined,
  );
  assert.equal(
    parseSlurmServerOutput("CALKIT_SLURM_NODE=node042.cluster.edu\r\n").host,
    "node042.cluster.edu",
  );
  // URLs that aren't the Jupyter server's are ignored
  assert.deepEqual(
    parseSlurmServerOutput("See https://example.com:443/docs for help"),
    { host: undefined, port: undefined },
  );
});

test("makeEnvironmentCandidates returns standalone notebook envs and nested slurm combinations", () => {
  const candidates = makeCalkitEnvKernelSourceCandidates({
    slurmOuter: { kind: "slurm", host: "cluster.school.edu" },
    juliaEnv: { kind: "julia", path: "Project.toml", julia: "1.11" },
    pyEnv: { kind: "uv", path: "pyproject.toml" },
    systemEnv: { kind: "system", host: "example.org" },
  });

  assert.ok(candidates.some((c) => c.label === "juliaEnv"));
  assert.ok(candidates.some((c) => c.label === "pyEnv"));
  assert.ok(!candidates.some((c) => c.label === "systemEnv"));

  const nestedLabels = candidates
    .filter((c) => c.outerSlurmEnvironment === "slurmOuter")
    .map((c) => c.label)
    .sort();

  assert.deepEqual(nestedLabels, [
    "slurmOuter:juliaEnv",
    "slurmOuter:pyEnv",
    "slurmOuter:systemEnv",
  ]);
});

test("makeEnvironmentCandidates excludes texlive docker environments", () => {
  const candidates = makeCalkitEnvKernelSourceCandidates({
    slurmOuter: { kind: "slurm", host: "cluster.school.edu" },
    texliveDocker: { kind: "docker", image: "texlive/texlive:latest" },
    normalDocker: { kind: "docker", image: "jupyter/minimal-notebook:latest" },
    pyEnv: { kind: "uv", path: "pyproject.toml" },
  });

  assert.ok(!candidates.some((c) => c.label === "texliveDocker"));
  assert.ok(!candidates.some((c) => c.label === "slurmOuter:texliveDocker"));
  assert.ok(candidates.some((c) => c.label === "normalDocker"));
  assert.ok(candidates.some((c) => c.label === "slurmOuter:normalDocker"));
});

test("findCalkitEnvKernelSourceCandidate resolves standalone and nested names", () => {
  const environments = {
    slurmOuter: { kind: "slurm", host: "cluster.school.edu" },
    juliaEnv: { kind: "julia", path: "Project.toml", julia: "1.11" },
  };

  const standalone = findCalkitEnvKernelSourceCandidate(
    environments,
    "juliaEnv",
  );
  const nested = findCalkitEnvKernelSourceCandidate(
    environments,
    "slurmOuter:juliaEnv",
  );
  const outerOnly = findCalkitEnvKernelSourceCandidate(
    environments,
    "slurmOuter",
  );

  assert.equal(standalone?.environmentName, "juliaEnv");
  assert.equal(nested?.environmentName, "slurmOuter:juliaEnv");
  assert.equal(nested?.outerSlurmEnvironment, "slurmOuter");
  assert.equal(outerOnly, undefined);
});

test("parseProjectDependencies reads deps past bracketed [project] fields", () => {
  // A realistic uv pyproject: array-valued fields (authors, classifiers)
  // appear before dependencies and must not break the scan.
  const pyproject = [
    "[project]",
    'name = "demo"',
    'version = "0.1.0"',
    'authors = [{ name = "A. Person", email = "a@example.com" }]',
    'classifiers = ["Private :: Do Not Upload"]',
    "dependencies = [",
    '  "requests>=2",',
    '  "numpy",',
    "]",
    "",
    "[tool.uv]",
    'dev-dependencies = ["pytest"]',
  ].join("\n");
  assert.deepEqual(parseProjectDependencies(pyproject), [
    "requests>=2",
    "numpy",
  ]);
  // Inline single-line array also works.
  assert.deepEqual(
    parseProjectDependencies('[project]\ndependencies = ["a", "b"]\n'),
    ["a", "b"],
  );
});

test("parseRequirementsTxt reads one package per line, skipping noise", () => {
  const reqs = [
    "# editable deps",
    "gitpython",
    "ipykernel  # for notebooks",
    "",
    "-e .",
    "numpy>=1.0",
  ].join("\n");
  assert.deepEqual(parseRequirementsTxt(reqs), [
    "gitpython",
    "ipykernel",
    "numpy>=1.0",
  ]);
});

test("parseUvPackages picks the parser by file shape", () => {
  // pyproject.toml shape
  assert.deepEqual(parseUvPackages('[project]\ndependencies = ["a"]\n'), ["a"]);
  // requirements.txt shape (no [project] table)
  assert.deepEqual(parseUvPackages("gitpython\nipykernel\n"), [
    "gitpython",
    "ipykernel",
  ]);
});

test("parsePixiPackages merges default and feature tables", () => {
  // pixi.toml with packages in the default [dependencies] table.
  const defaultLayout = [
    "[workspace]",
    'name = "clima-data"',
    "",
    "[dependencies]",
    'python = ">=3.11"',
    'gh = ">=2.40"',
    "",
    "[pypi-dependencies]",
    'requests = "*"',
  ].join("\n");
  assert.deepEqual(parsePixiPackages(defaultLayout, "clima-data"), {
    conda: ["python", "gh"],
    pip: ["requests"],
  });
  // pixi.toml with packages under a feature named after the env.
  const featureLayout = [
    "[feature.main.dependencies]",
    'numpy = "*"',
    "",
    "[feature.main.pypi-dependencies]",
    'rich = "*"',
  ].join("\n");
  assert.deepEqual(parsePixiPackages(featureLayout, "main"), {
    conda: ["numpy"],
    pip: ["rich"],
  });
  // "[dependencies]" must not be matched inside "[feature.x.dependencies]".
  assert.deepEqual(parsePixiPackages(featureLayout, "other"), {
    conda: [],
    pip: [],
  });
});
