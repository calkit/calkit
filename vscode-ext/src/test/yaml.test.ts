import assert from "node:assert/strict";
import test from "node:test";
import YAML from "yaml";

import { formatYamlSyntaxError, yamlSyntaxError } from "../yaml";

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
