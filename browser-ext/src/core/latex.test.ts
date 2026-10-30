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
  resultValues,
  roundedLike,
  tableFile,
  typedNumberCitation,
  typedNumberMatches,
  typedNumberProblem,
  typedTableMatches,
  typedTableProblem,
  typedNumbersIn,
  typedNumbersInDocument,
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
    // Made manually, so it says what to do
    expect(
      citationProblems(figure, {
        ...base,
        stage: "export-a",
        stage_kind: "manual-step",
        message: "In Photoshop, export figures/a.png",
        stale_reason: "pipeline",
      }).map((p) => p.message),
    ).toEqual([
      "Needs a manual step, since what it's made from changed: In " +
        "Photoshop, export figures/a.png",
    ]);
    // Imported from somewhere only described, which is worth a warning
    expect(
      citationProblems(figure, {
        ...base,
        stage: "plot",
        gaps: [
          {
            path: "data/raw.csv",
            steps: [
              { path: "figures/a.png", stage: "plot" },
              { path: "data/raw.csv" },
            ],
            unchecked: true,
          },
        ],
      }).map((p) => [p.severity, p.message]),
    ).toEqual([
      [
        "warning",
        "data/raw.csv, which it's made from, is imported from somewhere " +
          "that can't be checked (via plot)",
      ],
    ]);
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

describe("typedNumbersIn", () => {
  const texts = (line: string) =>
    typedNumbersIn(line).map((m) => m.number.text);

  test("finds numbers that look like results", () => {
    expect(
      texts("The mean deficit was 0.47, and the largest was 0.50."),
    ).toEqual(["0.47", "0.50"]);
    // Table cells, math, percentages, and either side of a ±
    expect(texts("        0.6 & 0.48 \\\\")).toEqual(["0.6", "0.48"]);
    expect(texts("an RMSE of $-1.2e-3$")).toEqual(["-1.2e-3"]);
    expect(texts("drops by 12\\% and 3~\\%, with 5 \\pm 2 runs")).toEqual([
      "12",
      "3",
      "5",
      "2",
    ]);
    expect(texts("from 1,234 samples")).toEqual(["1,234"]);
    const [match] = typedNumbersIn("RMSE: 1,234.50");
    expect(match.number).toEqual({
      text: "1,234.50",
      value: 1234.5,
      decimals: 2,
      grouped: true,
      exponent: null,
    });
    expect(match.start).toBe(6);
    expect(match.end).toBe(14);
  });

  test("skips numbers that aren't results", () => {
    // Whole numbers, versions, names, and lengths
    expect(texts("In 2024, Figure 3 shows 4 runs")).toEqual([]);
    expect(texts("with version 1.2.3 of H2O.5x")).toEqual([]);
    expect(texts("scaled to 0.7\\textwidth or 2.5em")).toEqual([]);
    // Options and arguments that aren't text
    expect(
      texts("\\includegraphics[width=0.7\\textwidth]{figs/v1.5.png}"),
    ).toEqual([]);
    expect(texts("\\vspace{0.5cm}\\hspace*{1.5em} \\ref{fig:1.2}")).toEqual([]);
    expect(texts("\\ckvalue[.2f]{results/fit.json}{k.0.5}")).toEqual([]);
    expect(texts("\\SI{0.48}{\\metre} and \\num{1.5}")).toEqual([]);
    expect(texts("0.25 % was 0.3 before")).toEqual(["0.25"]);
    // Text arguments still count
    expect(texts("\\textbf{0.48} \\caption{An error of 0.3}")).toEqual([
      "0.48",
      "0.3",
    ]);
    expect(texts("\\multicolumn{2}{c}{0.5} \\textcolor{red}{1.5}")).toEqual([
      "0.5",
      "1.5",
    ]);
  });
});

describe("typedNumbersInDocument", () => {
  test("only looks in the body, outside code and the bibliography", () => {
    const { numbers, tables } = typedNumbersInDocument([
      "\\documentclass{article}",
      "\\setlength{\\parskip}{0.5em} 1.5",
      "\\begin{document}",
      "The deficit was 0.47.",
      "\\begin{verbatim}",
      "x = 0.25",
      "\\end{verbatim}",
      "\\begin{lstlisting} y = 0.1 \\end{lstlisting}",
      "\\begin{thebibliography}{9}",
      "\\bibitem{a} Vol. 1.2",
      "\\end{thebibliography}",
      "and 0.50 at most.",
      "\\end{document}",
      "0.99",
    ]);
    expect(numbers.map(({ line, match }) => [line, match.number.text])).toEqual(
      [
        [3, "0.47"],
        [11, "0.50"],
      ],
    );
    expect(tables).toEqual([]);
    // A section file has no body of its own, so all of it counts
    expect(
      typedNumbersInDocument(["A 0.3 drop.", "% 0.4"]).numbers,
    ).toHaveLength(1);
  });

  test("keeps a table's numbers together", () => {
    const { numbers, tables } = typedNumbersInDocument([
      "\\begin{table}[h]",
      "  \\begin{tabular}{cc}",
      "    Tow speed (m/s) & Deficit \\\\",
      "    0.6 & 0.48 \\\\",
      "    0.8 & 0.45 % was 0.44",
      "  \\end{tabular} after 0.3",
      "  \\caption{Deficit, about 0.47 on average}",
      "\\end{table}",
      "\\begin{tabular}{c} 1.5 \\end{tabular} \\begin{tabular}{c} A \\end{tabular}",
    ]);
    expect(numbers.map(({ match }) => match.number.text)).toEqual([
      "0.3",
      "0.47",
    ]);
    expect(
      tables.map(({ start, end, env, numbers }) => ({
        start,
        end,
        env,
        numbers: numbers.map((n) => n.text),
      })),
    ).toEqual([
      {
        start: { line: 1, column: 2 },
        end: { line: 5, column: 15 },
        env: "tabular",
        numbers: ["0.6", "0.48", "0.8", "0.45"],
      },
      {
        start: { line: 8, column: 0 },
        end: { line: 8, column: 36 },
        env: "tabular",
        numbers: ["1.5"],
      },
    ]);
  });
});

describe("typedTableMatches", () => {
  const typed = typedNumbersInDocument([
    "\\begin{tabular}{cc}",
    "0.6 & 0.48 \\\\ 0.8 & 0.45 \\\\ 1.0 & 0.47 \\\\ 1.2 & 0.50 \\\\",
    "\\end{tabular}",
  ]).tables[0];
  const deficits = tableFile(
    "results/deficit_table.tex",
    [
      "\\begin{tabular}{cc}",
      "    Tow speed (m/s) & Deficit \\\\",
      "    \\hline",
      "    0.6 & 0.50 \\\\",
      "    0.8 & 0.44 \\\\",
      "    1.0 & 0.50 \\\\",
      "    1.2 & 0.44 \\\\",
      "\\end{tabular}",
    ].join("\n"),
  );

  test("reads the numbers of a table a stage writes", () => {
    expect(deficits?.numbers.map((n) => n.text)).toEqual([
      "0.6",
      "0.50",
      "0.8",
      "0.44",
      "1.0",
      "0.50",
      "1.2",
      "0.44",
    ]);
    // \cktable can't stand in for a tabular with these
    expect(tableFile("a.tex", "No table here, 0.5")).toBeNull();
    expect(
      tableFile("b.tex", "\\begin{table}\\begin{tabular}{c}0.5\\end{tabular}"),
    ).toBeNull();
  });

  test("ranks table files by how many of its numbers they have", () => {
    const other = tableFile(
      "results/other.tex",
      "\\begin{tabular}{c} 0.6 & 9.9 \\end{tabular}",
    );
    const files = [other!, deficits!];
    // The speeds and one deficit agree, though the rest are outdated
    expect(typedTableMatches(typed, files)).toEqual([
      { path: "results/deficit_table.tex", matched: 5 },
    ]);
    expect(typedTableProblem(typed, files).message).toBe(
      "Typed in, though results/deficit_table.tex has a table like it",
    );
    expect(typedTableProblem(typed, [other!]).message).toBe(
      "Typed in, and no table in the project matches it",
    );
  });
});

describe("typedNumberMatches", () => {
  const values = resultValues("results/wake.json", {
    mean_deficit: 0.4687155036498191,
    max_deficit: 0.5030064751108918,
    n_runs: 4,
    ok: true,
    label: "0.47",
    deficit_by_speed: { "0.6": 0.503, "0.8": 0.4373 },
    runs: [{ rmse: 0.012 }],
  });
  const number = (line: string) => typedNumbersIn(line)[0].number;

  test("reads every number in a results file by its dotted key", () => {
    expect(values.map((v) => v.key)).toEqual([
      "mean_deficit",
      "max_deficit",
      "n_runs",
      "deficit_by_speed.0.6",
      "deficit_by_speed.0.8",
      "runs.0.rmse",
    ]);
  });

  test("matches results that round to what was typed", () => {
    const { exact, close } = typedNumberMatches(number("was 0.47"), values);
    expect(exact.map((v) => v.key)).toEqual(["mean_deficit"]);
    expect(close).toEqual([]);
    // Rounding to fewer places matches more
    expect(
      typedNumberMatches(number("was 0.5"), values).exact.map((v) => v.key),
    ).toEqual(["mean_deficit", "max_deficit", "deficit_by_speed.0.6"]);
    expect(
      typedNumberMatches(number("of 1.2e-2"), values).exact.map((v) => v.key),
    ).toEqual(["runs.0.rmse"]);
  });

  test("offers the nearest results when none match", () => {
    const { exact, close } = typedNumberMatches(number("was 0.48"), values);
    expect(exact).toEqual([]);
    expect(close.map((v) => v.key)).toEqual([
      "mean_deficit",
      "deficit_by_speed.0.6",
      "max_deficit",
    ]);
    expect(typedNumberMatches(number("was 9.5"), values).close).toEqual([]);
  });

  test("cites a result the way the number was typed", () => {
    const [mean] = values;
    expect(typedNumberCitation(number("was 0.47"), mean)).toEqual({
      kind: "value",
      path: "results/wake.json",
      key: "mean_deficit",
      options: ".2f",
    });
    expect(typedNumberCitation(number("of 1,234.5"), mean).options).toBe(
      ",.1f",
    );
    expect(typedNumberCitation(number("of 4.7e-1"), mean).options).toBe(".1e");
    expect(typedNumberProblem(number("was 0.47"), values)).toEqual({
      severity: "warning",
      kind: "typed",
      message: "Typed in, though it matches mean_deficit in results/wake.json",
      path: "results/wake.json",
    });
    expect(typedNumberProblem(number("was 0.48"), values).message).toBe(
      "Typed in, and no result in the project matches it",
    );
    expect(roundedLike(number("was 0.48"), 0.5030064751108918)).toBe("0.50");
    expect(roundedLike(number("of 1,234.5"), 12345.67)).toBe("12,345.7");
    expect(roundedLike(number("of 4.7e-1"), 0.4687)).toBe("4.7e-1");
  });
});
