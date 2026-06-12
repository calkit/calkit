import assert from "node:assert/strict";
import test from "node:test";
import * as path from "node:path";
import {
  extractMarkdownImageRefs,
  resolveImageRefToRepoRelative,
} from "../figures/core";

test("extractMarkdownImageRefs finds image targets with their line numbers", () => {
  const text = [
    "# Slide",
    "",
    "![](../figures/farm-layout.png){width=100%}",
    'Some text ![alt](../figures/wind-rose.png "Wind rose") more',
    "![remote](https://example.com/x.png)",
    "no images here",
  ].join("\n");
  const refs = extractMarkdownImageRefs(text);
  assert.deepEqual(refs, [
    { line: 2, target: "../figures/farm-layout.png" },
    { line: 3, target: "../figures/wind-rose.png" },
    { line: 4, target: "https://example.com/x.png" },
  ]);
  // Multiple images on one line are all captured.
  const two = extractMarkdownImageRefs("![](a.png) and ![](b.png)");
  assert.deepEqual(
    two.map((r) => r.target),
    ["a.png", "b.png"],
  );
  // Angle-bracket wrapped targets are unwrapped.
  assert.equal(extractMarkdownImageRefs("![](<a b.png>)")[0].target, "a b.png");
});

test("resolveImageRefToRepoRelative resolves relative to the document dir", () => {
  const root = path.join("/", "repo");
  const qmd = path.join(root, "slides", "slides.qmd");
  // A figure one level up resolves to a repo-relative POSIX path.
  assert.equal(
    resolveImageRefToRepoRelative(qmd, "../figures/wind-rose.png", root),
    "figures/wind-rose.png",
  );
  // Remote URLs and data URIs are ignored.
  assert.equal(
    resolveImageRefToRepoRelative(qmd, "https://example.com/x.png", root),
    undefined,
  );
  assert.equal(
    resolveImageRefToRepoRelative(qmd, "data:image/png;base64,AAAA", root),
    undefined,
  );
  // Paths escaping the workspace are rejected.
  assert.equal(
    resolveImageRefToRepoRelative(qmd, "../../outside.png", root),
    undefined,
  );
});
