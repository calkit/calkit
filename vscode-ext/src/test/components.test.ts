import assert from "node:assert/strict";
import { test } from "node:test";
import {
  componentDiagnostics,
  componentsByLine,
  diagnosticSpan,
  figureComponent,
  definitionLine,
  displayValue,
  hoverLines,
  isLatexDocument,
  lensStages,
  lensTitle,
  objectLensTarget,
  objectLensTitle,
  questionDiagnostics,
  questionLines,
  stageLensTitle,
  withCheckedStatus,
} from "../components/core";
import type { Component } from "../components/core";

function component(overrides: Partial<Component> = {}): Component {
  return {
    kind: "value",
    path: "results/findings.json",
    key: "ratio",
    pages: [],
    stage: "summarize",
    stage_inputs: ["data.csv"],
    script: "scripts/summarize.py",
    provenance: "pipeline",
    document_value: "5.1",
    build_value: 5.1014,
    current_value: 5.1014,
    build_hash: null,
    current_hash: null,
    status: "ok",
    stale_reasons: [],
    locations: [],
    ...overrides,
  };
}

test("recognizes LaTeX documents", () => {
  assert.equal(isLatexDocument("/p/main.tex"), true);
  assert.equal(isLatexDocument("/p/MAIN.TeX"), true);
  assert.equal(isLatexDocument("/p/notes.md", "latex"), true);
  assert.equal(isLatexDocument("/p/notes.md"), false);
});

test("folds the pipeline's verdict into a positional lookup", () => {
  // Hovering skips the pipeline check to stay responsive, so a stale stage
  // has to come from the cached whole-document listing
  const found = [component()];
  const cached = [
    component({ status: "stale", stale_reasons: ["stage-out-of-date"] }),
  ];
  const merged = withCheckedStatus(found, cached);
  assert.equal(merged[0].status, "stale");
  assert.deepEqual(merged[0].stale_reasons, ["stage-out-of-date"]);
  // Whatever the position already found is kept, not replaced
  const drifted = [
    component({ status: "stale", stale_reasons: ["changed-since-build"] }),
  ];
  assert.deepEqual(withCheckedStatus(drifted, cached)[0].stale_reasons, [
    "stage-out-of-date",
    "changed-since-build",
  ]);
  // A missing file stays missing; a stale stage doesn't bring it back
  const gone = [component({ status: "missing" })];
  assert.equal(withCheckedStatus(gone, cached)[0].status, "missing");
  // Nothing cached yet means nothing to add
  assert.deepEqual(withCheckedStatus(found, undefined), found);
  // A component the listing doesn't have is left alone
  assert.equal(
    withCheckedStatus(found, [component({ key: "other" })])[0].status,
    "ok",
  );
  // A position that could not check reads as checked once the listing has,
  // rather than staying unknown next to a listing that says it is fine
  assert.equal(
    withCheckedStatus([component({ status: "unknown" })], [component()])[0]
      .status,
    "ok",
  );
});

test("shows the document's own typesetting for a value", () => {
  // What is on the page beats the raw value, since that is what someone is
  // looking at when they hover
  assert.equal(displayValue(component()), "5.1");
  assert.equal(
    displayValue(component({ document_value: null, current_value: 7.9 })),
    "7.9",
  );
  assert.equal(
    displayValue(component({ document_value: null, current_value: null })),
    undefined,
  );
  assert.equal(
    displayValue(component({ document_value: null, current_value: { a: 1 } })),
    '{"a":1}',
  );
});

test("hover says where a value came from", () => {
  const lines = hoverLines(component()).join("\n");
  assert.match(lines, /\*\*5\.1\*\*/);
  assert.match(lines, /results\/findings\.json.*ratio/);
  assert.match(lines, /Stage `summarize`.*scripts\/summarize\.py/);
  assert.doesNotMatch(lines, /Out of date/);
});

test("hover explains each way of being out of date", () => {
  const drifted = hoverLines(
    component({
      status: "stale",
      stale_reasons: ["changed-since-build"],
      build_value: 5.1014,
      current_value: 7.9,
    }),
  ).join("\n");
  assert.match(drifted, /Out of date.*moved on since this was built/);
  // The pair is only worth showing when the two actually differ
  assert.match(drifted, /Built with `5\.1014`, now `7\.9`/);
  const both = hoverLines(
    component({
      status: "stale",
      stale_reasons: ["stage-out-of-date", "changed-since-build"],
      current_value: 7.9,
    }),
  ).join("\n");
  assert.match(both, /needs a rerun, and the project has moved on/);
  const answer = hoverLines(
    component({
      kind: "block",
      path: "calkit.yaml",
      key: "2",
      document_value: null,
      status: "stale",
      stale_reasons: ["answer-stale"],
    }),
  ).join("\n");
  assert.match(answer, /\*\*Question 2\*\*/);
  assert.match(answer, /evidence changed after the answer was written/);
  const gone = hoverLines(component({ status: "missing" })).join("\n");
  assert.match(gone, /Missing/);
  assert.doesNotMatch(gone, /Out of date/);
});

test("hover flags a component nothing accounts for", () => {
  const undeclared = hoverLines(
    component({
      kind: "figure",
      path: "figures/schematic.png",
      key: null,
      stage: null,
      script: null,
      provenance: "undeclared",
      document_value: null,
      current_value: null,
    }),
  ).join("\n");
  assert.match(undeclared, /No provenance/);
  assert.match(undeclared, /calkit\.yaml/);
  // A file the pipeline makes needs no such note
  assert.doesNotMatch(hoverLines(component()).join("\n"), /provenance/i);
});

test("hover names the pages a value lands on", () => {
  assert.match(hoverLines(component({ pages: [3] })).join("\n"), /Page 3\b/);
  assert.match(
    hoverLines(component({ pages: [3, 7] })).join("\n"),
    /Pages 3, 7/,
  );
});

test("a lens says what needs doing, most urgent first", () => {
  assert.equal(lensTitle([]), undefined);
  // A line that is fine needs no lens saying so; naming its stage is the
  // other lens's job
  assert.equal(lensTitle([component()]), undefined);
  assert.match(
    lensTitle([
      component({ status: "stale", stale_reasons: ["stage-out-of-date"] }),
    ]) ?? "",
    /Rerun summarize/,
  );
  assert.match(
    lensTitle([
      component({ status: "stale", stale_reasons: ["changed-since-build"] }),
    ]) ?? "",
    /Changed since this was built/,
  );
  // A missing file outranks everything else on the line
  assert.match(
    lensTitle([
      component({ status: "stale", stale_reasons: ["stage-out-of-date"] }),
      component({ status: "missing", key: "other" }),
    ]) ?? "",
    /Missing/,
  );
  // Nothing stale, so nothing for this lens to say; a file nobody
  // accounts for is the artifact lens's business, since that is the one
  // that can go where it is fixed
  assert.equal(
    lensTitle([
      component({ stage: null, script: null, provenance: "undeclared" }),
    ]),
    undefined,
  );
  // Nothing to say about a current component with no stage
  assert.equal(
    lensTitle([component({ stage: null, provenance: "project" })]),
    undefined,
  );
});

test("a lens offers the stage behind the line, wherever it stands", () => {
  // The sidebar is where the script, the inputs and the outputs are, so
  // the way in is worth a lens whether or not anything is wrong
  assert.match(stageLensTitle([component()]) ?? "", /summarize/);
  assert.match(
    stageLensTitle([
      component({ status: "stale", stale_reasons: ["stage-out-of-date"] }),
    ]) ?? "",
    /summarize/,
  );
  // Two components from two stages name both, and the lens opens the first
  assert.match(
    stageLensTitle([component(), component({ stage: "plot", key: "b" })]) ?? "",
    /summarize, plot/,
  );
  assert.deepEqual(
    lensStages([component(), component({ stage: "plot", key: "b" })]),
    ["summarize", "plot"],
  );
  // Nothing to open for something no stage produces
  assert.equal(
    stageLensTitle([component({ stage: null, provenance: "undeclared" })]),
    undefined,
  );
  assert.deepEqual(lensStages([component({ stage: null })]), []);
});

test("groups components by the line they are written on", () => {
  const ratio = component({
    locations: [
      { source: "paper/main.tex", line: 6, column: 14 },
      { source: "paper/main.tex", line: 11, column: 1 },
    ],
  });
  const name = component({
    key: "name",
    locations: [
      { source: "paper/main.tex", line: 6, column: 39 },
      { source: "paper/sections/intro.tex", line: 2, column: 1 },
    ],
  });
  const byLine = componentsByLine([ratio, name], "paper/main.tex");
  // Lines come back 0-based, as the editor counts them
  assert.deepEqual(
    [...byLine.keys()].sort((a, b) => a - b),
    [5, 10],
  );
  assert.equal(byLine.get(5)?.length, 2);
  assert.deepEqual(byLine.get(10), [ratio]);
  // Another file's occurrences belong to that file's lenses, not this one's
  assert.deepEqual(
    [...componentsByLine([ratio, name], "paper/sections/intro.tex").keys()],
    [1],
  );
  // A component the source no longer names has nowhere to put a lens
  assert.equal(componentsByLine([component()], "paper/main.tex").size, 0);
});

test("finds the line a results key is on", () => {
  const json = '{\n  "alpha": 1,\n  "n_top": 8,\n  "beta": 2\n}\n';
  assert.equal(definitionLine(json, "n_top"), 2);
  const yaml = "alpha: 1\nnested:\n  n_top: 8\n";
  assert.equal(definitionLine(yaml, "nested.n_top"), 2);
  // A list index names no key, so the nearest named parent is used
  assert.equal(definitionLine(yaml, "nested.0"), 1);
  // A key that isn't there, and a component that has no key at all
  assert.equal(definitionLine(json, "missing"), undefined);
  assert.equal(definitionLine(json, null), undefined);
  // A key that exists literally wins, so one containing dots keeps working
  assert.equal(definitionLine('{\n  "a.b": 1\n}\n', "a.b"), 1);
  assert.equal(definitionLine('{\n  "a": {},\n  "b": 1\n}\n', "a.b"), 2);
  // A key that would otherwise be a regex is matched literally
  assert.equal(definitionLine('{\n  "a+b": 1\n}\n', "a+b"), 1);
  assert.equal(definitionLine('{\n  "axb": 1\n}\n', "a+b"), undefined);
});

test("a figure reference becomes a component the same lens can render", () => {
  // Quarto and Markdown have no provenance record, so a figure is resolved
  // by asking which stage produces the path. The lens is the same one; it
  // just has less to say.
  const made = figureComponent("figures/plot.png", "plot", "notes.qmd", 4);
  assert.equal(made.kind, "figure");
  assert.equal(made.stage, "plot");
  assert.equal(made.provenance, "pipeline");
  assert.deepEqual(made.locations, [
    { source: "notes.qmd", line: 4, column: 1 },
  ]);
  // Everything a record would add is genuinely unknown here, and says so
  // rather than reading as current
  assert.equal(made.status, "unknown");
  assert.deepEqual(made.pages, []);
  // Nothing wrong with it, so the way into the sidebar is the lens it gets
  assert.equal(lensTitle([made]), undefined);
  assert.match(stageLensTitle([made]) ?? "", /plot/);
  // A figure no stage produces is the same gap it is in a LaTeX document
  const orphan = figureComponent("img/hand.png", undefined, "notes.qmd", 9);
  assert.equal(orphan.provenance, "undeclared");
  assert.equal(orphan.stage, null);
  assert.match(objectLensTitle([orphan]) ?? "", /No provenance/);
  assert.deepEqual(objectLensTarget([orphan]), { path: "img/hand.png" });
  // And it lands on the line it was written on, 0-based for the editor
  assert.deepEqual([...componentsByLine([orphan], "notes.qmd").keys()], [8]);
});

test("reports only what is actually wrong, at the place that says it", () => {
  const diagnostics = componentDiagnostics(
    [
      component({
        status: "stale",
        stale_reasons: ["changed-since-build"],
        build_value: 5.1,
        current_value: 5.4,
        locations: [{ source: "paper/main.tex", line: 12, column: 5 }],
      }),
      component({
        kind: "figure",
        path: "figures/gone.png",
        key: null,
        status: "missing",
        locations: [{ source: "paper/main.tex", line: 20, column: 1 }],
      }),
      // Current and accounted for, so there is nothing to say about it
      component({
        locations: [{ source: "paper/main.tex", line: 30, column: 1 }],
      }),
    ],
    "paper/main.tex",
  );
  assert.equal(diagnostics.length, 2);
  assert.equal(diagnostics[0].line, 11);
  assert.equal(diagnostics[0].column, 4);
  assert.equal(diagnostics[0].severity, "warning");
  assert.match(diagnostics[0].message, /results\/findings\.json:ratio/);
  assert.match(diagnostics[0].message, /moved on since this was built/);
  // The pair is what makes a drift warning worth reading
  assert.match(diagnostics[0].message, /Built with 5\.1, now 5\.4/);
  assert.equal(diagnostics[1].severity, "error");
  assert.match(diagnostics[1].message, /no longer produced/);
});

test("a component nothing accounts for is worth attention", () => {
  // Nothing produced it, nobody imported it and nobody claims it, and no
  // rerun will change that: it needs a line in calkit.yaml, which nothing
  // but a person is going to write
  const [diagnostic] = componentDiagnostics(
    [
      component({
        kind: "figure",
        path: "paper/schematic.png",
        key: null,
        provenance: "undeclared",
        stage: null,
        locations: [{ source: "paper/main.tex", line: 4, column: 1 }],
      }),
    ],
    "paper/main.tex",
  );
  assert.equal(diagnostic.severity, "warning");
  assert.match(diagnostic.message, /needs an entry in calkit\.yaml/);
});

test("keeps to the source asked about, and repeats per place", () => {
  const diagnostics = componentDiagnostics(
    [
      component({
        status: "missing",
        locations: [
          { source: "paper/main.tex", line: 3, column: 1 },
          { source: "paper/main.tex", line: 9, column: 1 },
          { source: "paper/appendix.tex", line: 2, column: 1 },
        ],
      }),
    ],
    "paper/main.tex",
  );
  assert.deepEqual(
    diagnostics.map((d) => d.line),
    [2, 8],
  );
});

test("underlines the macro rather than the prose around it", () => {
  const line = "The error falls by \\result[Improvement]x, which is good.";
  assert.equal(
    diagnosticSpan(line, line.indexOf("\\result")),
    "\\result[Improvement]".length,
  );
  assert.equal(
    diagnosticSpan("\\ckfigure{../figures/a.pdf}", 0),
    "\\ckfigure{../figures/a.pdf}".length,
  );
  // Nothing macro-shaped: the rest of the line beats an invisible caret
  assert.equal(diagnosticSpan("plain text here   ", 6), "text here".length);
});

const CALKIT_YAML = `owner: pete
questions:
  - question: >-
      Do the top structures use the rectifier, and does that hold across
      the whole range rather than at one point?
    answer: "{n_top} of eight do."
    evidence:
      - kind: value
        path: results/findings.json
  - question: Does the closure cut error?
    answer: It does.
environments:
  py:
    kind: uv
`;

test("finds each question's line however its prose is folded", () => {
  // calkit.yaml is written at 80 columns, so matching on the question text
  // would miss exactly the questions long enough to be worth asking
  assert.deepEqual(questionLines(CALKIT_YAML), [2, 9]);
});

test("no questions block means nothing to place", () => {
  assert.deepEqual(questionLines("owner: pete\nname: p\n"), []);
});

test("places what the questions check found in calkit.yaml", () => {
  const diagnostics = questionDiagnostics(
    {
      questions: [
        {
          index: 1,
          question: "Do the top structures use the rectifier?",
          answered: true,
          status: "error",
          message: "placeholder {n_top} names no evidence",
        },
        {
          index: 2,
          question: "Does the closure cut error?",
          answered: true,
          status: "stale",
          message: null,
        },
      ],
    },
    CALKIT_YAML,
  );
  assert.deepEqual(diagnostics, [
    {
      line: 2,
      severity: "error",
      message: "placeholder {n_top} names no evidence",
    },
    {
      line: 9,
      severity: "warning",
      message:
        "The evidence has changed since this answer was last edited. Read " +
        "it again and edit the question, even if the answer still holds.",
    },
  ]);
});

test("an unanswered question is work outstanding, not a fault", () => {
  assert.deepEqual(
    questionDiagnostics(
      {
        questions: [
          {
            index: 1,
            question: "Open question",
            answered: false,
            status: "unanswered",
          },
          { index: 2, question: "Fine", answered: true, status: "ok" },
        ],
      },
      CALKIT_YAML,
    ),
    [],
  );
});

test("every kind of thing a document uses opens in the sidebar", () => {
  // The stage lens says how a thing is made, which has no answer for a
  // figure somebody drew or a question somebody wrote. This one says what
  // it is, and every kind of component has that.
  const undeclared = component({
    kind: "figure",
    path: "paper/schematic.png",
    key: null,
    stage: null,
    script: null,
    provenance: "undeclared",
  });
  assert.match(objectLensTitle([undeclared]) ?? "", /No provenance/);
  assert.deepEqual(objectLensTarget([undeclared]), {
    path: "paper/schematic.png",
  });
  // Accounted for, so named rather than flagged
  const imported = component({
    kind: "figure",
    path: "paper/logo.png",
    key: null,
    stage: null,
    provenance: "imported",
  });
  assert.equal(objectLensTitle([imported]), "$(file-media) logo.png");
  // A figure a stage makes still gets one; the stage lens answers a
  // different question and both are worth having
  assert.equal(
    objectLensTitle([
      component({ kind: "figure", path: "f/p.png", key: null }),
    ]),
    "$(file-media) p.png",
  );
  // A value is named by its key, which is what the document wrote
  assert.equal(objectLensTitle([component()]), "$(symbol-numeric) ratio");
  assert.deepEqual(objectLensTarget([component()]), {
    path: "results/findings.json",
  });
  // A question block opens the question itself, by its number
  const block = component({ kind: "block", path: "calkit.yaml", key: "2" });
  assert.equal(objectLensTitle([block]), "$(question) Question 2");
  assert.deepEqual(objectLensTarget([block]), { question: "2" });
  // Nothing on the line, nothing to open
  assert.equal(objectLensTitle([]), undefined);
  assert.equal(objectLensTarget([]), undefined);
});
