import assert from "node:assert/strict";
import test, { after } from "node:test";

// Create minimal vscode stub
const vscodeStub = {
  TreeItem: class TreeItem {
    label: string;
    collapsibleState: number;
    description?: string;
    iconPath?: any;
    command?: any;
    tooltip?: string;
    constructor(label: string, collapsibleState: number) {
      this.label = label;
      this.collapsibleState = collapsibleState;
    }
  },
  EventEmitter: class EventEmitter {
    event = {};
    fire() {}
  },
  ThemeIcon: class ThemeIcon {
    constructor(
      public readonly id: string,
      public readonly color?: any,
    ) {}
  },
  ThemeColor: class ThemeColor {
    constructor(public readonly id: string) {}
  },
  TreeItemCollapsibleState: {
    None: 0,
    Collapsed: 1,
    Expanded: 2,
  },
  Uri: {
    file: (f: string) => ({ fsPath: f, scheme: "file", path: f }),
  },
};

// Inject it into require cache before importing sidebar.ts
import * as Module from "node:module";
const originalRequire = (Module as any).prototype.require;
(Module as any).prototype.require = function (id: string) {
  if (id === "vscode") {
    return vscodeStub;
  }
  return originalRequire.apply(this, arguments);
};

// Restore the real require so the patch does not leak into other test files.
after(() => {
  (Module as any).prototype.require = originalRequire;
});

// Loaded via runtime require (not a static import) so it resolves AFTER the
// require patch above, regardless of TS import-hoisting.
const { CalkitSidebarProvider, SidebarItem } =
  require("../sidebar") as typeof import("../sidebar");

test("sidebar provider does not throw on object-form inputs in getStageProps", () => {
  const provider = new CalkitSidebarProvider();

  provider.refresh(
    "/workspace",
    {
      pipeline: {
        stages: {
          teststage: {
            kind: "command",
            inputs: ["plain.txt", { path: "data/raw.csv" } as any],
          },
        },
      },
    },
    undefined,
    new Set(),
  );

  // We can synthesize a stage item and pass it to getChildren.
  const stageItem = new SidebarItem(
    "teststage",
    vscodeStub.TreeItemCollapsibleState.None,
    "stage",
    "teststage",
  );
  const children = provider.getChildren(stageItem);

  assert.ok(Array.isArray(children));

  // Verify that an Input row for 'data/raw.csv' exists
  const hasRawCsv = children.some((c) => c.description === "data/raw.csv");
  assert.ok(hasRawCsv, "Should find input row with description data/raw.csv");
});

test("markdown stages nest the stages their blocks declare", () => {
  // The blocks live in the Markdown file, not calkit.yaml, so listing them
  // flat buries the one stage the user actually wrote
  const provider = new CalkitSidebarProvider();
  provider.refresh(
    "/workspace",
    {
      pipeline: {
        stages: {
          "README.md": { kind: "markdown" },
          other: { kind: "command", command: "echo hi" },
        },
      },
    } as never,
    {
      stages: {
        "README.md/analysis": { cmd: "python a.py" },
        "README.md/figure": { cmd: "python f.py" },
        other: { cmd: "echo hi" },
      },
    } as never,
    new Set(["README.md/figure"]),
  );

  const top = provider.getChildren(
    new SidebarItem("Pipeline", 1, "section-pipeline", "pipeline"),
  ) as InstanceType<typeof SidebarItem>[];
  const labels = top.map((i) => String(i.label)).sort();
  assert.deepEqual(labels, ["README.md", "other"]);

  // The Markdown stage reports its blocks' combined state
  const mdItem = top.find((i) => String(i.label) === "README.md");
  assert.equal(mdItem?.description, "stale");

  // Expanding it shows the blocks, labelled by name but keeping the full
  // stage name as the id so running them still works
  const children = provider.getChildren(mdItem) as InstanceType<
    typeof SidebarItem
  >[];
  assert.deepEqual(
    children.map((i) => [String(i.label), i.nodeId]),
    [
      ["analysis", "README.md/analysis"],
      ["figure", "README.md/figure"],
    ],
  );

  // And they point back at the Markdown stage, not the section
  assert.equal(provider.getParent(children[0])?.nodeId, "README.md");
});

test("a stage with no markdown parent still shows its properties", () => {
  const provider = new CalkitSidebarProvider();
  provider.refresh(
    "/workspace",
    {
      pipeline: {
        stages: { plain: { kind: "python-script", script_path: "a.py" } },
      },
    } as never,
    { stages: { plain: { cmd: "python a.py" } } } as never,
    new Set(),
  );
  const item = new SidebarItem("plain", 1, "stage", "plain");
  const children = provider.getChildren(item) as InstanceType<
    typeof SidebarItem
  >[];
  // Properties, not nested stages
  assert.ok(children.every((c) => c.nodeKind !== "stage"));
});
