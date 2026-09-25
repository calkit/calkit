import assert from "node:assert/strict";
import test from "node:test";
import { latexStageDiffArgs, latexWorkingDiffPath } from "../latex/core";

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

test("latexStageDiffArgs builds the diff the way the document's stage does", () => {
  const config = {
    pipeline: {
      stages: {
        other: { kind: "latex", target_path: "slides.tex", environment: "x" },
        paper: {
          kind: "latex",
          target_path: "paper/main.tex",
          environment: "tex",
          latexmkrc_path: "paper/latexmkrc",
          latexmk_args: ["-shell-escape"],
          latexdiff_args: ["--type=CFONT"],
          keep_diff_tex: true,
        },
      },
    },
  };
  assert.deepEqual(latexStageDiffArgs(config, "paper/main.tex"), [
    "-e",
    "tex",
    "-r",
    "paper/latexmkrc",
    "--latexmk-arg",
    "-shell-escape",
    "--latexdiff-arg",
    "--type=CFONT",
    "--keep-tex",
  ]);
  // A document no latex stage builds gets the CLI's defaults.
  assert.deepEqual(latexStageDiffArgs(config, "notes.tex"), []);
  assert.deepEqual(latexStageDiffArgs(undefined, "paper/main.tex"), []);
});
