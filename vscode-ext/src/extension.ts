import * as path from "node:path";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import * as http from "node:http";
import * as https from "node:https";
import * as net from "node:net";
import * as vscode from "vscode";
import YAML from "yaml";
import {
  compactSlurmOptions,
  findCalkitEnvKernelSourceCandidate,
  getDefaultSlurmOptions,
  kernelRegistrationKinds,
  makeCalkitEnvKernelSourceCandidates,
  slurmOptionsToOptionList,
  type CalkitEnvNotebookKernelSource,
  type CalkitEnvironment,
  type EnvKind,
  type SlurmLaunchOptions,
} from "./environments";
import { getConfiguredCandidateForNotebookPath as resolveConfiguredCandidateForNotebookPath } from "./notebooks";
import type { CalkitInfo, DvcYaml, EnvDescription } from "./types";
import { CalkitSidebarProvider } from "./sidebar";

const COMMAND_SELECT_ENV = "calkit-vscode.selectCalkitEnvironment";
const COMMAND_CREATE_ENV = "calkit-vscode.createCalkitEnvironment";
const COMMAND_EDIT_ENV = "calkit-vscode.editEnvironment";
const COMMAND_OPEN_STAGE_FILE = "calkit-vscode.openStageFile";
const COMMAND_START_SLURM = "calkit-vscode.startCalkitSlurmJob";
const COMMAND_STOP_SLURM = "calkit-vscode.stopCalkitSlurmJob";
const COMMAND_RESTART_JOB = "calkit-vscode.restartCalkitJob";
const COMMAND_SHOW_PROVENANCE = "calkit-vscode.showProvenance";
const COMMAND_RUN_STAGE = "calkit-vscode.runStage";
const COMMAND_RUN_STAGE_FOR_FILE = "calkit-vscode.runStageForFile";
const COMMAND_RUN_PIPELINE = "calkit-vscode.runPipeline";
const COMMAND_SHOW_DAG = "calkit-vscode.showPipelineDag";
const COMMAND_NEW_STAGE = "calkit-vscode.newStage";
const COMMAND_EDIT_STAGE = "calkit-vscode.editStage";
const COMMAND_DEFINE_PROVENANCE = "calkit-vscode.defineProvenance";
const COMMAND_DEFINE_ARTIFACT_STAGE = "calkit-vscode.defineArtifactStage";
const COMMAND_DEFINE_ARTIFACT_IMPORT = "calkit-vscode.defineArtifactImport";
const COMMAND_RUN_ARTIFACT_STAGE = "calkit-vscode.runArtifactStage";
const COMMAND_RUN_NOTEBOOK_STAGE = "calkit-vscode.runNotebookStage";
const COMMAND_EDIT_NOTEBOOK_STAGE = "calkit-vscode.editNotebookStage";
const COMMAND_DEFINE_NOTEBOOK_STAGE = "calkit-vscode.defineNotebookStage";
const COMMAND_REFRESH_SIDEBAR = "calkit-vscode.refreshSidebar";
const COMMAND_OPEN_CALKIT_YAML = "calkit-vscode.openCalkitYaml";
const COMMAND_OPEN_FIGURES_CAROUSEL = "calkit-vscode.openFiguresCarousel";
const COMMAND_OPEN_FILE_HISTORY = "calkit-vscode.openFileHistory";
const FIGURE_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".svg",
  ".pdf",
  ".eps",
  ".tiff",
  ".tif",
]);
const DATASET_EXTENSIONS = new Set([
  ".csv",
  ".h5",
  ".hdf5",
  ".parquet",
  ".nc",
  ".zarr",
  ".feather",
  ".arrow",
  ".avro",
  ".json",
  ".jsonl",
  ".ndjson",
]);
const NOTEBOOK_EXTENSION = ".ipynb";
const STATE_KEY_NOTEBOOK_PROFILES = "calkit.notebook.launchProfiles";
const execFileAsync = promisify(execFile);
const DEFAULT_MIN_CALKIT_VERSION = "0.38.3";
const DEFAULT_NOTEBOOK_SLURM_TIME = "120";
const CALKIT_INSTALL_DOCS_URL = "https://docs.calkit.org/installation";
const MISSING_IJULIA_ERROR_TEXT =
  "IJulia is not installed in this Julia environment";

let outputChannel: vscode.OutputChannel;
let slurmStatusBarItem: vscode.StatusBarItem | undefined;
let jupyterServerProcess: import("node:child_process").ChildProcess | undefined;
let activeJupyterServerSession: ActiveJupyterServerSession | undefined;
let extensionContextRef: vscode.ExtensionContext | undefined;
const autoSelectingNotebookUris = new Set<string>();
const configuredNotebooksThisSession = new Set<string>();
const slurmAutoStartDeclinedThisSession = new Set<string>();
const slurmAutoStartSuppressedThisSession = new Set<string>();
let hasCheckedCalkitCli = false;
const pipelineOutputUris = new Set<string>();
const staleOutputUris = new Set<string>();
const staleStageNames = new Set<string>();
const importedFigureUris = new Set<string>();
const pipelineNotebookUris = new Set<string>();
let pipelineDecorationProvider: vscode.Disposable | undefined;
let currentCalkitConfig: CalkitInfo | undefined;
let currentDvcYaml: DvcYaml | undefined;
let currentEnvDescriptions: Record<string, EnvDescription> | undefined;
let currentDetectedNotebooks: string[] = [];
let currentDetectedFigures: string[] = [];
let currentDetectedDatasets: string[] = [];
let sidebarProvider: CalkitSidebarProvider | undefined;
let sidebarTreeView:
  | vscode.TreeView<import("./sidebar").SidebarItem>
  | undefined;
let refreshDebounceTimer: NodeJS.Timeout | undefined;

function log(message: string): void {
  if (outputChannel) {
    outputChannel.appendLine(message);
  }
}

interface NotebookLaunchProfile {
  notebookUri: string;
  environmentName: string;
  innerEnvironment: string;
  innerKind: EnvKind;
  outerSlurmEnvironment?: string;
  slurmOptions?: SlurmLaunchOptions;
  preferredPort?: number;
}

interface ActiveJupyterServerSession {
  kind: "slurm" | "docker" | "other";
  notebookUri?: string;
}

export function activate(context: vscode.ExtensionContext): void {
  console.log("Calkit extension: activate() called");
  extensionContextRef = context;
  outputChannel = vscode.window.createOutputChannel("Calkit");
  context.subscriptions.push(outputChannel);
  slurmStatusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    200,
  );
  slurmStatusBarItem.text = "$(server-process)";
  slurmStatusBarItem.name = "Calkit SLURM Job";
  slurmStatusBarItem.tooltip =
    "Calkit Jupyter SLURM job is running. Click to stop.";
  slurmStatusBarItem.command = COMMAND_STOP_SLURM;
  context.subscriptions.push(slurmStatusBarItem);
  log("Calkit extension activated");
  console.log("Calkit extension: outputChannel created and registered");

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_SELECT_ENV, async () => {
      return await selectCalkitEnvironment(context);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_CREATE_ENV, async () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        void vscode.window.showErrorMessage(
          "Open a workspace folder to create Calkit environments.",
        );
        return;
      }
      await showEnvCreatorWebview(context, workspaceRoot);
      await refreshNotebookToolbarContext(context);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_EDIT_ENV,
      async (item?: import("./sidebar").SidebarItem) => {
        const envName = item?.nodeId;
        if (!envName) {
          return;
        }
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const env = currentCalkitConfig?.environments?.[envName];
        const desc = currentEnvDescriptions?.[envName];
        const specPath =
          desc?.spec_path ??
          (typeof env?.path === "string" ? env.path : undefined);
        await showEnvCreatorWebview(
          context,
          workspaceRoot,
          envName,
          env,
          specPath,
        );
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_OPEN_STAGE_FILE,
      async (item?: import("./sidebar").SidebarItem) => {
        const stageName = item?.nodeId;
        if (!stageName) {
          return;
        }
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const stage = currentCalkitConfig?.pipeline?.stages?.[stageName];
        const filePath =
          (typeof stage?.notebook_path === "string"
            ? stage.notebook_path
            : undefined) ??
          (typeof stage?.script_path === "string"
            ? stage.script_path
            : undefined) ??
          (typeof stage?.target_path === "string"
            ? stage.target_path
            : undefined);
        if (!filePath) {
          void vscode.window.showErrorMessage(
            `No source file found for stage '${stageName}'.`,
          );
          return;
        }
        const fileUri = vscode.Uri.file(path.join(workspaceRoot, filePath));
        if (filePath.endsWith(".ipynb")) {
          await vscode.commands.executeCommand(
            "vscode.openWith",
            fileUri,
            "jupyter-notebook",
          );
        } else {
          await vscode.window.showTextDocument(fileUri);
        }
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_START_SLURM, async () => {
      await startSlurmJobForActiveNotebook(context);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_STOP_SLURM, async () => {
      await stopSlurmJobForActiveNotebook(context);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_RESTART_JOB, async () => {
      await restartCalkitJobForActiveNotebook(context);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_SHOW_PROVENANCE,
      async (uri?: vscode.Uri) => {
        const fileUri = uri ?? vscode.window.activeTextEditor?.document.uri;
        if (!fileUri) {
          void vscode.window.showErrorMessage(
            "No file selected to show source for.",
          );
          return;
        }
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const stageName = await findStageForFile(workspaceRoot, fileUri);
        if (!stageName) {
          void vscode.window.showErrorMessage(
            `No pipeline stage found for '${path.basename(fileUri.fsPath)}'.`,
          );
          return;
        }
        const stageItem = sidebarProvider?.findStageItem(stageName);
        if (stageItem && sidebarTreeView) {
          await sidebarTreeView.reveal(stageItem, {
            select: true,
            focus: true,
            expand: true,
          });
        }
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_RUN_STAGE,
      (item?: import("./sidebar").SidebarItem) => {
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const stageName = item?.nodeId;
        if (!stageName) {
          return;
        }
        runStageInTerminal(workspaceRoot, stageName);
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_RUN_STAGE_FOR_FILE,
      async (uri?: vscode.Uri) => {
        const fileUri = uri ?? vscode.window.activeTextEditor?.document.uri;
        if (!fileUri) {
          return;
        }
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const stageName = await findStageForFile(workspaceRoot, fileUri);
        if (!stageName) {
          void vscode.window.showErrorMessage(
            `No pipeline stage found for '${path.basename(fileUri.fsPath)}'.`,
          );
          return;
        }
        runStageInTerminal(workspaceRoot, stageName);
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_RUN_PIPELINE, () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        return;
      }
      const terminal = getOrCreateTerminal("calkit: run", workspaceRoot);
      terminal.show();
      terminal.sendText("calkit run");
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_SHOW_DAG, () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        return;
      }
      showDagPanel(context, workspaceRoot);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_NEW_STAGE, async () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        return;
      }
      await showStageEditor(context, workspaceRoot, undefined);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_EDIT_STAGE,
      async (item?: import("./sidebar").SidebarItem) => {
        const stageName = item?.nodeId;
        if (!stageName) {
          return;
        }
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const stage = currentCalkitConfig?.pipeline?.stages?.[stageName];
        await showStageEditor(
          context,
          workspaceRoot,
          undefined,
          undefined,
          stageName,
          stage,
        );
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_DEFINE_PROVENANCE,
      async (uri?: vscode.Uri) => {
        const fileUri = uri ?? vscode.window.activeTextEditor?.document.uri;
        if (!fileUri) {
          return;
        }
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        await defineProvenance(context, workspaceRoot, fileUri);
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_DEFINE_ARTIFACT_STAGE,
      async (item?: import("./sidebar").SidebarItem) => {
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const artifactPath = item?.nodeId;
        if (!artifactPath) {
          return;
        }
        const artifactKind =
          item?.nodeKind === "dataset" ? "dataset" : "figure";
        await showStageEditor(
          context,
          workspaceRoot,
          artifactPath,
          undefined,
          undefined,
          undefined,
          artifactKind,
        );
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_DEFINE_ARTIFACT_IMPORT,
      async (item?: import("./sidebar").SidebarItem) => {
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const artifactPath = item?.nodeId;
        if (!artifactPath) {
          return;
        }
        const artifactKind =
          item?.nodeKind === "dataset" ? "dataset" : "figure";
        const url = await vscode.window.showInputBox({
          prompt: `URL this ${artifactKind} was imported from`,
          placeHolder: "https://...",
        });
        if (!url) {
          return;
        }
        try {
          await execFileAsync(
            "calkit",
            ["update", artifactKind, artifactPath, "--imported-from-url", url],
            { cwd: workspaceRoot },
          );
          void refreshPipelineOutputContext(context);
        } catch (error: unknown) {
          const err = error as { stderr?: string; message?: string };
          void vscode.window.showErrorMessage(
            (err.stderr ?? err.message ?? String(error)).trim(),
          );
        }
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_RUN_ARTIFACT_STAGE,
      (item?: import("./sidebar").SidebarItem) => {
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot || !item?.nodeId) {
          return;
        }
        const artifactPath = item.nodeId;
        const allEntries = [
          ...(currentCalkitConfig?.figures ?? []),
          ...(currentCalkitConfig?.datasets ?? []),
        ];
        const entry = allEntries.find((e) => e.path === artifactPath);
        const stageName =
          typeof entry?.stage === "string" ? entry.stage : undefined;
        if (!stageName) {
          void vscode.window.showErrorMessage(
            `No pipeline stage found for '${artifactPath}'.`,
          );
          return;
        }
        const terminal = getOrCreateTerminal("calkit: run", workspaceRoot);
        terminal.show(true);
        terminal.sendText(`calkit run ${shQuote(stageName)}`);
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_RUN_NOTEBOOK_STAGE, async () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        return;
      }
      const notebookUri = vscode.window.activeNotebookEditor?.notebook.uri;
      if (!notebookUri) {
        return;
      }
      const stageName = await findStageForFile(workspaceRoot, notebookUri);
      if (!stageName) {
        void vscode.window.showErrorMessage(
          "No pipeline stage found for this notebook.",
        );
        return;
      }
      const terminal = getOrCreateTerminal("calkit: run", workspaceRoot);
      terminal.show(true);
      terminal.sendText(`calkit run ${stageName}`);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_EDIT_NOTEBOOK_STAGE, async () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        return;
      }
      const notebookUri = vscode.window.activeNotebookEditor?.notebook.uri;
      if (!notebookUri) {
        return;
      }
      const stageName = await findStageForFile(workspaceRoot, notebookUri);
      if (!stageName) {
        void vscode.window.showErrorMessage(
          "No pipeline stage found for this notebook.",
        );
        return;
      }
      const stage = currentCalkitConfig?.pipeline?.stages?.[stageName];
      await showStageEditor(
        context,
        workspaceRoot,
        undefined,
        undefined,
        stageName,
        stage,
      );
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_DEFINE_NOTEBOOK_STAGE, async () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        return;
      }
      const notebookUri = vscode.window.activeNotebookEditor?.notebook.uri;
      if (!notebookUri) {
        return;
      }
      const relPath = path
        .relative(workspaceRoot, notebookUri.fsPath)
        .replace(/\\/g, "/");
      const profile = getLaunchProfileForActiveNotebook(context);
      const envName = profile?.environmentName;
      const prefillStage = envName
        ? { kind: "jupyter-notebook", environment: envName }
        : { kind: "jupyter-notebook" };
      await showStageEditor(
        context,
        workspaceRoot,
        undefined,
        relPath,
        undefined,
        prefillStage,
      );
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_OPEN_CALKIT_YAML, () => {
      const workspaceRoot = getWorkspaceRoot();
      if (!workspaceRoot) {
        return;
      }
      const fileUri = vscode.Uri.file(path.join(workspaceRoot, "calkit.yaml"));
      void vscode.commands.executeCommand("vscode.open", fileUri);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_REFRESH_SIDEBAR, async () => {
      const workspaceRoot = getWorkspaceRoot();
      if (workspaceRoot) {
        await scanDetectedFiles(workspaceRoot);
      }
      void refreshPipelineOutputContext(context);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_OPEN_FIGURES_CAROUSEL,
      (item?: import("./sidebar").SidebarItem) => {
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        const figList = currentCalkitConfig?.figures ?? [];
        const knownPaths = new Set(figList.map((f) => f.path));
        const allPaths = [...knownPaths];
        for (const p of currentDetectedFigures) {
          if (!knownPaths.has(p)) {
            allPaths.push(p);
          }
        }
        if (allPaths.length === 0) {
          void vscode.window.showInformationMessage("No figures found.");
          return;
        }
        // If triggered from a specific figure item, start at that index
        const startPath = item?.nodeKind === "figure" ? item.nodeId : undefined;
        const startIndex = startPath
          ? Math.max(0, allPaths.indexOf(startPath))
          : 0;
        openFiguresCarousel(context, workspaceRoot, allPaths, startIndex);
      },
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand(
      COMMAND_OPEN_FILE_HISTORY,
      async (item?: import("./sidebar").SidebarItem) => {
        const workspaceRoot = getWorkspaceRoot();
        if (!workspaceRoot) {
          return;
        }
        let filePath = item?.nodeId;
        if (!filePath) {
          const activeUri = vscode.window.activeTextEditor?.document.uri;
          if (activeUri) {
            filePath = path
              .relative(workspaceRoot, activeUri.fsPath)
              .replace(/\\/g, "/");
          }
        }
        if (!filePath) {
          void vscode.window.showErrorMessage("No file selected.");
          return;
        }
        await openFileHistoryPanel(context, workspaceRoot, filePath);
      },
    ),
  );

  sidebarProvider = new CalkitSidebarProvider();
  sidebarTreeView = vscode.window.createTreeView("calkit-sidebar", {
    treeDataProvider: sidebarProvider,
    showCollapseAll: true,
  });
  context.subscriptions.push(sidebarTreeView);

  context.subscriptions.push(
    vscode.window.onDidChangeActiveNotebookEditor(() => {
      void refreshNotebookToolbarContext(context);
    }),
  );

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      void refreshActiveFileStageContext(editor?.document.uri);
    }),
  );

  context.subscriptions.push(
    vscode.workspace.onDidOpenNotebookDocument(() => {
      void autoSelectEnvironmentForActiveNotebook(context);
    }),
  );

  context.subscriptions.push(
    vscode.workspace.onDidCloseNotebookDocument((document) => {
      const closedNotebookUri = document.uri.toString();
      void stopSlurmJobForClosedNotebook(context, closedNotebookUri);
    }),
  );

  void ensureCalkitCliReady();

  void refreshNotebookToolbarContext(context);
  void autoSelectEnvironmentForActiveNotebook(context);
  void refreshPipelineOutputContext(context);

  // Watch for changes to dvc.yaml/calkit.yaml to keep pipeline output context fresh.
  const dvcYamlWatcher =
    vscode.workspace.createFileSystemWatcher("**/dvc.yaml");
  context.subscriptions.push(dvcYamlWatcher);
  dvcYamlWatcher.onDidChange(() => {
    scheduleRefreshPipelineOutputContext(context);
  });
  dvcYamlWatcher.onDidCreate(() => {
    scheduleRefreshPipelineOutputContext(context);
  });
  dvcYamlWatcher.onDidDelete(() => {
    scheduleRefreshPipelineOutputContext(context);
  });

  const calkitYamlWatcher =
    vscode.workspace.createFileSystemWatcher("**/calkit.yaml");
  context.subscriptions.push(calkitYamlWatcher);
  calkitYamlWatcher.onDidChange(() => {
    scheduleRefreshPipelineOutputContext(context);
  });
  calkitYamlWatcher.onDidCreate(() => {
    scheduleRefreshPipelineOutputContext(context);
  });
  calkitYamlWatcher.onDidDelete(() => {
    scheduleRefreshPipelineOutputContext(context);
  });

  // Proposed API: shows Calkit in the top-level kernel source list.
  // This must never break activation when proposed APIs are unavailable.
  registerKernelSourceIfAvailable(context);

  console.log("Calkit extension: activate() completed successfully");
}

async function ensureCalkitCliReady(): Promise<void> {
  if (hasCheckedCalkitCli) {
    return;
  }
  hasCheckedCalkitCli = true;

  const minimumVersion = DEFAULT_MIN_CALKIT_VERSION;
  const workspaceRoot = getWorkspaceRoot();

  try {
    const { stdout, stderr } = await execFileAsync("calkit", ["--version"], {
      cwd: workspaceRoot,
      timeout: 5_000,
    });
    const output = `${stdout ?? ""}\n${stderr ?? ""}`;
    const installedVersion = extractFirstSemver(output);

    if (!installedVersion) {
      log(
        `Could not parse Calkit CLI version from 'calkit --version' output:\n  stdout: ${JSON.stringify(
          stdout,
        )}\n  stderr: ${JSON.stringify(stderr)}`,
      );
      return;
    }

    const hasNotebookUpdate = await hasUpdateNotebookCommand(workspaceRoot);
    if (!hasNotebookUpdate) {
      await promptCalkitInstallOrUpgrade({
        mode: "upgrade",
        title: "Calkit CLI is too old for this extension",
        message: `Detected Calkit ${installedVersion}, but this extension requires at least ${minimumVersion} with 'calkit update notebook'.`,
      });
      return;
    }

    if (compareSemver(installedVersion, minimumVersion) < 0) {
      await promptCalkitInstallOrUpgrade({
        mode: "upgrade",
        title: "Calkit CLI upgrade required",
        message: `Detected Calkit ${installedVersion}, but this extension requires version ${minimumVersion} or newer.`,
      });
      return;
    }

    log(
      `Calkit CLI check passed (installed=${installedVersion}, min=${minimumVersion})`,
    );
  } catch (error) {
    const details = error instanceof Error ? error.message : String(error);
    log(`Calkit CLI check failed: ${details}`);
    await promptCalkitInstallOrUpgrade({
      mode: "install",
      title: "Calkit CLI not found",
      message:
        "This extension requires the Calkit CLI in your PATH. Install it to use notebook environment features.",
    });
  }
}

function extractFirstSemver(input: string): string | undefined {
  // Prefer "Calkit X.Y.Z..." label (what `calkit --version` outputs)
  const labelMatch = input.match(/calkit\s+(\d+)\.(\d+)\.(\d+)/i);
  if (labelMatch?.[1] && labelMatch?.[2] && labelMatch?.[3]) {
    return `${labelMatch[1]}.${labelMatch[2]}.${labelMatch[3]}`;
  }
  // Fallback: any bare semver pattern in the output
  const match = input.match(/\b(\d+)\.(\d+)\.(\d+)/);
  return match?.[1] && match?.[2] && match?.[3]
    ? `${match[1]}.${match[2]}.${match[3]}`
    : undefined;
}

function compareSemver(a: string, b: string): number {
  const pa = a.split(".").map((n) => Number.parseInt(n, 10));
  const pb = b.split(".").map((n) => Number.parseInt(n, 10));
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const av = Number.isFinite(pa[i]) ? pa[i] : 0;
    const bv = Number.isFinite(pb[i]) ? pb[i] : 0;
    if (av > bv) {
      return 1;
    }
    if (av < bv) {
      return -1;
    }
  }
  return 0;
}

async function hasUpdateNotebookCommand(
  workspaceRoot?: string,
): Promise<boolean> {
  try {
    await execFileAsync("calkit", ["update", "notebook", "--help"], {
      cwd: workspaceRoot,
      timeout: 5_000,
    });
    return true;
  } catch {
    return false;
  }
}

async function promptCalkitInstallOrUpgrade(options: {
  mode: "install" | "upgrade";
  title: string;
  message: string;
}): Promise<void> {
  const primaryAction = options.mode === "install" ? "Install" : "Upgrade";
  const choice = await vscode.window.showWarningMessage(
    options.message,
    { modal: false, detail: options.title },
    primaryAction,
    "Open Install Docs",
  );

  if (choice === "Open Install Docs") {
    await vscode.env.openExternal(vscode.Uri.parse(CALKIT_INSTALL_DOCS_URL));
    return;
  }

  if (choice !== primaryAction) {
    return;
  }

  const command = await pickCalkitSetupCommand(options.mode);
  if (!command) {
    return;
  }

  const terminal = vscode.window.createTerminal("Calkit Setup");
  terminal.show(true);
  terminal.sendText(command, true);
  void vscode.window.showInformationMessage(
    "Started Calkit setup command in terminal. After it finishes, reload VS Code.",
  );
}

async function pickCalkitSetupCommand(
  mode: "install" | "upgrade",
): Promise<string | undefined> {
  const isWindows = process.platform === "win32";
  const installItems = [
    {
      label: "Official installer (recommended)",
      description: isWindows
        ? 'powershell -ExecutionPolicy ByPass -c "irm install-ps1.calkit.org | iex"'
        : "curl -LsSf install.calkit.org | sh",
      command: isWindows
        ? 'powershell -ExecutionPolicy ByPass -c "irm install-ps1.calkit.org | iex"'
        : "curl -LsSf install.calkit.org | sh",
    },
    {
      label: "uv tool",
      description:
        mode === "install"
          ? "uv tool install calkit-python"
          : "uv tool upgrade calkit-python",
      command:
        mode === "install"
          ? "uv tool install calkit-python"
          : "uv tool upgrade calkit-python",
    },
    {
      label: "pip",
      description: "python -m pip install --upgrade calkit-python",
      command: "python -m pip install --upgrade calkit-python",
    },
    {
      label: "Windows PowerShell installer",
      description:
        'powershell -ExecutionPolicy ByPass -c "irm install-ps1.calkit.org | iex"',
      command:
        'powershell -ExecutionPolicy ByPass -c "irm install-ps1.calkit.org | iex"',
    },
    {
      label: "Linux/macOS installer",
      description: "curl -LsSf install.calkit.org | sh",
      command: "curl -LsSf install.calkit.org | sh",
    },
  ];

  const selected = await vscode.window.showQuickPick(installItems, {
    title: mode === "install" ? "Install Calkit CLI" : "Upgrade Calkit CLI",
    placeHolder: "Choose an installation command to run in terminal",
    matchOnDescription: true,
  });
  return selected?.command;
}

export function deactivate(): void {
  // Shut down any running SLURM jobs for notebook kernels
  terminateJupyterServerProcess("extension deactivation");
}

async function fetchEnvDescriptions(
  workspaceRoot: string,
): Promise<Record<string, EnvDescription> | undefined> {
  try {
    const { stdout } = await execFileAsync("calkit", ["describe", "envs"], {
      cwd: workspaceRoot,
      timeout: 15_000,
    });
    return JSON.parse(stdout) as Record<string, EnvDescription>;
  } catch (error) {
    log(`Failed to fetch env descriptions: ${String(error)}`);
    return undefined;
  }
}

async function readDvcYaml(
  workspaceRoot: string,
): Promise<DvcYaml | undefined> {
  const fileUri = vscode.Uri.file(path.join(workspaceRoot, "dvc.yaml"));
  try {
    const bytes = await vscode.workspace.fs.readFile(fileUri);
    const raw = Buffer.from(bytes).toString("utf8");
    return (YAML.parse(raw) as DvcYaml | undefined) ?? {};
  } catch (error) {
    if (isFileNotFoundError(error)) {
      return {};
    }
    log(`Failed to read dvc.yaml: ${String(error)}`);
    return undefined;
  }
}

function dvcStageOutputPaths(stage: import("./types").DvcStage): string[] {
  const outs = stage.outs ?? [];
  return outs.flatMap((out) => {
    if (typeof out === "string") {
      return [out];
    }
    return Object.keys(out);
  });
}

function buildPipelineOutputMapFromYaml(
  workspaceRoot: string,
  dvcYaml: DvcYaml | undefined,
): Map<string, string> {
  const result = new Map<string, string>();
  if (!dvcYaml?.stages) {
    return result;
  }
  for (const [stageName, stage] of Object.entries(dvcYaml.stages)) {
    for (const outputPath of dvcStageOutputPaths(stage)) {
      result.set(path.join(workspaceRoot, outputPath), stageName);
    }
  }
  return result;
}

class PipelineOutputDecorationProvider
  implements vscode.FileDecorationProvider
{
  private readonly _onDidChangeFileDecorations = new vscode.EventEmitter<
    vscode.Uri[]
  >();
  readonly onDidChangeFileDecorations = this._onDidChangeFileDecorations.event;

  refresh(uris: vscode.Uri[]): void {
    this._onDidChangeFileDecorations.fire(uris);
  }

  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    const ext = path.extname(uri.fsPath).toLowerCase();
    if (pipelineOutputUris.has(uri.fsPath)) {
      if (staleOutputUris.has(uri.fsPath)) {
        return {
          tooltip: "Calkit pipeline output — stage is stale, needs re-run",
          color: new vscode.ThemeColor("list.warningForeground"),
        };
      }
      return undefined;
    }
    if (
      (FIGURE_EXTENSIONS.has(ext) && !importedFigureUris.has(uri.fsPath)) ||
      (ext === NOTEBOOK_EXTENSION &&
        !pipelineNotebookUris.has(uri.fsPath) &&
        !uri.fsPath.includes(
          `${path.sep}.calkit${path.sep}notebooks${path.sep}`,
        ))
    ) {
      return {
        badge: "!",
        tooltip: "Not produced by the pipeline — right-click to define source",
      };
    }
    return undefined;
  }
}

let decorationProvider: PipelineOutputDecorationProvider | undefined;

function updateSidebarBadge(): void {
  if (!sidebarTreeView || !sidebarProvider) {
    return;
  }
  const count = sidebarProvider.getAttentionCount();
  sidebarTreeView.badge =
    count > 0
      ? {
          value: count,
          tooltip: `${count} item${count === 1 ? "" : "s"} need attention`,
        }
      : undefined;
}

const DETECTED_FILES_EXCLUDE =
  "**/{.*,__pycache__,node_modules,venv,env,site-packages}/**";

const FIGURE_DIR_NAMES = new Set([
  "figures",
  "figs",
  "fig",
  "plots",
  "plot",
  "images",
  "img",
  "output",
  "outputs",
  "results",
]);

const DATA_DIR_NAMES = new Set([
  "data",
  "dataset",
  "datasets",
  "input",
  "inputs",
  "output",
  "outputs",
  "results",
]);

function hasAncestorIn(relPath: string, names: Set<string>): boolean {
  return relPath
    .split("/")
    .slice(0, -1)
    .some((p) => names.has(p.toLowerCase()));
}

const ARTIFACT_GLOB = `**/*.{${[...FIGURE_EXTENSIONS, ...DATASET_EXTENSIONS]
  .map((e) => e.replace(/^\./, ""))
  .join(",")}}`;

async function scanDetectedFiles(workspaceRoot: string): Promise<void> {
  const [notebookUris, allUris] = await Promise.all([
    vscode.workspace.findFiles(
      `**/*${NOTEBOOK_EXTENSION}`,
      DETECTED_FILES_EXCLUDE,
    ),
    vscode.workspace.findFiles(ARTIFACT_GLOB, DETECTED_FILES_EXCLUDE),
  ]);
  const toRelative = (
    uris: vscode.Uri[],
    exts: Set<string>,
    filter?: (rel: string) => boolean,
  ): string[] =>
    uris
      .filter((u) => exts.has(path.extname(u.fsPath).toLowerCase()))
      .map((u) => path.relative(workspaceRoot, u.fsPath).replace(/\\/g, "/"))
      .filter((rel) => !filter || filter(rel))
      .sort();
  currentDetectedNotebooks = notebookUris
    .map((u) => path.relative(workspaceRoot, u.fsPath).replace(/\\/g, "/"))
    .sort();
  const figuresFromFs = toRelative(allUris, FIGURE_EXTENSIONS, (rel) =>
    hasAncestorIn(rel, FIGURE_DIR_NAMES),
  );
  const datasetsFromFs = toRelative(allUris, DATASET_EXTENSIONS, (rel) =>
    hasAncestorIn(rel, DATA_DIR_NAMES),
  );
  // Also include pipeline outputs from dvc.yaml that match figure/dataset
  // extensions even if they don't exist on disk yet (e.g. stale DVC outputs).
  const figureSet = new Set(figuresFromFs);
  const datasetSet = new Set(datasetsFromFs);
  for (const stage of Object.values(currentDvcYaml?.stages ?? {})) {
    for (const rel of dvcStageOutputPaths(stage)) {
      const normalized = rel.replace(/\\/g, "/");
      const ext = path.extname(rel).toLowerCase();
      if (
        FIGURE_EXTENSIONS.has(ext) &&
        hasAncestorIn(normalized, FIGURE_DIR_NAMES)
      ) {
        figureSet.add(normalized);
      } else if (
        DATASET_EXTENSIONS.has(ext) &&
        hasAncestorIn(normalized, DATA_DIR_NAMES)
      ) {
        datasetSet.add(normalized);
      }
    }
  }
  currentDetectedFigures = [...figureSet].sort();
  currentDetectedDatasets = [...datasetSet].sort();
}

function scheduleRefreshPipelineOutputContext(
  context: vscode.ExtensionContext,
): void {
  if (refreshDebounceTimer !== undefined) {
    clearTimeout(refreshDebounceTimer);
  }
  refreshDebounceTimer = setTimeout(() => {
    refreshDebounceTimer = undefined;
    void refreshPipelineOutputContext(context);
  }, 300);
}

async function refreshPipelineOutputContext(
  context: vscode.ExtensionContext,
): Promise<void> {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    return;
  }
  const [dvcYaml, calkitConfig, envDescriptions] = await Promise.all([
    readDvcYaml(workspaceRoot),
    readCalkitConfig(workspaceRoot),
    fetchEnvDescriptions(workspaceRoot),
  ]);
  currentDvcYaml = dvcYaml;
  currentCalkitConfig = calkitConfig;
  currentEnvDescriptions = envDescriptions;
  const outputMap = buildPipelineOutputMapFromYaml(workspaceRoot, dvcYaml);
  const prevPaths = new Set([
    ...pipelineOutputUris,
    ...importedFigureUris,
    ...pipelineNotebookUris,
  ]);
  pipelineOutputUris.clear();
  importedFigureUris.clear();
  pipelineNotebookUris.clear();
  for (const absPath of outputMap.keys()) {
    pipelineOutputUris.add(absPath);
  }
  for (const fig of calkitConfig?.figures ?? []) {
    if (fig.imported_from != null) {
      importedFigureUris.add(path.join(workspaceRoot, fig.path));
    }
  }
  for (const stage of Object.values(calkitConfig?.pipeline?.stages ?? {})) {
    if (
      stage.kind === "jupyter-notebook" &&
      typeof stage.notebook_path === "string"
    ) {
      pipelineNotebookUris.add(path.join(workspaceRoot, stage.notebook_path));
    }
  }
  if (!decorationProvider) {
    decorationProvider = new PipelineOutputDecorationProvider();
    const disposable =
      vscode.window.registerFileDecorationProvider(decorationProvider);
    pipelineDecorationProvider = disposable;
    context.subscriptions.push(disposable);
  }
  const changedUris = [
    ...new Set([
      ...prevPaths,
      ...pipelineOutputUris,
      ...importedFigureUris,
      ...pipelineNotebookUris,
    ]),
  ].map((p) => vscode.Uri.file(p));
  decorationProvider.refresh(changedUris);
  await scanDetectedFiles(workspaceRoot);
  sidebarProvider?.refresh(
    workspaceRoot,
    calkitConfig,
    dvcYaml,
    staleStageNames,
    envDescriptions,
    currentDetectedNotebooks,
    currentDetectedFigures,
    currentDetectedDatasets,
  );
  updateSidebarBadge();
  // Run the staleness check after the fast decoration pass: "not produced
  // by the pipeline" badges are applied immediately, and stale-output
  // decorations follow once calkit status finishes.
  void refreshStaleOutputContext(workspaceRoot, outputMap, decorationProvider);
}

async function refreshStaleOutputContext(
  workspaceRoot: string,
  outputMap: Map<string, string>,
  provider: PipelineOutputDecorationProvider,
): Promise<void> {
  try {
    const { stdout } = await execFileAsync(
      "calkit",
      ["status", "--json", "-c", "pipeline"],
      { cwd: workspaceRoot, timeout: 60_000 },
    );
    const status = JSON.parse(stdout) as {
      pipeline?: { stale_stage_names?: string[] };
    };
    const freshStaleStageNames = new Set(
      status?.pipeline?.stale_stage_names ?? [],
    );
    const nextStale = new Set<string>();
    for (const [absPath, stageName] of outputMap) {
      if (freshStaleStageNames.has(stageName)) {
        nextStale.add(absPath);
      }
    }
    const prevStale = new Set(staleOutputUris);
    staleOutputUris.clear();
    for (const p of nextStale) {
      staleOutputUris.add(p);
    }
    const prevStageNames = new Set(staleStageNames);
    staleStageNames.clear();
    for (const n of freshStaleStageNames) {
      staleStageNames.add(n);
    }
    const changedUris = [...new Set([...prevStale, ...staleOutputUris])].map(
      (p) => vscode.Uri.file(p),
    );
    if (changedUris.length > 0) {
      provider.refresh(changedUris);
    }
    // Only re-render the sidebar if the set of stale stages actually changed
    const staleChanged =
      prevStageNames.size !== staleStageNames.size ||
      [...staleStageNames].some((n) => !prevStageNames.has(n));
    if (staleChanged) {
      sidebarProvider?.refresh(
        workspaceRoot,
        currentCalkitConfig,
        currentDvcYaml,
        staleStageNames,
        currentEnvDescriptions,
        currentDetectedNotebooks,
        currentDetectedFigures,
        currentDetectedDatasets,
      );
      updateSidebarBadge();
    }
  } catch (error) {
    log(`Staleness check failed: ${String(error)}`);
  }
}

function getNonce(): string {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  return Array.from(
    { length: 32 },
    () => chars[Math.floor(Math.random() * chars.length)],
  ).join("");
}

async function getDagMermaid(
  workspaceRoot: string,
): Promise<string | undefined> {
  try {
    const { stdout } = await execFileAsync(
      "calkit",
      ["dvc", "dag", "--mermaid"],
      { cwd: workspaceRoot, timeout: 15_000 },
    );
    return stdout.trim();
  } catch {
    return undefined;
  }
}

function showDagPanel(
  context: vscode.ExtensionContext,
  workspaceRoot: string,
): void {
  const nonce = getNonce();
  const panel = vscode.window.createWebviewPanel(
    "calkit.dag",
    "Pipeline DAG",
    vscode.ViewColumn.Active,
    { enableScripts: true },
  );
  context.subscriptions.push(panel);
  panel.webview.html = buildDagHtml(nonce);
  getDagMermaid(workspaceRoot)
    .then((mermaid) => {
      void panel.webview.postMessage({
        command: "dagReady",
        mermaid: mermaid ?? null,
      });
    })
    .catch(() => {
      void panel.webview.postMessage({ command: "dagReady", mermaid: null });
    });
}

function buildDagHtml(nonce: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}' https://cdn.jsdelivr.net 'unsafe-eval'; style-src 'unsafe-inline'; img-src data: blob:;">
<title>Pipeline DAG</title>
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); padding: 16px; margin: 0; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }
  #toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-shrink: 0; }
  h1 { font-size: 1.2em; margin: 0; flex: 1; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 3px 8px; cursor: pointer; border-radius: 2px; font-size: 1em; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  #zoom-label { font-size: 0.85em; color: var(--vscode-descriptionForeground); min-width: 3em; text-align: right; }
  #viewport { flex: 1; overflow: auto; cursor: grab; user-select: none; }
  #viewport.dragging { cursor: grabbing; }
  #canvas { display: inline-block; transform-origin: 0 0; }
  #dag-error { color: var(--vscode-descriptionForeground); font-style: italic; }
  .spinner { width: 18px; height: 18px; border: 2px solid var(--vscode-foreground); border-top-color: transparent; border-radius: 50%; animation: spin 0.7s linear infinite; margin-top: 20px; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div id="toolbar">
  <h1>Pipeline DAG</h1>
  <button id="btn-zoom-out" title="Zoom out">−</button>
  <span id="zoom-label">100%</span>
  <button id="btn-zoom-in" title="Zoom in">+</button>
  <button id="btn-reset" title="Reset zoom">Reset</button>
</div>
<div id="viewport"><div id="canvas"><div class="spinner"></div></div></div>
<script nonce="${nonce}" src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script nonce="${nonce}">
  const isDark = document.body.classList.contains('vscode-dark') || document.body.classList.contains('vscode-high-contrast');
  mermaid.initialize({ startOnLoad: false, theme: isDark ? 'dark' : 'default' });

  let scale = 1;
  const viewport = document.getElementById('viewport');
  const canvas = document.getElementById('canvas');
  const zoomLabel = document.getElementById('zoom-label');

  function applyZoom() {
    canvas.style.transform = 'scale(' + scale + ')';
    zoomLabel.textContent = Math.round(scale * 100) + '%';
  }
  function zoomBy(delta, originX, originY) {
    const prev = scale;
    scale = Math.min(4, Math.max(0.1, scale * (1 + delta)));
    if (originX !== undefined) {
      // Adjust scroll so zoom is centered on cursor
      viewport.scrollLeft = (viewport.scrollLeft + originX) * (scale / prev) - originX;
      viewport.scrollTop  = (viewport.scrollTop  + originY) * (scale / prev) - originY;
    }
    applyZoom();
  }

  document.getElementById('btn-zoom-in').addEventListener('click', function() { zoomBy(0.2); });
  document.getElementById('btn-zoom-out').addEventListener('click', function() { zoomBy(-0.2); });
  document.getElementById('btn-reset').addEventListener('click', function() { scale = 1; applyZoom(); });

  viewport.addEventListener('wheel', function(e) {
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const ox = e.clientX - rect.left;
    const oy = e.clientY - rect.top;
    zoomBy(e.deltaY < 0 ? 0.1 : -0.1, ox, oy);
  }, { passive: false });

  // Pan by drag
  let dragStart = null;
  let scrollStart = null;
  viewport.addEventListener('mousedown', function(e) {
    if (e.button !== 0) { return; }
    dragStart = { x: e.clientX, y: e.clientY };
    scrollStart = { left: viewport.scrollLeft, top: viewport.scrollTop };
    viewport.classList.add('dragging');
  });
  window.addEventListener('mousemove', function(e) {
    if (!dragStart) { return; }
    viewport.scrollLeft = scrollStart.left - (e.clientX - dragStart.x);
    viewport.scrollTop  = scrollStart.top  - (e.clientY - dragStart.y);
  });
  window.addEventListener('mouseup', function() {
    dragStart = null;
    viewport.classList.remove('dragging');
  });

  window.addEventListener('message', function(event) {
    const msg = event.data;
    if (msg.command !== 'dagReady') { return; }
    if (!msg.mermaid) {
      canvas.innerHTML = '<span id="dag-error">Pipeline diagram unavailable.</span>';
      return;
    }
    canvas.innerHTML = '<div class="mermaid"></div>';
    const el = canvas.querySelector('.mermaid');
    el.textContent = msg.mermaid;
    mermaid.run({ nodes: [el] }).catch(function(err) {
      canvas.innerHTML = '<span id="dag-error">Could not render diagram: ' + String(err) + '</span>';
    });
  });
</script>
</body>
</html>`;
}

async function defineProvenance(
  context: vscode.ExtensionContext,
  workspaceRoot: string,
  fileUri: vscode.Uri,
): Promise<void> {
  const relPath = path
    .relative(workspaceRoot, fileUri.fsPath)
    .replace(/\\/g, "/");
  const ext = path.extname(fileUri.fsPath).toLowerCase();
  const isNotebook = ext === NOTEBOOK_EXTENSION;
  const artifactKind: "figure" | "dataset" = DATASET_EXTENSIONS.has(ext)
    ? "dataset"
    : "figure";
  const envs = currentCalkitConfig?.environments ?? {};
  const envNames = Object.keys(envs);

  const choiceStage = "$(play) Produced by a script or notebook";
  const choiceImported = "$(cloud-download) Imported from an external source";
  const notebookChoiceStage =
    "$(play) Run this notebook and record as a pipeline stage";

  const picked = await vscode.window.showQuickPick(
    isNotebook
      ? [notebookChoiceStage, choiceImported]
      : [choiceStage, choiceImported],
    {
      title: `Define source for ${path.basename(fileUri.fsPath)}`,
      placeHolder: "How is this file produced?",
    },
  );
  if (!picked) {
    return;
  }

  if (picked === choiceImported) {
    const source = await vscode.window.showInputBox({
      title: "Mark as Imported",
      prompt: "Where was this file imported from?",
      placeHolder: "URL, project name, or brief description",
    });
    if (!source) {
      return;
    }
    try {
      await execFileAsync(
        "calkit",
        ["update", artifactKind, relPath, "--imported-from-url", source],
        { cwd: workspaceRoot },
      );
    } catch (err) {
      void vscode.window.showErrorMessage(
        `Failed to update ${artifactKind}: ${String(err)}`,
      );
      return;
    }
    void vscode.window.showInformationMessage(
      `Marked '${path.basename(fileUri.fsPath)}' as imported from '${source}'.`,
    );
    return;
  }

  // "Produced by script/notebook" path — open the stage editor
  await showStageEditor(
    context,
    workspaceRoot,
    isNotebook ? undefined : relPath,
    isNotebook ? relPath : undefined,
    undefined,
    undefined,
    isNotebook ? undefined : artifactKind,
  );
}

const SOURCE_GLOB = "**/*.{py,ipynb,R,jl,m,tex}";
const SOURCE_EXCLUDE =
  "**/{.calkit,.dvc,node_modules,.git,__pycache__,.ipynb_checkpoints}/**";
const ALL_FILES_EXCLUDE = "**/{.*}/**";

const KIND_BY_EXT: Record<string, string> = {
  ".ipynb": "jupyter-notebook",
  ".py": "script",
  ".R": "script",
  ".jl": "script",
  ".m": "script",
  ".tex": "latex",
};

async function showStageEditor(
  context: vscode.ExtensionContext,
  workspaceRoot: string,
  prefillOutput?: string,
  prefillSource?: string,
  editStageName?: string,
  existingStage?: import("./types").PipelineStage,
  artifactKind?: "figure" | "dataset",
): Promise<void> {
  const nonce = getNonce();
  const [sourceUris, allUris] = await Promise.all([
    vscode.workspace.findFiles(SOURCE_GLOB, SOURCE_EXCLUDE),
    vscode.workspace.findFiles("**/*", ALL_FILES_EXCLUDE),
  ]);
  const workspaceFiles = sourceUris
    .map((u) => path.relative(workspaceRoot, u.fsPath).replace(/\\/g, "/"))
    .sort();
  const allProjectFiles = allUris
    .map((u) => path.relative(workspaceRoot, u.fsPath).replace(/\\/g, "/"))
    .sort();
  const envs = currentCalkitConfig?.environments ?? {};
  const envEntries = Object.entries(envs).map(([name, env]) => ({
    name,
    kind: typeof env.kind === "string" ? env.kind : "",
  }));

  const isEdit = editStageName !== undefined;
  const panel = vscode.window.createWebviewPanel(
    "calkit.stageEditor",
    isEdit ? `Edit Stage: ${editStageName}` : "New Pipeline Stage",
    vscode.ViewColumn.Active,
    { enableScripts: true },
  );
  context.subscriptions.push(panel);
  panel.webview.html = buildStageEditorHtml(
    nonce,
    workspaceFiles,
    allProjectFiles,
    envEntries,
    prefillOutput,
    prefillSource,
    editStageName,
    existingStage,
  );

  panel.webview.onDidReceiveMessage(
    async (msg: {
      command: string;
      stageName: string;
      source: string;
      environment: string;
      output: string;
      outputStorage: string;
      inputs: string[];
      outputs: { path: string; storage: "dvc" | "git" }[];
      andRun: boolean;
    }) => {
      if (msg.command === "create") {
        const args: string[] = [];
        if (msg.environment) {
          args.push("-e", msg.environment);
        }
        if (msg.stageName) {
          args.push("--stage", msg.stageName);
        }
        for (const i of msg.inputs ?? []) {
          if (i) {
            args.push("-i", i);
          }
        }
        // calkit xr only supports DVC-tracked outputs (-o); Git-tracked
        // outputs are applied afterward via `calkit update stage`.
        const dvcOuts = (msg.outputs ?? [])
          .filter((o) => o.storage !== "git")
          .map((o) => o.path)
          .filter(Boolean);
        const gitOuts = (msg.outputs ?? [])
          .filter((o) => o.storage === "git")
          .map((o) => o.path)
          .filter(Boolean);
        for (const o of dvcOuts) {
          args.push("-o", o);
        }
        if (gitOuts.length > 0 && !msg.stageName) {
          void vscode.window.showErrorMessage(
            "A stage name is required to record Git-tracked outputs.",
          );
          return;
        }
        args.push(msg.source);
        // Link artifact → stage in calkit.yaml before running xr so both writes don't race
        if (artifactKind && prefillOutput && msg.stageName) {
          await execFileAsync(
            "calkit",
            ["update", artifactKind, prefillOutput, "--stage", msg.stageName],
            { cwd: workspaceRoot },
          ).catch((err: unknown) => {
            void vscode.window.showErrorMessage(
              `Failed to link ${artifactKind} to stage: ${String(err)}`,
            );
          });
        }
        const terminal = getOrCreateTerminal("calkit: run", workspaceRoot);
        terminal.show();
        let cmd = `calkit xr ${args.map(shQuote).join(" ")}`;
        if (gitOuts.length > 0) {
          const gitOutArgs = ["update", "stage", msg.stageName];
          for (const o of gitOuts) {
            gitOutArgs.push("--set-outputs-git", o);
          }
          cmd += ` && calkit ${gitOutArgs.map(shQuote).join(" ")}`;
        }
        terminal.sendText(cmd);
        void panel.dispose();
      } else if (msg.command === "save" && editStageName) {
        const updateArgs: string[] = ["update", "stage", editStageName];
        if (msg.environment !== undefined) {
          updateArgs.push("--environment", msg.environment);
        }
        for (const i of msg.inputs) {
          updateArgs.push("--set-inputs", i);
        }
        if (msg.inputs.length === 0) {
          updateArgs.push("--set-inputs", "");
        }
        const dvcOuts = msg.outputs
          .filter((o) => o.storage !== "git")
          .map((o) => o.path);
        const gitOuts = msg.outputs
          .filter((o) => o.storage === "git")
          .map((o) => o.path);
        for (const o of dvcOuts) {
          updateArgs.push("--set-outputs", o);
        }
        if (dvcOuts.length === 0) {
          updateArgs.push("--set-outputs", "");
        }
        for (const o of gitOuts) {
          updateArgs.push("--set-outputs-git", o);
        }
        if (gitOuts.length === 0) {
          updateArgs.push("--set-outputs-git", "");
        }
        void execFileAsync("calkit", updateArgs, { cwd: workspaceRoot })
          .then(() => {
            if (msg.andRun) {
              const terminal = getOrCreateTerminal(
                "calkit: run",
                workspaceRoot,
              );
              terminal.show();
              terminal.sendText(`calkit run ${shQuote(editStageName)}`);
            }
            void panel.dispose();
          })
          .catch((err: unknown) => {
            void vscode.window.showErrorMessage(
              `Failed to update stage: ${String(err)}`,
            );
          });
      }
    },
    undefined,
    context.subscriptions,
  );
}

function buildStageEditorHtml(
  nonce: string,
  workspaceFiles: string[],
  allProjectFiles: string[],
  envEntries: { name: string; kind: string }[],
  prefillOutput?: string,
  prefillSource?: string,
  editStageName?: string,
  existingStage?: import("./types").PipelineStage,
): string {
  const isEdit = editStageName !== undefined;
  const existingEnv =
    typeof existingStage?.environment === "string"
      ? existingStage.environment
      : "";
  const existingInputs = Array.isArray(existingStage?.inputs)
    ? (existingStage.inputs as string[]).filter((i) => typeof i === "string")
    : [];
  type OutputEntry = { path: string; storage: "dvc" | "git" };
  const existingOutputs: OutputEntry[] = Array.isArray(existingStage?.outputs)
    ? (
        existingStage.outputs as (string | { path: string; storage?: string })[]
      ).map((o) =>
        typeof o === "string"
          ? { path: o, storage: "dvc" as const }
          : {
              path: o.path,
              storage: (o.storage === "git" ? "git" : "dvc") as "dvc" | "git",
            },
      )
    : prefillOutput
    ? [{ path: prefillOutput, storage: "dvc" as const }]
    : [];

  // Source info for edit mode
  const sourceFile =
    typeof existingStage?.notebook_path === "string"
      ? existingStage.notebook_path
      : typeof existingStage?.script_path === "string"
      ? existingStage.script_path
      : typeof existingStage?.target_path === "string"
      ? existingStage.target_path
      : "";
  const stageKind =
    typeof existingStage?.kind === "string" ? existingStage.kind : "";

  const sourceOptions = workspaceFiles
    .map(
      (f) =>
        `<option value="${escHtml(f)}"${
          f === prefillSource ? " selected" : ""
        }>${escHtml(f)}</option>`,
    )
    .join("\n");
  const envOptions = [
    `<option value=""${!existingEnv ? " selected" : ""}>${
      isEdit ? "— none —" : "Detect automatically"
    }</option>`,
    ...envEntries.map(
      (e) =>
        `<option value="${escHtml(e.name)}"${
          e.name === existingEnv ? " selected" : ""
        }>${escHtml(e.name)}${e.kind ? ` (${escHtml(e.kind)})` : ""}</option>`,
    ),
    `<option value="__new__">New environment (enter spec path below)…</option>`,
  ].join("\n");

  const datalistOptions = allProjectFiles
    .map((f) => `<option value="${escHtml(f)}">`)
    .join("\n");

  const inputsJson = JSON.stringify(existingInputs);
  const outputsJson = JSON.stringify(existingOutputs); // [{path, storage}]

  const createSection = !isEdit
    ? `
<div class="field">
  <label>Source file</label>
  <select id="source">${sourceOptions}</select>
  <div id="kind-hint"></div>
</div>
<div class="field">
  <label>Stage name</label>
  <input id="stage-name" type="text" placeholder="Auto-generated if blank" />
</div>`
    : `
<div class="field">
  <label>Stage</label>
  <div class="info-row">${escHtml(editStageName ?? "")}</div>
</div>
${
  stageKind
    ? `<div class="field"><label>Kind</label><div class="info-row">${escHtml(
        stageKind,
      )}</div></div>`
    : ""
}
${
  sourceFile
    ? `<div class="field"><label>Source</label><div class="info-row">${escHtml(
        sourceFile,
      )}</div></div>`
    : ""
}`;

  const buttons = !isEdit
    ? `<button id="btn-create">Create Stage &amp; Run</button>`
    : `<button id="btn-save">Save</button> <button id="btn-save-run" style="margin-left:8px">Save &amp; Run</button>`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline';">
<title>${isEdit ? "Edit Stage" : "New Pipeline Stage"}</title>
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); padding: 20px; max-width: 580px; }
  h1 { font-size: 1.2em; margin-bottom: 18px; }
  .field { margin-bottom: 14px; }
  label { display: block; margin-bottom: 4px; font-weight: 600; color: var(--vscode-descriptionForeground); font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.04em; }
  input, select { width: 100%; box-sizing: border-box; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, #555); padding: 5px 8px; font-size: 1em; font-family: inherit; border-radius: 2px; }
  input:focus, select:focus { outline: 1px solid var(--vscode-focusBorder); border-color: var(--vscode-focusBorder); }
  .info-row { padding: 4px 0; color: var(--vscode-foreground); opacity: 0.8; }
  #kind-hint { font-size: 0.8em; color: var(--vscode-descriptionForeground); margin-top: 3px; height: 1.2em; }
  #new-env-row { margin-top: 6px; display: none; }
  .list-section { border: 1px solid var(--vscode-input-border, #555); border-radius: 2px; padding: 6px 8px; }
  .list-item { display: flex; gap: 6px; margin-bottom: 4px; align-items: center; position: relative; }
  .list-item input { flex: 1; min-width: 0; }
  .remove-btn { background: none; border: none; color: var(--vscode-descriptionForeground); cursor: pointer; font-size: 1.1em; padding: 2px 4px; margin-top: 0; flex-shrink: 0; }
  .remove-btn:hover { color: var(--vscode-foreground); }
  .add-btn { background: none; border: none; color: var(--vscode-textLink-foreground); cursor: pointer; font-size: 0.9em; padding: 2px 0; margin-top: 4px; }
  .add-btn:hover { text-decoration: underline; }
  .actions { margin-top: 20px; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 7px 18px; cursor: pointer; font-size: 1em; border-radius: 2px; margin-top: 0; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  .ac-wrap { position: relative; flex: 1; min-width: 0; }
  .ac-wrap input { width: 100%; box-sizing: border-box; }
  .ac-dropdown { position: absolute; top: 100%; left: 0; right: 0; z-index: 100; background: var(--vscode-input-background); border: 1px solid var(--vscode-focusBorder); list-style: none; margin: 0; padding: 0; max-height: 180px; overflow-y: auto; }
  .ac-dropdown li { padding: 4px 8px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ac-dropdown li:hover, .ac-dropdown li.ac-sel { background: var(--vscode-list-hoverBackground); }
</style>
</head>
<body>
<h1>${
    isEdit
      ? `Edit Stage: ${escHtml(editStageName ?? "")}`
      : "New Pipeline Stage"
  }</h1>
${createSection}
<div class="field">
  <label>Environment</label>
  <select id="env">${envOptions}</select>
  <div id="new-env-row">
    <input id="new-env-path" type="text" placeholder="e.g. pyproject.toml, environment.yml, Dockerfile" />
  </div>
</div>
<div class="field">
  <label>Inputs</label>
  <div class="list-section">
    <div id="inputs-list"></div>
    <button class="add-btn" id="add-input">+ Add input</button>
  </div>
</div>
<div class="field">
  <label>Outputs</label>
  <div class="list-section">
    <div id="outputs-list"></div>
    <button class="add-btn" id="add-output">+ Add output</button>
  </div>
</div>
<div class="actions">${buttons}</div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const kindByExt = ${JSON.stringify(KIND_BY_EXT)};
  const isEdit = ${JSON.stringify(isEdit)};
  const allProjectFiles = ${JSON.stringify(allProjectFiles)};

  function getKind(filePath) {
    const dot = filePath.lastIndexOf('.');
    return dot >= 0 ? (kindByExt[filePath.slice(dot)] ?? 'script') : '';
  }
  function slugify(s) {
    return s.replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase();
  }
  function attachAutocomplete(inp) {
    let dropdown = null;
    let selIdx = -1;
    function close() {
      if (dropdown) { dropdown.remove(); dropdown = null; }
      selIdx = -1;
    }
    function open(items) {
      close();
      if (!items.length) return;
      dropdown = document.createElement('ul');
      dropdown.className = 'ac-dropdown';
      items.forEach(function(text, i) {
        const li = document.createElement('li');
        li.textContent = text;
        li.addEventListener('mousedown', function(e) {
          e.preventDefault();
          inp.value = text;
          close();
        });
        dropdown.appendChild(li);
      });
      inp.closest('.ac-wrap').appendChild(dropdown);
    }
    function highlight(idx) {
      if (!dropdown) return;
      const items = dropdown.querySelectorAll('li');
      items.forEach(function(li, i) { li.classList.toggle('ac-sel', i === idx); });
      if (idx >= 0 && items[idx]) items[idx].scrollIntoView({ block: 'nearest' });
    }
    inp.addEventListener('input', function() {
      const val = inp.value.toLowerCase();
      const filtered = allProjectFiles.filter(function(f) { return f.toLowerCase().includes(val); }).slice(0, 30);
      open(filtered);
      selIdx = -1;
    });
    inp.addEventListener('keydown', function(e) {
      if (!dropdown) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          const filtered = allProjectFiles.filter(function(f) { return f.toLowerCase().includes(inp.value.toLowerCase()); }).slice(0, 30);
          open(filtered);
          selIdx = 0;
          highlight(selIdx);
        }
        return;
      }
      const items = dropdown.querySelectorAll('li');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selIdx = Math.min(selIdx + 1, items.length - 1);
        highlight(selIdx);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selIdx = Math.max(selIdx - 1, -1);
        highlight(selIdx);
      } else if (e.key === 'Enter' && selIdx >= 0) {
        e.preventDefault();
        inp.value = items[selIdx].textContent;
        close();
      } else if (e.key === 'Escape') {
        close();
      } else if (e.key === 'Tab') {
        if (selIdx >= 0) { inp.value = items[selIdx].textContent; }
        close();
      }
    });
    inp.addEventListener('blur', function() { setTimeout(close, 150); });
  }
  function makeListItem(listEl, value, withStorage) {
    const row = document.createElement('div');
    row.className = 'list-item';
    const wrap = document.createElement('div');
    wrap.className = 'ac-wrap';
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.value = (withStorage ? value.path : value) || '';
    attachAutocomplete(inp);
    wrap.appendChild(inp);
    row.appendChild(wrap);
    if (withStorage) {
      const sel = document.createElement('select');
      sel.className = 'storage-sel';
      sel.style.width = 'auto';
      sel.style.flexShrink = '0';
      [['dvc', 'DVC'], ['git', 'Git']].forEach(function([s, label]) {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = label;
        if (s === (value.storage || 'dvc')) { opt.selected = true; }
        sel.appendChild(opt);
      });
      row.appendChild(sel);
    }
    const btn = document.createElement('button');
    btn.className = 'remove-btn';
    btn.textContent = '×';
    btn.title = 'Remove';
    btn.addEventListener('click', function() { row.remove(); });
    row.appendChild(btn);
    listEl.appendChild(row);
    return inp;
  }
  function getInputValues(listEl) {
    return Array.from(listEl.querySelectorAll('input')).map(function(i) { return i.value.trim(); }).filter(Boolean);
  }
  function getOutputValues(listEl) {
    return Array.from(listEl.querySelectorAll('.list-item')).map(function(row) {
      const path = row.querySelector('input').value.trim();
      const sel = row.querySelector('select.storage-sel');
      return path ? { path: path, storage: sel ? sel.value : 'dvc' } : null;
    }).filter(Boolean);
  }

  const inputsList = document.getElementById('inputs-list');
  const outputsList = document.getElementById('outputs-list');
  const envEl = document.getElementById('env');
  const newEnvRow = document.getElementById('new-env-row');
  const newEnvPath = document.getElementById('new-env-path');

  // Pre-populate lists
  ${inputsJson}.forEach(function(v) { makeListItem(inputsList, v, false); });
  ${outputsJson}.forEach(function(v) { makeListItem(outputsList, v, true); });

  document.getElementById('add-input').addEventListener('click', function() {
    const inp = makeListItem(inputsList, '', false);
    inp.focus();
  });
  document.getElementById('add-output').addEventListener('click', function() {
    const inp = makeListItem(outputsList, { path: '', storage: 'dvc' }, true);
    inp.focus();
  });

  envEl.addEventListener('change', function() {
    newEnvRow.style.display = envEl.value === '__new__' ? 'block' : 'none';
  });

  function resolvedEnv() {
    return envEl.value === '__new__' ? newEnvPath.value.trim() : envEl.value;
  }

  if (!isEdit) {
    const sourceEl = document.getElementById('source');
    const stageNameEl = document.getElementById('stage-name');
    const kindHint = document.getElementById('kind-hint');
    let stageNameEdited = false;

    function firstOutputPath() {
      const first = outputsList.querySelector('input');
      return first ? first.value.trim() : '';
    }
    function updateKindHint() {
      const kind = getKind(sourceEl.value);
      kindHint.textContent = kind ? 'Kind: ' + kind : '';
    }
    function updateStageName() {
      if (!stageNameEdited) {
        const out = firstOutputPath();
        stageNameEl.value = out
          ? slugify(out.replace(/\\.[^.]+$/, ''))
          : slugify(sourceEl.value.replace(/\\.[^.]+$/, ''));
      }
    }
    sourceEl.addEventListener('change', function() { updateKindHint(); updateStageName(); });
    outputsList.addEventListener('input', updateStageName);
    stageNameEl.addEventListener('input', function() { stageNameEdited = true; });
    updateKindHint();
    updateStageName();

    document.getElementById('btn-create').addEventListener('click', function() {
      if (!sourceEl.value) { return; }
      const outs = getOutputValues(outputsList);
      const primaryOut = outs.length > 0 ? outs[0] : null;
      vscode.postMessage({
        command: 'create',
        source: sourceEl.value,
        environment: resolvedEnv(),
        output: primaryOut ? primaryOut.path : '',
        outputStorage: primaryOut ? primaryOut.storage : 'dvc',
        stageName: stageNameEl.value.trim(),
        inputs: getInputValues(inputsList),
        outputs: outs,
        andRun: true,
      });
    });
  } else {
    function save(andRun) {
      vscode.postMessage({
        command: 'save',
        environment: resolvedEnv(),
        inputs: getInputValues(inputsList),
        outputs: getOutputValues(outputsList),
        andRun,
      });
    }
    document.getElementById('btn-save').addEventListener('click', function() { save(false); });
    document.getElementById('btn-save-run').addEventListener('click', function() { save(true); });
  }
</script>
</body>
</html>`;
}

function escHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function openFiguresCarousel(
  context: vscode.ExtensionContext,
  workspaceRoot: string,
  figurePaths: string[],
  startIndex: number,
): void {
  const panel = vscode.window.createWebviewPanel(
    "calkit.figuresCarousel",
    "Figures",
    vscode.ViewColumn.Active,
    {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.file(workspaceRoot)],
    },
  );
  context.subscriptions.push(panel);

  // Build per-figure data: webview URI + provenance metadata
  const figList = currentCalkitConfig?.figures ?? [];
  type FigureData = {
    path: string;
    uriStr: string;
    ext: string;
    stage: string | undefined;
    importedFrom: string | undefined;
    title: string | undefined;
    description: string | undefined;
  };
  const figures: FigureData[] = figurePaths.map((p) => {
    const absUri = vscode.Uri.file(path.join(workspaceRoot, p));
    const webviewUri = panel.webview.asWebviewUri(absUri);
    const entry = figList.find((f) => f.path === p);
    const importedFrom =
      entry?.imported_from != null
        ? typeof entry.imported_from === "object" &&
          "url" in (entry.imported_from as object)
          ? (entry.imported_from as { url: string }).url
          : JSON.stringify(entry.imported_from)
        : undefined;
    return {
      path: p,
      uriStr: webviewUri.toString(),
      ext: path.extname(p).toLowerCase(),
      stage: typeof entry?.stage === "string" ? entry.stage : undefined,
      importedFrom,
      title: typeof entry?.title === "string" ? entry.title : undefined,
      description:
        typeof entry?.description === "string" ? entry.description : undefined,
    };
  });

  const nonce = getNonce();
  panel.webview.html = buildCarouselHtml(
    nonce,
    figures,
    startIndex,
    panel.webview.cspSource,
  );
}

function buildCarouselHtml(
  nonce: string,
  figures: {
    path: string;
    uriStr: string;
    ext: string;
    stage: string | undefined;
    importedFrom: string | undefined;
    title: string | undefined;
    description: string | undefined;
  }[],
  startIndex: number,
  cspSource: string,
): string {
  const RENDERABLE = new Set([
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".html",
    ".htm",
  ]);
  const figuresJson = JSON.stringify(figures);
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${
    figures.length > 0 ? cspSource : "'none'"
  } data:; frame-src ${cspSource}; object-src ${cspSource}; script-src 'nonce-${nonce}'; style-src 'unsafe-inline';">
<title>Figures</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); background: var(--vscode-editor-background); }
  #root { display: flex; flex-direction: column; height: 100vh; }
  #toolbar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--vscode-panel-border, #444); flex-shrink: 0; }
  #counter { color: var(--vscode-descriptionForeground); font-size: 0.85em; white-space: nowrap; }
  #path-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.9em; opacity: 0.8; }
  #viewer { flex: 1; position: relative; display: flex; align-items: center; justify-content: center; overflow: hidden; }
  #fig-content { max-width: 100%; max-height: 100%; display: flex; align-items: center; justify-content: center; }
  #fig-content img { max-width: 100%; max-height: calc(100vh - 140px); object-fit: contain; display: block; }
  #fig-content embed, #fig-content iframe { width: 100%; height: calc(100vh - 140px); border: none; background: white; }
  .no-render { color: var(--vscode-descriptionForeground); font-size: 0.9em; padding: 20px; text-align: center; }
  .nav-btn { background: var(--vscode-button-secondaryBackground, rgba(128,128,128,0.2)); color: var(--vscode-button-secondaryForeground, inherit); border: none; border-radius: 4px; padding: 6px 14px; cursor: pointer; font-size: 1.1em; flex-shrink: 0; }
  .nav-btn:hover:not(:disabled) { background: var(--vscode-button-secondaryHoverBackground, rgba(128,128,128,0.35)); }
  .nav-btn:disabled { opacity: 0.35; cursor: default; }
  #metadata { flex-shrink: 0; padding: 8px 12px; border-top: 1px solid var(--vscode-panel-border, #444); font-size: 0.82em; display: flex; gap: 16px; flex-wrap: wrap; }
  .meta-item { display: flex; gap: 4px; }
  .meta-label { color: var(--vscode-descriptionForeground); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.85em; }
  .meta-value { color: var(--vscode-foreground); opacity: 0.85; }
  #dots { display: flex; gap: 5px; align-items: center; overflow-x: auto; max-width: 300px; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--vscode-descriptionForeground); opacity: 0.35; cursor: pointer; flex-shrink: 0; }
  .dot.active { opacity: 1; background: var(--vscode-focusBorder, #007fd4); }
</style>
</head>
<body>
<div id="root">
  <div id="toolbar">
    <button class="nav-btn" id="btn-prev">&#8592;</button>
    <div id="dots"></div>
    <button class="nav-btn" id="btn-next">&#8594;</button>
    <span id="counter"></span>
    <span id="path-label"></span>
  </div>
  <div id="viewer">
    <div id="fig-content"></div>
  </div>
  <div id="metadata" id="metadata"></div>
</div>
<script nonce="${nonce}">
  const RENDERABLE = ${JSON.stringify([...RENDERABLE])};
  const figures = ${figuresJson};
  let idx = ${Math.max(0, Math.min(startIndex, figures.length - 1))};

  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const counter = document.getElementById('counter');
  const pathLabel = document.getElementById('path-label');
  const figContent = document.getElementById('fig-content');
  const metadata = document.getElementById('metadata');
  const dotsEl = document.getElementById('dots');

  // Build dots
  figures.forEach(function(_, i) {
    const dot = document.createElement('div');
    dot.className = 'dot';
    dot.addEventListener('click', function() { navigate(i); });
    dotsEl.appendChild(dot);
  });

  function navigate(newIdx) {
    idx = newIdx;
    render();
  }

  function render() {
    const fig = figures[idx];
    // Update toolbar
    counter.textContent = (idx + 1) + ' / ' + figures.length;
    pathLabel.textContent = fig.path;
    pathLabel.title = fig.path;
    btnPrev.disabled = idx === 0;
    btnNext.disabled = idx === figures.length - 1;
    // Update dots
    Array.from(dotsEl.querySelectorAll('.dot')).forEach(function(d, i) {
      d.classList.toggle('active', i === idx);
    });
    // Render figure
    figContent.innerHTML = '';
    const ext = fig.ext;
    if (ext === '.png' || ext === '.jpg' || ext === '.jpeg' || ext === '.gif' || ext === '.svg') {
      const img = document.createElement('img');
      img.src = fig.uriStr;
      img.alt = fig.path;
      figContent.appendChild(img);
    } else if (ext === '.pdf') {
      const embed = document.createElement('embed');
      embed.src = fig.uriStr;
      embed.type = 'application/pdf';
      embed.style.width = '100%';
      embed.style.height = 'calc(100vh - 140px)';
      figContent.appendChild(embed);
    } else if (ext === '.html' || ext === '.htm') {
      const frame = document.createElement('iframe');
      frame.src = fig.uriStr;
      frame.style.width = '100%';
      frame.style.height = 'calc(100vh - 140px)';
      frame.style.border = 'none';
      figContent.appendChild(frame);
    } else {
      const msg = document.createElement('div');
      msg.className = 'no-render';
      msg.textContent = 'Preview not available for ' + ext + ' files.';
      figContent.appendChild(msg);
    }
    // Update metadata
    metadata.innerHTML = '';
    function metaItem(label, value) {
      if (!value) return;
      const div = document.createElement('div');
      div.className = 'meta-item';
      const lbl = document.createElement('span');
      lbl.className = 'meta-label';
      lbl.textContent = label + ':';
      const val = document.createElement('span');
      val.className = 'meta-value';
      val.textContent = value;
      div.appendChild(lbl);
      div.appendChild(val);
      metadata.appendChild(div);
    }
    metaItem('Title', fig.title);
    metaItem('Stage', fig.stage);
    metaItem('Imported from', fig.importedFrom);
    metaItem('Description', fig.description);
  }

  btnPrev.addEventListener('click', function() { if (idx > 0) navigate(idx - 1); });
  btnNext.addEventListener('click', function() { if (idx < figures.length - 1) navigate(idx + 1); });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowLeft' && idx > 0) navigate(idx - 1);
    if (e.key === 'ArrowRight' && idx < figures.length - 1) navigate(idx + 1);
  });

  render();
</script>
</body>
</html>`;
}

// ─── File history panel ───────────────────────────────────────────────────────

interface CommitInfo {
  hash: string;
  shortHash: string;
  subject: string;
  author: string;
  date: string;
}

function readGitFileAtRef(
  workspaceRoot: string,
  ref: string,
  filePath: string,
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    const proc = spawn("git", ["show", `${ref}:${filePath}`], {
      cwd: workspaceRoot,
    });
    proc.stdout.on("data", (chunk: Buffer) => chunks.push(chunk));
    proc.on("error", reject);
    proc.on("close", (code) => {
      if (code === 0) {
        resolve(Buffer.concat(chunks));
      } else {
        reject(new Error(`git show exited with code ${code}`));
      }
    });
  });
}

function extToMime(ext: string): string {
  const map: Record<string, string> = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
  };
  return map[ext.toLowerCase()] ?? "application/octet-stream";
}

async function getGitHistory(
  workspaceRoot: string,
  filePath: string,
): Promise<CommitInfo[]> {
  try {
    const { stdout } = await execFileAsync(
      "git",
      [
        "log",
        "--follow",
        "-n",
        "50",
        "--format=%H|%h|%s|%an|%ai",
        "--",
        filePath,
      ],
      { cwd: workspaceRoot },
    );
    return stdout
      .trim()
      .split("\n")
      .filter(Boolean)
      .map((line) => {
        const [hash, shortHash, ...rest] = line.split("|");
        const subject = rest.slice(0, -2).join("|");
        const author = rest[rest.length - 2];
        const date = rest[rest.length - 1];
        return { hash, shortHash, subject, author, date };
      });
  } catch {
    return [];
  }
}

async function openFileHistoryPanel(
  context: vscode.ExtensionContext,
  workspaceRoot: string,
  filePath: string,
): Promise<void> {
  const ext = path.extname(filePath).toLowerCase();
  const mime = extToMime(ext);
  const absPath = path.join(workspaceRoot, filePath);

  const panel = vscode.window.createWebviewPanel(
    "calkit.fileHistory",
    `History: ${path.basename(filePath)}`,
    vscode.ViewColumn.Active,
    { enableScripts: true },
  );
  context.subscriptions.push(panel);

  const nonce = getNonce();
  const history = await getGitHistory(workspaceRoot, filePath);

  // Load current HEAD content from disk
  let headDataUri = "";
  try {
    const buf = await import("node:fs/promises").then((fs) =>
      fs.readFile(absPath),
    );
    headDataUri = `data:${mime};base64,${buf.toString("base64")}`;
  } catch {
    // file may not exist on disk yet
  }

  panel.webview.html = buildFileHistoryHtml(
    nonce,
    filePath,
    ext,
    mime,
    history,
    headDataUri,
  );

  panel.webview.onDidReceiveMessage(
    async (msg: { command: string; ref: string }) => {
      if (msg.command !== "getContent") {
        return;
      }
      let dataUri = "";
      try {
        const buf = await readGitFileAtRef(workspaceRoot, msg.ref, filePath);
        dataUri = `data:${mime};base64,${buf.toString("base64")}`;
      } catch {
        // file may not exist at this ref (e.g. DVC-tracked)
        try {
          const dvcBuf = await readGitFileAtRef(
            workspaceRoot,
            msg.ref,
            `${filePath}.dvc`,
          );
          void panel.webview.postMessage({
            command: "contentError",
            ref: msg.ref,
            reason: `DVC-tracked file. Pointer at this commit:\n${dvcBuf
              .toString("utf8")
              .trim()}`,
          });
          return;
        } catch {
          void panel.webview.postMessage({
            command: "contentError",
            ref: msg.ref,
            reason: "File not found in git at this commit.",
          });
          return;
        }
      }
      void panel.webview.postMessage({
        command: "content",
        ref: msg.ref,
        dataUri,
      });
    },
    undefined,
    context.subscriptions,
  );
}

function buildFileHistoryHtml(
  nonce: string,
  filePath: string,
  ext: string,
  _mime: string,
  history: CommitInfo[],
  headDataUri: string,
): string {
  const isImage =
    ext === ".png" ||
    ext === ".jpg" ||
    ext === ".jpeg" ||
    ext === ".gif" ||
    ext === ".svg";
  const isPdf = ext === ".pdf";
  const isHtml = ext === ".html" || ext === ".htm";
  const isRenderable = isImage || isPdf || isHtml;

  const historyJson = JSON.stringify(history);

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; frame-src data: blob:; object-src data: blob:; script-src 'nonce-${nonce}'; style-src 'unsafe-inline';">
<title>History: ${escHtml(path.basename(filePath))}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); background: var(--vscode-editor-background); overflow: hidden; }
  #root { display: flex; height: 100vh; }

  /* History sidebar */
  #sidebar { width: 210px; flex-shrink: 0; border-right: 1px solid var(--vscode-panel-border, #444); display: flex; flex-direction: column; overflow: hidden; }
  #sidebar-header { padding: 8px 10px; font-size: 0.8em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--vscode-descriptionForeground); border-bottom: 1px solid var(--vscode-panel-border, #444); flex-shrink: 0; }
  #commits { overflow-y: auto; flex: 1; }
  .commit { padding: 8px 10px; cursor: pointer; border-bottom: 1px solid var(--vscode-panel-border, #333); position: relative; }
  .commit:hover { background: var(--vscode-list-hoverBackground); }
  .commit.selected-a { background: var(--vscode-list-activeSelectionBackground); color: var(--vscode-list-activeSelectionForeground); }
  .commit.selected-b { background: color-mix(in srgb, var(--vscode-list-activeSelectionBackground) 60%, purple 40%); color: var(--vscode-list-activeSelectionForeground); }
  .commit-hash { font-family: monospace; font-size: 0.8em; opacity: 0.7; }
  .commit-subject { font-size: 0.85em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 175px; margin: 2px 0 1px; }
  .commit-meta { font-size: 0.75em; opacity: 0.6; }
  .badge { display: inline-block; font-size: 0.7em; font-weight: 700; padding: 1px 5px; border-radius: 3px; margin-left: 4px; vertical-align: middle; }
  .badge-a { background: #1a6fb5; color: #fff; }
  .badge-b { background: #7b31c9; color: #fff; }
  #clear-btn { display: none; margin: 6px 10px; background: none; border: 1px solid var(--vscode-panel-border, #444); color: var(--vscode-foreground); padding: 3px 10px; cursor: pointer; font-size: 0.82em; border-radius: 3px; }
  #clear-btn:hover { background: var(--vscode-list-hoverBackground); }

  /* Main view */
  #main { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
  #toolbar { padding: 6px 12px; border-bottom: 1px solid var(--vscode-panel-border, #444); font-size: 0.82em; color: var(--vscode-descriptionForeground); flex-shrink: 0; display: flex; align-items: center; gap: 8px; }
  .ref-badge { font-family: monospace; font-size: 0.95em; padding: 1px 6px; border-radius: 3px; color: #fff; }
  .ref-badge.a { background: #1a6fb5; }
  .ref-badge.b { background: #7b31c9; }
  #view-area { flex: 1; overflow: hidden; display: flex; min-height: 0; }
  .pane { flex: 1; overflow: auto; display: flex; align-items: center; justify-content: center; position: relative; min-width: 0; }
  .pane + .pane { border-left: 1px solid var(--vscode-panel-border, #444); }
  .pane img { max-width: 100%; max-height: 100%; object-fit: contain; display: block; }
  .pane embed, .pane iframe { width: 100%; height: 100%; border: none; background: white; }
  .pane-label { position: absolute; top: 6px; left: 8px; font-size: 0.75em; font-weight: 700; padding: 1px 6px; border-radius: 3px; color: #fff; z-index: 1; }
  .pane-label.a { background: #1a6fb5; }
  .pane-label.b { background: #7b31c9; }
  .no-render, .loading, .err { color: var(--vscode-descriptionForeground); font-size: 0.88em; padding: 20px; text-align: center; white-space: pre-wrap; }
  .err { color: var(--vscode-errorForeground, #f44); }
</style>
</head>
<body>
<div id="root">
  <div id="sidebar">
    <div id="sidebar-header">Version History</div>
    <button id="clear-btn">Clear selection</button>
    <div id="commits"></div>
  </div>
  <div id="main">
    <div id="toolbar"><span id="toolbar-text">Current version</span></div>
    <div id="view-area">
      <div class="pane" id="pane-a"></div>
      <div class="pane" id="pane-b" style="display:none"></div>
    </div>
  </div>
</div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const history = ${historyJson};
  const isRenderable = ${JSON.stringify(isRenderable)};
  const isImage = ${JSON.stringify(isImage)};
  const isPdf = ${JSON.stringify(isPdf)};
  const isHtml = ${JSON.stringify(isHtml)};
  const headDataUri = ${JSON.stringify(headDataUri)};
  const fileName = ${JSON.stringify(path.basename(filePath))};

  let refA = null;
  let refB = null;
  const pending = {}; // ref -> [resolve, reject]

  const commitsEl = document.getElementById('commits');
  const paneA = document.getElementById('pane-a');
  const paneB = document.getElementById('pane-b');
  const toolbarText = document.getElementById('toolbar-text');
  const clearBtn = document.getElementById('clear-btn');

  // ── Build commit list ──
  if (history.length === 0) {
    commitsEl.innerHTML = '<div class="commit" style="cursor:default;opacity:0.6">No history found.</div>';
  } else {
    history.forEach(function(c) {
      const el = document.createElement('div');
      el.className = 'commit';
      el.dataset.hash = c.shortHash;
      el.innerHTML =
        '<div class="commit-hash">' + esc(c.shortHash) + '</div>' +
        '<div class="commit-subject">' + esc(c.subject) + '</div>' +
        '<div class="commit-meta">' + esc(formatDate(c.date)) + ' · ' + esc(c.author) + '</div>';
      el.addEventListener('click', function() { onCommitClick(c.shortHash); });
      commitsEl.appendChild(el);
    });
  }

  function formatDate(iso) {
    try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
  }
  function esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Pane rendering ──
  function renderInPane(paneEl, dataUri, label) {
    paneEl.innerHTML = '';
    if (label) {
      const lb = document.createElement('div');
      lb.className = 'pane-label ' + label;
      lb.textContent = label.toUpperCase();
      paneEl.appendChild(lb);
    }
    if (!isRenderable) {
      const msg = document.createElement('div');
      msg.className = 'no-render';
      msg.textContent = 'Preview not available for this file type.';
      paneEl.appendChild(msg);
      return;
    }
    if (isImage) {
      const img = document.createElement('img');
      img.src = dataUri;
      paneEl.appendChild(img);
    } else if (isPdf) {
      const embed = document.createElement('embed');
      embed.src = dataUri;
      embed.type = 'application/pdf';
      embed.style.cssText = 'width:100%;height:100%;border:none';
      paneEl.appendChild(embed);
    } else if (isHtml) {
      const frame = document.createElement('iframe');
      frame.src = dataUri;
      frame.style.cssText = 'width:100%;height:100%;border:none';
      paneEl.appendChild(frame);
    }
  }

  function showLoading(paneEl, label) {
    paneEl.innerHTML = '';
    if (label) {
      const lb = document.createElement('div');
      lb.className = 'pane-label ' + label;
      lb.textContent = label.toUpperCase();
      paneEl.appendChild(lb);
    }
    const msg = document.createElement('div');
    msg.className = 'loading';
    msg.textContent = 'Loading…';
    paneEl.appendChild(msg);
  }

  function showError(paneEl, label, reason) {
    paneEl.innerHTML = '';
    if (label) {
      const lb = document.createElement('div');
      lb.className = 'pane-label ' + label;
      lb.textContent = label.toUpperCase();
      paneEl.appendChild(lb);
    }
    const msg = document.createElement('div');
    msg.className = 'err';
    msg.textContent = reason;
    paneEl.appendChild(msg);
  }

  // ── Toolbar ──
  function updateToolbar() {
    if (!refA && !refB) {
      toolbarText.textContent = 'Current version · ' + fileName;
      clearBtn.style.display = 'none';
    } else if (refA && !refB) {
      toolbarText.innerHTML = '<span class="ref-badge a">A</span> <code>' + esc(refA) + '</code> · click another commit to compare';
      clearBtn.style.display = 'inline-block';
    } else {
      toolbarText.innerHTML = '<span class="ref-badge a">A</span> <code>' + esc(refA) + '</code> &nbsp; vs &nbsp; <span class="ref-badge b">B</span> <code>' + esc(refB) + '</code>';
      clearBtn.style.display = 'inline-block';
    }
  }

  function updateCommitHighlights() {
    commitsEl.querySelectorAll('.commit').forEach(function(el) {
      el.classList.remove('selected-a', 'selected-b');
      const h = el.dataset.hash;
      if (h === refA) el.classList.add('selected-a');
      else if (h === refB) el.classList.add('selected-b');
      // update badges inside
      el.querySelectorAll('.badge').forEach(function(b) { b.remove(); });
      const hashEl = el.querySelector('.commit-hash');
      if (h === refA) { const b = document.createElement('span'); b.className = 'badge badge-a'; b.textContent = 'A'; hashEl.appendChild(b); }
      if (h === refB) { const b = document.createElement('span'); b.className = 'badge badge-b'; b.textContent = 'B'; hashEl.appendChild(b); }
    });
  }

  // ── Fetch content ──
  function getContent(ref) {
    return new Promise(function(resolve, reject) {
      pending[ref] = [resolve, reject];
      vscode.postMessage({ command: 'getContent', ref: ref });
    });
  }

  window.addEventListener('message', function(event) {
    const msg = event.data;
    if (msg.command === 'content') {
      if (pending[msg.ref]) { pending[msg.ref][0](msg.dataUri); delete pending[msg.ref]; }
    } else if (msg.command === 'contentError') {
      if (pending[msg.ref]) { pending[msg.ref][1](new Error(msg.reason)); delete pending[msg.ref]; }
    }
  });

  // ── Navigation ──
  function onCommitClick(hash) {
    if (!refA || refA === hash) {
      refA = hash;
      refB = null;
    } else if (!refB) {
      refB = hash;
    } else {
      refA = hash;
      refB = null;
    }
    updateCommitHighlights();
    updateToolbar();
    refreshView();
  }

  clearBtn.addEventListener('click', function() {
    refA = null;
    refB = null;
    updateCommitHighlights();
    updateToolbar();
    refreshView();
  });

  function refreshView() {
    if (!refA && !refB) {
      // Show current disk version
      paneB.style.display = 'none';
      paneA.style.flex = '1';
      if (headDataUri) {
        renderInPane(paneA, headDataUri, null);
      } else {
        showError(paneA, null, 'File not available on disk.');
      }
      return;
    }
    if (refA && !refB) {
      paneB.style.display = 'none';
      paneA.style.flex = '1';
      showLoading(paneA, 'a');
      getContent(refA).then(function(uri) {
        renderInPane(paneA, uri, 'a');
      }).catch(function(e) {
        showError(paneA, 'a', e.message);
      });
      return;
    }
    // Compare mode
    paneB.style.display = '';
    paneA.style.flex = '1';
    paneB.style.flex = '1';
    showLoading(paneA, 'a');
    showLoading(paneB, 'b');
    getContent(refA).then(function(uri) { renderInPane(paneA, uri, 'a'); }).catch(function(e) { showError(paneA, 'a', e.message); });
    getContent(refB).then(function(uri) { renderInPane(paneB, uri, 'b'); }).catch(function(e) { showError(paneB, 'b', e.message); });
  }

  // ── Init ──
  updateToolbar();
  refreshView();
</script>
</body>
</html>`;
}

function getOrCreateTerminal(name: string, cwd: string): vscode.Terminal {
  const existing = vscode.window.terminals.find((t) => t.name === name);
  if (existing) {
    return existing;
  }
  return vscode.window.createTerminal({ name, cwd });
}

function runStageInTerminal(workspaceRoot: string, stageName: string): void {
  const terminal = getOrCreateTerminal("calkit: run", workspaceRoot);
  terminal.show();
  terminal.sendText(`calkit run ${shQuote(stageName)}`);
}

async function findStageForFile(
  workspaceRoot: string,
  fileUri: vscode.Uri,
): Promise<string | undefined> {
  const relPath = path
    .relative(workspaceRoot, fileUri.fsPath)
    .replace(/\\/g, "/");
  const [dvcYaml, calkitConfig] = await Promise.all([
    readDvcYaml(workspaceRoot),
    readCalkitConfig(workspaceRoot),
  ]);
  for (const [stageName, stage] of Object.entries(dvcYaml?.stages ?? {})) {
    if (dvcStageOutputPaths(stage).includes(relPath)) {
      return stageName;
    }
  }
  for (const [stageName, stage] of Object.entries(
    calkitConfig?.pipeline?.stages ?? {},
  )) {
    if (
      stage.notebook_path === relPath ||
      stage.script_path === relPath ||
      stage.target_path === relPath
    ) {
      return stageName;
    }
  }
  return undefined;
}

async function selectCalkitEnvironment(
  context: vscode.ExtensionContext,
): Promise<string | undefined> {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    void vscode.window.showErrorMessage(
      "Open a workspace folder to use Calkit notebook environments.",
    );
    return undefined;
  }

  let picked: CalkitEnvNotebookKernelSource | undefined;
  let config: CalkitInfo | undefined;
  while (!picked) {
    config = await readCalkitConfig(workspaceRoot);
    if (!config) {
      return undefined;
    }

    const environments = config.environments ?? {};
    const candidates = makeCalkitEnvKernelSourceCandidates(environments);
    const items: Array<
      | (CalkitEnvNotebookKernelSource & { action: "select" })
      | vscode.QuickPickItem
    > = candidates.map((candidate) => ({
      ...candidate,
      action: "select",
    }));

    items.push({
      label: "$(add) Create new Calkit environment...",
    });

    const selected = await vscode.window.showQuickPick(items, {
      placeHolder: "Select a Calkit environment for this notebook",
      matchOnDescription: true,
      matchOnDetail: true,
    });

    if (!selected) {
      await refreshNotebookToolbarContext(context);
      return undefined;
    }

    if ((selected as { action?: string }).action === "select") {
      picked = selected as CalkitEnvNotebookKernelSource;
      break;
    }

    picked = await runCreateNotebookEnvironmentCreationFlow(workspaceRoot);
  }

  if (!picked) {
    await refreshNotebookToolbarContext(context);
    return undefined;
  }

  // Re-read config after selection/create flow so SLURM defaults reflect the
  // latest calkit.yaml state (especially right after creating environments).
  config = await readCalkitConfig(workspaceRoot);
  if (!config) {
    await refreshNotebookToolbarContext(context);
    return undefined;
  }

  const targetNotebookUri = getActiveNotebookUriKey();
  if (!targetNotebookUri) {
    await refreshNotebookToolbarContext(context);
    return undefined;
  }

  // Save the environment selection to calkit.yaml
  const notebookRelativePath = getNotebookRelativePathForUri(
    workspaceRoot,
    targetNotebookUri,
  );
  if (notebookRelativePath) {
    await saveNotebookEnvironmentSelection(
      workspaceRoot,
      notebookRelativePath,
      picked.environmentName,
    );
  }

  // uv environments should only register/check the kernel and then select it.
  // No Jupyter server launch is needed for this path.
  if (picked.innerKind === "uv") {
    const kernelId = await registerAndSelectKernel(
      workspaceRoot,
      picked.innerEnvironment,
      "-e",
      targetNotebookUri,
      picked.innerKind,
    );
    await refreshNotebookToolbarContext(context);
    return kernelId;
  }

  let slurmOptions: SlurmLaunchOptions | undefined;
  if (picked.outerSlurmEnvironment) {
    const defaultSlurmOptions = getNotebookSlurmOptionsWithDefaults(
      getDefaultSlurmOptions(
        config?.environments?.[picked.outerSlurmEnvironment],
      ),
    );
    slurmOptions = await chooseSlurmOptionsForLaunch(defaultSlurmOptions);
    if (!slurmOptions) {
      await refreshNotebookToolbarContext(context);
      return undefined;
    }
  }

  await saveLaunchProfileForNotebookUri(context, targetNotebookUri, {
    environmentName: picked.environmentName,
    innerEnvironment: picked.innerEnvironment,
    innerKind: picked.innerKind,
    outerSlurmEnvironment: picked.outerSlurmEnvironment,
    slurmOptions,
    preferredPort: getDefaultPort(),
  });

  if (picked.outerSlurmEnvironment) {
    slurmAutoStartSuppressedThisSession.delete(targetNotebookUri);
  }

  // For local/non-nested environments, only register/check the kernel and
  // then select it in VS Code. No server launch is needed here.
  if (
    !picked.outerSlurmEnvironment &&
    needsKernelRegistration(picked.innerKind)
  ) {
    const kernelId = await registerAndSelectKernel(
      workspaceRoot,
      picked.innerEnvironment,
      "-e",
      targetNotebookUri,
      picked.innerKind,
    );
    await refreshNotebookToolbarContext(context);
    return kernelId;
  }

  // Docker and Slurm environments need tokenized servers
  const needsToken =
    picked.outerSlurmEnvironment || picked.innerKind === "docker";
  const serverToken = needsToken ? createServerToken() : undefined;
  const port = getDefaultPort();
  let dockerContainerName: string | undefined;
  if (!picked.outerSlurmEnvironment && picked.innerKind === "docker") {
    dockerContainerName = getManagedDockerContainerName(
      picked.innerEnvironment,
      port,
    );
    await stopManagedDockerContainerIfExists(dockerContainerName);
    const portIsFree = await waitForPortToBeFree(port, 7_000);
    if (!portIsFree) {
      void vscode.window.showErrorMessage(
        `Cannot start Docker notebook server: localhost:${port} is already in use. Stop the process using that port or change 'calkit.notebook.defaultJupyterPort'.`,
      );
      return undefined;
    }
  }

  const expectedKernel = picked.outerSlurmEnvironment
    ? await getExpectedKernelSpecForEnvironment(
        workspaceRoot,
        picked.innerEnvironment,
        "-e",
      )
    : undefined;

  const launchCmd = buildLaunchCommand(
    picked,
    workspaceRoot,
    config,
    port,
    slurmOptions,
    serverToken,
    dockerContainerName,
    expectedKernel?.kernelName,
    notebookRelativePath,
  );

  startServerInBackground(launchCmd, workspaceRoot, {
    kind: picked.outerSlurmEnvironment
      ? "slurm"
      : picked.innerKind === "docker"
      ? "docker"
      : "other",
    notebookUri: targetNotebookUri,
  });

  const uri = serverToken
    ? `http://localhost:${port}/lab?token=${encodeURIComponent(serverToken)}`
    : `http://localhost:${port}/lab`;
  await vscode.env.clipboard.writeText(uri);
  const kernelsBeforeConnect =
    await getResolvedKernelIdsForActiveNotebook(targetNotebookUri);

  // Docker and Slurm environments require connecting to an existing server
  if (picked.outerSlurmEnvironment || picked.innerKind === "docker") {
    const envType = picked.outerSlurmEnvironment ? "Slurm" : "Docker";
    const runConnectFlow = async (): Promise<string | undefined> => {
      const serverReady = picked.outerSlurmEnvironment
        ? await waitForServerReady(uri, {
            sessionKind: "slurm",
            notebookUri: targetNotebookUri,
          })
        : await vscode.window.withProgress(
            {
              location: vscode.ProgressLocation.Notification,
              title: `${envType} notebook server starting...`,
              cancellable: false,
            },
            async () => {
              return await waitForServerReady(uri, {
                sessionKind: "docker",
                notebookUri: targetNotebookUri,
              });
            },
          );

      const connected = serverReady
        ? await selectExistingJupyterServer(uri)
        : false;

      // For Docker, we don't need to register a kernel separately since it should
      // be in the image, but we can try to select it if needed
      let selectedKernelId: string | undefined;
      if (picked.outerSlurmEnvironment && connected) {
        const expectedKernel = await getExpectedKernelSpecForEnvironment(
          workspaceRoot,
          picked.innerEnvironment,
          "-e",
        );
        selectedKernelId = expectedKernel
          ? await trySelectExpectedKernelFromAvailableCandidates({
              kernelName: expectedKernel.kernelName,
              displayName: expectedKernel.displayName,
              existingKernelIds: kernelsBeforeConnect,
              requireNewKernel: true,
              notebookUri: targetNotebookUri,
            })
          : undefined;
      } else if (picked.innerKind === "docker" && connected) {
        // After connecting to a Docker-backed server, try selecting a sensible
        // default kernel automatically before falling back to manual selection.
        selectedKernelId = await tryAutoSelectBestAvailableKernel({
          existingKernelIds: kernelsBeforeConnect,
          requireNewKernel: true,
        });
      }

      if (!connected) {
        const launchState =
          picked.outerSlurmEnvironment &&
          !hasRunningServerSession("slurm", targetNotebookUri)
            ? "failed to start"
            : "started";
        void vscode.window.showWarningMessage(
          `${envType} server ${launchState}, but VS Code could not auto-connect. URI copied: ${uri}`,
        );
      }

      const hasSelectedKernel =
        await hasAnyKernelSelectedForActiveNotebook(targetNotebookUri);

      if (!selectedKernelId && !hasSelectedKernel) {
        void vscode.window
          .showInformationMessage(
            `Launched ${envType} Jupyter server. Select the kernel manually if needed.`,
            "Select Kernel",
          )
          .then(async (action) => {
            if (action === "Select Kernel") {
              await openKernelPicker();
            }
          });
      }

      await refreshNotebookToolbarContext(context);
      return selectedKernelId;
    };

    return picked.outerSlurmEnvironment
      ? await withKernelProgress(
          "Starting Jupyter SLURM job and selecting kernel...",
          runConnectFlow,
        )
      : await runConnectFlow();
  }

  const serverReady = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Jupyter notebook server starting...",
      cancellable: false,
    },
    async () => {
      return await waitForServerReady(uri);
    },
  );
  const connected = serverReady
    ? await selectExistingJupyterServer(uri)
    : false;

  const action = await vscode.window.showInformationMessage(
    connected
      ? "Launched Jupyter via Calkit."
      : `Launched Jupyter via Calkit. Could not auto-connect yet; URI copied: ${uri}`,
    "Select Kernel",
  );

  if (action === "Select Kernel") {
    await openKernelPicker();
  }

  await refreshNotebookToolbarContext(context);
  return undefined;
}

function getWorkspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

async function readCalkitConfig(
  workspaceRoot: string,
): Promise<CalkitInfo | undefined> {
  const fileUri = vscode.Uri.file(path.join(workspaceRoot, "calkit.yaml"));
  try {
    const bytes = await vscode.workspace.fs.readFile(fileUri);
    const raw = Buffer.from(bytes).toString("utf8");
    const parsed = YAML.parse(raw) as CalkitInfo | undefined;
    return parsed ?? {};
  } catch (error) {
    if (isFileNotFoundError(error)) {
      return {};
    }
    void vscode.window.showErrorMessage(
      `Failed to read calkit.yaml: ${String(error)}`,
    );
    return undefined;
  }
}

function isFileNotFoundError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  const message = error.message.toLowerCase();
  return (
    message.includes("filenotfound") ||
    message.includes("no such file") ||
    message.includes("entry not found")
  );
}

async function saveNotebookEnvironmentSelection(
  workspaceRoot: string,
  notebookPath: string,
  environmentName: string,
): Promise<boolean> {
  try {
    // Use Calkit CLI to properly save the notebook environment
    // The CLI handles formatting and determines whether to use notebooks or pipeline section
    const { stderr } = await execFileAsync(
      "calkit",
      ["update", "notebook", notebookPath, "--set-env", environmentName],
      {
        cwd: workspaceRoot,
      },
    );

    if (stderr) {
      log(`calkit update notebook warning: ${stderr}`);
    }

    log(
      `Saved environment '${environmentName}' for notebook '${notebookPath}'`,
    );
    return true;
  } catch (error: unknown) {
    const err = error as {
      stdout?: string;
      stderr?: string;
      message?: string;
    };
    const details = (err.stderr || err.stdout || err.message || "").trim();
    log(`Failed to save environment selection: ${details}`);
    void vscode.window.showWarningMessage(
      `Failed to save environment to calkit.yaml: ${
        details || "unknown error"
      }`,
    );
    return false;
  }
}

async function runCreateEnvironmentWizard(
  workspaceRoot: string,
  options?: {
    includeSlurm?: boolean;
    title?: string;
    placeHolder?: string;
  },
): Promise<string | undefined> {
  const config = (await readCalkitConfig(workspaceRoot)) ?? {};
  const environments = config.environments ?? {};
  for (;;) {
    const kindItems = [
      {
        label: "conda",
        description: "Conda environment.yml-based environment",
      },
      {
        label: "julia",
        description: "Julia Project.toml-based environment",
      },
      {
        label: "uv",
        description: "uv pyproject.toml-based environment",
      },
    ];
    if (options?.includeSlurm ?? true) {
      kindItems.splice(2, 0, {
        label: "slurm",
        description: "Remote SLURM scheduler environment",
      });
    }

    const kindPick = await vscode.window.showQuickPick(kindItems, {
      title: options?.title ?? "Create Calkit environment",
      placeHolder: options?.placeHolder ?? "Pick environment kind",
    });
    if (!kindPick) {
      return undefined;
    }

    if (kindPick.label === "conda") {
      const created = await runCreateCondaEnvironmentWizard(
        workspaceRoot,
        config,
        environments,
      );
      if (created === "__back__") {
        continue;
      }
      return created;
    }

    if (kindPick.label === "julia") {
      const created = await runCreateJuliaEnvironmentWizard(
        workspaceRoot,
        config,
        environments,
      );
      if (created === "__back__") {
        continue;
      }
      return created;
    }

    if (kindPick.label === "slurm") {
      const created = await runCreateSlurmEnvironmentWizard(
        workspaceRoot,
        environments,
      );
      if (created === "__back__") {
        continue;
      }
      return created;
    }

    const created = await runCreateUvEnvironmentWizard(
      workspaceRoot,
      config,
      environments,
    );
    if (created === "__back__") {
      continue;
    }
    return created;
  }
}

async function readUvPackages(
  workspaceRoot: string,
  specPath: string,
): Promise<string[]> {
  try {
    const absPath = path.join(workspaceRoot, specPath);
    const raw = (
      await vscode.workspace.fs.readFile(vscode.Uri.file(absPath))
    ).toString();
    const match = raw.match(
      /\[project\][^\[]*?dependencies\s*=\s*\[([\s\S]*?)\]/,
    );
    if (!match) {
      return [];
    }
    return Array.from(match[1].matchAll(/"([^"]+)"/g)).map((m) => m[1]);
  } catch {
    return [];
  }
}

async function readJuliaPackages(
  workspaceRoot: string,
  specPath: string,
): Promise<string[]> {
  try {
    const absPath = path.join(workspaceRoot, specPath);
    const raw = (
      await vscode.workspace.fs.readFile(vscode.Uri.file(absPath))
    ).toString();
    const match = raw.match(/\[deps\]([\s\S]*?)(?:\[|$)/);
    if (!match) {
      return [];
    }
    return match[1]
      .split("\n")
      .map((l) => l.split("=")[0].trim())
      .filter(Boolean);
  } catch {
    return [];
  }
}

async function readCondaPackages(
  workspaceRoot: string,
  specPath: string,
): Promise<{ conda: string[]; pip: string[] }> {
  try {
    const absPath = path.join(workspaceRoot, specPath);
    const raw = (
      await vscode.workspace.fs.readFile(vscode.Uri.file(absPath))
    ).toString();
    const parsed = (await import("yaml")).parse(raw) as {
      dependencies?: unknown[];
    } | null;
    const deps = parsed?.dependencies ?? [];
    const conda = deps.filter((d): d is string => typeof d === "string");
    const pipDict = deps.find(
      (d): d is { pip: string[] } =>
        typeof d === "object" && d !== null && "pip" in d,
    );
    const pip = Array.isArray(pipDict?.pip)
      ? pipDict.pip.filter((p): p is string => typeof p === "string")
      : [];
    return { conda, pip };
  } catch {
    return { conda: [], pip: [] };
  }
}

async function showEnvCreatorWebview(
  context: vscode.ExtensionContext,
  workspaceRoot: string,
  editEnvName?: string,
  existingEnv?: import("./environments").CalkitEnvironment,
  specPath?: string,
): Promise<void> {
  const isEdit = editEnvName !== undefined;
  const kind = typeof existingEnv?.kind === "string" ? existingEnv.kind : "uv";
  let condaPackages: { conda: string[]; pip: string[] } = {
    conda: [],
    pip: [],
  };
  let uvPackages: string[] = [];
  let juliaPackages: string[] = [];
  if (isEdit && specPath) {
    if (kind === "conda") {
      condaPackages = await readCondaPackages(workspaceRoot, specPath);
    } else if (kind === "uv" || kind === "uv-venv") {
      uvPackages = await readUvPackages(workspaceRoot, specPath);
    } else if (kind === "julia") {
      juliaPackages = await readJuliaPackages(workspaceRoot, specPath);
    }
  }
  const nonce = getNonce();
  const panel = vscode.window.createWebviewPanel(
    "calkit.envCreator",
    isEdit ? `Edit Environment: ${editEnvName}` : "New Environment",
    vscode.ViewColumn.Active,
    { enableScripts: true },
  );
  context.subscriptions.push(panel);
  panel.webview.html = buildEnvCreatorHtml(
    nonce,
    editEnvName,
    existingEnv,
    specPath,
    condaPackages.conda,
    condaPackages.pip,
    uvPackages,
    juliaPackages,
  );
  panel.webview.onDidReceiveMessage(
    (msg: {
      command: string;
      name: string;
      kind: string;
      packages: string[];
      pipPackages: string[];
      origPackages: string[];
      origPipPackages: string[];
      pythonVersion: string;
      condaPath: string;
      image: string;
      base: string;
      dockerfilePath: string;
      host: string;
      defaultOptions: string[];
      defaultSetup: string[];
    }) => {
      if (msg.command !== "create" && msg.command !== "save") {
        return;
      }
      const args: string[] = [];
      if (msg.command === "save") {
        if (msg.kind === "conda") {
          args.push("update", "conda-env", "-n", msg.name);
          const origSet = new Set(msg.origPackages);
          const newSet = new Set(msg.packages);
          for (const p of msg.packages) {
            if (!origSet.has(p)) {
              args.push("--add", p);
            }
          }
          for (const p of msg.origPackages) {
            if (!newSet.has(p)) {
              args.push("--rm", p);
            }
          }
          const origPipSet = new Set(msg.origPipPackages);
          const newPipSet = new Set(msg.pipPackages);
          for (const p of msg.pipPackages) {
            if (!origPipSet.has(p)) {
              args.push("--add-pip", p);
            }
          }
          for (const p of msg.origPipPackages) {
            if (!newPipSet.has(p)) {
              args.push("--rm-pip", p);
            }
          }
        } else if (msg.kind === "uv" || msg.kind === "uv-venv") {
          args.push("update", "uv-env", "-n", msg.name, "--no-check");
          const origSet = new Set(msg.origPackages);
          const newSet = new Set(msg.packages);
          for (const p of msg.packages) {
            if (!origSet.has(p)) {
              args.push("--add", p);
            }
          }
          for (const p of msg.origPackages) {
            if (!newSet.has(p)) {
              args.push("--rm", p);
            }
          }
        } else if (msg.kind === "julia") {
          args.push("update", "julia-env", "-n", msg.name, "--no-check");
          const origSet = new Set(msg.origPackages);
          const newSet = new Set(msg.packages);
          for (const p of msg.packages) {
            if (!origSet.has(p)) {
              args.push("--add", p);
            }
          }
          for (const p of msg.origPackages) {
            if (!newSet.has(p)) {
              args.push("--rm", p);
            }
          }
        } else if (msg.kind === "docker") {
          args.push("update", "docker-env", "-n", msg.name);
          if (msg.image) {
            args.push("--image", msg.image);
          }
        } else if (msg.kind === "slurm") {
          args.push("update", "slurm-env", "-n", msg.name);
          if (msg.host) {
            args.push("--host", msg.host);
          }
          for (const opt of msg.defaultOptions) {
            args.push("--set-default-options", opt);
          }
          if (msg.defaultOptions.length === 0) {
            args.push("--set-default-options", "");
          }
          for (const cmd of msg.defaultSetup) {
            args.push("--set-default-setup", cmd);
          }
          if (msg.defaultSetup.length === 0) {
            args.push("--set-default-setup", "");
          }
        }
      } else {
        if (msg.kind === "uv") {
          args.push("new", "uv-env", "-n", msg.name, "--no-commit");
          if (msg.pythonVersion) {
            args.push("--python", msg.pythonVersion);
          }
          for (const pkg of msg.packages) {
            args.push(pkg);
          }
        } else if (msg.kind === "conda") {
          args.push("new", "conda-env", "-n", msg.name, "--no-commit");
          if (msg.condaPath) {
            args.push("--path", msg.condaPath);
          }
          for (const pkg of msg.packages) {
            args.push(pkg);
          }
        } else if (msg.kind === "docker") {
          args.push("new", "docker-env", "-n", msg.name);
          if (msg.base) {
            args.push("--from", msg.base);
            if (msg.dockerfilePath) {
              args.push("--path", msg.dockerfilePath);
            }
          } else if (msg.image) {
            args.push("--image", msg.image);
          }
          args.push("--no-check", "--no-commit");
        } else if (msg.kind === "slurm") {
          args.push(
            "new",
            "slurm-env",
            "-n",
            msg.name,
            "--host",
            msg.host,
            "--no-commit",
          );
          for (const opt of msg.defaultOptions) {
            args.push("--default-option", opt);
          }
          for (const cmd of msg.defaultSetup) {
            args.push("--default-setup", cmd);
          }
        }
      }
      const progressTitle = isEdit
        ? "Saving environment..."
        : "Creating environment...";
      const successMsg = isEdit
        ? `Environment '${msg.name}' updated.`
        : `Environment '${msg.name}' created successfully.`;
      void vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: progressTitle,
          cancellable: false,
        },
        async () => {
          try {
            await execFileAsync("calkit", args, { cwd: workspaceRoot });
            void vscode.window.showInformationMessage(successMsg);
            void refreshPipelineOutputContext(context);
            panel.dispose();
          } catch (error: unknown) {
            const err = error as {
              stderr?: string;
              stdout?: string;
              message?: string;
            };
            const output = [err.stdout, err.stderr]
              .filter(Boolean)
              .join("\n")
              .trim();
            if (output) {
              log(output);
            }
            const errMsg = (err.stderr ?? err.message ?? String(error)).trim();
            void vscode.window
              .showErrorMessage(errMsg, "View Output")
              .then((choice) => {
                if (choice === "View Output") {
                  outputChannel.show(true);
                }
              });
            void panel.webview.postMessage({
              command: "error",
              message: errMsg,
            });
          }
        },
      );
    },
  );
}

function buildEnvCreatorHtml(
  nonce: string,
  editEnvName?: string,
  existingEnv?: import("./environments").CalkitEnvironment,
  specPath?: string,
  editCondaPackages: string[] = [],
  editPipPackages: string[] = [],
  editUvPackages: string[] = [],
  editJuliaPackages: string[] = [],
): string {
  const isEdit = editEnvName !== undefined;
  const kind = typeof existingEnv?.kind === "string" ? existingEnv.kind : "uv";
  const existingImage =
    typeof existingEnv?.image === "string" ? existingEnv.image : "";
  const existingHost =
    typeof existingEnv?.host === "string" ? existingEnv.host : "";
  const existingOptions = Array.isArray(existingEnv?.default_options)
    ? (existingEnv.default_options as string[]).filter(
        (s) => typeof s === "string",
      )
    : [];
  const existingSetup = Array.isArray(existingEnv?.default_setup)
    ? (existingEnv.default_setup as string[]).filter(
        (s) => typeof s === "string",
      )
    : [];

  const optionsJson = JSON.stringify(existingOptions);
  const setupJson = JSON.stringify(existingSetup);

  const title = isEdit
    ? `Edit Environment: ${escHtml(editEnvName ?? "")}`
    : "New Environment";
  const btnLabel = isEdit ? "Save" : "Create";
  const spinnerLabel = isEdit ? "Saving..." : "Creating...";
  const postCommand = isEdit ? "save" : "create";

  const nameField = isEdit
    ? `<div class="field"><label>Name</label><div class="info-row">${escHtml(
        editEnvName ?? "",
      )}</div></div>`
    : `<div class="field"><label>Name</label><input id="name" type="text" required placeholder="e.g. default" /></div>`;

  const kindField = isEdit
    ? `<div class="field"><label>Kind</label><div class="info-row">${escHtml(
        kind,
      )}</div></div>`
    : `<div class="field"><label>Kind</label>
<select id="kind">
  <option value="uv">uv</option>
  <option value="conda">conda</option>
  <option value="julia">julia</option>
  <option value="docker">docker</option>
  <option value="slurm">slurm</option>
</select>
</div>`;

  const uvPackagesJson = JSON.stringify(editUvPackages);
  const juliaPackagesJson = JSON.stringify(editJuliaPackages);

  const uvSection =
    isEdit && kind !== "uv" && kind !== "uv-venv"
      ? ""
      : `
<div id="section-uv">
${
  isEdit
    ? `${
        specPath
          ? `  <div class="field"><label>Spec file</label><div class="info-row">${escHtml(
              specPath,
            )}</div></div>`
          : ""
      }
  <div class="field">
    <label>Packages</label>
    <div class="list-section">
      <div id="uv-packages-list"></div>
      <button class="add-btn" id="add-uv-package">+ Add package</button>
    </div>
  </div>`
    : `  <div class="field">
    <label>Python version <span style="font-weight:normal;text-transform:none">(optional)</span></label>
    <input id="python-version" type="text" placeholder="e.g. 3.11" />
  </div>
  <div class="field">
    <label>Packages</label>
    <div class="list-section">
      <div id="uv-packages-list"></div>
      <button class="add-btn" id="add-uv-package">+ Add package</button>
    </div>
  </div>`
}
</div>`;

  const juliaSection =
    isEdit && kind !== "julia"
      ? ""
      : `
<div id="section-julia"${!isEdit ? ' style="display:none"' : ""}>
${
  isEdit
    ? `${
        specPath
          ? `  <div class="field"><label>Spec file</label><div class="info-row">${escHtml(
              specPath,
            )}</div></div>`
          : ""
      }
  <div class="field">
    <label>Packages</label>
    <div class="list-section">
      <div id="julia-packages-list"></div>
      <button class="add-btn" id="add-julia-package">+ Add package</button>
    </div>
  </div>`
    : `  <div class="field">
    <label>Packages</label>
    <div class="list-section">
      <div id="julia-packages-list"></div>
      <button class="add-btn" id="add-julia-package">+ Add package</button>
    </div>
  </div>`
}
</div>`;

  const condaPackagesJson = JSON.stringify(editCondaPackages);
  const pipPackagesJson = JSON.stringify(editPipPackages);

  const condaSection =
    isEdit && kind !== "conda"
      ? ""
      : `
<div id="section-conda"${!isEdit ? ' style="display:none"' : ""}>
${
  isEdit
    ? `${
        specPath
          ? `  <div class="field"><label>Spec file</label><div class="info-row">${escHtml(
              specPath,
            )}</div></div>`
          : ""
      }
  <div class="field">
    <label>Conda packages</label>
    <div class="list-section">
      <div id="conda-packages-list"></div>
      <button class="add-btn" id="add-conda-package">+ Add package</button>
    </div>
  </div>
  <div class="field">
    <label>pip packages</label>
    <div class="list-section">
      <div id="pip-packages-list"></div>
      <button class="add-btn" id="add-pip-package">+ Add pip package</button>
    </div>
  </div>`
    : `  <div class="field">
    <label>Packages</label>
    <div class="list-section">
      <div id="conda-packages-list"></div>
      <button class="add-btn" id="add-conda-package">+ Add package</button>
    </div>
  </div>
  <div class="field">
    <label>Spec path <span style="font-weight:normal;text-transform:none">(optional)</span></label>
    <input id="conda-path" type="text" placeholder="environment.yml" />
  </div>`
}
</div>`;

  const dockerSection =
    isEdit && kind !== "docker"
      ? ""
      : `
<div id="section-docker"${!isEdit ? ' style="display:none"' : ""}>
  <div class="field">
    <label>Image</label>
    <input id="docker-image" type="text" value="${escHtml(
      existingImage,
    )}" placeholder="e.g. ubuntu:22.04 or myregistry/myimage:latest" />
  </div>
${
  !isEdit
    ? `  <div class="field">
    <label>Build from <span style="font-weight:normal;text-transform:none">(optional)</span></label>
    <input id="docker-base" type="text" placeholder="base image for Dockerfile, e.g. ubuntu:22.04" />
  </div>
  <div class="field" id="dockerfile-path-field" style="display:none">
    <label>Dockerfile path <span style="font-weight:normal;text-transform:none">(optional)</span></label>
    <input id="dockerfile-path" type="text" placeholder="Dockerfile" />
  </div>`
    : ""
}
</div>`;

  const slurmSection =
    isEdit && kind !== "slurm"
      ? ""
      : `
<div id="section-slurm"${!isEdit ? ' style="display:none"' : ""}>
  <div class="field">
    <label>Host</label>
    <input id="slurm-host" type="text" value="${escHtml(
      existingHost,
    )}" placeholder="e.g. myserver.edu" />
  </div>
  <div class="field">
    <label>Default options</label>
    <div class="list-section">
      <div id="slurm-options-list"></div>
      <button class="add-btn" id="add-slurm-option">+ Add option</button>
    </div>
  </div>
  <div class="field">
    <label>Default setup</label>
    <div class="list-section">
      <div id="slurm-setup-list"></div>
      <button class="add-btn" id="add-slurm-setup">+ Add command</button>
    </div>
  </div>
</div>`;

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline';">
<title>${title}</title>
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); padding: 20px; max-width: 580px; }
  h1 { font-size: 1.2em; margin-bottom: 18px; }
  .field { margin-bottom: 14px; }
  label { display: block; margin-bottom: 4px; font-weight: 600; color: var(--vscode-descriptionForeground); font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.04em; }
  input, select { width: 100%; box-sizing: border-box; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, #555); padding: 5px 8px; font-size: 1em; font-family: inherit; border-radius: 2px; }
  input:focus, select:focus { outline: 1px solid var(--vscode-focusBorder); border-color: var(--vscode-focusBorder); }
  .info-row { padding: 5px 0; color: var(--vscode-foreground); }
  .info-note { font-size: 0.9em; color: var(--vscode-descriptionForeground); padding: 4px 0; }
  .info-note code { font-family: var(--vscode-editor-font-family, monospace); }
  .list-section { border: 1px solid var(--vscode-input-border, #555); border-radius: 2px; padding: 6px 8px; }
  .list-item { display: flex; gap: 6px; margin-bottom: 4px; align-items: center; }
  .list-item input { flex: 1; }
  .remove-btn { background: none; border: none; color: var(--vscode-descriptionForeground); cursor: pointer; font-size: 1.1em; padding: 2px 4px; flex-shrink: 0; }
  .remove-btn:hover { color: var(--vscode-foreground); }
  .add-btn { background: none; border: none; color: var(--vscode-textLink-foreground); cursor: pointer; font-size: 0.9em; padding: 2px 0; margin-top: 4px; }
  .add-btn:hover { text-decoration: underline; }
  .actions { margin-top: 20px; }
  button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 7px 18px; cursor: pointer; font-size: 1em; border-radius: 2px; }
  button.primary:hover { background: var(--vscode-button-hoverBackground); }
  button.primary:disabled { opacity: 0.6; cursor: not-allowed; }
  .error-msg { color: var(--vscode-errorForeground, #f44); margin-top: 8px; font-size: 0.92em; display: none; }
  .spinner-text { margin-left: 10px; font-size: 0.92em; color: var(--vscode-descriptionForeground); display: none; }
</style>
</head>
<body>
<h1>${title}</h1>
${nameField}
${kindField}
${uvSection}
${juliaSection}
${condaSection}
${dockerSection}
${slurmSection}
<div class="actions">
  <button class="primary" id="btn-submit">${btnLabel}</button>
  <span class="spinner-text" id="spinner-text">${spinnerLabel}</span>
</div>
<div class="error-msg" id="error-msg"></div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const isEdit = ${isEdit};
  const fixedKind = ${isEdit ? `'${escHtml(kind)}'` : "null"};

  function getKind() {
    if (fixedKind) { return fixedKind; }
    return document.getElementById('kind').value;
  }

  ${
    !isEdit
      ? `
  const kindEl = document.getElementById('kind');
  const sections = {
    uv: document.getElementById('section-uv'),
    julia: document.getElementById('section-julia'),
    conda: document.getElementById('section-conda'),
    docker: document.getElementById('section-docker'),
    slurm: document.getElementById('section-slurm'),
  };
  function showSection(k) {
    for (const [key, el] of Object.entries(sections)) {
      if (el) { el.style.display = key === k ? '' : 'none'; }
    }
  }
  kindEl.addEventListener('change', function() { showSection(kindEl.value); });
  `
      : ""
  }

  function makeListItem(listEl, value, placeholder) {
    const row = document.createElement('div');
    row.className = 'list-item';
    const inp = document.createElement('input');
    inp.type = 'text';
    inp.placeholder = placeholder || '';
    if (value) { inp.value = value; }
    const btn = document.createElement('button');
    btn.className = 'remove-btn';
    btn.textContent = '\\u00d7';
    btn.title = 'Remove';
    btn.addEventListener('click', function() { row.remove(); });
    row.appendChild(inp);
    row.appendChild(btn);
    listEl.appendChild(row);
    return inp;
  }
  function getListValues(listEl) {
    return Array.from(listEl.querySelectorAll('input')).map(function(i) { return i.value.trim(); }).filter(Boolean);
  }

  // Pre-populate package lists
  const uvPkgList = document.getElementById('uv-packages-list');
  const juliaPkgList = document.getElementById('julia-packages-list');
  const condaPkgList = document.getElementById('conda-packages-list');
  const pipPkgList = document.getElementById('pip-packages-list');
  if (uvPkgList) {
    for (const v of ${uvPackagesJson}) { makeListItem(uvPkgList, v, 'e.g. numpy'); }
  }
  if (juliaPkgList) {
    for (const v of ${juliaPackagesJson}) { makeListItem(juliaPkgList, v, 'e.g. Plots'); }
  }
  if (condaPkgList) {
    for (const v of ${condaPackagesJson}) { makeListItem(condaPkgList, v, 'e.g. numpy'); }
  }
  if (pipPkgList) {
    for (const v of ${pipPackagesJson}) { makeListItem(pipPkgList, v, 'e.g. requests'); }
  }

  // Pre-populate slurm lists
  const slurmOptList = document.getElementById('slurm-options-list');
  const slurmSetupList = document.getElementById('slurm-setup-list');
  if (slurmOptList) {
    for (const v of ${optionsJson}) { makeListItem(slurmOptList, v, '--gpus=1'); }
  }
  if (slurmSetupList) {
    for (const v of ${setupJson}) { makeListItem(slurmSetupList, v, 'module load julia/1.11'); }
  }

  if (document.getElementById('add-uv-package')) {
    document.getElementById('add-uv-package').addEventListener('click', function() {
      makeListItem(uvPkgList, '', 'e.g. numpy').focus();
    });
  }
  if (document.getElementById('add-julia-package')) {
    document.getElementById('add-julia-package').addEventListener('click', function() {
      makeListItem(juliaPkgList, '', 'e.g. Plots').focus();
    });
  }
  if (document.getElementById('add-conda-package')) {
    document.getElementById('add-conda-package').addEventListener('click', function() {
      makeListItem(condaPkgList, '', 'e.g. numpy').focus();
    });
  }
  if (document.getElementById('add-pip-package')) {
    document.getElementById('add-pip-package').addEventListener('click', function() {
      makeListItem(pipPkgList, '', 'e.g. requests').focus();
    });
  }
  ${
    !isEdit
      ? `
  const dockerBaseEl = document.getElementById('docker-base');
  const dockerfilePathField = document.getElementById('dockerfile-path-field');
  if (dockerBaseEl) {
    dockerBaseEl.addEventListener('input', function() {
      dockerfilePathField.style.display = dockerBaseEl.value.trim() ? '' : 'none';
    });
  }`
      : ""
  }

  if (document.getElementById('add-slurm-option')) {
    document.getElementById('add-slurm-option').addEventListener('click', function() {
      makeListItem(slurmOptList, '', '--gpus=1').focus();
    });
  }
  if (document.getElementById('add-slurm-setup')) {
    document.getElementById('add-slurm-setup').addEventListener('click', function() {
      makeListItem(slurmSetupList, '', 'module load julia/1.11').focus();
    });
  }

  const btnSubmit = document.getElementById('btn-submit');
  const spinnerText = document.getElementById('spinner-text');
  const errorMsg = document.getElementById('error-msg');

  btnSubmit.addEventListener('click', function() {
    const kind = getKind();
    const name = isEdit ? ${
      isEdit ? JSON.stringify(editEnvName ?? "") : "''"
    } : document.getElementById('name').value.trim();
    if (!name) {
      errorMsg.textContent = 'Name is required.';
      errorMsg.style.display = 'block';
      return;
    }
    if (kind === 'slurm' && !document.getElementById('slurm-host').value.trim()) {
      errorMsg.textContent = 'Host is required for SLURM environments.';
      errorMsg.style.display = 'block';
      return;
    }
    errorMsg.style.display = 'none';
    btnSubmit.disabled = true;
    spinnerText.style.display = 'inline';
    let packages = [];
    if (kind === 'uv' || kind === 'uv-venv') {
      packages = uvPkgList ? getListValues(uvPkgList) : [];
    } else if (kind === 'julia') {
      packages = juliaPkgList ? getListValues(juliaPkgList) : [];
    } else if (kind === 'conda') {
      packages = condaPkgList ? getListValues(condaPkgList) : [];
    }
    const pipPackages = pipPkgList ? getListValues(pipPkgList) : [];
    const origPackages = kind === 'uv' || kind === 'uv-venv' ? ${uvPackagesJson}
      : kind === 'julia' ? ${juliaPackagesJson}
      : ${condaPackagesJson};
    vscode.postMessage({
      command: '${postCommand}',
      name,
      kind,
      packages,
      pipPackages,
      origPackages,
      origPipPackages: ${pipPackagesJson},
      pythonVersion: document.getElementById('python-version') ? document.getElementById('python-version').value.trim() : '',
      condaPath: document.getElementById('conda-path') ? document.getElementById('conda-path').value.trim() : '',
      image: document.getElementById('docker-image') ? document.getElementById('docker-image').value.trim() : '',
      base: document.getElementById('docker-base') ? document.getElementById('docker-base').value.trim() : '',
      dockerfilePath: document.getElementById('dockerfile-path') ? document.getElementById('dockerfile-path').value.trim() : '',
      host: document.getElementById('slurm-host') ? document.getElementById('slurm-host').value.trim() : '',
      defaultOptions: slurmOptList ? getListValues(slurmOptList) : [],
      defaultSetup: slurmSetupList ? getListValues(slurmSetupList) : [],
    });
  });

  window.addEventListener('message', function(event) {
    const msg = event.data;
    if (msg.command === 'error') {
      btnSubmit.disabled = false;
      spinnerText.style.display = 'none';
      errorMsg.textContent = msg.message;
      errorMsg.style.display = 'block';
    }
  });
</script>
</body>
</html>`;
}

type WizardStepResult<T> =
  | { kind: "value"; value: T }
  | { kind: "back" }
  | { kind: "cancel" };

async function showInputBoxStep(options: {
  title: string;
  prompt?: string;
  value?: string;
  placeHolder?: string;
  validateInput?: (
    value: string,
  ) => string | undefined | Promise<string | undefined>;
  canGoBack?: boolean;
}): Promise<WizardStepResult<string>> {
  const input = vscode.window.createInputBox();
  input.title = options.title;
  input.prompt = options.prompt;
  input.value = options.value ?? "";
  input.placeholder = options.placeHolder;
  if (options.canGoBack) {
    input.buttons = [vscode.QuickInputButtons.Back];
  }

  return await new Promise<WizardStepResult<string>>((resolve) => {
    let done = false;
    const finish = (result: WizardStepResult<string>) => {
      if (done) {
        return;
      }
      done = true;
      input.hide();
      input.dispose();
      resolve(result);
    };

    input.onDidTriggerButton((button) => {
      if (button === vscode.QuickInputButtons.Back) {
        finish({ kind: "back" });
      }
    });

    input.onDidAccept(async () => {
      const current = input.value;
      const validationMessage = options.validateInput
        ? await options.validateInput(current)
        : undefined;
      if (validationMessage) {
        input.validationMessage = validationMessage;
        return;
      }
      finish({ kind: "value", value: current });
    });

    input.onDidHide(() => {
      if (!done) {
        finish({ kind: "cancel" });
      }
    });

    input.show();
  });
}

async function runCreateSlurmEnvironmentWizard(
  workspaceRoot: string,
  environments: Record<string, CalkitEnvironment>,
): Promise<string | "__back__" | undefined> {
  let name = "cluster";
  let host = await detectLocalHostname(workspaceRoot);
  let defaults: SlurmLaunchOptions = {};
  let step = 0;

  while (step >= 0) {
    if (step === 0) {
      const nameStep = await showInputBoxStep({
        title: "Environment name",
        prompt: "Unique environment name in calkit.yaml",
        value: name,
        canGoBack: true,
        validateInput: (value) => {
          const trimmed = value.trim();
          if (trimmed.length === 0) {
            return "Environment name is required";
          }
          if (trimmed.includes(":")) {
            return "Environment names cannot contain ':'";
          }
          if (trimmed in environments) {
            return "An environment with this name already exists";
          }
          return undefined;
        },
      });
      if (nameStep.kind === "cancel") {
        return undefined;
      }
      if (nameStep.kind === "back") {
        return "__back__";
      }
      name = nameStep.value.trim();
      step = 1;
      continue;
    }

    if (step === 1) {
      const hostStep = await showInputBoxStep({
        title: "SLURM environment host",
        prompt: "Host where SLURM commands should run",
        value: host,
        placeHolder: "e.g., hpc.my-org.edu",
        canGoBack: true,
        validateInput: (value) =>
          value.trim().length === 0 ? "Host is required" : undefined,
      });
      if (hostStep.kind === "cancel") {
        return undefined;
      }
      if (hostStep.kind === "back") {
        step = 0;
        continue;
      }
      host = hostStep.value.trim();
      step = 2;
      continue;
    }

    const optionsStep = await askForSlurmOptionsWizard(defaults);
    if (optionsStep.kind === "cancel") {
      return undefined;
    }
    if (optionsStep.kind === "back") {
      step = 1;
      continue;
    }
    defaults = optionsStep.value;

    const setupStep = await askForSlurmSetupCommandsStep();
    if (setupStep.kind === "cancel") {
      return undefined;
    }
    if (setupStep.kind === "back") {
      step = 2;
      continue;
    }
    const setupCommands = setupStep.value;

    const args = ["new", "slurm-env", "--name", name, "--host", host];
    for (const option of slurmOptionsToOptionList(defaults)) {
      args.push("--default-option", option);
    }
    for (const cmd of setupCommands) {
      args.push("--default-setup", cmd);
    }
    args.push("--no-commit");

    try {
      await execFileAsync("calkit", args, {
        cwd: workspaceRoot,
      });
    } catch (error: unknown) {
      const err = error as {
        stdout?: string;
        stderr?: string;
        message?: string;
      };
      const details = (err.stderr || err.stdout || err.message || "").trim();
      log(`Failed to create SLURM environment: ${details}`);
      void vscode.window.showErrorMessage(
        `Failed to create SLURM environment: ${details || "unknown error"}`,
      );
      return undefined;
    }

    void vscode.window.showInformationMessage(
      `Created SLURM environment '${name}' in calkit.yaml.`,
    );
    return name;
  }

  return undefined;
}

async function runCreateNotebookEnvironmentCreationFlow(
  workspaceRoot: string,
): Promise<CalkitEnvNotebookKernelSource | undefined> {
  let outerSlurmEnvironment: string | undefined;

  for (;;) {
    const createdEnvironmentName = await runCreateEnvironmentWizard(
      workspaceRoot,
      outerSlurmEnvironment
        ? {
            includeSlurm: false,
            title: `Create inner environment for ${outerSlurmEnvironment}`,
            placeHolder: "Pick an environment kind to run inside SLURM",
          }
        : undefined,
    );

    if (!createdEnvironmentName) {
      return undefined;
    }

    const config = await readCalkitConfig(workspaceRoot);
    if (!config) {
      return undefined;
    }

    const environments = config.environments ?? {};
    const createdEnvironment = environments[createdEnvironmentName];
    if (!createdEnvironment) {
      void vscode.window.showWarningMessage(
        `Created environment '${createdEnvironmentName}' was not found in calkit.yaml.`,
      );
      return undefined;
    }

    if (createdEnvironment.kind === "slurm") {
      outerSlurmEnvironment = createdEnvironmentName;
      const nextAction = await vscode.window.showInformationMessage(
        `Created SLURM environment '${createdEnvironmentName}'. Create an inner environment for notebook kernels now?`,
        "Create Inner Environment",
        "Back to Environment List",
      );
      if (nextAction === "Create Inner Environment") {
        continue;
      }
      return undefined;
    }

    const environmentName = outerSlurmEnvironment
      ? `${outerSlurmEnvironment}:${createdEnvironmentName}`
      : createdEnvironmentName;
    return findCalkitEnvKernelSourceCandidate(environments, environmentName);
  }
}

async function runCreateJuliaEnvironmentWizard(
  workspaceRoot: string,
  config: CalkitInfo,
  environments: Record<string, CalkitEnvironment>,
): Promise<string | "__back__" | undefined> {
  const detectedJulia = await detectJuliaVersion(workspaceRoot);

  let name = "main";
  let projectTomlPath = "Project.toml";
  let juliaVersion = detectedJulia;
  let step = 0;

  while (step >= 0) {
    if (step === 0) {
      const nameStep = await showInputBoxStep({
        title: "Environment name",
        prompt: "Unique environment name in calkit.yaml",
        value: name,
        canGoBack: true,
        validateInput: (value) => {
          const trimmed = value.trim();
          if (trimmed.length === 0) {
            return "Environment name is required";
          }
          if (trimmed.includes(":")) {
            return "Environment names cannot contain ':'";
          }
          if (trimmed in environments) {
            return "An environment with this name already exists";
          }
          return undefined;
        },
      });
      if (nameStep.kind === "cancel") {
        return undefined;
      }
      if (nameStep.kind === "back") {
        return "__back__";
      }
      name = nameStep.value.trim();
      step = 1;
      continue;
    }

    if (step === 1) {
      const pathStep = await showInputBoxStep({
        title: "Julia project path",
        prompt:
          "Path to Project.toml or the Julia project folder, relative to the repo root",
        value: projectTomlPath,
        canGoBack: true,
        validateInput: (value) => {
          const trimmed = value.trim();
          if (trimmed.length === 0) {
            return "Path is required";
          }
          return undefined;
        },
      });
      if (pathStep.kind === "cancel") {
        return undefined;
      }
      if (pathStep.kind === "back") {
        step = 0;
        continue;
      }
      projectTomlPath = normalizeJuliaProjectTomlPath(
        pathStep.value.trim(),
        workspaceRoot,
      );
      step = 2;
      continue;
    }

    const versionStep = await showInputBoxStep({
      title: "Julia version (optional)",
      prompt: "Use detected version or specify a different major.minor version",
      value: juliaVersion,
      canGoBack: true,
      validateInput: (value) => {
        const trimmed = value.trim();
        if (trimmed.length === 0) {
          return "Julia version is required";
        }
        return undefined;
      },
    });
    if (versionStep.kind === "cancel") {
      return undefined;
    }
    if (versionStep.kind === "back") {
      step = 1;
      continue;
    }
    juliaVersion = versionStep.value.trim();

    try {
      const args: string[] = [
        "new",
        "julia-env",
        "--name",
        name,
        "--path",
        projectTomlPath,
      ];
      // Only pass --julia if it's different from the detected version
      if (juliaVersion !== detectedJulia) {
        args.push("--julia");
        args.push(juliaVersion);
      }
      args.push("--no-commit");

      await execFileAsync("calkit", args, { cwd: workspaceRoot });

      void vscode.window.showInformationMessage(
        `Created Julia environment '${name}' in calkit.yaml.`,
      );
      return name;
    } catch (error: unknown) {
      const err = error as {
        stderr?: string;
        message?: string;
      };
      const details = (err.stderr || err.message || "").trim();
      log(`Failed to create julia environment: ${details}`);
      void vscode.window.showErrorMessage(
        `Failed to create julia environment: ${details || "unknown error"}`,
      );
      return undefined;
    }
  }

  return undefined;
}

async function detectJuliaVersion(workspaceRoot: string): Promise<string> {
  try {
    const { stdout } = await execFileAsync("julia", ["--version"], {
      cwd: workspaceRoot,
      timeout: 5_000,
    });
    const versionMatch = stdout.match(/(\d+)\.(\d+)/);
    if (versionMatch) {
      return `${versionMatch[1]}.${versionMatch[2]}`;
    }
  } catch {
    // Fall back to a reasonable default when julia is unavailable.
  }
  return "1.10";
}

function normalizeJuliaProjectTomlPath(
  inputPath: string,
  workspaceRoot: string,
): string {
  const normalized = toRepoRelativePath(inputPath.trim(), workspaceRoot);
  if (normalized.length === 0) {
    return normalized;
  }
  if (path.basename(normalized) === "Project.toml") {
    return normalized;
  }
  return path.join(normalized, "Project.toml");
}

function toRepoRelativePath(inputPath: string, workspaceRoot: string): string {
  if (!inputPath || !path.isAbsolute(inputPath)) {
    return inputPath;
  }
  return path.relative(workspaceRoot, inputPath);
}

async function detectLocalHostname(workspaceRoot: string): Promise<string> {
  try {
    const { stdout } = await execFileAsync("hostname", [], {
      cwd: workspaceRoot,
      timeout: 2_000,
    });
    const hostname = stdout.trim();
    if (hostname.length > 0) {
      return hostname;
    }
  } catch {
    // Fallback if hostname cannot be detected.
  }
  return "localhost";
}

async function chooseSlurmOptionsForLaunch(
  defaults?: SlurmLaunchOptions,
): Promise<SlurmLaunchOptions | undefined> {
  const effectiveDefaults = getNotebookSlurmOptionsWithDefaults(defaults);
  const choice = await vscode.window.showQuickPick(
    [
      {
        label: "Use saved/default SLURM options",
        description: summarizeSlurmOptions(effectiveDefaults),
        action: "use",
      },
      {
        label: "Modify SLURM options...",
        description: "Edit --gpus, --time, and extra srun flags",
        action: "edit",
      },
    ],
    {
      title: "SLURM launch options",
      placeHolder: "Choose how to launch the SLURM notebook session",
      ignoreFocusOut: true,
    },
  );

  if (!choice) {
    return undefined;
  }

  if (choice.action === "use") {
    return effectiveDefaults;
  }

  return await askForSlurmOptions(effectiveDefaults);
}

function summarizeSlurmOptions(options: SlurmLaunchOptions): string {
  const parts: string[] = [];
  if (options.gpus) {
    parts.push(`--gpus=${options.gpus}`);
  }
  if (options.time) {
    parts.push(`--time=${options.time}`);
  }
  if (options.partition) {
    parts.push(`--partition=${options.partition}`);
  }
  if (options.extra) {
    parts.push(options.extra);
  }
  return parts.length > 0 ? parts.join(" ") : "No extra options";
}

async function askForSlurmSetupCommandsStep(): Promise<
  WizardStepResult<string[]>
> {
  const setupCommands: string[] = [];
  let addMore = true;

  while (addMore) {
    const result = await showInputBoxStep({
      title: "SLURM setup command",
      prompt:
        "Enter a shell command to run before SLURM jobs (e.g., 'module load julia/1.11')",
      value: "",
      placeHolder: "leave blank to skip",
      canGoBack: setupCommands.length > 0,
    });

    if (result.kind === "cancel") {
      return result;
    }

    if (result.kind === "back") {
      if (setupCommands.length === 0) {
        return { kind: "back" };
      }
      // Remove the last command
      setupCommands.pop();
      continue;
    }

    const trimmedCmd = result.value.trim();
    if (trimmedCmd.length > 0) {
      setupCommands.push(trimmedCmd);
    } else {
      addMore = false;
    }
  }

  return { kind: "value", value: setupCommands };
}

async function askForSlurmOptionsWizard(
  defaults: SlurmLaunchOptions,
): Promise<WizardStepResult<SlurmLaunchOptions>> {
  const values: SlurmLaunchOptions = {
    ...defaults,
  };
  let step = 0;

  while (step >= 0) {
    if (step === 0) {
      const result = await showInputBoxStep({
        title: "Slurm option: --gpus",
        prompt: "Optional GPU count or value (e.g., 1 or a100:1)",
        value: values.gpus ?? "",
        placeHolder: "leave blank to skip",
        canGoBack: true,
      });
      if (result.kind === "cancel") {
        return result;
      }
      if (result.kind === "back") {
        return { kind: "back" };
      }
      values.gpus = result.value;
      step = 1;
      continue;
    }

    if (step === 1) {
      const result = await showInputBoxStep({
        title: "Slurm option: --time",
        prompt: "Optional time (e.g., 60 or 01:00:00)",
        value: values.time ?? "",
        placeHolder: "leave blank to skip",
        canGoBack: true,
      });
      if (result.kind === "cancel") {
        return result;
      }
      if (result.kind === "back") {
        step = 0;
        continue;
      }
      values.time = result.value;
      step = 2;
      continue;
    }

    const result = await showInputBoxStep({
      title: "Additional srun options",
      prompt: "Optional raw options appended as-is (e.g., --cpus-per-task=8)",
      value: values.extra ?? "",
      placeHolder: "leave blank to skip",
      canGoBack: true,
    });
    if (result.kind === "cancel") {
      return result;
    }
    if (result.kind === "back") {
      step = 1;
      continue;
    }
    values.extra = result.value;
    return { kind: "value", value: compactSlurmOptions(values) };
  }

  return { kind: "cancel" };
}

async function runCreateCondaEnvironmentWizard(
  workspaceRoot: string,
  config: CalkitInfo,
  environments: Record<string, CalkitEnvironment>,
): Promise<string | "__back__" | undefined> {
  let name = "my-conda-env";
  let envPath = "environment.yml";
  let step = 0;

  while (step >= 0) {
    if (step === 0) {
      const nameStep = await showInputBoxStep({
        title: "Environment name",
        prompt: "Unique environment name in calkit.yaml",
        value: name,
        canGoBack: true,
        validateInput: (value) => {
          const trimmed = value.trim();
          if (trimmed.length === 0) {
            return "Environment name is required";
          }
          if (trimmed.includes(":")) {
            return "Environment names cannot contain ':'";
          }
          if (trimmed in environments) {
            return "An environment with this name already exists";
          }
          return undefined;
        },
      });
      if (nameStep.kind === "cancel") {
        return undefined;
      }
      if (nameStep.kind === "back") {
        return "__back__";
      }
      name = nameStep.value.trim();
      step = 1;
      continue;
    }

    const pathStep = await showInputBoxStep({
      title: "Conda environment.yml path",
      prompt: "Path to conda environment file, relative to the repo root",
      value: envPath,
      placeHolder: "e.g., environment.yml or env/conda-env.yml",
      canGoBack: true,
      validateInput: (value) => {
        const trimmed = value.trim();
        if (trimmed.length === 0) {
          return "Path is required";
        }
        if (!trimmed.endsWith(".yml") && !trimmed.endsWith(".yaml")) {
          return "Path must end with .yml or .yaml";
        }
        return undefined;
      },
    });
    if (pathStep.kind === "cancel") {
      return undefined;
    }
    if (pathStep.kind === "back") {
      step = 0;
      continue;
    }
    envPath = toRepoRelativePath(pathStep.value.trim(), workspaceRoot);

    try {
      await execFileAsync(
        "calkit",
        ["new", "conda-env", "--name", name, "--path", envPath, "--no-commit"],
        { cwd: workspaceRoot },
      );

      void vscode.window.showInformationMessage(
        `Created Conda environment '${name}' in calkit.yaml.`,
      );
      return name;
    } catch (error: unknown) {
      const err = error as {
        stderr?: string;
        message?: string;
      };
      const details = (err.stderr || err.message || "").trim();
      log(`Failed to create conda environment: ${details}`);
      void vscode.window.showErrorMessage(
        `Failed to create conda environment: ${details || "unknown error"}`,
      );
      return undefined;
    }
  }

  return undefined;
}

async function runCreateUvEnvironmentWizard(
  workspaceRoot: string,
  config: CalkitInfo,
  environments: Record<string, CalkitEnvironment>,
): Promise<string | "__back__" | undefined> {
  let name = "my-uv-env";
  let pyprojectPath = "pyproject.toml";
  let step = 0;

  while (step >= 0) {
    if (step === 0) {
      const nameStep = await showInputBoxStep({
        title: "Environment name",
        prompt: "Unique environment name in calkit.yaml",
        value: name,
        canGoBack: true,
        validateInput: (value) => {
          const trimmed = value.trim();
          if (trimmed.length === 0) {
            return "Environment name is required";
          }
          if (trimmed.includes(":")) {
            return "Environment names cannot contain ':'";
          }
          if (trimmed in environments) {
            return "An environment with this name already exists";
          }
          return undefined;
        },
      });
      if (nameStep.kind === "cancel") {
        return undefined;
      }
      if (nameStep.kind === "back") {
        return "__back__";
      }
      name = nameStep.value.trim();
      step = 1;
      continue;
    }

    const pathStep = await showInputBoxStep({
      title: "uv pyproject.toml path",
      prompt: "Path to pyproject.toml, relative to the repo root",
      value: pyprojectPath,
      placeHolder: "e.g., pyproject.toml or .calkit/envs/my-uv/pyproject.toml",
      canGoBack: true,
      validateInput: (value) => {
        const trimmed = value.trim();
        if (trimmed.length === 0) {
          return "Path is required";
        }
        if (!trimmed.endsWith("pyproject.toml")) {
          return "Path must end with pyproject.toml";
        }
        return undefined;
      },
    });
    if (pathStep.kind === "cancel") {
      return undefined;
    }
    if (pathStep.kind === "back") {
      step = 0;
      continue;
    }
    pyprojectPath = toRepoRelativePath(pathStep.value.trim(), workspaceRoot);

    try {
      await execFileAsync(
        "calkit",
        [
          "new",
          "uv-env",
          "--name",
          name,
          "--path",
          pyprojectPath,
          "--no-commit",
        ],
        { cwd: workspaceRoot },
      );

      void vscode.window.showInformationMessage(
        `Created uv environment '${name}' in calkit.yaml.`,
      );
      return name;
    } catch (error: unknown) {
      const err = error as {
        stderr?: string;
        message?: string;
      };
      const details = (err.stderr || err.message || "").trim();
      log(`Failed to create uv environment: ${details}`);
      void vscode.window.showErrorMessage(
        `Failed to create uv environment: ${details || "unknown error"}`,
      );
      return undefined;
    }
  }

  return undefined;
}

function getActiveNotebookUriKey(): string | undefined {
  return vscode.window.activeNotebookEditor?.notebook.uri.toString();
}

function getNotebookRelativePathForUri(
  workspaceRoot: string,
  notebookUri: string,
): string | undefined {
  const uri = vscode.Uri.parse(notebookUri);
  const relativePath = path.relative(workspaceRoot, uri.fsPath);
  return relativePath.replace(/\\/g, "/");
}

function getActiveNotebookRelativePath(
  workspaceRoot: string,
): string | undefined {
  const notebookUri = vscode.window.activeNotebookEditor?.notebook.uri;
  if (!notebookUri) {
    return undefined;
  }
  const notebookPath = notebookUri.fsPath;
  const relativePath = path.relative(workspaceRoot, notebookPath);
  // Use forward slashes for consistency in calkit.yaml
  return relativePath.replace(/\\/g, "/");
}

function getNotebookLaunchProfiles(
  context: vscode.ExtensionContext,
): Record<string, NotebookLaunchProfile> {
  return (
    context.workspaceState.get<Record<string, NotebookLaunchProfile>>(
      STATE_KEY_NOTEBOOK_PROFILES,
      {},
    ) ?? {}
  );
}

async function saveLaunchProfileForNotebookUri(
  context: vscode.ExtensionContext,
  notebookUri: string,
  profile: Omit<NotebookLaunchProfile, "notebookUri">,
): Promise<void> {
  const allProfiles = getNotebookLaunchProfiles(context);
  allProfiles[notebookUri] = {
    notebookUri,
    ...profile,
  };
  await context.workspaceState.update(STATE_KEY_NOTEBOOK_PROFILES, allProfiles);
}

function getLaunchProfileForActiveNotebook(
  context: vscode.ExtensionContext,
): NotebookLaunchProfile | undefined {
  const notebookUri = getActiveNotebookUriKey();
  if (!notebookUri) {
    return undefined;
  }
  return getLaunchProfileForNotebookUri(context, notebookUri);
}

function getLaunchProfileForNotebookUri(
  context: vscode.ExtensionContext,
  notebookUri: string,
): NotebookLaunchProfile | undefined {
  return getNotebookLaunchProfiles(context)[notebookUri];
}

function hasRunningServerSession(
  kind: ActiveJupyterServerSession["kind"],
  notebookUri?: string,
): boolean {
  if (
    !isProcessRunning(jupyterServerProcess) ||
    activeJupyterServerSession?.kind !== kind
  ) {
    return false;
  }
  if (notebookUri && activeJupyterServerSession.notebookUri !== notebookUri) {
    return false;
  }
  return true;
}

async function getConfiguredCandidateForNotebookPath(
  workspaceRoot: string,
  notebookRelativePath: string,
): Promise<CalkitEnvNotebookKernelSource | undefined> {
  const info = await readCalkitConfig(workspaceRoot);
  if (!info) {
    return undefined;
  }

  return resolveConfiguredCandidateForNotebookPath(info, notebookRelativePath);
}

async function autoSelectEnvironmentForActiveNotebook(
  context: vscode.ExtensionContext,
): Promise<void> {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    return;
  }

  const notebookUri = getActiveNotebookUriKey();
  if (!notebookUri) {
    return;
  }

  if (autoSelectingNotebookUris.has(notebookUri)) {
    return;
  }

  const notebookRelativePath = getActiveNotebookRelativePath(workspaceRoot);
  if (!notebookRelativePath) {
    return;
  }

  const configuredCandidate = await getConfiguredCandidateForNotebookPath(
    workspaceRoot,
    notebookRelativePath,
  );
  if (!configuredCandidate) {
    log(
      `No environment configured in calkit.yaml for notebook ${notebookRelativePath}`,
    );
    return;
  }

  // Show the SLURM auto-start confirmation as early as possible when there is
  // no active session, so users don't wait through kernel checks first.
  if (
    configuredCandidate.outerSlurmEnvironment &&
    !hasRunningServerSession("slurm", notebookUri)
  ) {
    if (slurmAutoStartSuppressedThisSession.has(notebookUri)) {
      log(
        `Skipping auto-start for '${configuredCandidate.environmentName}' because this notebook's SLURM session was stopped and requires explicit restart.`,
      );
      await refreshNotebookToolbarContext(context);
      return;
    }

    if (slurmAutoStartDeclinedThisSession.has(notebookUri)) {
      log(
        `Skipping auto-start for '${configuredCandidate.environmentName}' because it was declined earlier in this session.`,
      );
      await refreshNotebookToolbarContext(context);
      return;
    }

    const shouldStart = await confirmAutoStartSlurmNotebookSession(
      configuredCandidate.environmentName,
      notebookRelativePath,
    );
    if (!shouldStart) {
      slurmAutoStartDeclinedThisSession.add(notebookUri);
      await refreshNotebookToolbarContext(context);
      return;
    }

    slurmAutoStartDeclinedThisSession.delete(notebookUri);
  }

  const config = await readCalkitConfig(workspaceRoot);
  if (!config) {
    return;
  }

  // If this notebook has already been configured in this session,
  // check if the kernel matches and skip if it does.
  // This avoids re-checking the environment when switching tabs.
  if (configuredNotebooksThisSession.has(notebookUri)) {
    const expectedKernelName = await getExpectedKernelNameForEnvironment(
      workspaceRoot,
      configuredCandidate.innerEnvironment,
      "-e",
    );
    if (expectedKernelName) {
      const selectedKernelName =
        getSelectedKernelNameForActiveNotebook(notebookUri);
      const hasMatchingServer = configuredCandidate.outerSlurmEnvironment
        ? hasRunningServerSession("slurm", notebookUri)
        : true;
      if (selectedKernelName === expectedKernelName && hasMatchingServer) {
        log(
          `Notebook kernel '${selectedKernelName}' already matches the calkit environment '${configuredCandidate.environmentName}'; skipping re-selection.`,
        );
        return;
      }
    }
  }

  autoSelectingNotebookUris.add(notebookUri);

  try {
    log(
      `Auto-selecting calkit.yaml environment '${configuredCandidate.environmentName}' for notebook ${notebookRelativePath}.`,
    );

    if (configuredCandidate.outerSlurmEnvironment) {
      await saveLaunchProfileForNotebookUri(context, notebookUri, {
        environmentName: configuredCandidate.environmentName,
        innerEnvironment: configuredCandidate.innerEnvironment,
        innerKind: configuredCandidate.innerKind,
        outerSlurmEnvironment: configuredCandidate.outerSlurmEnvironment,
        slurmOptions: getNotebookSlurmOptionsWithDefaults(
          getDefaultSlurmOptions(
            config.environments?.[configuredCandidate.outerSlurmEnvironment],
          ),
        ),
        preferredPort: getDefaultPort(),
      });

      if (hasRunningServerSession("slurm", notebookUri)) {
        log(
          `Reusing running SLURM notebook session for '${configuredCandidate.environmentName}' and ensuring the kernel is selected.`,
        );
        const expectedKernel = await getExpectedKernelSpecForEnvironment(
          workspaceRoot,
          configuredCandidate.innerEnvironment,
          "-e",
        );
        const kernelId = expectedKernel
          ? await trySelectExpectedKernelFromAvailableCandidates({
              kernelName: expectedKernel.kernelName,
              displayName: expectedKernel.displayName,
              notebookUri,
            })
          : undefined;
        if (kernelId) {
          configuredNotebooksThisSession.add(notebookUri);
        }
      } else {
        log(
          `Auto-starting SLURM notebook session for '${configuredCandidate.environmentName}'.`,
        );
        const connected = await startSlurmJobForActiveNotebook(
          context,
          notebookUri,
        );
        if (connected) {
          configuredNotebooksThisSession.add(notebookUri);
        }
      }

      await refreshNotebookToolbarContext(context);
      return;
    }

    const kernelId = await registerAndSelectKernel(
      workspaceRoot,
      configuredCandidate.innerEnvironment,
      "-e",
      notebookUri,
      configuredCandidate.innerKind,
    );
    if (kernelId) {
      log(
        `Auto-selected kernel ${kernelId} for environment ${configuredCandidate.environmentName}`,
      );
      configuredNotebooksThisSession.add(notebookUri);
    }

    await refreshNotebookToolbarContext(context);
  } finally {
    autoSelectingNotebookUris.delete(notebookUri);
  }
}

async function askForSlurmOptions(
  defaults?: SlurmLaunchOptions,
): Promise<SlurmLaunchOptions | undefined> {
  const effectiveDefaults = getNotebookSlurmOptionsWithDefaults(defaults);
  const gpus = await vscode.window.showInputBox({
    title: "Slurm option: --gpus",
    prompt: "Optional GPU count or value (e.g., 1 or a100:1)",
    value: effectiveDefaults.gpus ?? "",
    placeHolder: "leave blank to skip",
  });
  if (gpus === undefined) {
    return undefined;
  }

  const time = await vscode.window.showInputBox({
    title: "Slurm option: --time",
    prompt: "Optional time (e.g., 60 or 01:00:00)",
    value: effectiveDefaults.time ?? "",
    placeHolder: "leave blank to skip",
  });
  if (time === undefined) {
    return undefined;
  }

  const extra = await vscode.window.showInputBox({
    title: "Additional srun options",
    prompt: "Optional raw options appended as-is (e.g., --cpus-per-task=8)",
    value: effectiveDefaults.extra ?? "",
    placeHolder: "leave blank to skip",
  });
  if (extra === undefined) {
    return undefined;
  }

  return compactSlurmOptions({
    gpus,
    time,
    partition: effectiveDefaults.partition,
    extra,
  });
}

function getNotebookSlurmOptionsWithDefaults(
  defaults?: SlurmLaunchOptions,
): SlurmLaunchOptions {
  return compactSlurmOptions({
    gpus: defaults?.gpus,
    time: defaults?.time ?? DEFAULT_NOTEBOOK_SLURM_TIME,
    partition: defaults?.partition,
    extra: defaults?.extra,
  });
}

async function confirmAutoStartSlurmNotebookSession(
  environmentName: string,
  notebookPath: string,
): Promise<boolean> {
  const choice = await vscode.window.showWarningMessage(
    `Notebook '${notebookPath}' is configured to run in '${environmentName}', which starts a SLURM job. Start it now?`,
    "Start SLURM Job",
    "Not Now",
  );
  return choice === "Start SLURM Job";
}

function getDefaultPort(): number {
  const configured = vscode.workspace
    .getConfiguration("calkit.notebook")
    .get<number>("defaultJupyterPort", 8888);
  return configured > 0 ? configured : 8888;
}

function buildLaunchCommand(
  picked: CalkitEnvNotebookKernelSource,
  workspaceRoot: string,
  config: CalkitInfo,
  port: number,
  slurmOptions?: SlurmLaunchOptions,
  serverToken?: string,
  dockerContainerName?: string,
  defaultKernelName?: string,
  notebookRelativePath?: string,
): string {
  const cdPart = `cd ${shQuote(workspaceRoot)}`;
  const checkPart = `calkit check env -n ${shQuote(picked.innerEnvironment)}`;
  // For non-docker environments, check the kernel (with --no-check to skip
  // redundant env check since we already do calkit check env above)
  const kernelCheckPart =
    picked.innerKind !== "docker"
      ? `calkit nb check-kernel -e ${shQuote(
          picked.innerEnvironment,
        )} --no-check`
      : "";

  // Docker and Slurm need ip=0.0.0.0 and token for external access
  const needsExternalAccess =
    picked.outerSlurmEnvironment || picked.innerKind === "docker";
  const defaultKernelFlag = buildDefaultKernelFlag(defaultKernelName);
  const jupyterPart = needsExternalAccess
    ? `calkit jupyter lab --ip=0.0.0.0 --no-browser --port=${port}${
        serverToken ? ` --IdentityProvider.token=${shQuote(serverToken)}` : ""
      }${defaultKernelFlag}`
    : `calkit jupyter lab --no-browser --IdentityProvider.token='' --ServerApp.password='' --port=${port}${defaultKernelFlag}`;

  const xenvPart = `calkit xenv -n ${shQuote(
    picked.innerEnvironment,
  )} -- ${jupyterPart}`;

  const prefixParts = [cdPart];
  // Check env first, then check kernel (without redundant env check)
  if (picked.innerKind === "docker") {
    prefixParts.push(checkPart);
  } else {
    prefixParts.push(checkPart, kernelCheckPart);
  }

  if (!picked.outerSlurmEnvironment) {
    // uv/julia kernels can be registered up front and used directly by Jupyter.
    if (needsKernelRegistration(picked.innerKind)) {
      return `${prefixParts.join(" && ")} && ${jupyterPart}`;
    }

    // Docker environments launch Jupyter inside the container
    if (picked.innerKind === "docker") {
      return buildDockerRunCommand(
        picked,
        workspaceRoot,
        config,
        port,
        serverToken,
        dockerContainerName,
      );
    }
    return `${prefixParts.join(" && ")} && ${xenvPart}`;
  }

  const slurmSetupCommands = getEffectiveSlurmSetupCommands(
    config,
    picked,
    notebookRelativePath,
  );
  const opts: string[] = [];
  if (slurmOptions?.gpus?.trim()) {
    opts.push(`--gpus=${slurmOptions.gpus.trim()}`);
  }
  if (slurmOptions?.time?.trim()) {
    opts.push(`--time=${slurmOptions.time.trim()}`);
  }
  if (slurmOptions?.partition?.trim()) {
    opts.push(`--partition=${slurmOptions.partition.trim()}`);
  }
  if (slurmOptions?.extra?.trim()) {
    opts.push(slurmOptions.extra.trim());
  }

  // For a SLURM outer environment, run jupyter directly under srun.
  // Run checks and launch in the same remote shell so setup side effects
  // (e.g., module loads) apply to both kernel checks and Jupyter startup.
  const rawJupyterCmd = `calkit jupyter lab --ip=0.0.0.0 --no-browser --port=${port}${
    serverToken ? ` --IdentityProvider.token=${shQuote(serverToken)}` : ""
  }${defaultKernelFlag}`;
  const remoteParts = [
    ...slurmSetupCommands,
    checkPart,
    ...(picked.innerKind === "docker" ? [] : [kernelCheckPart]),
    rawJupyterCmd,
  ];
  const remoteCmd = remoteParts.join(" && ");
  const srunOptions = opts.join(" ");
  const srunPart =
    `srun -J ckvscode --kill-on-bad-exit ${srunOptions} bash -lc ${shQuote(
      remoteCmd,
    )}`.trim();
  return `${cdPart} && ${srunPart}`;
}

function getEffectiveSlurmSetupCommands(
  config: CalkitInfo,
  picked: CalkitEnvNotebookKernelSource,
  notebookRelativePath?: string,
): string[] {
  if (!picked.outerSlurmEnvironment) {
    return [];
  }
  const env = config.environments?.[picked.outerSlurmEnvironment];
  const envSetup = Array.isArray(env?.default_setup)
    ? env.default_setup
        .map((cmd) => (typeof cmd === "string" ? cmd.trim() : ""))
        .filter((cmd) => cmd.length > 0)
    : [];
  const stageSetup = getNotebookStageSlurmSetupCommands(
    config,
    notebookRelativePath,
    picked.environmentName,
  );
  const merged = [...envSetup, ...stageSetup];
  return merged.filter((cmd, idx) => merged.indexOf(cmd) === idx);
}

function getNotebookStageSlurmSetupCommands(
  config: CalkitInfo,
  notebookRelativePath: string | undefined,
  environmentName: string,
): string[] {
  if (!notebookRelativePath) {
    return [];
  }
  const targetPath = normalizeConfigPath(notebookRelativePath);
  const stages = config.pipeline?.stages;
  if (!stages) {
    return [];
  }
  for (const stage of Object.values(stages)) {
    if (stage.kind !== "jupyter-notebook") {
      continue;
    }
    if (stage.environment !== environmentName) {
      continue;
    }
    const stagePath =
      typeof stage.notebook_path === "string"
        ? normalizeConfigPath(stage.notebook_path)
        : undefined;
    if (stagePath !== targetPath) {
      continue;
    }
    const setup = stage.slurm?.setup;
    if (!Array.isArray(setup)) {
      return [];
    }
    return setup
      .map((cmd) => (typeof cmd === "string" ? cmd.trim() : ""))
      .filter((cmd) => cmd.length > 0);
  }
  return [];
}

function normalizeConfigPath(pathText: string): string {
  return pathText.replace(/\\/g, "/");
}

function buildDefaultKernelFlag(kernelName?: string): string {
  return kernelName?.trim()
    ? ` --MappingKernelManager.default_kernel_name=${shQuote(
        kernelName.trim(),
      )}`
    : "";
}

function buildDockerRunCommand(
  picked: CalkitEnvNotebookKernelSource,
  workspaceRoot: string,
  config: CalkitInfo,
  port: number,
  serverToken?: string,
  containerName?: string,
): string {
  const env = config.environments?.[picked.innerEnvironment];
  if (!env) {
    throw new Error(`Environment ${picked.innerEnvironment} not found`);
  }

  const image = env.image || picked.innerEnvironment;
  const wdir = env.wdir || "/work";

  const dockerArgs: string[] = ["docker", "run"];

  // Platform
  if (env.platform) {
    dockerArgs.push("--platform", env.platform);
  }

  // Environment variables
  if (env.env_vars) {
    for (const [key, value] of Object.entries(env.env_vars)) {
      dockerArgs.push("-e", `${key}=${value}`);
    }
  }

  // GPUs
  if (env.gpus) {
    dockerArgs.push("--gpus", env.gpus);
  }

  // Port mapping - ensure Jupyter port is mapped
  const portMapped = env.ports?.some((p: string) => p.includes(`${port}`));
  if (!portMapped) {
    dockerArgs.push("-p", `${port}:${port}`);
  }
  if (env.ports) {
    for (const portSpec of env.ports) {
      // Skip if we already added this port
      if (!portSpec.includes(`${port}`)) {
        dockerArgs.push("-p", portSpec);
      }
    }
  }

  // User mapping (defaults to current user)
  if (env.user !== undefined) {
    dockerArgs.push("--user", env.user);
  }

  // Additional args from environment config
  if (env.args) {
    dockerArgs.push(...env.args);
  }

  // Standard docker run flags for background execution
  dockerArgs.push("--rm");
  if (containerName) {
    dockerArgs.push("--name", containerName);
  }

  // Working directory and volume mount
  dockerArgs.push("-w", wdir);
  dockerArgs.push("-v", `${workspaceRoot}:${wdir}`);

  // Image name
  dockerArgs.push(image);

  // Jupyter command (no need for --ip=0.0.0.0 with port mapping)
  const tokenArg = serverToken
    ? `--IdentityProvider.token=${shQuote(serverToken)}`
    : "";
  dockerArgs.push(
    "sh",
    "-c",
    `jupyter lab --no-browser --port=${port} ${tokenArg}`.trim(),
  );

  const dockerCmd = dockerArgs.map(shQuote).join(" ");

  // Prepend environment check to lock the environment
  const cdPart = `cd ${shQuote(workspaceRoot)}`;
  const checkPart = `calkit check env -n ${shQuote(picked.innerEnvironment)}`;

  return `${cdPart} && ${checkPart} && ${dockerCmd}`;
}

function needsKernelRegistration(kind: EnvKind): boolean {
  return kernelRegistrationKinds.has(kind);
}

function createServerToken(): string {
  return `calkit-${Math.random().toString(36).slice(2, 12)}`;
}

function getManagedDockerContainerName(envName: string, port: number): string {
  const safeEnv = envName.toLowerCase().replace(/[^a-z0-9_.-]/g, "-");
  return `calkit-nb-${safeEnv}-${port}`;
}

async function stopManagedDockerContainerIfExists(
  containerName: string,
): Promise<void> {
  try {
    await execFileAsync("docker", ["rm", "-f", containerName]);
    log(`Removed existing managed Docker container: ${containerName}`);
  } catch {
    // Container not found or not running; nothing to do.
  }
}

async function waitForPortToBeFree(
  port: number,
  timeoutMs = 5_000,
): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isPortFree(port)) {
      return true;
    }
    await sleep(250);
  }
  return false;
}

async function isPortFree(port: number): Promise<boolean> {
  return await new Promise<boolean>((resolve) => {
    const server = net.createServer();
    server.unref();

    server.once("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "EADDRINUSE") {
        resolve(false);
      } else {
        resolve(false);
      }
    });

    server.listen(port, "127.0.0.1", () => {
      server.close(() => resolve(true));
    });
  });
}

async function selectExistingJupyterServer(uri: string): Promise<boolean> {
  // Try a few command shapes; Jupyter command contracts vary across versions.
  const attempts: Array<{ command: string; args: unknown[] }> = [
    { command: "jupyter.selectjupyteruri", args: [uri] },
    { command: "jupyter.selectjupyteruri", args: [{ uri }] },
    { command: "jupyter.commandLineSelectJupyterURI", args: [uri] },
    { command: "jupyter.selectjupyteruri", args: [] },
  ];

  for (const attempt of attempts) {
    try {
      await vscode.commands.executeCommand(attempt.command, ...attempt.args);
      return true;
    } catch {
      // Try next command signature.
    }
  }

  return false;
}

async function switchToLocalJupyterServerSilently(): Promise<boolean> {
  // Best effort: move notebooks off a dead remote server after SLURM stop.
  const attempts: Array<{ command: string; args: unknown[] }> = [
    { command: "jupyter.selectjupyteruri", args: ["local"] },
    { command: "jupyter.selectjupyteruri", args: [{ uri: "local" }] },
    { command: "jupyter.commandLineSelectJupyterURI", args: ["local"] },
    { command: "jupyter.selectjupyteruri", args: [""] },
    { command: "jupyter.selectjupyteruri", args: [{ uri: "" }] },
  ];

  for (const attempt of attempts) {
    try {
      await vscode.commands.executeCommand(attempt.command, ...attempt.args);
      return true;
    } catch {
      // Try next signature.
    }
  }

  return false;
}

async function waitForServerReady(
  uri: string,
  options?: {
    sessionKind?: ActiveJupyterServerSession["kind"];
    notebookUri?: string;
  },
  timeoutMs = 300_000,
  pollMs = 1_000,
): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (
      options?.sessionKind &&
      !hasRunningServerSession(options.sessionKind, options.notebookUri)
    ) {
      return false;
    }
    if (await isHttpEndpointReachable(uri)) {
      return true;
    }
    await sleep(pollMs);
  }
  return false;
}

async function isHttpEndpointReachable(targetUrl: string): Promise<boolean> {
  return await new Promise<boolean>((resolve) => {
    let parsed: URL;
    try {
      parsed = new URL(targetUrl);
    } catch {
      resolve(false);
      return;
    }

    const client = parsed.protocol === "https:" ? https : http;
    const req = client.request(
      {
        method: "GET",
        hostname: parsed.hostname,
        port: parsed.port,
        path: `${parsed.pathname}${parsed.search}`,
        timeout: 1_500,
      },
      (res) => {
        // Any HTTP response means the server is accepting connections.
        res.resume();
        resolve(true);
      },
    );

    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
    req.end();
  });
}

async function registerAndSelectKernel(
  workspaceRoot: string,
  envName: string,
  envFlag: "-n" | "-e",
  expectedNotebookUri?: string,
  kind?: EnvKind,
): Promise<string | undefined> {
  log(`Registering and selecting kernel for env: ${envName} (kind=${kind})`);

  return await withKernelProgress(
    "Checking environment and setting kernel...",
    async () => {
      const kernelSpec = await getExpectedKernelSpecForEnvironment(
        workspaceRoot,
        envName,
        envFlag,
        true,
      );
      if (!kernelSpec) {
        return undefined;
      }

      const { kernelName, displayName } = kernelSpec;
      log(`Extracted kernel name: ${kernelName}`);

      const selectedKernelId = await tryAutoSelectKernel(
        kernelName,
        displayName,
        expectedNotebookUri,
      );

      if (selectedKernelId) {
        log(`Kernel selection successful`);
        return selectedKernelId;
      }

      log(`Kernel selection failed or unconfirmed`);
      void vscode.window.showWarningMessage(
        `Kernel '${kernelName}' was registered but auto-selection timed out. It should appear in the notebook kernel picker (top-right).`,
      );
      return undefined;
    },
  );
}

async function tryAutoSelectKernel(
  kernelName: string,
  displayName?: string,
  expectedNotebookUri?: string,
): Promise<string | undefined> {
  const editor = getNotebookEditorForUri(expectedNotebookUri);
  if (!editor) {
    if (expectedNotebookUri) {
      log(
        `No notebook editor found for kernel selection (target=${expectedNotebookUri})`,
      );
    } else {
      log("No active notebook editor found for kernel selection");
    }
    return undefined;
  }

  log(`Attempting to select kernel: ${kernelName}`);
  const editorId = getActiveNotebookEditorId() ?? "(none)";
  log(`Editor ID: ${editorId}`);

  const selectedKernelId = await trySelectKernelViaNotebookApi(
    editor,
    kernelName,
    displayName,
  );
  if (selectedKernelId) {
    log(`Successfully selected kernel controller: ${selectedKernelId}`);
    return selectedKernelId;
  }

  log(`Failed to select kernel: ${kernelName}`);
  return undefined;
}

async function trySelectExpectedKernelFromAvailableCandidates(options: {
  kernelName: string;
  displayName?: string;
  existingKernelIds?: Set<string>;
  requireNewKernel?: boolean;
  notebookUri?: string;
}): Promise<string | undefined> {
  const editor = getNotebookEditorForUri(options.notebookUri);
  if (!editor) {
    return undefined;
  }

  const existingIds = options.existingKernelIds ?? new Set<string>();
  const requireNewKernel = options.requireNewKernel ?? false;

  for (let attempt = 0; attempt < 15; attempt++) {
    const resolved = await getResolvedNotebookKernels(editor);
    if (!Array.isArray(resolved) || resolved.length === 0) {
      await sleep(400);
      continue;
    }

    const candidates = resolved.filter((kernel) => {
      const id = kernel.id ?? "";
      return id.includes("/");
    });

    const candidatePool = requireNewKernel
      ? candidates.filter((kernel) => {
          const id = kernel.id ?? "";
          return id.length > 0 && !existingIds.has(id);
        })
      : candidates;

    if (requireNewKernel && candidatePool.length === 0) {
      await sleep(400);
      continue;
    }

    const matchingCandidates = candidatePool.filter((candidate) =>
      kernelMatchesPreference(
        candidate,
        options.kernelName,
        options.displayName,
      ),
    );

    if (matchingCandidates.length === 0) {
      await sleep(400);
      continue;
    }

    const sorted = [...matchingCandidates].sort((a, b) => {
      const sa = scoreKernelCandidate(
        a,
        "",
        options.kernelName,
        options.displayName,
      );
      const sb = scoreKernelCandidate(
        b,
        "",
        options.kernelName,
        options.displayName,
      );
      return sb - sa;
    });

    for (const candidate of sorted) {
      const id = candidate.id ?? "";
      const slash = id.indexOf("/");
      if (slash <= 0 || slash >= id.length - 1) {
        continue;
      }

      const extension = id.slice(0, slash);
      const controllerId = id.slice(slash + 1);

      try {
        await vscode.commands.executeCommand("notebook.selectKernel", {
          extension,
          id: controllerId,
          notebookEditor: editor,
          skipIfAlreadySelected: false,
        });
        await sleep(500);

        if (
          await isKernelSelectedForActiveNotebook(options.kernelName, editor)
        ) {
          log(`Selected expected server kernel: ${id}`);
          return id;
        }

        log(
          `Selected expected kernel candidate '${id}', but metadata confirmation timed out. Assuming selection succeeded.`,
        );
        return id;
      } catch {
        // Try next candidate.
      }
    }

    await sleep(400);
  }

  log(
    `Could not find expected kernel '${options.kernelName}' from connected server candidates.`,
  );
  return undefined;
}

async function tryAutoSelectBestAvailableKernel(options?: {
  existingKernelIds?: Set<string>;
  requireNewKernel?: boolean;
  preferredKernelName?: string;
  preferredDisplayName?: string;
  requirePreferredMatch?: boolean;
}): Promise<string | undefined> {
  const editor = vscode.window.activeNotebookEditor;
  if (!editor) {
    return undefined;
  }

  const languageHint = getNotebookLanguageHint(editor).toLowerCase();
  const existingIds = options?.existingKernelIds ?? new Set<string>();
  const requireNewKernel = options?.requireNewKernel ?? false;
  const preferredKernelName = options?.preferredKernelName;
  const preferredDisplayName = options?.preferredDisplayName;
  const requirePreferredMatch = options?.requirePreferredMatch ?? false;

  for (let attempt = 0; attempt < 15; attempt++) {
    const resolved = await getResolvedNotebookKernels(editor);

    if (!Array.isArray(resolved) || resolved.length === 0) {
      await sleep(400);
      continue;
    }

    const candidates = resolved.filter((k) => {
      const id = k.id ?? "";
      return id.includes("/");
    });

    const newCandidates = candidates.filter((k) => {
      const id = k.id ?? "";
      return id.length > 0 && !existingIds.has(id);
    });

    const candidatePool = newCandidates.length > 0 ? newCandidates : candidates;
    if (requireNewKernel && newCandidates.length === 0) {
      await sleep(400);
      continue;
    }

    const preferredCandidates =
      preferredKernelName || preferredDisplayName
        ? candidatePool.filter((candidate) =>
            kernelMatchesPreference(
              candidate,
              preferredKernelName,
              preferredDisplayName,
            ),
          )
        : [];
    if (
      requirePreferredMatch &&
      (preferredKernelName || preferredDisplayName) &&
      preferredCandidates.length === 0
    ) {
      await sleep(400);
      continue;
    }

    const selectionPool =
      preferredCandidates.length > 0 ? preferredCandidates : candidatePool;

    const sorted = [...selectionPool].sort((a, b) => {
      const sa = scoreKernelCandidate(
        a,
        languageHint,
        preferredKernelName,
        preferredDisplayName,
      );
      const sb = scoreKernelCandidate(
        b,
        languageHint,
        preferredKernelName,
        preferredDisplayName,
      );
      return sb - sa;
    });

    for (const candidate of sorted) {
      const id = candidate.id ?? "";
      const slash = id.indexOf("/");
      if (slash <= 0 || slash >= id.length - 1) {
        continue;
      }

      const extension = id.slice(0, slash);
      const controllerId = id.slice(slash + 1);

      try {
        await vscode.commands.executeCommand("notebook.selectKernel", {
          extension,
          id: controllerId,
          notebookEditor: editor,
          skipIfAlreadySelected: false,
        });
        await sleep(400);

        if (await hasAnyKernelSelectedForActiveNotebook()) {
          log(`Auto-selected best available kernel: ${id}`);
          return id;
        }
      } catch {
        // Try next candidate.
      }
    }

    await sleep(400);
  }

  return undefined;
}

function scoreKernelCandidate(
  kernel: {
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  },
  languageHint: string,
  preferredKernelName?: string,
  preferredDisplayName?: string,
): number {
  const id = (kernel.id ?? "").toLowerCase();
  const label = (kernel.label ?? "").toLowerCase();
  const desc = (kernel.description ?? "").toLowerCase();
  const detail = (kernel.detail ?? "").toLowerCase();

  let score = 0;

  if (id.startsWith("ms-toolsai.jupyter/")) {
    score += 50;
  }

  if (
    kernelMatchesPreference(kernel, preferredKernelName, preferredDisplayName)
  ) {
    score += 1000;
  }

  if (languageHint.length > 0) {
    if (
      label.includes(languageHint) ||
      desc.includes(languageHint) ||
      detail.includes(languageHint)
    ) {
      score += 100;
    }
  }

  if (
    languageHint === "python" &&
    (label.includes("ipykernel") || label.includes("python"))
  ) {
    score += 30;
  }
  if (languageHint === "julia" && label.includes("julia")) {
    score += 30;
  }
  if (languageHint === "r" && label.includes("r")) {
    score += 30;
  }

  return score;
}

function kernelMatchesPreference(
  kernel: {
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  },
  kernelName?: string,
  displayName?: string,
): boolean {
  const normalizedKernel = (kernelName ?? "").toLowerCase();
  const normalizedDisplay = (displayName ?? "").toLowerCase();
  const id = (kernel.id ?? "").toLowerCase();
  const label = (kernel.label ?? "").toLowerCase();
  const desc = (kernel.description ?? "").toLowerCase();
  const detail = (kernel.detail ?? "").toLowerCase();
  const idCompact = id.replace(/[^a-z0-9]/g, "");
  const kernelCompact = normalizedKernel.replace(/[^a-z0-9]/g, "");
  const displayCompact = normalizedDisplay.replace(/[^a-z0-9]/g, "");

  return (
    (normalizedKernel.length > 0 && id.endsWith(`/${normalizedKernel}`)) ||
    (normalizedKernel.length > 0 && id === normalizedKernel) ||
    (normalizedKernel.length > 0 && id.includes(normalizedKernel)) ||
    (kernelCompact.length > 0 && idCompact.includes(kernelCompact)) ||
    (normalizedDisplay.length > 0 && label === normalizedDisplay) ||
    (normalizedDisplay.length > 0 && label.includes(normalizedDisplay)) ||
    (normalizedDisplay.length > 0 && desc.includes(normalizedDisplay)) ||
    (normalizedDisplay.length > 0 && detail.includes(normalizedDisplay)) ||
    (displayCompact.length > 0 &&
      label.replace(/[^a-z0-9]/g, "").includes(displayCompact)) ||
    (normalizedKernel.length > 0 && label.includes(normalizedKernel))
  );
}

function getNotebookLanguageHint(editor: vscode.NotebookEditor): string {
  const metadata = editor.notebook.metadata as any;
  const fromMetadata =
    metadata?.language_info?.name ?? metadata?.metadata?.language_info?.name;
  if (typeof fromMetadata === "string" && fromMetadata.trim()) {
    return fromMetadata.trim();
  }

  const firstCodeCell = editor.notebook
    .getCells()
    .find((cell) => cell.kind === vscode.NotebookCellKind.Code);
  if (firstCodeCell?.document.languageId) {
    return firstCodeCell.document.languageId;
  }

  return "";
}

async function getResolvedNotebookKernels(
  editor: vscode.NotebookEditor,
): Promise<
  Array<{ id?: string; label?: string; description?: string; detail?: string }>
> {
  const resolved = (await vscode.commands.executeCommand(
    "_resolveNotebookKernels",
    {
      viewType: editor.notebook.notebookType,
      uri: editor.notebook.uri,
    },
  )) as Array<{
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  }>;
  return Array.isArray(resolved) ? resolved : [];
}

async function getResolvedKernelIdsForActiveNotebook(
  notebookUri?: string,
): Promise<Set<string>> {
  const editor = getNotebookEditorForUri(notebookUri);
  if (!editor) {
    return new Set<string>();
  }

  const kernels = await getResolvedNotebookKernels(editor);
  const ids = kernels
    .map((k) => k.id)
    .filter((id): id is string => typeof id === "string" && id.length > 0);
  return new Set(ids);
}

async function trySelectKernelViaNotebookApi(
  editor: vscode.NotebookEditor,
  kernelName: string,
  displayName?: string,
): Promise<string | undefined> {
  type ResolvedKernel = {
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  };

  try {
    const normalizedDisplay = (displayName ?? "").toLowerCase();
    const normalizedKernel = kernelName.toLowerCase();

    // Jupyter kernel discovery can lag behind check-kernel. Poll briefly.
    let candidate: ResolvedKernel | undefined;
    for (let attempt = 0; attempt < 10; attempt++) {
      const resolved = (await vscode.commands.executeCommand(
        "_resolveNotebookKernels",
        {
          viewType: editor.notebook.notebookType,
          uri: editor.notebook.uri,
        },
      )) as ResolvedKernel[];

      if (!Array.isArray(resolved) || resolved.length === 0) {
        log(
          `No kernels returned by _resolveNotebookKernels (attempt ${
            attempt + 1
          }/10)`,
        );
        await sleep(300);
        continue;
      }

      log(`Resolved ${resolved.length} kernels (attempt ${attempt + 1}/10)`);

      candidate = resolved.find((k) =>
        kernelMatchesPreference(k, normalizedKernel, normalizedDisplay),
      );

      if (candidate?.id) {
        break;
      }

      await sleep(300);
    }

    if (!candidate?.id) {
      log(
        `No matching controller found for kernel '${kernelName}' (${
          displayName ?? "no display name"
        })`,
      );
      return undefined;
    }

    const slash = candidate.id.indexOf("/");
    if (slash <= 0 || slash >= candidate.id.length - 1) {
      log(
        `Resolved controller id is not in extension/id format: ${candidate.id}`,
      );
      return undefined;
    }

    const extension = candidate.id.slice(0, slash);
    const id = candidate.id.slice(slash + 1);

    log(`Selecting kernel controller for '${kernelName}'`);
    await vscode.commands.executeCommand("notebook.selectKernel", {
      extension,
      id,
      notebookEditor: editor,
      skipIfAlreadySelected: false,
    });

    // Give VS Code/Jupyter time to bind the selected controller and update metadata.
    await sleep(500);

    if (await isKernelSelectedForActiveNotebook(kernelName, editor)) {
      log(`Kernel selection confirmed in notebook metadata`);
      return candidate.id;
    }

    // Selection may have succeeded even though metadata check failed
    // (metadata update can be delayed in some VS Code versions).
    // Log the situation but still return success if controller was actually selected.
    log(
      `Kernel controller was selected but metadata confirmation timed out. Assuming selection succeeded.`,
    );
    return candidate.id;
  } catch (err) {
    log(
      `Controller selection failed: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }

  return undefined;
}

async function isKernelSelectedForActiveNotebook(
  kernelName: string,
  editor?: vscode.NotebookEditor,
): Promise<boolean> {
  // Let Jupyter update notebook metadata after a kernel change.
  await sleep(250);
  const targetEditor = editor ?? vscode.window.activeNotebookEditor;
  const md = targetEditor?.notebook.metadata as any;
  const selectedName =
    md?.kernelspec?.name ?? md?.metadata?.kernelspec?.name ?? "";
  const notebookPath = targetEditor?.notebook.uri.fsPath;

  log(`Checking kernel selection - notebook: ${notebookPath}`);
  log(
    `Current kernel metadata: ${
      typeof selectedName === "string" ? selectedName : "(not set)"
    }`,
  );
  log(`Expected kernel: ${kernelName}`);

  // Check for exact match on the kernel name
  const isSelected =
    typeof selectedName === "string" && selectedName === kernelName;
  if (!isSelected) {
    // Log additional debugging info when not selected
    log(`Full metadata object: ${JSON.stringify(md, null, 2)}`);
  }
  return isSelected;
}

function getNotebookEditorForUri(
  notebookUri?: string,
): vscode.NotebookEditor | undefined {
  if (!notebookUri) {
    return vscode.window.activeNotebookEditor;
  }

  const active = vscode.window.activeNotebookEditor;
  if (active?.notebook.uri.toString() === notebookUri) {
    return active;
  }

  return vscode.window.visibleNotebookEditors.find(
    (editor) => editor.notebook.uri.toString() === notebookUri,
  );
}

async function hasAnyKernelSelectedForActiveNotebook(
  notebookUri?: string,
): Promise<boolean> {
  // Give Jupyter a brief moment to attach kernelspec metadata after connect.
  await sleep(200);
  const md = getNotebookEditorForUri(notebookUri)?.notebook.metadata as any;
  const selectedName =
    md?.kernelspec?.name ?? md?.metadata?.kernelspec?.name ?? "";
  return typeof selectedName === "string" && selectedName.trim().length > 0;
}

function getSelectedKernelNameForActiveNotebook(
  notebookUri?: string,
): string | undefined {
  const md = getNotebookEditorForUri(notebookUri)?.notebook.metadata as any;
  const selectedName =
    md?.kernelspec?.name ?? md?.metadata?.kernelspec?.name ?? "";
  return typeof selectedName === "string" && selectedName.trim().length > 0
    ? selectedName
    : undefined;
}

async function getExpectedKernelNameForEnvironment(
  workspaceRoot: string,
  envName: string,
  envFlag: "-n" | "-e",
): Promise<string | undefined> {
  const result = await getExpectedKernelSpecForEnvironment(
    workspaceRoot,
    envName,
    envFlag,
  );
  return result?.kernelName;
}

async function getExpectedKernelSpecForEnvironment(
  workspaceRoot: string,
  envName: string,
  envFlag: "-n" | "-e",
  allowAutoInstallPrompt = false,
): Promise<{ kernelName: string; displayName?: string } | undefined> {
  const runCheckKernel = async (): Promise<{
    kernelSpec?: { kernelName: string; displayName?: string };
    details?: string;
  }> => {
    try {
      const args = [
        "nb",
        "check-kernel",
        envFlag,
        envName,
        "--json",
        "--auto-add-deps",
      ];
      const { stdout, stderr } = await execFileAsync("calkit", args, {
        cwd: workspaceRoot,
      });
      log(`calkit output: ${stdout}`);
      const kernelSpec = parseCheckKernelJson(stdout);
      if (!kernelSpec) {
        const details = `${stderr || stdout || "Invalid JSON output"}`.trim();
        return { details };
      }
      return { kernelSpec };
    } catch (error: unknown) {
      const err = error as {
        stdout?: string;
        stderr?: string;
        message?: string;
      };
      const details = (err.stderr || err.stdout || err.message || "").trim();
      return { details };
    }
  };

  const firstAttempt = await runCheckKernel();
  if (firstAttempt.kernelSpec) {
    return firstAttempt.kernelSpec;
  }

  const details = firstAttempt.details || "unknown error";
  const missingIJulia = details.includes(MISSING_IJULIA_ERROR_TEXT);
  if (allowAutoInstallPrompt && missingIJulia) {
    const choice = await vscode.window.showWarningMessage(
      "IJulia is missing from this Julia environment. Install it now so the notebook kernel can be registered?",
      "Install IJulia",
      "Cancel",
    );
    if (choice === "Install IJulia") {
      const secondAttempt = await runCheckKernel();
      if (secondAttempt.kernelSpec) {
        return secondAttempt.kernelSpec;
      }
      const retryDetails = secondAttempt.details || "unknown error";
      log(`Error after auto-install retry: ${retryDetails}`);
      void vscode.window.showErrorMessage(
        `Failed to run 'calkit nb check-kernel ${envFlag} ${envName}' after installing IJulia: ${retryDetails}`,
      );
      return undefined;
    }
    return undefined;
  }

  if (allowAutoInstallPrompt) {
    log(`Error: ${details}`);
    void vscode.window.showErrorMessage(
      `Failed to run 'calkit nb check-kernel ${envFlag} ${envName}': ${details}`,
    );
  }

  if (!allowAutoInstallPrompt) {
    return undefined;
  }

  return undefined;
}

function parseCheckKernelJson(
  stdout: string,
): { kernelName: string; displayName?: string } | undefined {
  try {
    const jsonMatch = stdout.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return undefined;
    }
    const result = JSON.parse(jsonMatch[0]);
    const kernelName = result.kernel_name;
    if (typeof kernelName !== "string" || kernelName.length === 0) {
      return undefined;
    }
    const displayName =
      typeof result.display_name === "string" && result.display_name.length > 0
        ? result.display_name
        : undefined;
    return { kernelName, displayName };
  } catch {
    return undefined;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getActiveNotebookEditorId(): string | undefined {
  const editorAny = vscode.window.activeNotebookEditor as
    | (vscode.NotebookEditor & { id?: string })
    | undefined;
  if (!editorAny?.id) {
    return undefined;
  }
  return editorAny.id;
}

async function openKernelPicker(): Promise<void> {
  if (!vscode.window.activeNotebookEditor) {
    void vscode.window.showWarningMessage(
      "Open a notebook editor first, then select a kernel.",
    );
    return;
  }

  const editorId = getActiveNotebookEditorId();
  const args = editorId ? { notebookEditorId: editorId } : undefined;
  try {
    if (args) {
      await vscode.commands.executeCommand("notebook.selectKernel", args);
    } else {
      await vscode.commands.executeCommand("notebook.selectKernel");
    }
  } catch {
    // Fallback to no-args invocation for VS Code versions that ignore args.
    await vscode.commands.executeCommand("notebook.selectKernel");
  }
}

function shQuote(input: string): string {
  return `'${input.replace(/'/g, `'\\''`)}'`;
}

async function startSlurmJobForActiveNotebook(
  context: vscode.ExtensionContext,
  notebookUri?: string,
): Promise<boolean> {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    void vscode.window.showErrorMessage(
      "Open a workspace folder to start a Calkit Jupyter SLURM job.",
    );
    return false;
  }

  const targetNotebookUri = notebookUri ?? getActiveNotebookUriKey();
  const profile = targetNotebookUri
    ? getLaunchProfileForNotebookUri(context, targetNotebookUri)
    : undefined;
  if (!profile?.outerSlurmEnvironment) {
    void vscode.window.showInformationMessage(
      "No saved SLURM notebook profile for this notebook. Select a nested slurm:environment first.",
    );
    return false;
  }

  if (targetNotebookUri) {
    slurmAutoStartSuppressedThisSession.delete(targetNotebookUri);
    slurmAutoStartDeclinedThisSession.delete(targetNotebookUri);
  }

  const config = await readCalkitConfig(workspaceRoot);
  if (!config?.environments) {
    void vscode.window.showErrorMessage(
      "Could not read environments from calkit.yaml.",
    );
    return false;
  }

  const picked: CalkitEnvNotebookKernelSource = {
    label: profile.environmentName,
    description: `${profile.outerSlurmEnvironment} + ${profile.innerKind}`,
    detail: "Resume SLURM notebook session",
    environmentName: profile.environmentName,
    innerEnvironment: profile.innerEnvironment,
    innerKind: profile.innerKind,
    outerSlurmEnvironment: profile.outerSlurmEnvironment,
    outerKind: "slurm",
  };

  const port = profile.preferredPort ?? getDefaultPort();
  const serverToken = createServerToken();

  return await withKernelProgress(
    "Starting Jupyter SLURM job and selecting kernel...",
    async () => {
      const expectedKernel = await getExpectedKernelSpecForEnvironment(
        workspaceRoot,
        profile.innerEnvironment,
        "-e",
      );
      const launchCmd = buildLaunchCommand(
        picked,
        workspaceRoot,
        config,
        port,
        profile.slurmOptions,
        serverToken,
        undefined,
        expectedKernel?.kernelName,
        getNotebookRelativePathForUri(workspaceRoot, profile.notebookUri),
      );

      startServerInBackground(launchCmd, workspaceRoot, {
        kind: "slurm",
        notebookUri: profile.notebookUri,
      });

      const uri = `http://localhost:${port}/lab?token=${encodeURIComponent(
        serverToken,
      )}`;
      await vscode.env.clipboard.writeText(uri);
      const kernelsBeforeConnect = await getResolvedKernelIdsForActiveNotebook(
        profile.notebookUri,
      );

      const serverReady = await waitForServerReady(uri, {
        sessionKind: "slurm",
        notebookUri: profile.notebookUri,
      });
      const connected = serverReady
        ? await selectExistingJupyterServer(uri)
        : false;

      let selectedKernelId: string | undefined;
      if (connected) {
        const expectedKernel = await getExpectedKernelSpecForEnvironment(
          workspaceRoot,
          profile.innerEnvironment,
          "-e",
        );
        selectedKernelId = expectedKernel
          ? await trySelectExpectedKernelFromAvailableCandidates({
              kernelName: expectedKernel.kernelName,
              displayName: expectedKernel.displayName,
              existingKernelIds: kernelsBeforeConnect,
              requireNewKernel: true,
              notebookUri: profile.notebookUri,
            })
          : undefined;
      }

      if (!connected) {
        const launchState = hasRunningServerSession(
          "slurm",
          profile.notebookUri,
        )
          ? "started"
          : "failed to start";
        void vscode.window.showWarningMessage(
          `SLURM server ${launchState}, but VS Code could not auto-connect. URI copied: ${uri}`,
        );
      } else if (!selectedKernelId) {
        void vscode.window.showInformationMessage(
          "Connected to SLURM server. Select kernel manually if needed.",
        );
      }

      await refreshNotebookToolbarContext(context);
      return connected;
    },
  );
}

async function stopSlurmJobForActiveNotebook(
  context: vscode.ExtensionContext,
): Promise<void> {
  const runningProcess = jupyterServerProcess;
  if (!runningProcess) {
    void vscode.window.showInformationMessage(
      "No running Calkit Jupyter SLURM job.",
    );
    await refreshNotebookToolbarContext(context);
    return;
  }
  if (
    !isProcessRunning(runningProcess) ||
    activeJupyterServerSession?.kind !== "slurm"
  ) {
    void vscode.window.showInformationMessage(
      "No running Calkit Jupyter SLURM job.",
    );
    await refreshNotebookToolbarContext(context);
    return;
  }

  terminateJupyterServerProcess("user requested SLURM stop");
  log("Stopped Jupyter SLURM job by user request");
  const stoppedNotebookUri =
    activeJupyterServerSession?.notebookUri ?? getActiveNotebookUriKey();
  activeJupyterServerSession = undefined;
  jupyterServerProcess = undefined;

  if (stoppedNotebookUri) {
    slurmAutoStartSuppressedThisSession.add(stoppedNotebookUri);
    slurmAutoStartDeclinedThisSession.delete(stoppedNotebookUri);
  }

  // Best effort to break Jupyter's reconnect loop to a dead remote kernel.
  await switchToLocalJupyterServerSilently();

  // Actively select the inner environment's local kernel to break the
  // "Reconnecting to the kernel..." loop. Using the inner environment from the
  // launch profile gives the best chance of landing on the right kernel.
  const workspaceRoot = getWorkspaceRoot();
  const stoppedProfile = stoppedNotebookUri
    ? getLaunchProfileForNotebookUri(context, stoppedNotebookUri)
    : undefined;

  let kernelSelected: string | undefined;
  if (workspaceRoot && stoppedProfile?.innerEnvironment) {
    const kernelSpec = await getExpectedKernelSpecForEnvironment(
      workspaceRoot,
      stoppedProfile.innerEnvironment,
      "-e",
    );
    if (kernelSpec) {
      kernelSelected = await tryAutoSelectKernel(
        kernelSpec.kernelName,
        kernelSpec.displayName,
        stoppedNotebookUri,
      );
    }
  }

  if (!kernelSelected) {
    kernelSelected = await tryAutoSelectBestAvailableKernel(
      stoppedProfile?.innerEnvironment
        ? { preferredKernelName: stoppedProfile.innerEnvironment }
        : {},
    );
  }

  if (!kernelSelected) {
    // Couldn't auto-select a kernel; open the kernel picker as a fallback so
    // the user can choose one and the reconnect loop is broken.
    const editorId = getActiveNotebookEditorId();
    try {
      await vscode.commands.executeCommand(
        "notebook.selectKernel",
        editorId ? { notebookEditorId: editorId } : undefined,
      );
    } catch {
      // Not critical; suppress.
    }
  }

  await refreshNotebookToolbarContext(context);
}

async function stopSlurmJobForClosedNotebook(
  context: vscode.ExtensionContext,
  notebookUri: string,
): Promise<void> {
  const runningProcess = jupyterServerProcess;
  if (
    !runningProcess ||
    !isProcessRunning(runningProcess) ||
    activeJupyterServerSession?.kind !== "slurm" ||
    activeJupyterServerSession.notebookUri !== notebookUri
  ) {
    return;
  }

  terminateJupyterServerProcess("notebook closed");
  log(`Stopped SLURM notebook job because notebook was closed: ${notebookUri}`);
  activeJupyterServerSession = undefined;
  jupyterServerProcess = undefined;

  // Notebook is gone; clear session-only auto-start state for this URI.
  slurmAutoStartSuppressedThisSession.delete(notebookUri);
  slurmAutoStartDeclinedThisSession.delete(notebookUri);

  await switchToLocalJupyterServerSilently();
  await refreshNotebookToolbarContext(context);
}

async function restartCalkitJobForActiveNotebook(
  context: vscode.ExtensionContext,
): Promise<void> {
  const sessionKindToRestart = activeJupyterServerSession?.kind;

  // First, stop any running server
  const runningProcess = jupyterServerProcess;
  if (runningProcess && isProcessRunning(runningProcess)) {
    terminateJupyterServerProcess("server restart");
    log("Stopped notebook server to restart");
    activeJupyterServerSession = undefined;
    jupyterServerProcess = undefined;
    // Give the server a moment to shut down
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  // Then, start a new server based on the session type
  if (sessionKindToRestart === "slurm") {
    await startSlurmJobForActiveNotebook(context);
  } else if (sessionKindToRestart === "docker") {
    // For Docker, we would need to trigger the docker container restart
    // For now, just show an info message
    void vscode.window.showInformationMessage(
      "Docker server restarted. You may need to reconnect.",
    );
    await refreshNotebookToolbarContext(context);
  } else {
    void vscode.window.showInformationMessage(
      "No running notebook server to restart.",
    );
  }
}

async function refreshActiveFileStageContext(
  fileUri: vscode.Uri | undefined,
): Promise<void> {
  const workspaceRoot = getWorkspaceRoot();
  let hasStage = false;
  if (workspaceRoot && fileUri) {
    hasStage = (await findStageForFile(workspaceRoot, fileUri)) !== undefined;
  }
  await vscode.commands.executeCommand(
    "setContext",
    "calkit.activeFileHasStage",
    hasStage,
  );
}

async function refreshNotebookToolbarContext(
  context: vscode.ExtensionContext,
): Promise<void> {
  const profile = getLaunchProfileForActiveNotebook(context);
  const hasResumableSlurm = Boolean(profile?.outerSlurmEnvironment);
  const isRunningSlurm = hasRunningServerSession("slurm");
  const isRunningDocker = hasRunningServerSession("docker");
  const workspaceRoot = getWorkspaceRoot();
  const notebookUri = vscode.window.activeNotebookEditor?.notebook.uri;
  let notebookHasStage = false;
  if (workspaceRoot && notebookUri) {
    const stageName = await findStageForFile(workspaceRoot, notebookUri);
    notebookHasStage = stageName !== undefined;
  }

  await vscode.commands.executeCommand(
    "setContext",
    "calkit.hasResumableSlurmSession",
    hasResumableSlurm,
  );
  await vscode.commands.executeCommand(
    "setContext",
    "calkit.hasRunningSlurmSession",
    isRunningSlurm,
  );
  await vscode.commands.executeCommand(
    "setContext",
    "calkit.hasRunningDockerSession",
    isRunningDocker,
  );
  await vscode.commands.executeCommand(
    "setContext",
    "calkit.notebookHasStage",
    notebookHasStage,
  );

  if (slurmStatusBarItem) {
    if (isRunningSlurm) {
      slurmStatusBarItem.show();
    } else {
      slurmStatusBarItem.hide();
    }
  }
}

async function setKernelCheckingState(isChecking: boolean): Promise<void> {
  await vscode.commands.executeCommand(
    "setContext",
    "calkit.isSettingKernel",
    isChecking,
  );
}

async function withKernelProgress<T>(
  message: string,
  task: () => Promise<T>,
): Promise<T> {
  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: message,
      cancellable: false,
    },
    async () => {
      await setKernelCheckingState(true);
      try {
        return await task();
      } finally {
        await setKernelCheckingState(false);
      }
    },
  );
}

function isProcessRunning(
  process: import("node:child_process").ChildProcess | undefined,
): boolean {
  return Boolean(process && process.exitCode === null && !process.killed);
}

function terminateJupyterServerProcess(reason: string): void {
  const runningProcess = jupyterServerProcess;
  if (!runningProcess || !isProcessRunning(runningProcess)) {
    return;
  }

  terminateChildProcessTree(runningProcess);
  log(`Stopped managed notebook server process (${reason})`);
  jupyterServerProcess = undefined;
  activeJupyterServerSession = undefined;
}

function terminateChildProcessTree(
  child: import("node:child_process").ChildProcess,
): void {
  const pid = child.pid;
  if (!pid) {
    child.kill();
    return;
  }

  if (process.platform === "win32") {
    const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
    killer.on("error", () => {
      child.kill();
    });
    return;
  }

  try {
    // Kill the process group so shell children like srun are terminated too.
    process.kill(-pid, "SIGTERM");
    setTimeout(() => {
      try {
        process.kill(-pid, "SIGKILL");
      } catch {
        // Ignore if the process group already exited.
      }
    }, 2_000);
  } catch {
    child.kill();
  }
}

function startServerInBackground(
  command: string,
  cwd: string,
  session: ActiveJupyterServerSession,
): void {
  if (
    jupyterServerProcess &&
    jupyterServerProcess.exitCode === null &&
    !jupyterServerProcess.killed
  ) {
    log("Stopping previous Calkit server process");
    terminateJupyterServerProcess("starting a new server");
  }

  log(`Starting server in background: ${command}`);
  const child = spawn(command, {
    cwd,
    shell: true,
    detached: process.platform !== "win32",
    env: process.env,
  });
  jupyterServerProcess = child;
  activeJupyterServerSession = session;

  child.stdout?.on("data", (chunk: Buffer | string) => {
    const text = chunk.toString().trim();
    if (text) {
      log(`[server] ${text}`);
    }
  });

  child.stderr?.on("data", (chunk: Buffer | string) => {
    const text = chunk.toString().trim();
    if (text) {
      log(`[server:err] ${text}`);
    }
  });

  child.on("error", (error) => {
    log(`Background server failed to start: ${String(error)}`);
    void vscode.window.showErrorMessage(
      `Failed to start Calkit notebook server in background: ${String(error)}`,
    );
  });

  child.on("close", (code, signal) => {
    log(
      `Background server exited (code=${code ?? "null"}, signal=${
        signal ?? "null"
      })`,
    );
    if (jupyterServerProcess === child) {
      jupyterServerProcess = undefined;
      activeJupyterServerSession = undefined;
      if (extensionContextRef) {
        void refreshNotebookToolbarContext(extensionContextRef);
      }
    }
  });
}

function registerKernelSourceIfAvailable(
  context: vscode.ExtensionContext,
): void {
  try {
    const notebooksAny = vscode.notebooks as any;
    if (typeof notebooksAny.registerKernelSourceActionProvider !== "function") {
      return;
    }

    const provider = {
      provideNotebookKernelSourceActions: async () => {
        return [
          {
            label: "Calkit environments...",
            detail: "Select a Calkit environment and kernel",
            command: {
              title: "Calkit environments...",
              command: COMMAND_SELECT_ENV,
            },
          },
        ];
      },
    };

    context.subscriptions.push(
      notebooksAny.registerKernelSourceActionProvider(
        "jupyter-notebook",
        provider,
      ),
    );
  } catch (error) {
    console.warn(
      "Calkit: notebook kernel source proposal unavailable; using stable command/toolbar entry points only.",
      error,
    );
  }
}
