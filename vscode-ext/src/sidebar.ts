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
  // Cached section items so reveal() can use getParent()
  private readonly envsSectionItem = this.makeSection("Environments", "envs");
  private readonly pipelineSectionItem = this.makeSection(
    "Pipeline",
    "pipeline",
  );
  private stageItemCache = new Map<string, SidebarItem>();

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
    this.stageItemCache.clear();
    this._onDidChangeTreeData.fire();
  }

  findStageItem(stageName: string): SidebarItem | undefined {
    // Ensure cache is populated by building items if needed
    if (this.stageItemCache.size === 0) {
      this.getStageItems();
    }
    return this.stageItemCache.get(stageName);
  }

  getParent(element: SidebarItem): SidebarItem | undefined {
    if (element.nodeKind === "stage") {
      return this.pipelineSectionItem;
    }
    if (element.nodeKind === "env") {
      return this.envsSectionItem;
    }
    return undefined;
  }

  getTreeItem(element: SidebarItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: SidebarItem): SidebarItem[] {
    if (!element) {
      return [this.envsSectionItem, this.pipelineSectionItem];
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
      item.contextValue = "env";
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
    if (typeof env.image === "string") {
      prop("Image", env.image, undefined, "vm");
    }
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
    const items = [...allNames].map((stageName) => {
      const cached = this.stageItemCache.get(stageName);
      if (cached) {
        return cached;
      }
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
      this.stageItemCache.set(stageName, item);
      return item;
    });
    return items;
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
      if (typeof calkitStage.target_path === "string") {
        prop(
          "Source",
          calkitStage.target_path,
          "file-code",
          calkitStage.target_path,
        );
      }
      if (typeof calkitStage.environment === "string") {
        const envItem = new SidebarItem(
          "Environment",
          vscode.TreeItemCollapsibleState.None,
          "stage-env-prop",
          calkitStage.environment,
        );
        envItem.description = calkitStage.environment;
        envItem.iconPath = new vscode.ThemeIcon("package");
        envItem.contextValue = "stage-env-prop";
        items.push(envItem);
      }
    }

    if (calkitStage) {
      for (const input of Array.isArray(calkitStage.inputs)
        ? (calkitStage.inputs as string[])
        : []) {
        prop("Input", input, "arrow-left", input);
      }
      const explicitOutputs = Array.isArray(calkitStage.outputs)
        ? (calkitStage.outputs as string[])
        : [];
      for (const output of explicitOutputs) {
        prop("Output", output, "arrow-right", output);
      }
      // Implicit PDF output for latex stages
      if (
        calkitStage.kind === "latex" &&
        typeof calkitStage.target_path === "string"
      ) {
        const pdfPath = calkitStage.target_path.replace(/\.tex$/, ".pdf");
        if (!explicitOutputs.includes(pdfPath)) {
          prop("Output", pdfPath, "arrow-right", pdfPath);
        }
      }
    }

    return items;
  }
}
