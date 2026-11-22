/**
 * Labels on notebook cells for the values, figures, and tables saved from
 * them, and the commands adding and removing them, through
 * `calkit nb add-output`.
 */
import { execFile } from "node:child_process";
import * as path from "node:path";
import * as vscode from "vscode";
import {
  type CellOutputKind,
  type CellOutput,
  getAssignedNames,
  getDefaultOutputPath,
  getAddOutputArgs,
  getCellOutputLabel,
  getCellOutputsForCell,
  getCellOutputInsertText,
  getCellOutputTarget,
  getRemoveOutputArgs,
  hasImageOutput,
  parseCellOutputs,
  rankNamesForKind,
} from "./core";

const cellOutputsByNotebook = new Map<string, CellOutput[]>();
const cellOutputsChanged = new vscode.EventEmitter<void>();
// The project's documents, as absolute paths, set when registered
let getDocumentPaths: () => string[] = () => [];

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

/** Read what a notebook's cells save, and relabel them. */
async function loadCellOutputs(
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
  cellOutputsByNotebook.set(notebook.uri.toString(), parseCellOutputs(stdout));
  cellOutputsChanged.fire();
}

function reloadAll(root: string): void {
  for (const notebook of vscode.workspace.notebookDocuments) {
    void loadCellOutputs(root, notebook);
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

/** Ask for a variable's name, for one a cell's code doesn't show. */
async function askVariableName(kindLabel: string): Promise<string | undefined> {
  const typed = await vscode.window.showInputBox({
    title: `Save ${kindLabel.toLowerCase()}`,
    prompt: "Variable name",
    validateInput: (v) =>
      /^[A-Za-z_][A-Za-z0-9_]*$/.test(v) ? undefined : "Not a variable name",
  });
  return typed?.trim() || undefined;
}

/** Ask what a cell makes for documents, and save it on each run. */
async function addCellOutput(root: string, arg: unknown): Promise<void> {
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
        detail: "Number or text, e.g., a fitted constant",
        outputKind: "value" as CellOutputKind,
      },
      {
        label: "Figure",
        description: "\\ckfigure",
        detail: "Plot or image",
        outputKind: "figure" as CellOutputKind,
      },
      {
        label: "Table",
        description: "\\cktable",
        detail: "DataFrame or list of rows",
        outputKind: "table" as CellOutputKind,
      },
    ],
    { title: "Save as", placeHolder: "Select kind" },
  );
  if (!kindPick) {
    return;
  }
  const kind = kindPick.outputKind;
  // The variable it's saved from, or for a figure or table, what the cell
  // shows: its image, or the result of its last line, e.g., df.head()
  const shown =
    kind === "figure"
      ? "$(file-media) Image this cell shows"
      : "$(table) Result this cell shows";
  const other = "$(edit) Other variable…";
  const names = rankNamesForKind(
    getAssignedNames(cell.document.getText()),
    kind,
  );
  const mimeTypes = cell.outputs.flatMap((o) => o.items.map((i) => i.mime));
  const isShown =
    kind === "figure"
      ? hasImageOutput(mimeTypes)
      : cell.outputs.some((o) => o.metadata?.outputType === "execute_result");
  const items: vscode.QuickPickItem[] = [
    ...(kind !== "value" && isShown ? [{ label: shown }] : []),
    ...names.map((n) => ({ label: n })),
    { label: other },
    ...(kind !== "value" && !isShown
      ? [{ label: shown, detail: "Run the cell first to see it here" }]
      : []),
  ];
  // Several values can be saved after one cell at once
  let variableNames: string[] = [];
  if (kind === "value") {
    const picks = await vscode.window.showQuickPick(items, {
      title: `Save ${kindPick.label.toLowerCase()}`,
      placeHolder: "Select variables",
      canPickMany: true,
    });
    if (!picks?.length) {
      return;
    }
    variableNames = picks.map((p) => p.label).filter((l) => l !== other);
    if (picks.some((p) => p.label === other)) {
      const typed = await askVariableName(kindPick.label);
      if (!typed) {
        return;
      }
      variableNames.push(typed);
    }
  } else {
    const variablePick = await vscode.window.showQuickPick(items, {
      title: `Save ${kindPick.label.toLowerCase()}`,
      placeHolder: "Select variable",
    });
    if (!variablePick) {
      return;
    }
    if (variablePick.label === other) {
      const typed = await askVariableName(kindPick.label);
      if (!typed) {
        return;
      }
      variableNames = [typed];
    } else if (variablePick.label !== shown) {
      variableNames = [variablePick.label];
    }
  }
  const variable = variableNames[0];
  let target = variableNames.join(", ");
  if (kind !== "value") {
    const exts =
      kind === "figure"
        ? [".pdf", ".png", ".svg", ".jpg", ".jpeg"]
        : [".tex", ".csv", ".md", ".json"];
    const chosen = await vscode.window.showInputBox({
      title: `Save ${kindPick.label.toLowerCase()}`,
      prompt:
        kind === "figure"
          ? "Path to save it to; PDF stays sharp in a paper"
          : "Path to save it to; .tex for \\cktable",
      value: getDefaultOutputPath(kind, notebookPath, variable),
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
    getAddOutputArgs({
      notebookPath,
      cellId,
      cellIndex: cell.index,
      kind,
      variableNames,
      outputPath: kind === "value" ? undefined : target,
    }),
  );
  if (!result.ok) {
    void vscode.window.showErrorMessage(
      getErrorText(result.stderr, result.stdout),
    );
    return;
  }
  vscode.window.setStatusBarMessage(
    `$(check) Saving ${target} on each run`,
    4000,
  );
  await loadCellOutputs(root, cell.notebook);
}

/** What to do with an output, from its label: copy how to cite it, insert
 * it in a document, or stop saving it.
 */
async function showCellOutputActions(
  root: string,
  notebookUri: vscode.Uri,
  output: CellOutput,
): Promise<void> {
  // Open documents first, the visible ones at their cursors
  const documents = [
    ...vscode.window.visibleTextEditors.map((e) => e.document.uri),
    ...vscode.workspace.textDocuments.map((d) => d.uri),
  ]
    .filter((u) => u.scheme === "file")
    .map((u) => u.fsPath)
    .concat(getDocumentPaths())
    .filter((p, i, all) => all.indexOf(p) === i)
    .map((fsPath) => ({
      fsPath,
      relPath: path.relative(root, fsPath).replace(/\\/g, "/"),
    }))
    .filter((d) => !d.relPath.startsWith("../") && !path.isAbsolute(d.relPath))
    // Not what Calkit writes, e.g., _calkit/values.tex
    .filter(
      (d) =>
        !d.relPath
          .split("/")
          .some((part) => part === "_calkit" || part === ".calkit"),
    )
    .map((d) => ({ ...d, text: getCellOutputInsertText(output, d.relPath) }))
    .filter((d) => d.text !== null);
  const copy = output.citation ? `$(copy) Copy ${output.citation}` : undefined;
  const insert = documents.length ? "$(insert) Insert in document" : undefined;
  const remove = "$(close) Stop saving";
  const picked = await vscode.window.showQuickPick(
    [...(copy ? [copy] : []), ...(insert ? [insert] : []), remove],
    { title: getCellOutputTarget(output) },
  );
  if (picked === copy && output.citation) {
    await vscode.env.clipboard.writeText(output.citation);
    vscode.window.setStatusBarMessage(
      `$(check) Copied ${output.citation}`,
      4000,
    );
  } else if (picked === insert) {
    const document = await vscode.window.showQuickPick(
      documents.map((d) => ({
        label: d.relPath,
        description: d.text ?? "",
        document: d,
      })),
      { title: "Insert in" },
    );
    if (!document) {
      return;
    }
    const uri = vscode.Uri.file(document.document.fsPath);
    const editor = await vscode.window.showTextDocument(uri, {
      viewColumn:
        vscode.window.visibleTextEditors.find(
          (e) => e.document.uri.fsPath === uri.fsPath,
        )?.viewColumn ?? vscode.ViewColumn.Beside,
    });
    const text = document.document.text ?? "";
    await editor.edit((edit) => edit.replace(editor.selection, text));
  } else if (picked === remove) {
    const notebookPath = getNotebookPath(root, notebookUri);
    if (!notebookPath) {
      return;
    }
    const result = await runCalkit(
      root,
      getRemoveOutputArgs(notebookPath, output),
    );
    if (!result.ok) {
      void vscode.window.showErrorMessage(
        getErrorText(result.stderr, result.stdout),
      );
    }
    const notebook = vscode.workspace.notebookDocuments.find(
      (n) => n.uri.toString() === notebookUri.toString(),
    );
    if (notebook) {
      await loadCellOutputs(root, notebook);
    }
  }
}

/** Register the cell labels and commands for adding cell outputs. */
export function registerCellOutputs(
  context: vscode.ExtensionContext,
  getWorkspaceRoot: () => string | undefined,
  getProjectDocumentPaths: () => string[],
): void {
  getDocumentPaths = getProjectDocumentPaths;
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
        onDidChangeCellStatusBarItems: cellOutputsChanged.event,
        provideCellStatusBarItems: (cell) => {
          const cellOutputs = cellOutputsByNotebook.get(
            cell.notebook.uri.toString(),
          );
          if (!cellOutputs?.length) {
            return [];
          }
          const cellId =
            typeof cell.metadata?.id === "string"
              ? cell.metadata.id
              : undefined;
          const isLast = cell.index === cell.notebook.cellCount - 1;
          return getCellOutputsForCell(
            cellOutputs,
            cell.index,
            cellId,
            isLast,
          ).map((output) => {
            const { text, tooltip } = getCellOutputLabel(output);
            const item = new vscode.NotebookCellStatusBarItem(
              `$(pin) Calkit: ${text}`,
              vscode.NotebookCellStatusBarAlignment.Left,
            );
            item.tooltip = tooltip;
            item.command = {
              command: "calkit-vscode.cellOutputActions",
              title: "Cell output",
              arguments: [cell.notebook.uri, output],
            };
            return item;
          });
        },
      },
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.addCellOutput",
      withRoot(addCellOutput),
    ),
    vscode.commands.registerCommand(
      "calkit-vscode.cellOutputActions",
      withRoot(showCellOutputActions),
    ),
    vscode.workspace.onDidOpenNotebookDocument((notebook) => {
      const root = getWorkspaceRoot();
      if (root) {
        void loadCellOutputs(root, notebook);
      }
    }),
    vscode.workspace.onDidCloseNotebookDocument((notebook) => {
      cellOutputsByNotebook.delete(notebook.uri.toString());
    }),
    cellOutputsChanged,
  );
  // Outputs change with calkit.yaml, and saved values with each run
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
