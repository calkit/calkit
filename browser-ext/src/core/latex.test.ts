import { describe, expect, test } from "vitest";

import {
  citationAt,
  citationText,
  isDiffableDocument,
  latexDiffPath,
  refDirName,
} from "./latex";

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

describe("citationAt", () => {
  const line =
    "Error \\ckvalue[.2f]{results/m.json}{fit.rmse} and \\ckfigure{figures/a.png} % \\cktable{tables/t.tex}";

  test("finds the command the cursor is in, whichever part", () => {
    const value = {
      kind: "value",
      path: "results/m.json",
      key: "fit.rmse",
      options: ".2f",
    };
    expect(citationAt(line, line.indexOf("\\ckvalue"))).toEqual(value);
    expect(citationAt(line, line.indexOf("fit.rmse"))).toEqual(value);
    expect(citationAt(line, line.indexOf("figures/a.png"))).toEqual({
      kind: "figure",
      path: "figures/a.png",
      key: undefined,
      options: "",
    });
  });

  test("ignores text between commands and commands in comments", () => {
    expect(citationAt(line, line.indexOf("and"))).toBeNull();
    expect(citationAt(line, line.indexOf("tables/t.tex"))).toBeNull();
  });

  test("builds what it parses", () => {
    for (const offset of [line.indexOf("fit"), line.indexOf("figures")]) {
      const citation = citationAt(line, offset);
      expect(citation).not.toBeNull();
      if (citation) {
        expect(line).toContain(citationText(citation));
      }
    }
    expect(
      citationText({ kind: "table", path: "tables/t.tex", options: "" }),
    ).toBe("\\cktable{tables/t.tex}");
  });
});
