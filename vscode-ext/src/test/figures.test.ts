import assert from "node:assert/strict";
import test from "node:test";
import * as path from "node:path";
import {
  extractLatexImageRefs,
  extractMarkdownImageRefs,
  resolveFigureRefStage,
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

test("extractLatexImageRefs finds includegraphics targets with their line numbers", () => {
  const text = [
    "\\begin{figure}",
    "\\includegraphics[width=0.8\\textwidth]{figures/wind-rose}",
    "\\includegraphics{../figures/farm-layout.pdf}",
    "no graphics here",
    "\\includegraphics*[scale=1]{a} text \\includegraphics{b.png}",
  ].join("\n");
  const refs = extractLatexImageRefs(text);
  assert.deepEqual(refs, [
    { line: 1, target: "figures/wind-rose" },
    { line: 2, target: "../figures/farm-layout.pdf" },
    { line: 4, target: "a" },
    { line: 4, target: "b.png" },
  ]);
});

test("resolveFigureRefStage matches outputs, trying graphics extensions when none", () => {
  const map = new Map<string, string>([
    ["figures/wind-rose.pdf", "plot-wind-rose"],
    ["figures/farm-layout.png", "plot-layout"],
    ["data/results.csv", "collect"],
  ]);
  // Exact path with extension matches directly.
  assert.equal(
    resolveFigureRefStage("figures/farm-layout.png", map),
    "plot-layout",
  );
  // Extension-less LaTeX target resolves via a graphics extension.
  assert.equal(
    resolveFigureRefStage("figures/wind-rose", map),
    "plot-wind-rose",
  );
  // Non-outputs and non-graphics matches return undefined.
  assert.equal(resolveFigureRefStage("figures/missing", map), undefined);
  assert.equal(resolveFigureRefStage("data/results", map), undefined);
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
