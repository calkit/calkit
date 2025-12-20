import { ToolbarButton } from "@jupyterlab/apputils";
import { Cell, ICellModel } from "@jupyterlab/cells";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import { Menu } from "@lumino/widgets";
import { CommandRegistry } from "@lumino/commands";
import { calkitIcon } from "./icons";

/**
 * The output type metadata key
 */
const OUTPUT_TYPE_KEY = "calkit_output_type";

/**
 * Possible output types
 */
export type OutputType = "none" | "figure" | "dataset" | "result" | "table";

/**
 * Create a toolbar button for marking cell outputs
 * This is called by the toolbar factory for each code cell
 */
export function createOutputMarkerButton(
  cell: Cell<ICellModel>,
  translator?: ITranslator,
): ToolbarButton {
  const trans = (translator || nullTranslator).load("calkit");

  // Create commands for the menu
  const commands = new CommandRegistry();

  const options: { value: OutputType; label: string }[] = [
    { value: "none", label: trans.__("None") },
    { value: "figure", label: trans.__("Figure") },
    { value: "dataset", label: trans.__("Dataset") },
    { value: "result", label: trans.__("Result") },
    { value: "table", label: trans.__("Table") },
  ];

  // Register commands for each output type
  options.forEach((opt) => {
    commands.addCommand(`set-output-type-${opt.value}`, {
      label: opt.label,
      execute: () => {
        setOutputType(cell, opt.value);
        updateButton(cell, button);
      },
    });
  });

  const button = new ToolbarButton({
    icon: calkitIcon,
    tooltip: trans.__("Mark output type"),
    onClick: () => {
      // Create menu
      const menu = new Menu({ commands });

      options.forEach((opt) => {
        menu.addItem({
          command: `set-output-type-${opt.value}`,
          args: {},
        });
      });

      // Show menu at button position
      const rect = button.node.getBoundingClientRect();
      menu.open(rect.left, rect.bottom);
    },
  });

  // Update button appearance initially
  updateButton(cell, button);

  // Listen for metadata changes
  cell.model.metadataChanged.connect(() => {
    updateButton(cell, button);
    updateCellClass(cell);
  });

  return button;
}

/**
 * Update button appearance based on current output type
 */
function updateButton(cell: Cell<ICellModel>, button: ToolbarButton): void {
  const outputType = getCellOutputType(cell);
  button.node.classList.remove("calkit-output-marked");
  if (outputType !== "none") {
    button.node.classList.add("calkit-output-marked");
  }
}

/**
 * Set the output type for a cell
 */
function setOutputType(cell: Cell<ICellModel>, outputType: OutputType): void {
  if (outputType === "none") {
    cell.model.deleteMetadata(OUTPUT_TYPE_KEY);
  } else {
    cell.model.setMetadata(OUTPUT_TYPE_KEY, outputType);
  }
  updateCellClass(cell);
}

/**
 * Update the cell's CSS class based on output type
 */
function updateCellClass(cell: Cell<ICellModel>): void {
  const outputType = getCellOutputType(cell);

  // Remove all output type classes
  const allTypes: OutputType[] = ["figure", "dataset", "result", "table"];
  allTypes.forEach((type) => {
    cell.node.classList.remove(`calkit-output-${type}`);
  });

  // Add current type class
  if (outputType !== "none") {
    cell.node.classList.add(`calkit-output-${outputType}`);
  }
}

/**
 * Get the output type for a cell
 */
export function getCellOutputType(cell: Cell<ICellModel>): OutputType {
  return (cell.model.getMetadata(OUTPUT_TYPE_KEY) as OutputType) || "none";
}
