/**
 * The Calkit sidebar's Overleaf section: each synced folder's status,
 * checked in the background, with buttons to sync, to run, save, and sync
 * in one step, and to import a project, walking someone through a file
 * that changed in two places when that stops a sync.
 */
import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import type { CalkitSidebarProvider, SidebarItem } from "../sidebar";
import {
  getClash,
  getClashMessage,
  getContinueArgs,
  getOverleafRow,
  parseOverleafStatus,
  type Clash,
  type OverleafState,
} from "./core";

const SIDEBAR_VIEW_ID = "calkit-sidebar";
const RUN_SAVE_SYNC = ["run", "--save", "--overleaf"];

let running = false;
let provider: CalkitSidebarProvider | undefined;
let state: OverleafState = { checking: false };
// The workspace whose folders are checked, while it syncs with Overleaf
let syncedRoot: string | undefined;
let checkTimer: ReturnType<typeof setInterval> | undefined;
let lastChecked = 0;
// What the last sync in the background stopped on, said only once
let lastAutoSyncError: string | undefined;
let log: (message: string) => void = () => undefined;

/** Whether folders that need a sync are synced in the background. */
function isAutoSyncOn(): boolean {
  return vscode.workspace
    .getConfiguration("calkit")
    .get<boolean>("overleaf.autoSync", false);
}

/** Run a Calkit command out of sight, for its exit code and output. */
function runCalkitQuietly(
  root: string,
  args: string[],
): Promise<{ code: number; output: string }> {
  return new Promise((resolve) => {
    const child = execFile(
      "calkit",
      args,
      { cwd: root, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) =>
        resolve({
          code: error ? (typeof error.code === "number" ? error.code : 1) : 0,
          output: `${stdout}${stderr}`,
        }),
    );
    // Nobody's there to answer a question
    child.stdin?.end();
  });
}

/**
 * Sync with Overleaf in the background, offering to resolve a file that
 * changed in both places, and saying once why it stopped otherwise.
 */
async function autoSync(root: string): Promise<void> {
  running = true;
  state = { ...state, checking: true };
  provider?.setOverleafState(state);
  let result: { code: number; output: string };
  try {
    result = await runCalkitQuietly(root, ["overleaf", "sync"]);
  } finally {
    running = false;
    state = { ...state, checking: false };
  }
  log(`Auto-sync with Overleaf:\n${result.output}`);
  await checkOverleaf(false);
  if (result.code === 0) {
    lastAutoSyncError = undefined;
    return;
  }
  const found = await findClash(root);
  if (found) {
    await offerToResolve(root, found, []);
    return;
  }
  const lines = result.output
    .split("\n")
    .map((line) => line.replace(/\x1b\[[0-9;]*m/g, "").trim())
    .filter(Boolean);
  const error = (lines[lines.length - 1] ?? "").replace(/^Error: /, "");
  if (error === lastAutoSyncError) {
    return;
  }
  lastAutoSyncError = error;
  const choice = await vscode.window.showWarningMessage(
    `Auto-sync with Overleaf stopped: ${error}`,
    "Run, Save, and Sync",
  );
  if (choice) {
    await runSaveSync(root);
  }
}

/** Run a Calkit command as a task, so its output shows, for its exit code. */
async function runCalkitTask(
  root: string,
  args: string[],
): Promise<number | undefined> {
  const task = new vscode.Task(
    { type: "calkit" },
    vscode.TaskScope.Workspace,
    `calkit ${args.join(" ")}`,
    "calkit",
    // The extension may have added where calkit is installed to PATH
    new vscode.ProcessExecution("calkit", args, {
      cwd: root,
      env: { PATH: process.env.PATH ?? "" },
    }),
  );
  task.presentationOptions = {
    reveal: vscode.TaskRevealKind.Always,
    panel: vscode.TaskPanelKind.Shared,
    clear: true,
  };
  return new Promise((resolve) => {
    const ended = vscode.tasks.onDidEndTaskProcess((e) => {
      if (e.execution.task === task) {
        ended.dispose();
        resolve(e.exitCode);
      }
    });
    vscode.tasks.executeTask(task).then(undefined, (error) => {
      ended.dispose();
      void vscode.window.showErrorMessage(
        `Couldn't run calkit: ${
          error instanceof Error ? error.message : error
        }`,
      );
      resolve(undefined);
    });
  });
}

/** A command's output, or nothing if it failed. */
function getOutput(
  command: string,
  root: string,
  args: string[],
  allowFailure = false,
): Promise<string | null> {
  return new Promise((resolve) => {
    execFile(
      command,
      args,
      { cwd: root, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout) => resolve(error && !allowFailure ? null : stdout),
    );
  });
}

/** Whether a sync with Overleaf stopped on a file changed in both places. */
function hasOverleafConflict(repoRoot: string): boolean {
  return fs.existsSync(
    path.join(repoRoot, ".calkit", "overleaf", "CONFLICT.json"),
  );
}

/** What a run or sync stopped on, if it was a file changed in two places. */
async function findClash(
  root: string,
): Promise<{ clash: Clash; repoRoot: string; remoteUrl?: string } | null> {
  const repoRoot = (
    await getOutput("git", root, ["rev-parse", "--show-toplevel"])
  )?.trim();
  if (!repoRoot) {
    return null;
  }
  const unmerged = await getOutput("git", root, [
    "diff",
    "--name-only",
    "--diff-filter=U",
    "-z",
  ]);
  const clash = getClash({
    overleafConflict: hasOverleafConflict(repoRoot),
    merging:
      (await getOutput("git", root, [
        "rev-parse",
        "-q",
        "--verify",
        "MERGE_HEAD",
      ])) !== null,
    unmerged: (unmerged ?? "").split("\0").filter(Boolean),
  });
  if (!clash) {
    return null;
  }
  const remoteUrl = (
    await getOutput("git", root, ["remote", "get-url", "origin"])
  )?.trim();
  return { clash, repoRoot, remoteUrl };
}

/** Open a file in two places in VS Code's merge editor, or as text. */
async function openClashedFile(repoRoot: string, file: string): Promise<void> {
  const uri = vscode.Uri.file(path.join(repoRoot, file));
  try {
    await vscode.commands.executeCommand("git.openMergeEditor", uri);
  } catch {
    await vscode.window.showTextDocument(uri);
  }
}

/**
 * Say what clashed, with buttons to resolve it and carry on, finishing
 * what stopped and then running ``then``.
 */
async function offerToResolve(
  root: string,
  found: { clash: Clash; repoRoot: string; remoteUrl?: string },
  then: string[][],
): Promise<void> {
  const { clash, repoRoot, remoteUrl } = found;
  const actions = clash.files.length ? ["Resolve", "Continue"] : ["Continue"];
  const choice = await vscode.window.showWarningMessage(
    getClashMessage(clash, remoteUrl),
    ...actions,
  );
  if (choice === "Resolve") {
    await openClashedFile(repoRoot, clash.files[0]);
    // The message closes on a click, and is still needed to carry on
    await offerToResolve(root, found, then);
  } else if (choice === "Continue") {
    await runSteps(root, [getContinueArgs(clash), ...then], then);
  }
}

/**
 * Run Calkit commands in turn, stopping at one that fails, with the sidebar
 * showing they're going. A clash that stops one is offered to resolve,
 * then ``after`` runs.
 */
async function runSteps(
  root: string,
  steps: string[][],
  after: string[][],
  done?: string,
): Promise<void> {
  if (running) {
    void vscode.window.showInformationMessage("Already running");
    return;
  }
  running = true;
  let ok = false;
  try {
    ok = await vscode.window.withProgress(
      { location: { viewId: SIDEBAR_VIEW_ID } },
      async () => {
        for (const step of steps) {
          if ((await runCalkitTask(root, step)) !== 0) {
            return false;
          }
        }
        return true;
      },
    );
  } finally {
    running = false;
    void checkOverleaf();
  }
  if (ok) {
    if (done) {
      void vscode.window.showInformationMessage(done);
    }
    return;
  }
  const found = await findClash(root);
  if (found) {
    await offerToResolve(root, found, after);
  } else {
    void vscode.window.showErrorMessage(
      "Calkit stopped. See the terminal for why.",
    );
  }
}

/** Run the pipeline, save, and sync with Overleaf, in one step. */
export function runSaveSync(root: string): Promise<void> {
  return runSteps(
    root,
    [RUN_SAVE_SYNC],
    [RUN_SAVE_SYNC],
    "Ran, saved, and synced",
  );
}

/**
 * Ask Calkit what a sync of each folder would do, and show it, syncing in
 * the background if that's on and ``allowAutoSync``.
 */
export async function checkOverleaf(allowAutoSync = true): Promise<void> {
  const root = syncedRoot;
  if (!root || !provider || state.checking) {
    return;
  }
  lastChecked = Date.now();
  state = { ...state, checking: true };
  provider.setOverleafState(state);
  const stdout = await getOutput(
    "calkit",
    root,
    ["overleaf", "status", "--json"],
    true,
  );
  if (root !== syncedRoot) {
    return;
  }
  const checked = parseOverleafStatus(stdout ?? "");
  const repoRoot = (
    await getOutput("git", root, ["rev-parse", "--show-toplevel"])
  )?.trim();
  state = {
    ...checked,
    // What was known stays shown when Overleaf can't be reached
    statuses:
      checked.statuses ?? (checked.needsLogin ? undefined : state.statuses),
    error: checked.statuses ? undefined : checked.error,
    conflict: repoRoot ? hasOverleafConflict(repoRoot) : false,
  };
  provider.setOverleafState(state);
  if (
    allowAutoSync &&
    isAutoSyncOn() &&
    !running &&
    !state.conflict &&
    state.statuses?.some((status) => getOverleafRow(status, state).needsSync)
  ) {
    await autoSync(root);
  }
}

/**
 * Check folders synced with Overleaf in the background while a workspace
 * syncs any, every ``calkit.overleaf.checkInterval`` seconds while VS Code
 * has focus, and again on coming back to it.
 */
export function setOverleafSynced(root: string, synced: boolean): void {
  const wasSynced = syncedRoot === root;
  syncedRoot = synced ? root : undefined;
  if (!synced) {
    state = { checking: false };
    provider?.setOverleafState(state);
    return;
  }
  if (!wasSynced) {
    void checkOverleaf();
  }
}

/** Register the Overleaf section's commands and background checks. */
export function registerOverleaf(
  context: vscode.ExtensionContext,
  sidebarProvider: CalkitSidebarProvider,
  getWorkspaceRoot: () => string | undefined,
  logMessage: (message: string) => void,
): void {
  provider = sidebarProvider;
  log = logMessage;
  const showAutoSync = () =>
    vscode.commands.executeCommand(
      "setContext",
      "calkit-vscode.autoSyncOverleaf",
      isAutoSyncOn(),
    );
  void showAutoSync();
  const setAutoSync = async (on: boolean) => {
    // Only for this project, since it saves and pushes on its own
    await vscode.workspace
      .getConfiguration("calkit")
      .update("overleaf.autoSync", on, vscode.ConfigurationTarget.Workspace);
    lastAutoSyncError = undefined;
    if (on) {
      void checkOverleaf();
    }
  };
  const getInterval = () =>
    vscode.workspace
      .getConfiguration("calkit")
      .get<number>("overleaf.checkInterval", 120);
  const schedule = () => {
    if (checkTimer) {
      clearInterval(checkTimer);
      checkTimer = undefined;
    }
    const seconds = getInterval();
    if (seconds > 0) {
      checkTimer = setInterval(() => {
        if (vscode.window.state.focused) {
          void checkOverleaf();
        }
      }, seconds * 1000);
    }
  };
  schedule();
  const withRoot =
    (run: (root: string, item?: SidebarItem) => unknown) =>
    (item?: SidebarItem) => {
      const root = getWorkspaceRoot();
      if (root) {
        void run(root, item);
      }
    };
  context.subscriptions.push(
    { dispose: () => checkTimer && clearInterval(checkTimer) },
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("calkit.overleaf.checkInterval")) {
        schedule();
      }
      if (e.affectsConfiguration("calkit.overleaf.autoSync")) {
        void showAutoSync();
      }
    }),
    vscode.window.onDidChangeWindowState((windowState) => {
      const seconds = getInterval();
      if (
        windowState.focused &&
        seconds > 0 &&
        Date.now() - lastChecked > seconds * 1000
      ) {
        void checkOverleaf();
      }
    }),
    vscode.commands.registerCommand(
      "calkit-vscode.enableAutoSyncOverleaf",
      () => setAutoSync(true),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.disableAutoSyncOverleaf",
      () => setAutoSync(false),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.runSaveSync",
      withRoot((root) => runSaveSync(root)),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.syncOverleaf",
      withRoot((root, item) => {
        const args = ["overleaf", "sync"];
        if (item?.nodeKind.startsWith("overleaf-folder") && item.nodeId) {
          args.push(item.nodeId);
        }
        return runSteps(root, [args], [], "Synced with Overleaf");
      }),
    ),
    vscode.commands.registerCommand("calkit-vscode.refreshOverleaf", () =>
      checkOverleaf(),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.openOnOverleaf",
      (item?: SidebarItem) => {
        const url = state.statuses?.find(
          (status) => status.path === item?.nodeId,
        )?.overleaf_url;
        if (url) {
          void vscode.env.openExternal(vscode.Uri.parse(url));
        }
      },
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.overleafLogin",
      withRoot((root) => runSteps(root, [["overleaf", "login"]], [])),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.resolveOverleafConflict",
      withRoot(async (root) => {
        const found = await findClash(root);
        if (found) {
          await offerToResolve(root, found, []);
        } else {
          void checkOverleaf();
        }
      }),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.importOverleaf",
      withRoot(async (root) => {
        const url = await vscode.window.showInputBox({
          title: "Import from Overleaf",
          prompt: "Overleaf project URL",
          placeHolder: "https://www.overleaf.com/project/...",
          ignoreFocusOut: true,
          validateInput: (value) =>
            /overleaf\.com\/project\/\w+/.test(value)
              ? undefined
              : "Paste the URL of an Overleaf project",
        });
        if (!url) {
          return;
        }
        const folder = await vscode.window.showInputBox({
          title: "Import from Overleaf",
          prompt: "Folder in this project to put it in",
          value: "paper",
          ignoreFocusOut: true,
        });
        if (!folder) {
          return;
        }
        await runSteps(
          root,
          [["overleaf", "import", url.trim(), folder.trim()]],
          [],
          `Imported into ${folder.trim()}`,
        );
      }),
    ),
  );
}
