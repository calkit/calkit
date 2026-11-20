/**
 * The cell toolbar button marking a value, figure, or table a notebook cell
 * makes, to be saved when the pipeline runs the notebook, and the labels on
 * cells for their marks.
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
  imageIcon,
  LabIcon,
  numberingIcon,
  tableRowsIcon,
} from "@jupyterlab/ui-components";
import { CommandRegistry } from "@lumino/commands";
import { Menu, PanelLayout, Widget } from "@lumino/widgets";
import {
  type CellOutputKind,
  type ICellOutputMark,
  filterCellOutputMarks,
  getDefaultMarkPath,
  getMarkLabel,
  getMarkPathError,
  getMarkRequestBody,
  getMarksForCell,
  getOutputMimeTypes,
  getUnmarkQuery,
  getVariableChoices,
  hasImageOutput,
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

const marksByPanel = new WeakMap<NotebookPanel, ICellOutputMark[]>();
const loadCountByPanel = new WeakMap<NotebookPanel, number>();
const labelsByCell = new WeakMap<Cell, Widget>();

/** The message a request failed with. */
function getErrorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Read what a notebook's cells are marked to make, and relabel them. */
async function loadMarks(panel: NotebookPanel): Promise<void> {
  // Only the latest load counts, since an earlier one can finish after it
  const n = (loadCountByPanel.get(panel) ?? 0) + 1;
  loadCountByPanel.set(panel, n);
  let marks: ICellOutputMark[] = [];
  try {
    const query = new URLSearchParams({ path: panel.context.path });
    marks = filterCellOutputMarks(await requestAPI(`${ROUTE}?${query}`));
  } catch (error) {
    console.warn("Failed to load cell outputs:", error);
  }
  if (loadCountByPanel.get(panel) !== n || panel.isDisposed) {
    return;
  }
  marksByPanel.set(panel, marks);
  relabelCells(panel);
}

/** Label each cell with its marks, matching cells by ID. */
function relabelCells(panel: NotebookPanel): void {
  const marks = marksByPanel.get(panel) ?? [];
  const cells = panel.content.widgets;
  cells.forEach((cell, i) => {
    setCellLabels(
      panel,
      cell,
      getMarksForCell(marks, i, cell.model.id, i === cells.length - 1),
    );
  });
}

/** Show a cell's marks under its input, once the cell is rendered. */
function setCellLabels(
  panel: NotebookPanel,
  cell: Cell,
  marks: ICellOutputMark[],
): void {
  let labels = labelsByCell.get(cell);
  if (!labels) {
    if (!marks.length) {
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
    ...marks.map((mark) => createLabelNode(panel, mark)),
  );
  labels.setHidden(!marks.length);
}

/** A cell's label for a mark, which offers what to do with it. */
function createLabelNode(
  panel: NotebookPanel,
  mark: ICellOutputMark,
): HTMLElement {
  const { text, tooltip } = getMarkLabel(mark);
  const node = document.createElement("button");
  node.className = "calkit-cell-output-label";
  node.title = tooltip;
  const textNode = document.createElement("span");
  textNode.textContent = text;
  node.append(
    KIND_ICONS[mark.kind].element({
      tag: "span",
      className: "calkit-cell-output-label-icon",
    }),
    textNode,
  );
  node.addEventListener("click", () => showMarkActions(panel, mark, node));
  return node;
}

/** What to do with a mark, from its label: copy how to cite it, or stop saving it. */
function showMarkActions(
  panel: NotebookPanel,
  mark: ICellOutputMark,
  anchor: HTMLElement,
): void {
  const commands = new CommandRegistry();
  const menu = new Menu({ commands });
  const citation = mark.citation;
  if (citation) {
    commands.addCommand("copy", {
      label: `Copy ${citation}`,
      icon: copyIcon,
      execute: () => {
        Clipboard.copyToSystem(citation);
        Notification.success(`Copied ${citation}`, { autoClose: 4000 });
      },
    });
    menu.addItem({ command: "copy" });
  }
  commands.addCommand("unmark", {
    label: "Stop saving",
    icon: closeIcon,
    execute: async () => {
      try {
        await requestAPI(
          `${ROUTE}?${getUnmarkQuery(panel.context.path, mark)}`,
          {
            method: "DELETE",
          },
        );
      } catch (error) {
        Notification.error(getErrorText(error));
      }
      await loadMarks(panel);
    },
  });
  menu.addItem({ command: "unmark" });
  const rect = anchor.getBoundingClientRect();
  menu.open(rect.left, rect.bottom);
}

/** Ask what a cell's output is saved from and to, and mark it. */
async function markCellOutput(
  panel: NotebookPanel,
  cell: Cell,
  kind: CellOutputKind,
): Promise<void> {
  const title = `Save ${kind}`;
  const notebookPath = panel.context.path;
  // The variable it's saved from, or for a figure, what the cell shows
  const outputs = (cell.model as ICodeCellModel).outputs?.toJSON() ?? [];
  const choices = getVariableChoices(
    cell.model.sharedModel.getSource(),
    kind,
    hasImageOutput(getOutputMimeTypes(outputs)),
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
      label: "Variables it's saved from",
      items: choices.map((c) => c.label),
      defaults: [choices[0].label],
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
    let choice = choices[0];
    if (choices.length > 1) {
      const picked = await InputDialog.getItem({
        title,
        label: "Variable it's saved from",
        items: choices.map((c) => c.label),
        current: 0,
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
      text: getDefaultMarkPath(kind, notebookPath, variable),
      required: true,
    });
    if (!chosen.button.accept || !chosen.value?.trim()) {
      return;
    }
    const error = getMarkPathError(kind, chosen.value);
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
    const marked = await requestAPI<{ warning: string | null }>(ROUTE, {
      method: "POST",
      body: JSON.stringify(
        getMarkRequestBody({
          notebookPath,
          cellId: cell.model.id,
          kind,
          variableNames,
          outputPath: kind === "value" ? undefined : target,
        }),
      ),
    });
    Notification.success(`Saving ${target} on each run`, { autoClose: 4000 });
    if (marked.warning) {
      Notification.warning(marked.warning);
    }
  } catch (error) {
    Notification.error(getErrorText(error));
  }
  await loadMarks(panel);
}

/** A code cell's toolbar button for marking what it makes. */
function createMarkButton(
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
          void markCellOutput(panel, cell, kind);
        }
      },
    });
    menu.addItem({ command: kind });
  }
  const button = new ToolbarButton({
    icon: calkitIcon,
    tooltip: trans.__("Save as output"),
    onClick: () => {
      const rect = button.node.getBoundingClientRect();
      menu.open(rect.left, rect.bottom);
    },
  });
  button.disposed.connect(() => menu.dispose());
  return button;
}

/**
 * Register the cell toolbar button for marking cell outputs, and label
 * cells with their marks when a notebook opens, is saved, or runs.
 */
export function registerCellOutputMarking(
  notebookTracker: INotebookTracker,
  toolbarRegistry: IToolbarWidgetRegistry,
  translator?: ITranslator,
): void {
  toolbarRegistry.addFactory("Cell", "calkit-output-marker", (widget) => {
    const cell = widget as Cell;
    if (cell.model.type === "code") {
      return createMarkButton(cell, notebookTracker, translator);
    }
    // Non-code cells need a widget too, so give them a hidden one
    const empty = new Widget();
    empty.hide();
    return empty;
  });
  const watchNotebook = (panel: NotebookPanel) => {
    const reload = () => void loadMarks(panel);
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
      notebookTracker.forEach((panel) => void loadMarks(panel));
    }
    wasRunning = isRunning;
  });
}
