import assert from "node:assert/strict";
import test from "node:test";
import {
  latexStagePdf,
  latexStageSource,
  latexWorkingDiffPath,
  pipelineLatexDiffs,
} from "../latex/core";

test("latexWorkingDiffPath mirrors the CLI's working tree diff path", () => {
  // No revision means the CLI's default-branch merge base.
  assert.equal(
    latexWorkingDiffPath("paper/main.tex"),
    ".calkit/local/latex-diffs/default-branch..working/paper/main.pdf",
  );
  // Refs are flattened into one path component.
  assert.equal(
    latexWorkingDiffPath("paper/main.tex", "origin/feature_x"),
    ".calkit/local/latex-diffs/origin-feature-x..working/paper/main.pdf",
  );
  assert.equal(
    latexWorkingDiffPath("main.tex", "HEAD~2"),
    ".calkit/local/latex-diffs/HEAD-2..working/main.pdf",
  );
});

test("pipelineLatexDiffs mirrors the CLI's pipeline diff names and paths", () => {
  const diffs = pipelineLatexDiffs({
    paper: {
      kind: "latex",
      target_path: "pubs/paper/main.tex",
      diffs: ["main", ["paper-v1", "origin/paper_v2"]],
    },
    other: { kind: "python-script", script_path: "run.py" },
  });
  assert.deepEqual(diffs, [
    {
      path: ".calkit/latex-diffs/main/pubs/paper/main.pdf",
      document: "pubs/paper/main.tex",
      latexStage: "paper",
      stage: "paper-diff-main",
      fromRef: "main",
      toRef: undefined,
    },
    {
      path: ".calkit/latex-diffs/paper-v1..origin-paper-v2/pubs/paper/main.pdf",
      document: "pubs/paper/main.tex",
      latexStage: "paper",
      stage: "paper-diff-paper-v1-origin-paper-v2",
      fromRef: "paper-v1",
      toRef: "origin/paper_v2",
    },
  ]);
});

test("latexStagePdf and latexStageSource map a latex stage's document and PDF", () => {
  const stages = {
    paper: { kind: "latex", target_path: "main.tex", wdir: "pubs/paper" },
    report: { kind: "quarto", target_path: "report.qmd" },
  };
  assert.equal(
    latexStagePdf(stages, "pubs/paper/main.tex"),
    "pubs/paper/main.pdf",
  );
  assert.equal(
    latexStageSource(stages, "pubs/paper/main.pdf"),
    "pubs/paper/main.tex",
  );
  // Only latex stages count, and only their own document
  assert.equal(latexStagePdf(stages, "report.qmd"), undefined);
  assert.equal(latexStageSource(stages, "other.pdf"), undefined);
});
