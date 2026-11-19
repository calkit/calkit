/**
 * The Calkit sidebar's Run, save, and sync button: runs the pipeline, saves,
 * and syncs with Overleaf, and walks someone through a file that changed in
 * two places when that stops it.
 */
import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import { getClash, getClashMessage, getContinueArgs, type Clash } from "./core";

const SIDEBAR_VIEW_ID = "calkit-sidebar";

let running = false;

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

/** Git's output for a command, or nothing if it failed. */
function getGitOutput(root: string, args: string[]): Promise<string | null> {
  return new Promise((resolve) => {
    execFile("git", args, { cwd: root }, (error, stdout) =>
      resolve(error ? null : stdout),
    );
  });
}

/** What a run stopped on, if it was a file changed in two places. */
async function findClash(
  root: string,
): Promise<{ clash: Clash; repoRoot: string; remoteUrl?: string } | null> {
  const repoRoot = (
    await getGitOutput(root, ["rev-parse", "--show-toplevel"])
  )?.trim();
  if (!repoRoot) {
    return null;
  }
  const unmerged = await getGitOutput(root, [
    "diff",
    "--name-only",
    "--diff-filter=U",
    "-z",
  ]);
  const clash = getClash({
    overleafConflict: fs.existsSync(
      path.join(repoRoot, ".calkit", "overleaf", "CONFLICT.json"),
    ),
    merging:
      (await getGitOutput(root, [
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
    await getGitOutput(root, ["remote", "get-url", "origin"])
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

/** Say what clashed, with buttons to resolve it and carry on. */
async function offerToResolve(
  root: string,
  found: { clash: Clash; repoRoot: string; remoteUrl?: string },
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
    await offerToResolve(root, found);
  } else if (choice === "Continue") {
    await runSaveSync(root, getContinueArgs(clash));
  }
}

/**
 * Run the pipeline, save, and sync with Overleaf, first running ``first``,
 * e.g., to finish combining a file, with the sidebar showing it's going.
 */
export async function runSaveSync(
  root: string,
  first?: string[],
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
        if (first && (await runCalkitTask(root, first)) !== 0) {
          return false;
        }
        return (
          (await runCalkitTask(root, ["run", "--save", "--overleaf"])) === 0
        );
      },
    );
  } finally {
    running = false;
  }
  if (ok) {
    void vscode.window.showInformationMessage("Ran, saved, and synced");
    return;
  }
  const found = await findClash(root);
  if (found) {
    await offerToResolve(root, found);
  } else {
    void vscode.window.showErrorMessage(
      "Run, save, and sync failed. See the terminal for why.",
    );
  }
}
