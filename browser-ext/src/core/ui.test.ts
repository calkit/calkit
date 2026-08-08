import { describe, expect, test } from "vitest";

import { el } from "./ui";

describe("el", () => {
  test("sets value on every element that carries one", () => {
    // An option that doesn't take its value falls back to its own text, so
    // a select reports the visible label instead of the value set here.
    // That silently broke the hub picker and every other select.
    const option = el("option", { value: "local", text: "Local (api.local)" });
    expect(option.value).toBe("local");
    expect(el("input", { value: "abc" }).value).toBe("abc");
    expect(el("textarea", { value: "note" }).value).toBe("note");
  });

  test("a select reports the selected option's value, not its label", () => {
    const select = el("select");
    select.append(
      el("option", { value: "production", text: "calkit.io" }),
      el("option", { value: "local", text: "Local development" }),
    );
    select.value = "local";
    expect(select.value).toBe("local");
    // Assigning a value no option carries leaves nothing selected, which is
    // how a dropped option value shows up
    select.value = "nonexistent";
    expect(select.value).toBe("");
  });

  test("applies the rest of the options it's given", () => {
    const clicks: string[] = [];
    const button = el("button", {
      class: "action",
      text: "Sync",
      title: "Sync now",
      onClick: () => clicks.push("clicked"),
      attrs: { "data-testid": "sync" },
    });
    expect(button.className).toBe("action");
    expect(button.textContent).toBe("Sync");
    expect(button.title).toBe("Sync now");
    expect(button.getAttribute("data-testid")).toBe("sync");
    button.click();
    expect(clicks).toEqual(["clicked"]);
    // A disabled button swallows the click, which is what keeps a panel from
    // firing a sync twice while one is already running
    const disabled = el("button", {
      text: "Sync",
      disabled: true,
      onClick: () => clicks.push("again"),
    });
    expect(disabled.disabled).toBe(true);
    disabled.click();
    expect(clicks).toEqual(["clicked"]);
  });

  test("opens links in a new tab without leaking the referrer", () => {
    const link = el("a", { text: "Project", href: "https://calkit.io/a/b" });
    expect(link.href).toBe("https://calkit.io/a/b");
    expect(link.target).toBe("_blank");
    expect(link.rel).toBe("noreferrer noopener");
  });

  test("skips absent children so conditional rendering reads cleanly", () => {
    const row = el("div", {}, [
      el("span", { text: "a" }),
      false,
      null,
      undefined,
      el("span", { text: "b" }),
    ]);
    expect(row.childElementCount).toBe(2);
  });
});
