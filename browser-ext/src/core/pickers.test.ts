import { describe, expect, test, vi } from "vitest";

import { listDir, pathScore, renderPathPicker } from "./pickers";

vi.mock("./messages", () => ({
  RequestFailed: class extends Error {},
  send: async () => ["scripts/fit.py", "scripts/plot.py", "run.py"],
}));

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

describe("renderPathPicker", () => {
  test("browses into a folder without closing", async () => {
    const { element, input } = renderPathPicker({ owner: "o", project: "p" });
    document.body.append(element);
    const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
    const picks = () =>
      [...element.querySelectorAll("button.pick")].map((b) => b.textContent);
    input.focus();
    await settle();
    expect(picks()).toEqual(["scripts/", "run.py"]);
    const folder = element.querySelector("button.pick") as HTMLButtonElement;
    // A click doesn't take focus from the input
    const down = new MouseEvent("mousedown", {
      bubbles: true,
      cancelable: true,
    });
    folder.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
    // and if something else gave the folder focus, opening it takes it back
    folder.focus();
    folder.click();
    await settle();
    expect(document.activeElement).toBe(input);
    expect(picks()).toEqual(["\u2190 scripts/", "fit.py", "plot.py"]);
    const list = element.querySelector(".picks") as HTMLElement;
    expect(list.style.display).toBe("");
    element.remove();
  });
});
