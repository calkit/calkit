import { describe, expect, test } from "vitest";

import { isDiffableDocument, latexDiffPath, refDirName } from "./latex";

describe("latexDiffPath", () => {
  test("mirrors the document's own path under the comparison", () => {
    // A `latex` stage with `diffs: [main]` writes this, so the extension
    // has to derive the same path the Python package does
    expect(latexDiffPath("main", "pubs/paper-1/main.pdf")).toBe(
      ".calkit/latex-diffs/main/pubs/paper-1/main.pdf",
    );
  });

  test("names a ref the way a directory can be named", () => {
    expect(refDirName("main")).toBe("main");
    // Slashes are path separators, so a branch that has one is flattened
    expect(refDirName("release/1.0")).toBe("release-1.0");
    expect(refDirName("feature/some_thing")).toBe("feature-some-thing");
    expect(latexDiffPath("release/1.0", "paper.pdf")).toBe(
      ".calkit/latex-diffs/release-1.0/paper.pdf",
    );
  });
});

describe("isDiffableDocument", () => {
  test("only a PDF has a marked-up counterpart", () => {
    expect(isDiffableDocument("pubs/paper-1/main.pdf")).toBe(true);
    expect(isDiffableDocument("MAIN.PDF")).toBe(true);
    expect(isDiffableDocument("figures/plot.png")).toBe(false);
    expect(isDiffableDocument("data/results.csv")).toBe(false);
  });
});
