import assert from "node:assert/strict";
import test from "node:test";
import YAML from "yaml";

import {
  formatYamlSyntaxError,
  pathLikeScalars,
  stageDefinitionLine,
  yamlSyntaxError,
} from "../yaml";

test("yamlSyntaxError describes parse failures and ignores other errors", () => {
  // A block sequence used as an implicit map key, as reported in issue #1567
  const raw = [
    "stages:",
    "  build:",
    "    cmd: echo hi",
    "- --export=ALL",
  ].join("\n");
  let caught: unknown;
  try {
    YAML.parse(raw);
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, "expected malformed YAML to throw");
  const described = yamlSyntaxError(caught);
  assert.ok(described);
  // The parser's " at line L, column C:" suffix and source snippet are
  // stripped, since the position is rendered separately
  assert.ok(!described.message.includes("at line"));
  assert.ok(!described.message.includes("\n"));
  assert.equal(typeof described.line, "number");
  assert.equal(typeof described.column, "number");
  // Non-parse errors are left for the caller to handle
  assert.equal(yamlSyntaxError(new Error("EACCES")), undefined);
  assert.equal(yamlSyntaxError(undefined), undefined);
  // Valid YAML doesn't throw at all
  assert.deepEqual(YAML.parse("a: 1"), { a: 1 });
});

test("formatYamlSyntaxError names the file and whatever position is known", () => {
  assert.equal(
    formatYamlSyntaxError("calkit.yaml", {
      message: "Bad indent",
      line: 368,
      column: 1,
    }),
    "calkit.yaml has a YAML syntax error at line 368, column 1: Bad indent",
  );
  assert.equal(
    formatYamlSyntaxError("dvc.yaml", { message: "Bad indent", line: 2 }),
    "dvc.yaml has a YAML syntax error at line 2: Bad indent",
  );
  assert.equal(
    formatYamlSyntaxError("dvc.yaml", { message: "Bad indent" }),
    "dvc.yaml has a YAML syntax error: Bad indent",
  );
});

const CALKIT_YAML = `owner: pete
name: test-1
questions:
  - question: What does plot do?
    answer: It plots. See the plot stage.
pipeline:
  stages:
    # plot is mentioned in this comment
    collect:
      kind: python-script
      script_path: scripts/collect.py
    plot:
      kind: python-script
      script_path: scripts/plot.py
      outputs:
        - figures/plot.png
    "build-paper":
      kind: latex
      target_path: paper/main.tex
environments:
  plot:
    kind: uv
`;

test("finds where a stage is defined, not where its name appears", () => {
  // 0-based, as the editor counts
  assert.equal(stageDefinitionLine(CALKIT_YAML, "collect"), 8);
  // Not the comment on line 7, nor the question that says "plot stage",
  // nor the environment of the same name further down
  assert.equal(stageDefinitionLine(CALKIT_YAML, "plot"), 11);
  // A quoted key is the same key
  assert.equal(stageDefinitionLine(CALKIT_YAML, "build-paper"), 16);
  assert.equal(stageDefinitionLine(CALKIT_YAML, "nope"), undefined);
});

test("a file with no pipeline has no stage to go to", () => {
  assert.equal(stageDefinitionLine("owner: pete\n", "plot"), undefined);
  // Malformed YAML is somebody else's error to report, not a crash here
  assert.equal(
    stageDefinitionLine("pipeline:\n  stages:\n   - [", "plot"),
    undefined,
  );
});

test("offers every value that could be a path, and no keys", () => {
  const text = [
    "owner: pete",
    "pipeline:",
    "  stages:",
    "    plot:",
    "      kind: python-script",
    "      script_path: scripts/plot.py",
    "      outputs:",
    "        - figures/plot.png",
    '        - "figures/quoted.png"',
    "figures:",
    "  - path: figures/plot.png",
    "    title: A plot of things",
    "    imported_from:",
    "      url: https://example.com/plot.png",
    "notes: |",
    "  A long note",
    "  over two lines",
  ].join("\n");
  const found = pathLikeScalars(text);
  const values = found.map((f) => f.value);
  // Values, including inside sequences, and the same path twice where it
  // is written twice
  assert.ok(values.includes("scripts/plot.py"));
  assert.deepEqual(
    values.filter((v) => v === "figures/plot.png"),
    ["figures/plot.png", "figures/plot.png"],
  );
  // A quoted value is offered without its quotes, and the span covers
  // exactly the text
  const quoted = found.find((f) => f.value === "figures/quoted.png");
  assert.ok(quoted);
  assert.equal(
    text.slice(quoted.offset, quoted.offset + quoted.length),
    "figures/quoted.png",
  );
  // Keys are field names, not paths
  assert.ok(!values.includes("script_path"));
  assert.ok(!values.includes("path"));
  assert.ok(!values.includes("stages"));
  // A URL is somebody else's to resolve, and a block scalar is prose
  assert.ok(!values.some((v) => v.startsWith("https://")));
  assert.ok(!values.some((v) => v.includes("over two lines")));
});

test("every span points at the text it says it does", () => {
  // The provider turns these into ranges, so an offset that is off by the
  // width of a quote underlines the wrong characters
  const text = "a: plain/path.py\nb: \"quoted/path.py\"\nc: 'single/path.py'\n";
  for (const found of pathLikeScalars(text)) {
    assert.equal(
      text.slice(found.offset, found.offset + found.length),
      found.value,
    );
  }
  assert.deepEqual(
    pathLikeScalars(text).map((f) => f.value),
    ["plain/path.py", "quoted/path.py", "single/path.py"],
  );
});
