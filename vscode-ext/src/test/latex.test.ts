import assert from "node:assert/strict";
import test from "node:test";
import { latexWorkingDiffPath } from "../latex/core";

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
