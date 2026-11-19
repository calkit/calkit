/**
 * The Calkit sidebar's Overleaf section and Run and Save button: each
 * synced folder's status, checked in the background, with buttons to sync
 * and import, and running and saving in one step, syncing with Overleaf
 * too if that's on, walking someone through a file that changed in two
 * places when that stops it.
 */
import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import type { CalkitSidebarProvider, SidebarItem } from "../sidebar";
import {
  getClash,
  getClashMessage,
  getCommitMessageSuggestion,
  getContinueArgs,
  parseOverleafStatus,
  quoteShellArg,
  type Clash,
  type OverleafState,
} from "./core";

const SIDEBAR_VIEW_ID = "calkit-sidebar";

let running = false;
// Terminals with a command running, which typing into would interrupt
const busyTerminals = new Set<vscode.Terminal>();
let provider: CalkitSidebarProvider | undefined;
let state: OverleafState = { checking: false };
// The workspace whose folders are checked, while it syncs with Overleaf
let syncedRoot: string | undefined;
let checkTimer: ReturnType<typeof setInterval> | undefined;
let lastChecked = 0;
// Longer than this, asking Overleaf has hung, and later checks shouldn't
// wait on it
const STATUS_TIMEOUT_MS = 120_000;
/**
 * Whether Run and Save also syncs with Overleaf, when the project syncs
 * with it.
 */
function isAutoSyncOn(): boolean {
  return vscode.workspace
    .getConfiguration("calkit")
    .get<boolean>("overleaf.autoSync", true);
}

/**
 * Run Calkit commands in turn in the terminal Run Pipeline uses, so they
 * show there and it stays usable after, or a new one if something's
 * running in it, for whether they all worked, or nothing if the shell
 * can't say, in which case only the first is typed in.
 */
async function runInTerminal(
  root: string,
  steps: string[][],
): Promise<boolean | undefined> {
  const name = "calkit: run";
  const terminal =
    vscode.window.terminals.find(
      (t) => t.name === name && !t.exitStatus && !busyTerminals.has(t),
    ) ?? vscode.window.createTerminal({ name, cwd: root });
  terminal.show();
  // Ends early if the terminal is closed, e.g., to stop a run
  const untilClosed = <T>(promise: Promise<T>): Promise<T | undefined> =>
    new Promise((resolve) => {
      const closed = vscode.window.onDidCloseTerminal((t) => {
        if (t === terminal) {
          closed.dispose();
          resolve(undefined);
        }
      });
      void promise.then((value) => {
        closed.dispose();
        resolve(value);
      });
    });
  const integration =
    terminal.shellIntegration ??
    (await untilClosed(
      new Promise<vscode.TerminalShellIntegration | undefined>((resolve) => {
        const timeout = setTimeout(() => {
          changed.dispose();
          resolve(undefined);
        }, 3000);
        const changed = vscode.window.onDidChangeTerminalShellIntegration(
          (e) => {
            if (e.terminal === terminal) {
              clearTimeout(timeout);
              changed.dispose();
              resolve(e.shellIntegration);
            }
          },
        );
      }),
    ));
  // From the project, wherever the terminal has been since
  const commandLines = steps.map((step) =>
    ["calkit", "-C", root, ...step].map(quoteShellArg).join(" "),
  );
  if (!integration) {
    // Without knowing how one went, the next isn't chained on, since
    // shells chain differently, e.g., Windows PowerShell has no &&
    terminal.sendText(commandLines[0]);
    return undefined;
  }
  for (const commandLine of commandLines) {
    const execution = integration.executeCommand(commandLine);
    const code = await untilClosed(
      new Promise<number | undefined>((resolve) => {
        const ended = vscode.window.onDidEndTerminalShellExecution((e) => {
          if (e.execution === execution) {
            ended.dispose();
            resolve(e.exitCode);
          }
        });
      }),
    );
    if (code === undefined) {
      return undefined;
    }
    if (code !== 0) {
      return false;
    }
  }
  return true;
}

/** A command's output, or nothing if it failed. */
function getOutput(
  command: string,
  root: string,
  args: string[],
  allowFailure = false,
  timeout = 0,
): Promise<string | null> {
  return new Promise((resolve) => {
    execFile(
      command,
      args,
      { cwd: root, maxBuffer: 16 * 1024 * 1024, timeout },
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

/** The synced folder whose sync with Overleaf stopped on a conflict. */
function getOverleafConflictFolder(repoRoot: string): string | undefined {
  try {
    const info = JSON.parse(
      fs.readFileSync(
        path.join(repoRoot, ".calkit", "overleaf", "CONFLICT.json"),
        "utf-8",
      ),
    );
    return typeof info.wdir === "string" ? info.wdir : ".";
  } catch {
    return undefined;
  }
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
): Promise<void> {
  if (running) {
    void vscode.window.showInformationMessage("Already running");
    return;
  }
  running = true;
  let ok: boolean | undefined;
  try {
    ok = await vscode.window.withProgress(
      { location: { viewId: SIDEBAR_VIEW_ID } },
      () => runInTerminal(root, steps),
    );
  } finally {
    running = false;
    void checkOverleaf();
  }
  // The terminal and sidebar show it worked, and the shell may not say
  if (ok !== false) {
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

/** Run the pipeline in the terminal Run and Save uses. */
export function runPipeline(root: string): Promise<void> {
  return runSteps(root, [["run"]], []);
}

/** A commit message for the one file changed, if only one has. */
export async function suggestCommitMessage(
  root: string,
): Promise<string | undefined> {
  const porcelain = await getOutput("git", root, [
    "status",
    "--porcelain",
    "-z",
    "-uall",
  ]);
  return porcelain ? getCommitMessageSuggestion(porcelain) : undefined;
}

/**
 * Run the pipeline and save, with a message for the one file changed, or
 * one asked for if that's on, syncing with Overleaf too if the project
 * syncs with it and that's on.
 */
export async function runAndSave(root: string): Promise<void> {
  const sync = syncedRoot === root && isAutoSyncOn();
  const suggested = (await suggestCommitMessage(root)) ?? "Run pipeline";
  const ask = vscode.workspace
    .getConfiguration("calkit")
    .get<boolean>("runAndSave.askForMessage", false);
  const message = ask
    ? await vscode.window.showInputBox({
        title: sync ? "Calkit: Run, Save, and Sync" : "Calkit: Run and Save",
        prompt: "Commit message for saving your work",
        value: suggested,
        ignoreFocusOut: true,
      })
    : suggested;
  // Cancelled (Escape) returns undefined; an empty message is not allowed
  if (message === undefined) {
    return;
  }
  if (!message.trim()) {
    void vscode.window.showErrorMessage(
      "A commit message is required to save.",
    );
    return;
  }
  const steps = [
    ["run", "--save", "-m", message.trim(), ...(sync ? ["--overleaf"] : [])],
  ];
  await runSteps(root, steps, steps);
}

/** Ask Calkit what a sync of each folder would do, and show it. */
export async function checkOverleaf(): Promise<void> {
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
    STATUS_TIMEOUT_MS,
  );
  // Another workspace's folders are checked now, if any
  if (root !== syncedRoot) {
    state = { ...state, checking: false };
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
    conflict: repoRoot ? getOverleafConflictFolder(repoRoot) : undefined,
  };
  provider.setOverleafState(state);
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
): void {
  provider = sidebarProvider;
  const showAutoSync = () =>
    vscode.commands.executeCommand(
      "setContext",
      "calkit-vscode.autoSyncOverleaf",
      isAutoSyncOn(),
    );
  void showAutoSync();
  const setAutoSync = (on: boolean) =>
    vscode.workspace
      .getConfiguration("calkit")
      .update("overleaf.autoSync", on, vscode.ConfigurationTarget.Workspace);
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
    vscode.window.onDidStartTerminalShellExecution((e) =>
      busyTerminals.add(e.terminal),
    ),
    vscode.window.onDidEndTerminalShellExecution((e) =>
      busyTerminals.delete(e.terminal),
    ),
    vscode.window.onDidCloseTerminal((terminal) =>
      busyTerminals.delete(terminal),
    ),
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
      "calkit-vscode.runSave",
      withRoot((root) => runAndSave(root)),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.runSaveSync",
      withRoot((root) => runAndSave(root)),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.syncOverleaf",
      withRoot((root, item) => {
        const args = ["overleaf", "sync"];
        if (item?.nodeKind.startsWith("overleaf-folder") && item.nodeId) {
          args.push(item.nodeId);
        }
        return runSteps(root, [args], []);
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
        );
      }),
    ),
  );
}
