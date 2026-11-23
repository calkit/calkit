/**
 * The cell toolbar button adding a value, figure, or table a notebook cell
 * makes, to be saved when the pipeline runs the notebook, and the labels on
 * cells for their outputs.
 */
import {
  Clipboard,
  IToolbarWidgetRegistry,
  InputDialog,
  Notification,
  ToolbarButton,
} from "@jupyterlab/apputils";
import { Cell, ICodeCellModel } from "@jupyterlab/cells";
import { INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import {
  closeIcon,
  copyIcon,
  editIcon,
  imageIcon,
  LabIcon,
  numberingIcon,
  tableRowsIcon,
} from "@jupyterlab/ui-components";
import { CommandRegistry } from "@lumino/commands";
import { Menu, PanelLayout, Widget } from "@lumino/widgets";
import {
  type CellOutputKind,
  type ICellOutput,
  filterCellOutputs,
  getDefaultOutputPath,
  getCellOutputLabel,
  getOutputPathError,
  getAddOutputRequestBody,
  getCellOutputsForCell,
  getOutputMimeTypes,
  getCopyChoices,
  getEditChoices,
  getRemoveOutputQuery,
  getVariableChoices,
  hasImageOutput,
  hasResultOutput,
  isVariableName,
} from "./cell-outputs";
import { calkitIcon } from "./icons";
import { pipelineState } from "./pipeline-state";
import { requestAPI } from "./request";

const ROUTE = "notebook/cell/outputs";

const KIND_ICONS: Record<CellOutputKind, LabIcon> = {
  value: numberingIcon,
  figure: imageIcon,
  table: tableRowsIcon,
};

const cellOutputsByPanel = new WeakMap<NotebookPanel, ICellOutput[]>();
const loadListeners = new Set<(panel: NotebookPanel) => void>();

/** What a notebook's cells save, as last loaded. */
export function getLoadedCellOutputs(panel: NotebookPanel): ICellOutput[] {
  return cellOutputsByPanel.get(panel) ?? [];
}

/** Call `listener` with each notebook whose cell outputs load, until the
 * returned function is called.
 */
export function onCellOutputsLoaded(
  listener: (panel: NotebookPanel) => void,
): () => void {
  loadListeners.add(listener);
  return () => loadListeners.delete(listener);
}
const loadCountByPanel = new WeakMap<NotebookPanel, number>();
const labelsByCell = new WeakMap<Cell, Widget>();

/** The message a request failed with. */
function getErrorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Read what a notebook's cells save, and relabel them. */
async function loadCellOutputs(panel: NotebookPanel): Promise<void> {
  // Only the latest load counts, since an earlier one can finish after it
  const n = (loadCountByPanel.get(panel) ?? 0) + 1;
  loadCountByPanel.set(panel, n);
  let cellOutputs: ICellOutput[] = [];
  try {
    const query = new URLSearchParams({ path: panel.context.path });
    cellOutputs = filterCellOutputs(await requestAPI(`${ROUTE}?${query}`));
  } catch (error) {
    console.warn("Failed to load cell outputs:", error);
  }
  if (loadCountByPanel.get(panel) !== n || panel.isDisposed) {
    return;
  }
  cellOutputsByPanel.set(panel, cellOutputs);
  relabelCells(panel);
  loadListeners.forEach((listener) => listener(panel));
}

/** Label each cell with its outputs, matching cells by ID. */
function relabelCells(panel: NotebookPanel): void {
  const cellOutputs = cellOutputsByPanel.get(panel) ?? [];
  const cells = panel.content.widgets;
  cells.forEach((cell, i) => {
    setCellLabels(
      panel,
      cell,
      getCellOutputsForCell(
        cellOutputs,
        i,
        cell.model.id,
        i === cells.length - 1,
      ),
    );
  });
}

/** Show a cell's outputs under its input, once the cell is rendered. */
function setCellLabels(
  panel: NotebookPanel,
  cell: Cell,
  cellOutputs: ICellOutput[],
): void {
  let labels = labelsByCell.get(cell);
  if (!labels) {
    if (!cellOutputs.length) {
      return;
    }
    const widget = (labels = new Widget());
    widget.addClass("calkit-cell-output-labels");
    labelsByCell.set(cell, widget);
    void cell.ready.then(() => {
      if (cell.isDisposed) {
        return;
      }
      const layout = cell.layout as PanelLayout;
      const i = layout.widgets.findIndex((w) =>
        w.hasClass("jp-Cell-inputWrapper"),
      );
      layout.insertWidget(i >= 0 ? i + 1 : layout.widgets.length - 1, widget);
    });
  }
  labels.node.replaceChildren(
    ...cellOutputs.map((output) => createLabelNode(panel, output)),
  );
  labels.setHidden(!cellOutputs.length);
}

/** A cell's label for an output, which offers what to do with it. */
function createLabelNode(
  panel: NotebookPanel,
  output: ICellOutput,
): HTMLElement {
  const { text, tooltip } = getCellOutputLabel(output);
  const node = document.createElement("button");
  node.className = "calkit-cell-output-label";
  node.title = tooltip;
  const textNode = document.createElement("span");
  textNode.textContent = `Calkit: ${text}`;
  node.append(
    KIND_ICONS[output.kind].element({
      tag: "span",
      className: "calkit-cell-output-label-icon",
    }),
    textNode,
  );
  node.addEventListener("click", () =>
    showCellOutputActions(panel, output, node),
  );
  return node;
}

/** What to do with an output, from its label: copy how to cite it, edit
 * it, or stop saving it.
 */
function showCellOutputActions(
  panel: NotebookPanel,
  output: ICellOutput,
  anchor: HTMLElement,
): void {
  const commands = new CommandRegistry();
  const menu = new Menu({ commands });
  getCopyChoices(output).forEach(({ label, text }, i) => {
    commands.addCommand(`copy-${i}`, {
      label,
      icon: copyIcon,
      execute: () => {
        Clipboard.copyToSystem(text);
        Notification.success(`Copied ${text}`, { autoClose: 4000 });
      },
    });
    menu.addItem({ command: `copy-${i}` });
  });
  // Edit, as any kind, which asks again with what it is now filled in
  const cell =
    output.cell_index !== null
      ? panel.content.widgets[output.cell_index]
      : undefined;
  if (cell) {
    const editMenu = new Menu({ commands });
    editMenu.title.label = "Edit";
    editMenu.title.icon = editIcon;
    const kinds: CellOutputKind[] = ["value", "figure", "table"];
    // What it is now first
    kinds.sort((a, b) => Number(b === output.kind) - Number(a === output.kind));
    for (const kind of kinds) {
      commands.addCommand(`edit-${kind}`, {
        label: kind[0].toUpperCase() + kind.slice(1),
        icon: KIND_ICONS[kind],
        execute: () => void addCellOutput(panel, cell, kind, output),
      });
      editMenu.addItem({ command: `edit-${kind}` });
    }
    menu.addItem({ type: "submenu", submenu: editMenu });
  }
  commands.addCommand("remove", {
    label: "Stop saving",
    icon: closeIcon,
    execute: async () => {
      try {
        await requestAPI(
          `${ROUTE}?${getRemoveOutputQuery(panel.context.path, output)}`,
          {
            method: "DELETE",
          },
        );
      } catch (error) {
        Notification.error(getErrorText(error));
      }
      await loadCellOutputs(panel);
    },
  });
  menu.addItem({ command: "remove" });
  const rect = anchor.getBoundingClientRect();
  menu.open(rect.left, rect.bottom);
}

/** Ask what a cell's output is saved from and to, and add it, or with
 * `editing`, replace that output with it.
 */
async function addCellOutput(
  panel: NotebookPanel,
  cell: Cell,
  kind: CellOutputKind,
  editing?: ICellOutput,
): Promise<void> {
  const title = editing ? `Edit ${kind}` : `Save ${kind}`;
  const current = editing?.kind === kind ? editing : undefined;
  const notebookPath = panel.context.path;
  // The variable it's saved from, or for a figure or table, what the cell
  // shows: its image, or the result of its last line, e.g., df.head()
  const outputs = (cell.model as ICodeCellModel).outputs?.toJSON() ?? [];
  const { choices, index } = getEditChoices(
    getVariableChoices(
      cell.model.sharedModel.getSource(),
      kind,
      kind === "figure"
        ? hasImageOutput(getOutputMimeTypes(outputs))
        : hasResultOutput(outputs),
    ),
    current,
  );
  // Several values can be saved after one cell at once
  let variableNames: string[] = [];
  const askName = async (): Promise<string | undefined> => {
    const typed = await InputDialog.getText({
      title,
      label: "Variable name",
      pattern: "[A-Za-z_][A-Za-z0-9_]*",
      required: true,
    });
    const name = typed.button.accept ? typed.value?.trim() : undefined;
    if (name && !isVariableName(name)) {
      Notification.error("Not a variable name");
      return undefined;
    }
    return name || undefined;
  };
  if (kind === "value") {
    const picked = await InputDialog.getMultipleItems({
      title,
      label: "Variables",
      items: choices.map((c) => c.label),
      defaults: [choices[index].label],
    });
    if (!picked.button.accept || !picked.value?.length) {
      return;
    }
    const chosen = choices.filter((c) => picked.value?.includes(c.label));
    variableNames = chosen
      .map((c) => c.variable)
      .filter((v): v is string => !!v);
    if (chosen.some((c) => c.isOther)) {
      const typed = await askName();
      if (!typed) {
        return;
      }
      variableNames.push(typed);
    }
  } else {
    let choice = choices[index];
    if (choices.length > 1) {
      const picked = await InputDialog.getItem({
        title,
        label: "Variable",
        items: choices.map((c) => c.label),
        current: index,
      });
      if (!picked.button.accept) {
        return;
      }
      choice = choices.find((c) => c.label === picked.value) ?? choice;
    }
    if (choice.isOther) {
      const typed = await askName();
      if (!typed) {
        return;
      }
      variableNames = [typed];
    } else if (choice.variable) {
      variableNames = [choice.variable];
    }
  }
  const variable = variableNames[0];
  // Where a figure or table is saved to
  let target = variableNames.join(", ");
  if (kind !== "value") {
    const chosen = await InputDialog.getText({
      title,
      label:
        kind === "figure"
          ? "Path; PDF stays sharp in a paper"
          : "Path; .tex for \\cktable",
      text:
        current?.output_path ??
        getDefaultOutputPath(kind, notebookPath, variable),
      required: true,
    });
    if (!chosen.button.accept || !chosen.value?.trim()) {
      return;
    }
    const error = getOutputPathError(kind, chosen.value);
    if (error) {
      Notification.error(error);
      return;
    }
    target = chosen.value.trim();
  }
  // The cell's ID is what's recorded, so it must be on disk, which it isn't
  // for an older notebook until it's saved, even with no unsaved changes
  try {
    await panel.context.save();
  } catch (error) {
    Notification.error(getErrorText(error));
    return;
  }
  // An edit replaces the output, which is put back if the new one fails
  if (editing) {
    try {
      await requestAPI(
        `${ROUTE}?${getRemoveOutputQuery(notebookPath, editing)}`,
        { method: "DELETE" },
      );
    } catch (error) {
      Notification.error(getErrorText(error));
      return;
    }
  }
  try {
    const added = await requestAPI<{ warning: string | null }>(ROUTE, {
      method: "POST",
      body: JSON.stringify(
        getAddOutputRequestBody({
          notebookPath,
          cellId: cell.model.id,
          kind,
          variableNames,
          outputPath: kind === "value" ? undefined : target,
          format: current?.format,
          stage: editing?.stage,
        }),
      ),
    });
    Notification.success(`Saving ${target} on each run`, { autoClose: 4000 });
    if (added.warning) {
      Notification.warning(added.warning);
    }
  } catch (error) {
    if (editing) {
      await requestAPI(ROUTE, {
        method: "POST",
        body: JSON.stringify(
          getAddOutputRequestBody({
            notebookPath,
            cellId: editing.cell_id ?? cell.model.id,
            kind: editing.kind,
            variableNames: editing.variable_name ? [editing.variable_name] : [],
            outputPath: editing.output_path ?? undefined,
            format: editing.format,
            stage: editing.stage,
          }),
        ),
      }).catch(() => undefined);
    }
    Notification.error(getErrorText(error));
  }
  await loadCellOutputs(panel);
}

/** A code cell's toolbar button for adding what it makes as an output. */
function createAddOutputButton(
  cell: Cell,
  notebookTracker: INotebookTracker,
  translator?: ITranslator,
): ToolbarButton {
  const trans = (translator ?? nullTranslator).load("calkit");
  const commands = new CommandRegistry();
  const menu = new Menu({ commands });
  const kinds: [CellOutputKind, string][] = [
    ["value", trans.__("Value")],
    ["figure", trans.__("Figure")],
    ["table", trans.__("Table")],
  ];
  for (const [kind, label] of kinds) {
    commands.addCommand(kind, {
      label,
      icon: KIND_ICONS[kind],
      execute: () => {
        const panel = notebookTracker.find((p) =>
          p.content.widgets.includes(cell),
        );
        if (panel) {
          void addCellOutput(panel, cell, kind);
        }
      },
    });
    menu.addItem({ command: kind });
  }
  const button = new ToolbarButton({
    icon: calkitIcon,
    tooltip: trans.__("Save as Calkit output"),
    onClick: () => {
      const rect = button.node.getBoundingClientRect();
      menu.open(rect.left, rect.bottom);
    },
  });
  button.disposed.connect(() => menu.dispose());
  return button;
}

/**
 * Register the cell toolbar button for adding cell outputs, and label
 * cells with their outputs when a notebook opens, is saved, or runs.
 */
export function registerCellOutputs(
  notebookTracker: INotebookTracker,
  toolbarRegistry: IToolbarWidgetRegistry,
  translator?: ITranslator,
): void {
  toolbarRegistry.addFactory("Cell", "calkit-add-output", (widget) => {
    const cell = widget as Cell;
    if (cell.model.type === "code") {
      return createAddOutputButton(cell, notebookTracker, translator);
    }
    // Non-code cells need a widget too, so give them a hidden one
    const empty = new Widget();
    empty.hide();
    return empty;
  });
  const watchNotebook = (panel: NotebookPanel) => {
    const reload = () => void loadCellOutputs(panel);
    void panel.context.ready.then(() => {
      reload();
      panel.content.model?.cells.changed.connect(() => relabelCells(panel));
    });
    panel.context.saveState.connect((_, state) => {
      if (state === "completed") {
        reload();
      }
    });
    panel.context.pathChanged.connect(reload);
  };
  // Including notebooks already open, e.g., restored with the layout
  notebookTracker.forEach(watchNotebook);
  notebookTracker.widgetAdded.connect((_, panel) => watchNotebook(panel));
  // Saved values change with each run
  let wasRunning = false;
  pipelineState.subscribe((state) => {
    const isRunning = state.isRunning || state.isSessionInProgress;
    if (wasRunning && !isRunning) {
      notebookTracker.forEach((panel) => void loadCellOutputs(panel));
    }
    wasRunning = isRunning;
  });
}
