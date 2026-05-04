import * as vscode from "vscode";
import * as path from "node:path";
import type {
  CalkitInfo,
  DatasetEntry,
  DvcYaml,
  EnvDescription,
  FigureEntry,
  NotebookEntry,
  PipelineStage,
} from "./types";

function outputEntryPath(
  output: string | { path: string; [key: string]: unknown },
): string {
  return typeof output === "string" ? output : output.path;
}

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
  private detectedNotebooks: string[] = [];
  private detectedFigures: string[] = [];
  private detectedDatasets: string[] = [];

  // Cached section items so reveal() can use getParent()
  private readonly envsSectionItem = this.makeSection("Environments", "envs");
  private readonly pipelineSectionItem = this.makeSection(
    "Pipeline",
    "pipeline",
  );
  private readonly notebooksSectionItem = this.makeSection(
    "Notebooks",
    "notebooks",
  );
  private readonly figuresSectionItem = this.makeSection("Figures", "figures");
  private readonly datasetsSectionItem = this.makeSection(
    "Datasets",
    "datasets",
  );
  private stageItemCache = new Map<string, SidebarItem>();

  refresh(
    workspaceRoot: string | undefined,
    calkitConfig: CalkitInfo | undefined,
    dvcYaml: DvcYaml | undefined,
    staleStageNames: Set<string>,
    envDescriptions?: Record<string, EnvDescription>,
    detectedNotebooks?: string[],
    detectedFigures?: string[],
    detectedDatasets?: string[],
  ): void {
    this.workspaceRoot = workspaceRoot;
    this.calkitConfig = calkitConfig;
    this.dvcYaml = dvcYaml;
    this.staleStageNames = staleStageNames;
    this.envDescriptions = envDescriptions;
    this.detectedNotebooks = detectedNotebooks ?? [];
    this.detectedFigures = detectedFigures ?? [];
    this.detectedDatasets = detectedDatasets ?? [];
    this.stageItemCache.clear();
    this._onDidChangeTreeData.fire();
  }

  getAttentionCount(): number {
    let count = 0;
    // Stale pipeline stages
    count += this.staleStageNames.size;
    // Notebooks with no environment
    const stages = this.calkitConfig?.pipeline?.stages ?? {};
    const listed = this.calkitConfig?.notebooks ?? [];
    const knownNbPaths = new Set(listed.map((n) => n.path));
    for (const stage of Object.values(stages)) {
      if (typeof stage.notebook_path === "string") {
        knownNbPaths.add(stage.notebook_path);
      }
    }
    const allNbPaths = [...knownNbPaths];
    for (const p of this.detectedNotebooks) {
      if (!knownNbPaths.has(p)) {
        allNbPaths.push(p);
      }
    }
    for (const nbPath of allNbPaths) {
      const { entry, stage: nbStage } = this.resolveNotebookEntry(nbPath);
      const envName = entry.environment ?? nbStage?.environment;
      if (!envName) {
        count++;
      }
    }
    // Figures with no provenance or stale stage
    const figList = this.calkitConfig?.figures ?? [];
    const knownFigPaths = new Set(figList.map((f) => f.path));
    const allFigPaths = [...knownFigPaths];
    for (const p of this.detectedFigures) {
      if (!knownFigPaths.has(p)) {
        allFigPaths.push(p);
      }
    }
    for (const figPath of allFigPaths) {
      const entry = figList.find((f) => f.path === figPath) ?? {
        path: figPath,
      };
      if (!entry.stage && !entry.imported_from) {
        count++;
      } else if (
        typeof entry.stage === "string" &&
        this.staleStageNames.has(entry.stage)
      ) {
        // Already counted via stale stages
      }
    }
    // Datasets with no provenance
    const dataList = this.calkitConfig?.datasets ?? [];
    const knownDataPaths = new Set(dataList.map((d) => d.path));
    const allDataPaths = [...knownDataPaths];
    for (const p of this.detectedDatasets) {
      if (!knownDataPaths.has(p)) {
        allDataPaths.push(p);
      }
    }
    for (const dataPath of allDataPaths) {
      const entry = dataList.find((d) => d.path === dataPath) ?? {
        path: dataPath,
      };
      if (!entry.stage && !entry.imported_from) {
        count++;
      }
    }
    return count;
  }

  findStageItem(stageName: string): SidebarItem | undefined {
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
    if (element.nodeKind === "notebook") {
      return this.notebooksSectionItem;
    }
    if (element.nodeKind === "figure") {
      return this.figuresSectionItem;
    }
    if (element.nodeKind === "dataset") {
      return this.datasetsSectionItem;
    }
    return undefined;
  }

  getTreeItem(element: SidebarItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: SidebarItem): SidebarItem[] {
    if (!element) {
      return [
        this.envsSectionItem,
        this.pipelineSectionItem,
        this.notebooksSectionItem,
        this.figuresSectionItem,
        this.datasetsSectionItem,
      ];
    }
    switch (element.nodeKind) {
      case "section-envs":
        return this.getEnvItems();
      case "section-pipeline":
        return this.getStageItems();
      case "section-notebooks":
        return this.getNotebookItems();
      case "section-figures":
        return this.getArtifactItems("figures");
      case "section-datasets":
        return this.getArtifactItems("datasets");
      case "env":
        return this.getEnvProps(element.nodeId ?? "");
      case "stage":
        return this.getStageProps(element.nodeId ?? "");
      case "notebook":
        return this.getNotebookProps(element.nodeId ?? "");
      case "figure":
      case "dataset":
        return this.getArtifactProps(
          element.nodeId ?? "",
          element.nodeKind as "figure" | "dataset",
        );
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

  private resolveNotebookEntry(nbPath: string): {
    entry: NotebookEntry;
    stage: PipelineStage | undefined;
    stageName: string | undefined;
  } {
    const listed = this.calkitConfig?.notebooks ?? [];
    const stages = this.calkitConfig?.pipeline?.stages ?? {};
    const explicit = listed.find((n) => n.path === nbPath);
    // Find stage where notebook_path matches
    const stageEntry = Object.entries(stages).find(
      ([, s]) => s.notebook_path === nbPath,
    );
    const stageName = explicit?.stage ?? stageEntry?.[0];
    const stage = stageName ? stages[stageName] : undefined;
    const envName = explicit?.environment ?? stage?.environment;
    return {
      entry: explicit ?? {
        path: nbPath,
        environment: envName,
        stage: stageName,
      },
      stage,
      stageName,
    };
  }

  private getNotebookItems(): SidebarItem[] {
    const listed = this.calkitConfig?.notebooks ?? [];
    const stages = this.calkitConfig?.pipeline?.stages ?? {};
    const knownPaths = new Set(listed.map((n) => n.path));
    // Add notebooks from pipeline stages
    for (const [, stage] of Object.entries(stages)) {
      if (typeof stage.notebook_path === "string") {
        if (!knownPaths.has(stage.notebook_path)) {
          knownPaths.add(stage.notebook_path);
        }
      }
    }
    // Add auto-detected notebooks not already known
    const allPaths = [...knownPaths];
    for (const p of this.detectedNotebooks) {
      if (!knownPaths.has(p)) {
        allPaths.push(p);
      }
    }
    if (allPaths.length === 0) {
      return [
        new SidebarItem(
          "No notebooks found",
          vscode.TreeItemCollapsibleState.None,
          "empty",
        ),
      ];
    }
    return allPaths.map((nbPath) => {
      const { entry, stage, stageName } = this.resolveNotebookEntry(nbPath);
      const envName = entry.environment ?? stage?.environment;
      const hasStage = !!stageName;
      const label = path.basename(nbPath);
      const collapsible =
        hasStage || !!envName
          ? vscode.TreeItemCollapsibleState.Collapsed
          : vscode.TreeItemCollapsibleState.None;
      const item = new SidebarItem(label, collapsible, "notebook", nbPath);
      item.description = nbPath;
      if (!envName) {
        item.iconPath = new vscode.ThemeIcon(
          "warning",
          new vscode.ThemeColor("list.warningForeground"),
        );
        item.tooltip = `${nbPath} — no environment defined`;
        item.contextValue = "notebook-no-env";
      } else {
        item.iconPath = new vscode.ThemeIcon("notebook");
        item.tooltip = stageName
          ? `${nbPath} — stage: ${stageName}, env: ${envName}`
          : `${nbPath} — env: ${envName}`;
        item.contextValue = "notebook";
      }
      if (
        this.workspaceRoot &&
        collapsible === vscode.TreeItemCollapsibleState.None
      ) {
        const absPath = path.join(this.workspaceRoot, nbPath);
        item.command = {
          command: "vscode.open",
          title: "Open",
          arguments: [vscode.Uri.file(absPath)],
        };
      }
      return item;
    });
  }

  private getNotebookProps(nbPath: string): SidebarItem[] {
    const { entry, stage, stageName } = this.resolveNotebookEntry(nbPath);
    const items: SidebarItem[] = [];
    const envName = entry.environment ?? stage?.environment;
    if (envName) {
      const envItem = new SidebarItem(
        "Environment",
        vscode.TreeItemCollapsibleState.None,
        "stage-env-prop",
        envName,
      );
      envItem.description = envName;
      envItem.iconPath = new vscode.ThemeIcon("package");
      envItem.contextValue = "stage-env-prop";
      items.push(envItem);
    }
    if (stageName && stage) {
      const stageItem = new SidebarItem(
        "Stage",
        vscode.TreeItemCollapsibleState.None,
        "notebook-stage-prop",
        stageName,
      );
      stageItem.description = stageName;
      stageItem.iconPath = new vscode.ThemeIcon("layers");
      stageItem.contextValue = "notebook-stage-prop";
      items.push(stageItem);
      for (const input of Array.isArray(stage.inputs)
        ? (stage.inputs as string[])
        : []) {
        const inputItem = new SidebarItem(
          "Input",
          vscode.TreeItemCollapsibleState.None,
          "stage-prop",
        );
        inputItem.description = input;
        inputItem.iconPath = new vscode.ThemeIcon("arrow-left");
        if (this.workspaceRoot) {
          inputItem.command = {
            command: "vscode.open",
            title: "Open",
            arguments: [vscode.Uri.file(path.join(this.workspaceRoot, input))],
          };
        }
        items.push(inputItem);
      }
      for (const rawOutput of Array.isArray(stage.outputs)
        ? stage.outputs
        : []) {
        const output = outputEntryPath(rawOutput as string | { path: string });
        const outItem = new SidebarItem(
          "Output",
          vscode.TreeItemCollapsibleState.None,
          "stage-prop",
        );
        outItem.description = output;
        outItem.iconPath = new vscode.ThemeIcon("arrow-right");
        if (this.workspaceRoot) {
          outItem.command = {
            command: "vscode.open",
            title: "Open",
            arguments: [vscode.Uri.file(path.join(this.workspaceRoot, output))],
          };
        }
        items.push(outItem);
      }
    }
    if (this.workspaceRoot) {
      const openItem = new SidebarItem(
        "Open",
        vscode.TreeItemCollapsibleState.None,
        "notebook-open",
        nbPath,
      );
      openItem.iconPath = new vscode.ThemeIcon("go-to-file");
      openItem.command = {
        command: "vscode.open",
        title: "Open",
        arguments: [vscode.Uri.file(path.join(this.workspaceRoot, nbPath))],
      };
      items.push(openItem);
    }
    return items;
  }

  private resolveArtifactEntry(
    artifactPath: string,
    kind: "figure" | "dataset",
  ): FigureEntry | DatasetEntry {
    const list =
      kind === "figure"
        ? this.calkitConfig?.figures ?? []
        : this.calkitConfig?.datasets ?? [];
    return list.find((e) => e.path === artifactPath) ?? { path: artifactPath };
  }

  private getArtifactItems(kind: "figures" | "datasets"): SidebarItem[] {
    const nodeKind = kind === "figures" ? "figure" : "dataset";
    const list: (FigureEntry | DatasetEntry)[] =
      this.calkitConfig?.[kind] ?? [];
    const knownPaths = new Set(list.map((e) => e.path));
    const detected =
      kind === "figures" ? this.detectedFigures : this.detectedDatasets;
    const allPaths = [...knownPaths];
    for (const p of detected) {
      if (!knownPaths.has(p)) {
        allPaths.push(p);
      }
    }
    if (allPaths.length === 0) {
      return [
        new SidebarItem(
          kind === "figures" ? "No figures found" : "No datasets found",
          vscode.TreeItemCollapsibleState.None,
          "empty",
        ),
      ];
    }
    return allPaths.map((artifactPath) =>
      this.makeArtifactItem(
        this.resolveArtifactEntry(artifactPath, nodeKind),
        nodeKind,
      ),
    );
  }

  private makeArtifactItem(
    entry: FigureEntry | DatasetEntry,
    nodeKind: "figure" | "dataset",
  ): SidebarItem {
    const label = path.basename(entry.path);
    const hasProvenance = !!entry.stage || !!entry.imported_from;
    const isStale =
      typeof entry.stage === "string" && this.staleStageNames.has(entry.stage);
    const collapsible = hasProvenance
      ? vscode.TreeItemCollapsibleState.Collapsed
      : vscode.TreeItemCollapsibleState.None;
    const item = new SidebarItem(label, collapsible, nodeKind, entry.path);
    item.description = entry.path;
    if (!hasProvenance) {
      item.iconPath = new vscode.ThemeIcon(
        "warning",
        new vscode.ThemeColor("list.warningForeground"),
      );
      item.tooltip = `${entry.path} — no source defined`;
      item.contextValue = `${nodeKind}-no-provenance`;
    } else if (isStale) {
      item.iconPath = new vscode.ThemeIcon(
        "warning",
        new vscode.ThemeColor("list.warningForeground"),
      );
      item.tooltip = `${entry.path} — stage '${entry.stage}' is stale`;
      item.contextValue = `${nodeKind}-stale`;
    } else {
      item.iconPath = new vscode.ThemeIcon(
        nodeKind === "figure" ? "file-media" : "database",
        new vscode.ThemeColor("testing.iconPassed"),
      );
      item.tooltip = entry.stage
        ? `${entry.path} — stage: ${entry.stage}`
        : `${entry.path} — imported`;
      item.contextValue = nodeKind;
    }
    if (this.workspaceRoot && !hasProvenance) {
      const absPath = path.join(this.workspaceRoot, entry.path);
      item.command = {
        command: "vscode.open",
        title: "Open",
        arguments: [vscode.Uri.file(absPath)],
      };
    }
    return item;
  }

  private getArtifactProps(
    artifactPath: string,
    nodeKind: "figure" | "dataset",
  ): SidebarItem[] {
    const entry = this.resolveArtifactEntry(artifactPath, nodeKind);
    const items: SidebarItem[] = [];
    const stages = this.calkitConfig?.pipeline?.stages ?? {};
    if (typeof entry.stage === "string") {
      const stageName = entry.stage;
      const stage = stages[stageName];
      const stageItem = new SidebarItem(
        "Stage",
        vscode.TreeItemCollapsibleState.None,
        "artifact-stage-prop",
        stageName,
      );
      stageItem.description = stageName;
      stageItem.iconPath = new vscode.ThemeIcon("layers");
      stageItem.contextValue = "artifact-stage-prop";
      items.push(stageItem);
      if (stage && typeof stage.environment === "string") {
        const envItem = new SidebarItem(
          "Environment",
          vscode.TreeItemCollapsibleState.None,
          "stage-env-prop",
          stage.environment,
        );
        envItem.description = stage.environment;
        envItem.iconPath = new vscode.ThemeIcon("package");
        envItem.contextValue = "stage-env-prop";
        items.push(envItem);
      }
    } else if (entry.imported_from) {
      const src =
        typeof entry.imported_from === "object" &&
        entry.imported_from !== null &&
        "url" in (entry.imported_from as object)
          ? (entry.imported_from as { url: string }).url
          : JSON.stringify(entry.imported_from);
      const importItem = new SidebarItem(
        "Imported from",
        vscode.TreeItemCollapsibleState.None,
        "artifact-import-prop",
      );
      importItem.description = src;
      importItem.iconPath = new vscode.ThemeIcon("cloud-download");
      items.push(importItem);
    }
    if (this.workspaceRoot) {
      const openItem = new SidebarItem(
        "Open",
        vscode.TreeItemCollapsibleState.None,
        "artifact-open",
        artifactPath,
      );
      openItem.iconPath = new vscode.ThemeIcon("go-to-file");
      openItem.command = {
        command: "vscode.open",
        title: "Open",
        arguments: [
          vscode.Uri.file(path.join(this.workspaceRoot, artifactPath)),
        ],
      };
      items.push(openItem);
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
      for (const input of Array.isArray(calkitStage.inputs)
        ? (calkitStage.inputs as string[])
        : []) {
        prop("Input", input, "arrow-left", input);
      }
      const explicitOutputs = Array.isArray(calkitStage.outputs)
        ? (calkitStage.outputs as (string | { path: string })[]).map(
            outputEntryPath,
          )
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
