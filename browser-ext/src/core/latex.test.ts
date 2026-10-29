import { describe, expect, test } from "vitest";

import {
  canBeCreatedByPerson,
  citationAt,
  citationProblems,
  citationsIn,
  citationText,
  citationCandidates,
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
    // Any other TeX a stage writes is a file, as a plain \input is
    expect(citationAt("\\ckinclude{results/n}", 3)).toEqual({
      kind: "file",
      path: "results/n",
      key: undefined,
      options: "",
    });
  });

  test("ignores text between commands and commands in comments", () => {
    expect(citationAt(line, line.indexOf("and"))).toBeNull();
    expect(citationAt(line, line.indexOf("tables/t.tex"))).toBeNull();
    // Only a value takes a second brace group, as in calkit/latex.py
    const after = "\\ckfigure{figures/a}{caption}";
    expect(citationAt(after, after.indexOf("caption"))).toBeNull();
    expect(citationAt("\\ckvalue{results/m.json}", 3)).toBeNull();
  });

  test("finds every command in a line, with where each is", () => {
    const found = citationsIn(line);
    expect(found.map((m) => line.slice(m.start, m.end))).toEqual([
      "\\ckvalue[.2f]{results/m.json}{fit.rmse}",
      "\\ckfigure{figures/a.png}",
    ]);
    expect(found[1].citation.path).toBe("figures/a.png");
    expect(citationsIn("% \\ckfigure{a}")).toEqual([]);
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
    expect(
      citationText({ kind: "file", path: "results/n.tex", options: "" }),
    ).toBe("\\ckinclude{results/n.tex}");
  });
});

describe("citationCandidates", () => {
  test("tries the name as written, then what TeX would add", () => {
    const figure = { kind: "figure", options: "", included: true } as const;
    expect(
      citationCandidates("paper", { ...figure, path: "figs/fit" }),
    ).toEqual([
      "paper/figs/fit",
      "paper/figs/fit.pdf",
      "paper/figs/fit.png",
      "paper/figs/fit.jpg",
      "paper/figs/fit.jpeg",
      "paper/figs/fit.eps",
      "paper/figs/fit.ps",
      "paper/figs/fit.gif",
    ]);
    // An extension already written is the only place to look, and a path
    // can climb out of the paper's folder
    expect(
      citationCandidates("pubs/paper", {
        ...figure,
        path: "../../figures/a.PNG",
      }),
    ).toEqual(["figures/a.PNG"]);
    expect(
      citationCandidates(".", {
        kind: "file",
        path: "./t",
        options: "",
        included: true,
      }),
    ).toEqual(["t", "t.tex"]);
  });

  test("finds calkit.sty's components from the project root", () => {
    // Extensions first, as calkit.sty looks for them
    expect(
      citationCandidates("paper", {
        kind: "figure",
        path: "figures/fit_1.5",
        options: "",
      }),
    ).toEqual([
      "figures/fit_1.5.pdf",
      "figures/fit_1.5.png",
      "figures/fit_1.5.jpg",
      "figures/fit_1.5.jpeg",
      "figures/fit_1.5.eps",
      "figures/fit_1.5.ps",
      "figures/fit_1.5.gif",
      "figures/fit_1.5",
    ]);
    expect(
      citationCandidates("paper", {
        kind: "table",
        path: "tables/t.tex",
        options: "",
      }),
    ).toEqual(["tables/t.tex"]);
    expect(
      citationCandidates("paper", {
        kind: "value",
        path: "results/m.json",
        key: "x",
        options: "",
      }),
    ).toEqual(["results/m.json"]);
  });
});

describe("citationProblems", () => {
  const figure = {
    kind: "figure",
    path: "figures/a.png",
    options: "",
  } as const;
  const base = { path: "figures/a.png", exists: true, inputs: [] };
  const self = { path: "figures/a.png", steps: [{ path: "figures/a.png" }] };

  test("says what's wrong, worst first", () => {
    // Fine: the pipeline makes it and it's current
    expect(citationProblems(figure, { ...base, stage: "plot" })).toEqual([]);
    // Nothing defines where it came from
    expect(
      citationProblems(figure, { ...base, gaps: [self] }).map((p) => p.message),
    ).toEqual(["Origin not defined"]);
    // Something it's made from has no origin, and it's out of date
    const problems = citationProblems(figure, {
      ...base,
      stage: "plot",
      stale_reason: "pipeline",
      gaps: [
        {
          path: "data/raw.csv",
          steps: [
            { path: "figures/a.png", stage: "plot" },
            { path: "data/raw.csv" },
          ],
        },
      ],
    });
    expect(problems.map((p) => [p.severity, p.kind, p.path])).toEqual([
      ["error", "origin", "data/raw.csv"],
      ["warning", "stale", "figures/a.png"],
    ]);
    expect(problems[0].message).toBe(
      "Origin not defined for data/raw.csv, which it's made from (via plot)",
    );
  });

  test("names what isn't in the project, except a plain include", () => {
    const missing = { ...base, exists: false, gaps: [self] };
    expect(citationProblems(figure, missing).map((p) => p.message)).toEqual([
      "figures/a.png isn't in the project",
    ]);
    expect(citationProblems({ ...figure, included: true }, missing)).toEqual(
      [],
    );
    // A value says what's wrong with reading it
    const value = {
      kind: "value",
      path: "r.json",
      key: "x",
      options: "",
    } as const;
    expect(
      citationProblems(value, {
        ...base,
        path: "r.json",
        value_error: "r.json has no key x",
      }).map((p) => p.message),
    ).toEqual(["r.json has no key x"]);
  });
});

describe("canBeCreatedByPerson", () => {
  test("rules out formats something else exports", () => {
    expect(canBeCreatedByPerson("figures/photo.jpeg")).toBe(true);
    expect(canBeCreatedByPerson("figures/drawn.svg")).toBe(true);
    expect(canBeCreatedByPerson("data/raw.csv")).toBe(true);
    expect(canBeCreatedByPerson("figures/plot.png")).toBe(false);
    expect(canBeCreatedByPerson("figures/PLOT.PDF")).toBe(false);
  });
});
