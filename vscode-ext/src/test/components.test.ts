import assert from "node:assert/strict";
import { test } from "node:test";
import {
  componentsByLine,
  definitionLine,
  displayValue,
  hoverLines,
  isLatexDocument,
  lensTitle,
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
  assert.match(answer, /answer no longer matches its evidence/);
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
  assert.match(lensTitle([component()]) ?? "", /summarize/);
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
  // Nothing stale, but something nobody accounts for
  assert.match(
    lensTitle([
      component({ stage: null, script: null, provenance: "undeclared" }),
    ]) ?? "",
    /No provenance/,
  );
  // Nothing to say about a current component with no stage
  assert.equal(
    lensTitle([component({ stage: null, provenance: "project" })]),
    undefined,
  );
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
