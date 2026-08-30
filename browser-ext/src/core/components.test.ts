import { describe, expect, it } from "vitest";

import {
  componentBadge,
  componentLabel,
  componentProblem,
  componentsSummary,
  editUrl,
  sortComponents,
  valueText,
} from "./components";
import type { DocumentComponent } from "./types";

function component(
  overrides: Partial<DocumentComponent> = {},
): DocumentComponent {
  return {
    kind: "value",
    path: "results/findings.json",
    key: "ratio",
    pages: [1, 3],
    stage: "summarize",
    script: "scripts/summarize.py",
    provenance: "pipeline",
    build_value: 5.1014,
    current_value: 5.1014,
    status: "ok",
    stale_reasons: [],
    ...overrides,
  };
}

describe("sortComponents", () => {
  it("puts what needs doing first, then groups a file's values", () => {
    const sorted = sortComponents([
      component({ path: "results/b.json", key: "z", status: "ok" }),
      component({ path: "figures/plot.pdf", key: null, status: "unknown" }),
      component({ path: "results/a.json", key: "b", status: "stale" }),
      component({ path: "figures/gone.pdf", key: null, status: "missing" }),
      component({ path: "results/a.json", key: "a", status: "stale" }),
    ]);
    expect(sorted.map((i) => `${i.path}:${i.key ?? ""}`)).toEqual([
      "figures/gone.pdf:",
      "results/a.json:a",
      "results/a.json:b",
      "figures/plot.pdf:",
      "results/b.json:z",
    ]);
    // The caller's array is left alone
    const input = [component({ status: "ok" }), component({ status: "stale" })];
    sortComponents(input);
    expect(input.map((i) => i.status)).toEqual(["ok", "stale"]);
  });
});

describe("componentProblem", () => {
  it("says what is wrong in terms someone writing a paper can act on", () => {
    expect(
      componentProblem(
        component({ status: "stale", stale_reasons: ["stage-out-of-date"] }),
      ),
    ).toBe("its stage needs a rerun");
    // Both can hold at once, and they are fixed differently
    expect(
      componentProblem(
        component({
          status: "stale",
          stale_reasons: ["stage-out-of-date", "changed-since-build"],
        }),
      ),
    ).toBe(
      "its stage needs a rerun, and the project has moved on since this was built",
    );
    // Missing outranks anything else that might be said
    expect(
      componentProblem(
        component({ status: "missing", stale_reasons: ["answer-stale"] }),
      ),
    ).toBe("the project no longer has this file");
    // Nothing produces it and nobody claims it, which no rerun fixes
    expect(
      componentProblem(
        component({
          status: "unknown",
          stage: null,
          script: null,
          provenance: "undeclared",
        }),
      ),
    ).toBe("nothing produces this and nobody has said where it came from");
    // A component that is fine has nothing to report
    expect(componentProblem(component())).toBe("");
    expect(componentProblem(component({ stale_reasons: undefined }))).toBe("");
  });
});

describe("componentBadge", () => {
  it("shouts only about what needs attention", () => {
    expect(componentBadge(component({ status: "missing" }))).toEqual({
      text: "missing",
      level: "danger",
    });
    expect(componentBadge(component({ status: "stale" }))).toEqual({
      text: "out of date",
      level: "warn",
    });
    expect(
      componentBadge(
        component({ status: "unknown", provenance: "undeclared" }),
      ),
    ).toEqual({ text: "no provenance", level: "warn" });
    // Unchecked is not a clean bill of health, but it isn't a problem
    expect(componentBadge(component({ status: "unknown" }))).toEqual({
      text: "unchecked",
      level: "dim",
    });
    expect(componentBadge(component())).toBeNull();
  });
});

describe("componentsSummary", () => {
  it("counts what needs attention, and stays quiet otherwise", () => {
    expect(
      componentsSummary([
        component({ status: "stale" }),
        component({ status: "missing", key: "b" }),
        component({ status: "unknown", provenance: "undeclared", key: "c" }),
        component({ key: "d" }),
      ]),
    ).toBe("2 out of date, 1 with no provenance");
    expect(componentsSummary([component({ status: "stale" })])).toBe(
      "1 out of date",
    );
    // A missing file is counted once, not again for having no provenance
    expect(
      componentsSummary([
        component({ status: "missing", provenance: "undeclared" }),
      ]),
    ).toBe("1 out of date");
    expect(componentsSummary([component()])).toBe("");
    expect(componentsSummary([])).toBe("");
  });
});

describe("editUrl", () => {
  it("goes to what someone would change, not to what they can see", () => {
    // Overleaf can't run the pipeline, so the useful destination is the
    // script that makes the number, not the number
    expect(editUrl("https://calkit.io", "me", "proj", component())).toBe(
      "https://calkit.io/me/proj/files?path=scripts%2Fsummarize.py",
    );
    // A stage with no script still has a stage to open
    expect(
      editUrl("https://calkit.io", "me", "proj", component({ script: null })),
    ).toBe("https://calkit.io/me/proj/pipeline?stage=summarize");
    // Nothing makes it, so the file itself is all there is to go to
    expect(
      editUrl(
        "https://calkit.io",
        "me",
        "proj",
        component({ path: "img/a b.png", stage: null, script: null }),
      ),
    ).toBe("https://calkit.io/me/proj/files?path=img%2Fa%20b.png");
  });
});

describe("componentLabel and valueText", () => {
  it("names a component and renders whatever a results file holds", () => {
    expect(componentLabel(component())).toBe("results/findings.json: ratio");
    expect(componentLabel(component({ key: null }))).toBe(
      "results/findings.json",
    );
    expect(valueText(5.1014)).toBe("5.1014");
    expect(valueText(0)).toBe("0");
    expect(valueText(false)).toBe("false");
    expect(valueText({ a: 1 })).toBe('{"a":1}');
    // Nothing to show, rather than the word "null"
    expect(valueText(null)).toBe("");
    expect(valueText(undefined)).toBe("");
  });
});
