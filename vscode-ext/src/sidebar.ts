import * as vscode from "vscode";
import * as path from "node:path";
import * as fs from "node:fs";
import type {
  ArtifactEntry,
  CalkitInfo,
  DvcYaml,
  EnvDescription,
  NotebookEntry,
  PipelineStage,
} from "./types";
import { getExecutedNotebookHtmlPath } from "./notebooks";

// Singular node kinds and the matching calkit.yaml collection keys for the
// artifact-style sections (figures, datasets, results, publications,
// presentations), which share the same item machinery.
type ArtifactKind =
  | "figure"
  | "dataset"
  | "result"
  | "publication"
  | "presentation";
type ArtifactCollection =
  | "figures"
  | "datasets"
  | "results"
  | "publications"
  | "presentations";

function outputEntryPath(
  output: string | { path: string; [key: string]: unknown },
): string {
  return typeof output === "string" ? output : output.path;
}

// Base codicon for each artifact kind (used when the artifact has provenance and
// isn't stale; imported artifacts use a cloud icon instead).
const ARTIFACT_ICONS: Record<ArtifactKind, string> = {
  figure: "file-media",
  dataset: "database",
  result: "graph",
  publication: "book",
  presentation: "device-desktop",
};

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
  private runningStageNames = new Set<string>();
  private envDescriptions: Record<string, EnvDescription> | undefined;
  private detectedNotebooks: string[] = [];
  private detectedFigures: string[] = [];
  private detectedDatasets: string[] = [];
  private detectedResults: string[] = [];
  private detectedPresentations: string[] = [];
  private hiddenSections = new Set<string>();
  private lastFingerprint: string | undefined;

  // Cached section items so reveal() can use getParent()
  private readonly questionsSectionItem = this.makeSection(
    "Questions",
    "questions",
  );
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
  private readonly publicationsSectionItem = this.makeSection(
    "Publications",
    "publications",
  );
  private readonly presentationsSectionItem = this.makeSection(
    "Presentations",
    "presentations",
  );
  private readonly resultsSectionItem = this.makeSection("Results", "results");
  private stageItemCache = new Map<string, SidebarItem>();
  private envItemCache = new Map<string, SidebarItem>();

  refresh(
    workspaceRoot: string | undefined,
    calkitConfig: CalkitInfo | undefined,
    dvcYaml: DvcYaml | undefined,
    staleStageNames: Set<string>,
    envDescriptions?: Record<string, EnvDescription>,
    detectedNotebooks?: string[],
    detectedFigures?: string[],
    detectedDatasets?: string[],
    runningStageNames?: Set<string>,
    detectedResults?: string[],
    detectedPresentations?: string[],
    hiddenSections?: Set<string>,
  ): void {
    const nextFingerprint = JSON.stringify([
      calkitConfig,
      dvcYaml,
      [...staleStageNames].sort(),
      envDescriptions,
      detectedNotebooks,
      detectedFigures,
      detectedDatasets,
      [...(runningStageNames ?? [])].sort(),
      detectedResults,
      detectedPresentations,
      [...(hiddenSections ?? [])].sort(),
    ]);
    if (nextFingerprint === this.lastFingerprint) {
      return;
    }
    this.lastFingerprint = nextFingerprint;
    this.workspaceRoot = workspaceRoot;
    this.calkitConfig = calkitConfig;
    this.dvcYaml = dvcYaml;
    this.staleStageNames = staleStageNames;
    this.runningStageNames = runningStageNames ?? new Set();
    this.envDescriptions = envDescriptions;
    this.detectedNotebooks = detectedNotebooks ?? [];
    this.detectedFigures = detectedFigures ?? [];
    this.detectedDatasets = detectedDatasets ?? [];
    this.detectedResults = detectedResults ?? [];
    this.detectedPresentations = detectedPresentations ?? [];
    this.hiddenSections = hiddenSections ?? new Set();
    this.stageItemCache.clear();
    this.envItemCache.clear();
    this._onDidChangeTreeData.fire();
  }

  getAttentionCount(): number {
    // Not a Calkit project (no calkit.yaml): the tree shows the welcome view,
    // so auto-detected files shouldn't drive a "needs attention" badge.
    if (this.calkitConfig === undefined) {
      return 0;
    }
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
    const outputToStage = this.buildOutputToStageMap();
    for (const figPath of this.mergedArtifactPaths("figures")) {
      const entry = this.resolveArtifactEntry(figPath, "figure", outputToStage);
      if (!entry.stage && !entry.imported_from) {
        count++;
      }
    }
    // Datasets with no provenance
    for (const dataPath of this.mergedArtifactPaths("datasets")) {
      const entry = this.resolveArtifactEntry(
        dataPath,
        "dataset",
        outputToStage,
      );
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

  findEnvItem(envName: string): SidebarItem | undefined {
    if (this.envItemCache.size === 0) {
      this.getEnvItems();
    }
    return this.envItemCache.get(envName);
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
      // No calkit.yaml: leave the tree empty so the "Initialize Calkit
      // Project" welcome view (contributed in package.json) is shown instead.
      if (this.calkitConfig === undefined) {
        return [];
      }
      // Full ordered list; users hide sections they don't want via the
      // calkit.sidebar.hiddenSections setting (the section id is the suffix
      // after "section-").
      return [
        this.questionsSectionItem,
        this.envsSectionItem,
        this.pipelineSectionItem,
        this.notebooksSectionItem,
        this.figuresSectionItem,
        this.datasetsSectionItem,
        this.publicationsSectionItem,
        this.presentationsSectionItem,
        this.resultsSectionItem,
      ].filter(
        (s) => !this.hiddenSections.has(s.nodeKind.replace(/^section-/, "")),
      );
    }
    switch (element.nodeKind) {
      case "section-questions":
        return this.getQuestionItems();
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
      case "section-publications":
        return this.getArtifactItems("publications");
      case "section-presentations":
        return this.getArtifactItems("presentations");
      case "section-results":
        return this.getArtifactItems("results");
      case "env":
        return this.getEnvProps(element.nodeId ?? "");
      case "stage":
        return this.getStageProps(element.nodeId ?? "");
      case "notebook":
        return this.getNotebookProps(element.nodeId ?? "");
      case "figure":
      case "dataset":
      case "result":
      case "publication":
      case "presentation":
        return this.getArtifactProps(
          element.nodeId ?? "",
          element.nodeKind as ArtifactKind,
        );
      default:
        return [];
    }
  }

  private getQuestionItems(): SidebarItem[] {
    const questions = this.calkitConfig?.questions ?? [];
    if (questions.length === 0) {
      return [
        new SidebarItem(
          "No questions defined",
          vscode.TreeItemCollapsibleState.None,
          "empty",
        ),
      ];
    }
    return questions.map((text, i) => {
      // nodeId carries the 1-based index used by `calkit rm question <index>`.
      const item = new SidebarItem(
        text,
        vscode.TreeItemCollapsibleState.None,
        "question",
        String(i + 1),
      );
      item.iconPath = new vscode.ThemeIcon("question");
      item.tooltip = text;
      item.contextValue = "question";
      return item;
    });
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
      const cached = this.envItemCache.get(name);
      if (cached) {
        return cached;
      }
      const item = new SidebarItem(
        name,
        vscode.TreeItemCollapsibleState.Collapsed,
        "env",
        name,
      );
      item.description = typeof env.kind === "string" ? env.kind : undefined;
      item.iconPath = new vscode.ThemeIcon("package");
      item.contextValue = "env";
      this.envItemCache.set(name, item);
      return item;
    });
  }

  // An "Environment" property node (shown under stages, notebooks, and
  // artifacts). Clicking it jumps to the environment in the Environments
  // section, expanded.
  private makeEnvPropItem(envName: string): SidebarItem {
    const item = new SidebarItem(
      "Environment",
      vscode.TreeItemCollapsibleState.None,
      "stage-env-prop",
      envName,
    );
    item.description = envName;
    item.iconPath = new vscode.ThemeIcon("package");
    item.contextValue = "stage-env-prop";
    item.command = {
      command: "calkit-vscode.viewEnvironment",
      title: "View Environment",
      arguments: [item],
    };
    return item;
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
      // Clicking a notebook opens it (and expands its section if collapsible),
      // matching how figures and datasets behave.
      if (this.workspaceRoot) {
        const absPath = path.join(this.workspaceRoot, nbPath);
        item.command = {
          command: "vscode.openWith",
          title: "Open",
          arguments: [vscode.Uri.file(absPath), "jupyter-notebook"],
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
      items.push(this.makeEnvPropItem(envName));
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
      stageItem.command = {
        command: "calkit-vscode.viewStage",
        title: "View Stage",
        arguments: [stageItem],
      };
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
      // The notebook itself opens when clicked in the tree, so no separate
      // "Open" child is needed. Offer the executed HTML when it has been
      // generated.
      const htmlRel = getExecutedNotebookHtmlPath(nbPath);
      if (fs.existsSync(path.join(this.workspaceRoot, htmlRel))) {
        const htmlItem = new SidebarItem(
          "Open executed HTML",
          vscode.TreeItemCollapsibleState.None,
          "notebook-html",
          nbPath,
        );
        htmlItem.iconPath = new vscode.ThemeIcon("file-pdf");
        htmlItem.command = {
          command: "calkit-vscode.openNotebookHtml",
          title: "Open executed HTML",
          arguments: [nbPath],
        };
        items.push(htmlItem);
      }
    }
    return items;
  }

  private buildOutputToStageMap(): Map<string, string> {
    const map = new Map<string, string>();
    for (const [stageName, stage] of Object.entries(
      this.calkitConfig?.pipeline?.stages ?? {},
    )) {
      for (const out of stage.outputs ?? []) {
        map.set(outputEntryPath(out), stageName);
      }
    }
    for (const [stageName, stage] of Object.entries(
      this.dvcYaml?.stages ?? {},
    )) {
      for (const out of stage.outs ?? []) {
        const p =
          typeof out === "string" ? out : String(Object.keys(out)[0] ?? "");
        if (p) {
          map.set(p, stageName);
        }
      }
    }
    return map;
  }

  private detectedForCollection(kind: ArtifactCollection): string[] {
    switch (kind) {
      case "figures":
        return this.detectedFigures;
      case "datasets":
        return this.detectedDatasets;
      case "results":
        return this.detectedResults;
      case "presentations":
        return this.detectedPresentations;
      case "publications":
        return []; // publications are declared-only
    }
  }

  private resolveArtifactEntry(
    artifactPath: string,
    kind: ArtifactKind,
    outputToStage: Map<string, string>,
  ): ArtifactEntry {
    const list = (this.calkitConfig?.[`${kind}s`] ?? []) as ArtifactEntry[];
    const fromList = list.find((e) => e.path === artifactPath);
    if (fromList?.stage || fromList?.imported_from) {
      return fromList;
    }
    const stageName = outputToStage.get(artifactPath);
    if (stageName) {
      return { ...(fromList ?? { path: artifactPath }), stage: stageName };
    }
    return fromList ?? { path: artifactPath };
  }

  // Registered artifact paths for a kind plus any newly detected ones. Detected
  // paths are already filtered at the detection source (submodules, files
  // inside registered artifact/output folders, and folder collapsing), so here
  // we only need to drop exact duplicates of the registered entries.
  mergedArtifactPaths(kind: ArtifactCollection): string[] {
    const list = (this.calkitConfig?.[kind] ?? []) as ArtifactEntry[];
    const knownPaths = new Set(list.map((e) => e.path));
    const allPaths = [...knownPaths];
    for (const p of this.detectedForCollection(kind)) {
      if (!knownPaths.has(p)) {
        allPaths.push(p);
      }
    }
    return allPaths;
  }

  private getArtifactItems(kind: ArtifactCollection): SidebarItem[] {
    const nodeKind = kind.slice(0, -1) as ArtifactKind;
    const allPaths = this.mergedArtifactPaths(kind);
    if (allPaths.length === 0) {
      return [
        new SidebarItem(
          `No ${kind} found`,
          vscode.TreeItemCollapsibleState.None,
          "empty",
        ),
      ];
    }
    const outputToStage = this.buildOutputToStageMap();
    return allPaths.map((artifactPath) =>
      this.makeArtifactItem(
        this.resolveArtifactEntry(artifactPath, nodeKind, outputToStage),
        nodeKind,
      ),
    );
  }

  private makeArtifactItem(
    entry: ArtifactEntry,
    nodeKind: ArtifactKind,
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
      const isImported = !!entry.imported_from;
      item.iconPath = new vscode.ThemeIcon(
        isImported ? "cloud-download" : ARTIFACT_ICONS[nodeKind],
        new vscode.ThemeColor("testing.iconPassed"),
      );
      item.tooltip = entry.stage
        ? `${entry.path} — stage: ${entry.stage}`
        : `${entry.path} — imported`;
      item.contextValue = nodeKind;
    }
    // Clicking a figure opens the carousel; everything else opens the file.
    if (this.workspaceRoot) {
      if (nodeKind === "figure") {
        item.command = {
          command: "calkit-vscode.openFiguresCarousel",
          title: "Browse Figures",
          arguments: [item],
        };
      } else {
        const absPath = path.join(this.workspaceRoot, entry.path);
        item.command = {
          command: "vscode.open",
          title: "Open",
          arguments: [vscode.Uri.file(absPath)],
        };
      }
    }
    return item;
  }

  private getArtifactProps(
    artifactPath: string,
    nodeKind: ArtifactKind,
  ): SidebarItem[] {
    const entry = this.resolveArtifactEntry(
      artifactPath,
      nodeKind,
      this.buildOutputToStageMap(),
    );
    const items: SidebarItem[] = [];
    if (typeof entry.stage === "string") {
      const stageName = entry.stage;
      const stageItem = new SidebarItem(
        "Stage",
        vscode.TreeItemCollapsibleState.None,
        "artifact-stage-prop",
        stageName,
      );
      stageItem.description = stageName;
      stageItem.iconPath = new vscode.ThemeIcon("layers");
      stageItem.contextValue = "artifact-stage-prop";
      stageItem.command = {
        command: "calkit-vscode.viewStage",
        title: "View Stage",
        arguments: [stageItem],
      };
      items.push(stageItem);
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
      const isRunning = this.runningStageNames.has(stageName);
      const isStale = this.staleStageNames.has(stageName);
      const item = new SidebarItem(
        stageName,
        vscode.TreeItemCollapsibleState.Collapsed,
        "stage",
        stageName,
      );
      item.description = isRunning ? "running" : isStale ? "stale" : undefined;
      item.iconPath = isRunning
        ? new vscode.ThemeIcon("loading~spin")
        : isStale
        ? new vscode.ThemeIcon(
            "warning",
            new vscode.ThemeColor("list.warningForeground"),
          )
        : new vscode.ThemeIcon(
            "check",
            new vscode.ThemeColor("testing.iconPassed"),
          );
      item.contextValue = "stage";
      item.tooltip = isRunning
        ? `${stageName} — running`
        : isStale
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
        items.push(this.makeEnvPropItem(calkitStage.environment));
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
