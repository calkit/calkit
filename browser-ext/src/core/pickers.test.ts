import { describe, expect, test } from "vitest";

import { listDir, pathScore } from "./pickers";

describe("pathScore", () => {
  test("matches fragments in order, best in the file name", () => {
    expect(pathScore("fitpy", "scripts/fit.py")).not.toBeNull();
    expect(pathScore("pyfit", "scripts/fit.py")).toBeNull();
    expect(pathScore("", "anything")).toBe(0);
    // A run in the file name beats the same letters scattered in folders
    const name = pathScore("plot", "scripts/plot.py")!;
    const scattered = pathScore("plot", "pubs/longer/output/thing.py")!;
    expect(name).toBeGreaterThan(scattered);
    expect(pathScore("FIT", "scripts/fit.py")).toBe(
      pathScore("fit", "scripts/fit.py"),
    );
  });
});

describe("listDir", () => {
  test("lists what's directly in a folder", () => {
    const paths = ["a.py", "scripts/b.py", "scripts/sub/c.py", "data/d.csv"];
    expect(listDir(paths, "")).toEqual({
      dirs: ["data", "scripts"],
      files: ["a.py"],
    });
    expect(listDir(paths, "scripts")).toEqual({
      dirs: ["scripts/sub"],
      files: ["scripts/b.py"],
    });
    expect(listDir(paths, "nope")).toEqual({ dirs: [], files: [] });
  });
});
