import * as vscode from "vscode";
import * as path from "node:path";
import type { CalkitInfo, DvcYaml, EnvDescription } from "./types";

export class SidebarItem extends vscode.TreeItem {
  constructor(
    label: string,
    collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly nodeKind: string,
    public readonly nodeId?: string,
  ) {
    super(label, collapsibleState);
  }
}

export class CalkitSidebarProvider
  implements vscode.TreeDataProvider<SidebarItem>
{
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<
    SidebarItem | undefined | null | void
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private workspaceRoot: string | undefined;
  private calkitConfig: CalkitInfo | undefined;
  private dvcYaml: DvcYaml | undefined;
  private staleStageNames = new Set<string>();
  private envDescriptions: Record<string, EnvDescription> | undefined;

  refresh(
    workspaceRoot: string | undefined,
    calkitConfig: CalkitInfo | undefined,
    dvcYaml: DvcYaml | undefined,
    staleStageNames: Set<string>,
    envDescriptions?: Record<string, EnvDescription>,
  ): void {
    this.workspaceRoot = workspaceRoot;
    this.calkitConfig = calkitConfig;
    this.dvcYaml = dvcYaml;
    this.staleStageNames = staleStageNames;
    this.envDescriptions = envDescriptions;
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: SidebarItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: SidebarItem): SidebarItem[] {
    if (!element) {
      return [
        this.makeSection("Environments", "envs"),
        this.makeSection("Pipeline", "pipeline"),
      ];
    }
    switch (element.nodeKind) {
      case "section-envs":
        return this.getEnvItems();
      case "section-pipeline":
        return this.getStageItems();
      case "env":
        return this.getEnvProps(element.nodeId ?? "");
      case "stage":
        return this.getStageProps(element.nodeId ?? "");
      default:
        return [];
    }
  }

  private makeSection(label: string, id: string): SidebarItem {
    const item = new SidebarItem(
      label,
      vscode.TreeItemCollapsibleState.Expanded,
      `section-${id}`,
    );
    item.contextValue = `section-${id}`;
    return item;
  }

  private getEnvItems(): SidebarItem[] {
    const envs = this.calkitConfig?.environments ?? {};
    if (Object.keys(envs).length === 0) {
      const empty = new SidebarItem(
        "No environments defined",
        vscode.TreeItemCollapsibleState.None,
        "empty",
      );
      empty.description = "";
      return [empty];
    }
    return Object.entries(envs).map(([name, env]) => {
      const item = new SidebarItem(
        name,
        vscode.TreeItemCollapsibleState.Collapsed,
        "env",
        name,
      );
      item.description = typeof env.kind === "string" ? env.kind : undefined;
      item.iconPath = new vscode.ThemeIcon("package");
      return item;
    });
  }

  private getEnvProps(envName: string): SidebarItem[] {
    const env = this.calkitConfig?.environments?.[envName];
    if (!env) {
      return [];
    }
    const items: SidebarItem[] = [];
    const prop = (
      label: string,
      val: string,
      openPath?: string,
      icon?: string,
    ): void => {
      const item = new SidebarItem(
        label,
        vscode.TreeItemCollapsibleState.None,
        "env-prop",
      );
      item.description = val;
      if (icon) {
        item.iconPath = new vscode.ThemeIcon(icon);
      }
      if (openPath && this.workspaceRoot) {
        const absPath = path.join(this.workspaceRoot, openPath);
        item.command = {
          command: "vscode.open",
          title: "Open",
          arguments: [vscode.Uri.file(absPath)],
        };
        item.tooltip = `Open ${openPath}`;
      }
      items.push(item);
    };
    const desc = this.envDescriptions?.[envName];
    const specPath =
      desc?.spec_path ?? (typeof env.path === "string" ? env.path : undefined);
    const lockPath = desc?.lock_path;
    const prefix =
      desc?.prefix ?? (typeof env.prefix === "string" ? env.prefix : undefined);
    const python =
      desc?.python ?? (typeof env.python === "string" ? env.python : undefined);
    if (specPath) {
      prop("Spec", specPath, specPath, "file-code");
    }
    if (lockPath) {
      prop("Lock", lockPath, lockPath, "lock");
    }
    if (prefix) {
      prop("Prefix", prefix, undefined, "folder");
    }
    if (python) {
      prop("Python", python, undefined, "symbol-namespace");
    }
    return items;
  }

  private getStageItems(): SidebarItem[] {
    const calkitStages = this.calkitConfig?.pipeline?.stages ?? {};
    const dvcStages = this.dvcYaml?.stages ?? {};
    const allNames = new Set([
      ...Object.keys(calkitStages),
      ...Object.keys(dvcStages),
    ]);
    if (allNames.size === 0) {
      const empty = new SidebarItem(
        "No pipeline stages defined",
        vscode.TreeItemCollapsibleState.None,
        "empty",
      );
      return [empty];
    }
    return [...allNames].map((stageName) => {
      const isStale = this.staleStageNames.has(stageName);
      const item = new SidebarItem(
        stageName,
        vscode.TreeItemCollapsibleState.Collapsed,
        "stage",
        stageName,
      );
      item.description = isStale ? "stale" : undefined;
      item.iconPath = isStale
        ? new vscode.ThemeIcon(
            "warning",
            new vscode.ThemeColor("list.warningForeground"),
          )
        : new vscode.ThemeIcon(
            "check",
            new vscode.ThemeColor("testing.iconPassed"),
          );
      item.contextValue = "stage";
      item.tooltip = isStale
        ? `${stageName} — stage is stale`
        : `${stageName} — up to date`;
      return item;
    });
  }

  private getStageProps(stageName: string): SidebarItem[] {
    const calkitStage = this.calkitConfig?.pipeline?.stages?.[stageName];
    const dvcStage = this.dvcYaml?.stages?.[stageName];
    const items: SidebarItem[] = [];

    const prop = (
      label: string,
      val: string,
      icon: string,
      openPath?: string,
    ): void => {
      const item = new SidebarItem(
        label,
        vscode.TreeItemCollapsibleState.None,
        "stage-prop",
      );
      item.description = val;
      item.iconPath = new vscode.ThemeIcon(icon);
      if (openPath && this.workspaceRoot) {
        const absPath = path.join(this.workspaceRoot, openPath);
        item.command = {
          command: "vscode.open",
          title: "Open",
          arguments: [vscode.Uri.file(absPath)],
        };
        item.tooltip = `Open ${openPath}`;
      }
      items.push(item);
    };

    if (calkitStage) {
      if (typeof calkitStage.kind === "string") {
        prop("Kind", calkitStage.kind, "symbol-enum");
      }
      if (typeof calkitStage.notebook_path === "string") {
        prop(
          "Notebook",
          calkitStage.notebook_path,
          "notebook",
          calkitStage.notebook_path,
        );
      }
      if (typeof calkitStage.script_path === "string") {
        prop(
          "Script",
          calkitStage.script_path,
          "file-code",
          calkitStage.script_path,
        );
      }
      if (typeof calkitStage.environment === "string") {
        prop("Environment", calkitStage.environment, "package");
      }
    }

    if (calkitStage) {
      for (const input of Array.isArray(calkitStage.inputs)
        ? (calkitStage.inputs as string[])
        : []) {
        prop("Input", input, "arrow-right", input);
      }
      for (const output of Array.isArray(calkitStage.outputs)
        ? (calkitStage.outputs as string[])
        : []) {
        prop("Output", output, "arrow-left", output);
      }
    }

    return items;
  }
}
