import { describe, expect, test } from "vitest";

import {
  citationAt,
  citationText,
  includeCandidates,
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

  test("finds plain includes too, by the path as written", () => {
    const plain =
      "\\includegraphics[width=\\linewidth]{figs/fit} \\input{tables/t} % \\input{no}";
    expect(citationAt(plain, plain.indexOf("figs"))).toEqual({
      kind: "figure",
      path: "figs/fit",
      options: "width=\\linewidth",
      included: true,
    });
    expect(citationAt(plain, plain.indexOf("tables"))).toEqual({
      kind: "file",
      path: "tables/t",
      options: "",
      included: true,
    });
    expect(citationAt(plain, plain.indexOf("no}"))).toBeNull();
    // Not to be mistaken for an include
    const other = "\\inputencoding{utf8} \\includesvg{x}";
    expect(citationAt(other, other.indexOf("utf8"))).toBeNull();
    expect(citationAt(other, other.indexOf("x}"))).toBeNull();
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

describe("includeCandidates", () => {
  test("tries the name as written, then what TeX would add", () => {
    const figure = { kind: "figure", options: "", included: true } as const;
    expect(includeCandidates("paper", { ...figure, path: "figs/fit" })).toEqual(
      [
        "paper/figs/fit",
        "paper/figs/fit.pdf",
        "paper/figs/fit.png",
        "paper/figs/fit.jpg",
        "paper/figs/fit.jpeg",
        "paper/figs/fit.eps",
        "paper/figs/fit.ps",
        "paper/figs/fit.gif",
      ],
    );
    // An extension already written is the only place to look, and a path
    // can climb out of the paper's folder
    expect(
      includeCandidates("pubs/paper", {
        ...figure,
        path: "../../figures/a.PNG",
      }),
    ).toEqual(["figures/a.PNG"]);
    expect(
      includeCandidates(".", { kind: "file", path: "./t", options: "" }),
    ).toEqual(["t", "t.tex"]);
  });
});
