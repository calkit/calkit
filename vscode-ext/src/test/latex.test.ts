import assert from "node:assert/strict";
import test from "node:test";
import {
  findInSource,
  findText,
  latexStagePdf,
  latexStageSource,
  latexWorkingDiffPath,
  lineMap,
  normalizeSelection,
  paragraphLines,
  parseSynctex,
  pipelineLatexDiffs,
  synctexForward,
  synctexInputFile,
  synctexReverse,
  synctexTag,
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

test("SyncTeX maps between source lines and places on the page", () => {
  // Trimmed from a real build in a container, where the project is at /work
  const s = parseSynctex(
    [
      "SyncTeX Version:1",
      "Input:1:/work/paper/./main.tex",
      "Input:2:/usr/share/texmf/tex/latex/base/article.cls",
      "Input:10:/work/paper/./intro.tex",
      "Output:pdf",
      "Magnification:1000",
      "Unit:1",
      "X Offset:0",
      "Y Offset:0",
      "Content:",
      "!1181",
      "{1",
      "[1,17:4736286,46220574:26673152,41484288,0",
      "(1,6:8799518,10300473:22609920,455111,127431",
      "x10,1:10092037,10300473",
      "x10,2:26806203,10300473",
      ")",
      "(1,13:8799518,11873337:22609920,455111,127431",
      "h1,10:8799518,11873337:983040,0,0",
      "x1,10:10911235,11873337",
      "x1,11:15398185,11873337",
      "k1,11:20000000,11873337:260097",
      ")",
      "]",
      "}1",
      "{2",
      "(1,13:8799518,5000000:22609920,455111,127431",
      "x1,12:9000000,5000000",
      ")",
      "}2",
    ].join("\n"),
  );
  const main = synctexTag(s, "paper/main.tex");
  const intro = synctexTag(s, "paper/intro.tex");
  assert.deepEqual([main, intro], [1, 10]);
  assert.equal(synctexTag(s, "main.tex"), 1);
  assert.equal(synctexTag(s, "paper/other.tex"), undefined);
  // Forward, a line goes to the line of text it's on, in PDF points
  const rect = synctexForward(s, 1, 10)!;
  assert.equal(rect.page, 1);
  assert.ok(Math.abs(rect.x - 133.768) < 0.01);
  assert.ok(Math.abs(rect.y + rect.height - (180.5 + 1.94)) < 0.1);
  assert.ok(Math.abs(rect.width - 343.711) < 0.01);
  // A line with nothing on the page, e.g., a comment, goes to the next one,
  // and a paragraph's end can be on a later page
  assert.deepEqual(synctexForward(s, 1, 8), rect);
  assert.equal(synctexForward(s, 1, 12, true)!.page, 2);
  assert.equal(synctexForward(s, 99, 1), undefined);
  // Back, a point goes to the closest thing left of it on its line
  const y = rect.y + rect.height / 2;
  assert.deepEqual(synctexReverse(s, 1, 200, y), {
    input: "/work/paper/./main.tex",
    line: 10,
  });
  assert.equal(synctexReverse(s, 1, 300, y)!.line, 11);
  assert.deepEqual(synctexReverse(s, 1, 420, 158), {
    input: "/work/paper/./intro.tex",
    line: 2,
  });
  // Between lines, the nearest one
  assert.equal(synctexReverse(s, 1, 200, rect.y + 30)!.line, 10);
  assert.equal(synctexReverse(s, 3, 200, 100), undefined);
  // Inputs map back to the project by the longest path that exists
  const files = new Set(["paper/intro.tex", "intro.tex"]);
  assert.equal(
    synctexInputFile("/work/paper/./intro.tex", (f) => files.has(f)),
    "paper/intro.tex",
  );
  assert.equal(
    synctexInputFile("C:\\work\\paper\\intro.tex", (f) => files.has(f)),
    "paper/intro.tex",
  );
  assert.equal(
    synctexInputFile("/x/y.tex", (f) => files.has(f)),
    undefined,
  );
});

test("paragraphLines finds where a line's paragraph starts and ends", () => {
  const lines = [
    "\\section{Intro}",
    "First line",
    "second line",
    "",
    "% COMMENT",
    "%   A:",
    "%     Hi.",
    "Third",
    "fourth % inline",
    "\\begin{equation}",
  ];
  // A heading starts a paragraph that runs to the next blank line, as in
  // the CLI
  assert.deepEqual(paragraphLines(lines, 3), { start: 1, end: 3 });
  assert.deepEqual(paragraphLines(lines, 9), { start: 8, end: 9 });
  assert.deepEqual(paragraphLines(lines, 1), { start: 1, end: 3 });
});

test("findText finds text across a PDF's items, breaks, and ligatures", () => {
  const items = [
    { str: "The model \ufb01ts the data reason-" },
    { str: "" },
    { str: "ably well, and the model" },
    { str: " \u201cfits\u201d too." },
  ];
  assert.deepEqual(findText(items, "fits the data"), [
    { start: { item: 0, offset: 10 }, end: { item: 0, offset: 22 } },
  ]);
  // A hyphenated line break and the spaces around items don't matter
  assert.deepEqual(findText(items, "reasonably well"), [
    { start: { item: 0, offset: 23 }, end: { item: 2, offset: 9 } },
  ]);
  // Every occurrence, in order
  assert.deepEqual(
    findText(items, "the model").map((r) => r.start.item),
    [2],
  );
  assert.equal(findText(items, "model").length, 2);
  assert.equal(findText(items, '"fits" too').length, 1);
  assert.deepEqual(findText(items, "  "), []);
  assert.deepEqual(findText(items, "absent"), []);
  // Typeset math reads as the source writes it: a minus sign as a hyphen,
  // and an increment as a capital delta
  const math = [{ str: "\u2206u = \u2212\u03b1mc2 (1)" }];
  assert.equal(findText(math, "\u0394u = -\u03b1mc2").length, 1);
});

test("lineMap follows lines across comments added and removed", () => {
  const built = ["a", "", "b", "c", "", "d", "e"];
  const now = ["a", "", "% COMMENT", "%   X:", "%     Hi.", "b", "c", "", "e"];
  const { toAfter, toBefore } = lineMap(built, now);
  assert.deepEqual([1, 2, 3, 4, 5, 6, 7].map(toAfter), [1, 2, 6, 7, 8, 9, 9]);
  // A line in the new comment goes to the paragraph below it
  assert.deepEqual(
    [1, 3, 4, 5, 6, 7, 8, 9].map(toBefore),
    [1, 3, 3, 3, 3, 4, 5, 7],
  );
  const same = lineMap(built, built);
  assert.equal(same.toAfter(4), 4);
  assert.equal(same.toBefore(7), 7);
  assert.equal(lineMap([], ["x"]).toBefore(1), 0);
});

test("functions injected into the webview are self-contained", () => {
  // The webview has no CommonJS `exports` for them to refer to
  for (const fn of [findText, normalizeSelection]) {
    assert.ok(!fn.toString().includes("exports"));
  }
  assert.equal(
    normalizeSelection("the wake re-\ncovers ﬁne\n quickly"),
    "the wake recovers fine quickly",
  );
});

test("findInSource finds selected PDF text near a source line", () => {
  const lines = [
    "The model in Eq.~\\eqref{eq:wake} fits the data",
    "reasonably well, and the wake recovers by",
    "$x/D=3$ in all cases.",
  ];
  // Exactly, on the line or one near it
  assert.deepEqual(findInSource(lines, 2, "the wake recovers"), {
    line: 2,
    start: 21,
    end: 38,
  });
  assert.deepEqual(findInSource(lines, 3, "fits the data"), {
    line: 1,
    start: 33,
    end: 46,
  });
  // Across a macro or a line break, as many of its first words as match
  assert.equal(findInSource(lines, 1, "fits the data reasonably")!.end, 46);
  assert.equal(findInSource(lines, 1, "The model in Eq. (1)")!.start, 0);
  assert.equal(findInSource(lines, 1, "absent words"), undefined);
  assert.equal(findInSource(lines, 1, "in"), undefined);
});
