/**
 * Labels on notebook cells for the values, figures, and tables they're
 * marked to make, and the commands marking them, through `calkit nb mark`.
 */
import { execFile } from "node:child_process";
import * as path from "node:path";
import * as vscode from "vscode";
import {
  type CellOutputKind,
  type CellOutputMark,
  getAssignedNames,
  getDefaultMarkPath,
  getMarkArgs,
  getMarkLabel,
  getMarksForCell,
  getMarkTarget,
  getUnmarkArgs,
  hasImageOutput,
  parseCellOutputs,
  rankNamesForKind,
} from "./core";

const marksByNotebook = new Map<string, CellOutputMark[]>();
const marksChanged = new vscode.EventEmitter<void>();

/** What Calkit printed, and whether it worked. */
function runCalkit(
  root: string,
  args: string[],
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    execFile(
      "calkit",
      args,
      { cwd: root, maxBuffer: 16 * 1024 * 1024 },
      (error, stdout, stderr) =>
        resolve({ ok: !error, stdout: String(stdout), stderr: String(stderr) }),
    );
  });
}

/** Calkit's error, without the traceback or its "Error: " prefix. */
function getErrorText(stderr: string, stdout: string): string {
  const lines = `${stderr}\n${stdout}`
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const error = lines.reverse().find((l) => l.startsWith("Error: "));
  return (error ?? lines[0] ?? "Calkit failed").replace(/^Error: /, "");
}

/** A notebook's path in the project, or nothing if it's outside it. */
function getNotebookPath(root: string, uri: vscode.Uri): string | undefined {
  const rel = path.relative(root, uri.fsPath);
  if (!rel || rel.startsWith("..") || path.isAbsolute(rel)) {
    return undefined;
  }
  return rel.split(path.sep).join("/");
}

/** Read what a notebook's cells are marked to make, and relabel them. */
async function loadMarks(
  root: string,
  notebook: vscode.NotebookDocument,
): Promise<void> {
  const notebookPath = getNotebookPath(root, notebook.uri);
  if (!notebookPath || notebook.notebookType !== "jupyter-notebook") {
    return;
  }
  const { stdout } = await runCalkit(root, [
    "nb",
    "outputs",
    notebookPath,
    "--json",
  ]);
  marksByNotebook.set(notebook.uri.toString(), parseCellOutputs(stdout));
  marksChanged.fire();
}

function reloadAll(root: string): void {
  for (const notebook of vscode.workspace.notebookDocuments) {
    void loadMarks(root, notebook);
  }
}

/** The cell a command is for: the one whose toolbar it's in, or else the
 * first selected in the active notebook.
 */
function getCommandCell(arg: unknown): vscode.NotebookCell | undefined {
  if (
    arg &&
    typeof arg === "object" &&
    "notebook" in arg &&
    "index" in arg &&
    "document" in arg
  ) {
    return arg as vscode.NotebookCell;
  }
  const editor = vscode.window.activeNotebookEditor;
  const selection = editor?.selections[0];
  return editor && selection && !selection.isEmpty
    ? editor.notebook.cellAt(selection.start)
    : undefined;
}

/** Ask what a cell makes for documents, and mark it to be saved. */
async function markCellOutput(root: string, arg: unknown): Promise<void> {
  const cell = getCommandCell(arg);
  if (!cell || cell.kind !== vscode.NotebookCellKind.Code) {
    void vscode.window.showErrorMessage("Select a code cell");
    return;
  }
  const notebookPath = getNotebookPath(root, cell.notebook.uri);
  if (!notebookPath) {
    void vscode.window.showErrorMessage("Notebook isn't in this project");
    return;
  }
  const kindPick = await vscode.window.showQuickPick(
    [
      {
        label: "Value",
        description: "\\ckvalue",
        detail: "A number or text, e.g., a fitted constant",
        markKind: "value" as CellOutputKind,
      },
      {
        label: "Figure",
        description: "\\ckfigure",
        detail: "A plot, from its variable or the image the cell shows",
        markKind: "figure" as CellOutputKind,
      },
      {
        label: "Table",
        description: "\\cktable",
        detail: "A DataFrame, or a list of rows",
        markKind: "table" as CellOutputKind,
      },
    ],
    { title: "Mark as", placeHolder: "What this cell makes for documents" },
  );
  if (!kindPick) {
    return;
  }
  const kind = kindPick.markKind;
  // The variable it's saved from, or for a figure, what the cell shows
  const shown = "$(file-media) Image this cell shows";
  const other = "$(edit) Other variable…";
  const names = rankNamesForKind(
    getAssignedNames(cell.document.getText()),
    kind,
  );
  const mimeTypes = cell.outputs.flatMap((o) => o.items.map((i) => i.mime));
  const items: vscode.QuickPickItem[] = [
    ...(kind === "figure" && hasImageOutput(mimeTypes)
      ? [{ label: shown }]
      : []),
    ...names.map((n) => ({ label: n })),
    { label: other },
    ...(kind === "figure" && !hasImageOutput(mimeTypes)
      ? [{ label: shown, detail: "Run the cell first to see it here" }]
      : []),
  ];
  const variablePick = await vscode.window.showQuickPick(items, {
    title: `Mark ${kindPick.label.toLowerCase()}`,
    placeHolder: "Variable it's saved from",
  });
  if (!variablePick) {
    return;
  }
  let variable: string | undefined = variablePick.label;
  if (variable === shown) {
    variable = undefined;
  } else if (variable === other) {
    variable = await vscode.window.showInputBox({
      title: `Mark ${kindPick.label.toLowerCase()}`,
      prompt: "Variable name",
      validateInput: (v) =>
        /^[A-Za-z_][A-Za-z0-9_]*$/.test(v) ? undefined : "Not a variable name",
    });
    if (!variable) {
      return;
    }
  }
  let target = variable ?? "";
  if (kind !== "value") {
    const exts =
      kind === "figure"
        ? [".pdf", ".png", ".svg", ".jpg", ".jpeg"]
        : [".tex", ".csv", ".md", ".json"];
    const chosen = await vscode.window.showInputBox({
      title: `Mark ${kindPick.label.toLowerCase()}`,
      prompt:
        kind === "figure"
          ? "Path to save it to; PDF stays sharp in a paper"
          : "Path to save it to; .tex for \\cktable",
      value: getDefaultMarkPath(kind, notebookPath, variable),
      validateInput: (v) =>
        exts.some((e) => v.toLowerCase().endsWith(e))
          ? undefined
          : `Use ${exts.join(", ")}`,
    });
    if (!chosen) {
      return;
    }
    target = chosen.trim();
  }
  // The cell's ID is what's recorded, which needs the notebook saved
  if (cell.notebook.isDirty) {
    await cell.notebook.save();
  }
  const cellId =
    typeof cell.metadata?.id === "string" ? cell.metadata.id : undefined;
  const result = await runCalkit(
    root,
    getMarkArgs({
      notebookPath,
      cellId,
      cellIndex: cell.index,
      kind,
      variable,
      path: kind === "value" ? undefined : target,
    }),
  );
  if (!result.ok) {
    void vscode.window.showErrorMessage(
      getErrorText(result.stderr, result.stdout),
    );
    return;
  }
  vscode.window.setStatusBarMessage(`$(check) Marked ${target}`, 4000);
  await loadMarks(root, cell.notebook);
}

/** What to do with a mark, from its label: copy how to cite it, or unmark. */
async function showMarkActions(
  root: string,
  notebookUri: vscode.Uri,
  mark: CellOutputMark,
): Promise<void> {
  const copy = mark.citation ? `$(copy) Copy ${mark.citation}` : undefined;
  const unmark = "$(close) Unmark";
  const picked = await vscode.window.showQuickPick(
    [...(copy ? [copy] : []), unmark],
    { title: getMarkTarget(mark) },
  );
  if (picked === copy && mark.citation) {
    await vscode.env.clipboard.writeText(mark.citation);
    vscode.window.setStatusBarMessage(`$(check) Copied ${mark.citation}`, 4000);
  } else if (picked === unmark) {
    const notebookPath = getNotebookPath(root, notebookUri);
    if (!notebookPath) {
      return;
    }
    const result = await runCalkit(root, getUnmarkArgs(notebookPath, mark));
    if (!result.ok) {
      void vscode.window.showErrorMessage(
        getErrorText(result.stderr, result.stdout),
      );
    }
    const notebook = vscode.workspace.notebookDocuments.find(
      (n) => n.uri.toString() === notebookUri.toString(),
    );
    if (notebook) {
      await loadMarks(root, notebook);
    }
  }
}

/** Register the cell labels and commands for marking cell outputs. */
export function registerCellOutputs(
  context: vscode.ExtensionContext,
  getWorkspaceRoot: () => string | undefined,
): void {
  const withRoot =
    <T extends unknown[]>(fn: (root: string, ...args: T) => Promise<void>) =>
    async (...args: T) => {
      const root = getWorkspaceRoot();
      if (root) {
        await fn(root, ...args);
      }
    };
  context.subscriptions.push(
    vscode.notebooks.registerNotebookCellStatusBarItemProvider(
      "jupyter-notebook",
      {
        onDidChangeCellStatusBarItems: marksChanged.event,
        provideCellStatusBarItems: (cell) => {
          const marks = marksByNotebook.get(cell.notebook.uri.toString());
          if (!marks?.length) {
            return [];
          }
          const cellId =
            typeof cell.metadata?.id === "string"
              ? cell.metadata.id
              : undefined;
          const isLast = cell.index === cell.notebook.cellCount - 1;
          return getMarksForCell(marks, cell.index, cellId, isLast).map(
            (mark) => {
              const { text, tooltip } = getMarkLabel(mark);
              const item = new vscode.NotebookCellStatusBarItem(
                text,
                vscode.NotebookCellStatusBarAlignment.Left,
              );
              item.tooltip = tooltip;
              item.command = {
                command: "calkit-vscode.cellOutputActions",
                title: "Cell output",
                arguments: [cell.notebook.uri, mark],
              };
              return item;
            },
          );
        },
      },
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.markCellOutput",
      withRoot(markCellOutput),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.cellOutputActions",
      withRoot(showMarkActions),
    ),
    vscode.workspace.onDidOpenNotebookDocument((notebook) => {
      const root = getWorkspaceRoot();
      if (root) {
        void loadMarks(root, notebook);
      }
    }),
    vscode.workspace.onDidCloseNotebookDocument((notebook) => {
      marksByNotebook.delete(notebook.uri.toString());
    }),
    marksChanged,
  );
  // Marks change with calkit.yaml, and saved values with each run
  for (const pattern of [
    "**/calkit.yaml",
    "**/.calkit/notebooks/outputs/**/values.json",
  ]) {
    const watcher = vscode.workspace.createFileSystemWatcher(pattern);
    const reload = () => {
      const root = getWorkspaceRoot();
      if (root) {
        reloadAll(root);
      }
    };
    watcher.onDidChange(reload);
    watcher.onDidCreate(reload);
    watcher.onDidDelete(reload);
    context.subscriptions.push(watcher);
  }
  const root = getWorkspaceRoot();
  if (root) {
    reloadAll(root);
  }
}
