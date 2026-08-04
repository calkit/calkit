import assert from "node:assert/strict";
import test from "node:test";

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

import { CalkitSidebarProvider, SidebarItem } from "../sidebar";

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
