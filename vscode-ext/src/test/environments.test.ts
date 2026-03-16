import assert from "node:assert/strict";
import test from "node:test";
import {
  getDefaultSlurmOptions,
  makeCalkitEnvKernelSourceCandidates,
  parseSlurmOptionList,
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
    extra: "--cpus-per-task=8 --mem=32G",
  });
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

test("getDefaultSlurmOptions falls back to legacy object format", () => {
  const parsed = getDefaultSlurmOptions({
    kind: "slurm",
    default_slurm_options: {
      gpus: "2",
      time: "240",
    },
  });

  assert.equal(parsed?.gpus, "2");
  assert.equal(parsed?.time, "240");
  assert.equal(parsed?.partition, undefined);
  assert.equal(parsed?.extra, undefined);
});

test("makeEnvironmentCandidates returns standalone notebook envs and nested slurm combinations", () => {
  const candidates = makeCalkitEnvKernelSourceCandidates({
    slurmOuter: { kind: "slurm", host: "cluster.school.edu" },
    juliaEnv: { kind: "julia", path: "Project.toml", julia: "1.11" },
    pyEnv: { kind: "uv", path: "pyproject.toml" },
    sshEnv: { kind: "ssh", host: "example.org" },
  });

  assert.ok(candidates.some((c) => c.label === "juliaEnv"));
  assert.ok(candidates.some((c) => c.label === "pyEnv"));
  assert.ok(!candidates.some((c) => c.label === "sshEnv"));

  const nestedLabels = candidates
    .filter((c) => c.outerSlurmEnvironment === "slurmOuter")
    .map((c) => c.label)
    .sort();

  assert.deepEqual(nestedLabels, [
    "slurmOuter:juliaEnv",
    "slurmOuter:pyEnv",
    "slurmOuter:sshEnv",
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
