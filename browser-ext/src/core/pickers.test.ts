import { describe, expect, test, vi } from "vitest";

import { listDir, pathScore, renderPathPicker } from "./pickers";

vi.mock("./messages", () => ({
  RequestFailed: class extends Error {},
  send: vi.fn(async () => [
    "drawings/setup.psd",
    "drawings/old/a.psd",
    "x.png",
  ]),
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
  test("stays open while browsing into folders, and picks a file", async () => {
    const { element, input } = renderPathPicker({ owner: "me", project: "p" });
    document.body.append(element);
    const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
    const picks = () =>
      [...element.querySelectorAll<HTMLButtonElement>("button.pick")].map(
        (b) => b.textContent,
      );
    const click = async (text: string) => {
      const button = [
        ...element.querySelectorAll<HTMLButtonElement>("button.pick"),
      ].find((b) => b.textContent === text)!;
      button.focus();
      button.click();
      await settle();
    };
    input.focus();
    await settle();
    // Hidden files and folders aren't offered
    expect(picks()).toEqual(["drawings/", "x.png"]);
    // A click doesn't take focus from the input
    const folder = element.querySelector<HTMLButtonElement>("button.pick")!;
    const down = new MouseEvent("mousedown", {
      bubbles: true,
      cancelable: true,
    });
    folder.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
    // and if something else gave the folder focus, opening it takes it back,
    // since the folder's button is gone after, and focus with it would
    // close the list
    await click("drawings/");
    const results = element.querySelector<HTMLElement>(".picks")!;
    expect(document.activeElement).toBe(input);
    expect(results.style.display).toBe("");
    expect(picks()).toEqual(["← drawings/", "old/", "setup.psd"]);
    await click("old/");
    expect(picks()).toEqual(["← drawings/old/", "a.psd"]);
    await click("a.psd");
    expect(input.value).toBe("drawings/old/a.psd");
    expect(results.style.display).toBe("none");
    element.remove();
  });
});
