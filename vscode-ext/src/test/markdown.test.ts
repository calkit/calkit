import assert from "node:assert/strict";
import test from "node:test";
import * as fs from "node:fs";
import * as path from "node:path";

import {
  findMarkdownStageBlocks,
  findProjectDir,
  markdownStageNameForFile,
} from "../markdown/core";

test("findMarkdownStageBlocks finds annotated fences with their lines", () => {
  const text = [
    "# Title", // 0
    "", // 1
    "```python calkit stage name=analysis outputs=[fig.png]", // 2
    "import numpy", // 3
    "```", // 4
    "", // 5
    "```sh", // 6
    "uv sync", // 7
    "```", // 8
    "", // 9
    "```python calkit stage name=analysis", // 10
    "print(1)", // 11
    "```", // 12
  ].join("\n");
  assert.deepEqual(findMarkdownStageBlocks(text), [
    { name: "analysis", line: 2 },
    { name: "analysis", line: 10 },
  ]);
});

test("findMarkdownStageBlocks ignores blocks inside a longer fence", () => {
  // This is how a file documents the feature without the examples it shows
  // becoming stages, so they must not get a Run action either
  const text = [
    "````md",
    "```python calkit stage name=not-real",
    'print("documentation")',
    "```",
    "````",
  ].join("\n");
  assert.deepEqual(findMarkdownStageBlocks(text), []);
});

test("findMarkdownStageBlocks reads a directive comment above a block", () => {
  const text = [
    "<!-- calkit stage name=example environment=main", // 0
    "     inputs=[a.csv, b.csv] -->", // 1
    "", // 2
    "```python", // 3
    'print("hello")', // 4
    "```", // 5
  ].join("\n");
  // The lens belongs on the comment, which is where the declaration starts
  assert.deepEqual(findMarkdownStageBlocks(text), [
    { name: "example", line: 0 },
  ]);
});

test("findMarkdownStageBlocks ignores unannotated and non-stage blocks", () => {
  const text = [
    "```python",
    "print(1)",
    "```",
    "```text calkit output stage=analysis",
    "some output",
    "```",
    "<!-- an ordinary comment -->",
    "```python",
    "print(2)",
    "```",
  ].join("\n");
  assert.deepEqual(findMarkdownStageBlocks(text), []);
});

test("findMarkdownStageBlocks handles quoted names and tilde fences", () => {
  const text = [
    '~~~python calkit stage name="my stage" environment=main',
    "print(1)",
    "~~~",
  ].join("\n");
  assert.deepEqual(findMarkdownStageBlocks(text), [
    { name: "my stage", line: 0 },
  ]);
});

test("markdownStageNameForFile only matches declared markdown stages", () => {
  const config = {
    pipeline: {
      stages: {
        "README.md": { kind: "markdown" },
        docs: { kind: "markdown", path: "docs/guide.md" },
        other: { kind: "python-script", script_path: "x.py" },
      },
    },
  } as never;
  assert.equal(markdownStageNameForFile(config, "README.md"), "README.md");
  assert.equal(markdownStageNameForFile(config, "docs/guide.md"), "docs");
  // A Markdown file the pipeline doesn't source is not a stage, however
  // many annotations someone put in it
  assert.equal(markdownStageNameForFile(config, "NOTES.md"), undefined);
  assert.equal(markdownStageNameForFile(undefined, "README.md"), undefined);
});

test("findMarkdownStageBlocks matches the example project's stages", () => {
  const readme = path.join(
    __dirname,
    "..",
    "..",
    "..",
    "examples",
    "markdown",
    "README.md",
  );
  if (!fs.existsSync(readme)) {
    return;
  }
  const names = findMarkdownStageBlocks(fs.readFileSync(readme, "utf8")).map(
    (b) => b.name,
  );
  // The documentation section shows 'example' inside a longer fence, so it
  // must not appear here
  assert.deepEqual([...new Set(names)].sort(), [
    "analysis",
    "figure",
    "julia",
    "r",
  ]);
});

test("findProjectDir finds a project in a subfolder", () => {
  // A repo can hold self-contained projects in subdirectories without
  // declaring them as subprojects, as this repo's examples do
  const present = new Set([
    "/repo/examples/markdown/calkit.yaml",
    "/repo/calkit.yaml",
  ]);
  const exists = (p: string): boolean => present.has(p);
  assert.equal(
    findProjectDir(
      "/repo/examples/markdown/README.md",
      "/repo",
      exists,
      path.posix,
    ),
    "/repo/examples/markdown",
  );
  // A file with no project of its own falls back to the enclosing one
  assert.equal(
    findProjectDir("/repo/docs/notes.md", "/repo", exists, path.posix),
    "/repo",
  );
});

test("findProjectDir stops at the workspace root", () => {
  // Walking above the root would reach projects the user hasn't opened
  const exists = (p: string): boolean => p === "/outside/calkit.yaml";
  assert.equal(
    findProjectDir(
      "/outside/repo/docs/notes.md",
      "/outside/repo",
      exists,
      path.posix,
    ),
    undefined,
  );
});

test("findProjectDir returns undefined when there is no project", () => {
  assert.equal(
    findProjectDir("/repo/a/b.md", "/repo", () => false, path.posix),
    undefined,
  );
});
