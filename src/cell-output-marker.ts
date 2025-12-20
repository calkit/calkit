import { ToolbarButton } from '@jupyterlab/apputils';
import { Cell, ICellModel } from '@jupyterlab/cells';
import { ITranslator, nullTranslator } from '@jupyterlab/translation';
import { Menu } from '@lumino/widgets';
import { CommandRegistry } from '@lumino/commands';
import { LabIcon } from '@jupyterlab/ui-components';

// Simple tag icon SVG
const tagIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16">
  <path fill="currentColor" d="M21.41 11.58l-9-9C12.05 2.22 11.55 2 11 2H4c-1.1 0-2 .9-2 2v7c0 .55.22 1.05.59 1.42l9 9c.36.36.86.58 1.41.58.55 0 1.05-.22 1.41-.59l7-7c.37-.36.59-.86.59-1.41 0-.55-.23-1.06-.59-1.42zM5.5 7C4.67 7 4 6.33 4 5.5S4.67 4 5.5 4 7 4.67 7 5.5 6.33 7 5.5 7z"/>
</svg>`;

const tagIcon = new LabIcon({
  name: 'calkit:tag',
  svgstr: tagIconSvg
});

/**
 * The output type metadata key
 */
const OUTPUT_TYPE_KEY = 'calkit_output_type';

/**
 * Possible output types
 */
export type OutputType = 'none' | 'figure' | 'dataset' | 'result' | 'table';

/**
 * Create a toolbar button for marking cell outputs
 * This is called by the toolbar factory for each code cell
 */
export function createOutputMarkerButton(
  cell: Cell<ICellModel>,
  translator?: ITranslator
): ToolbarButton {
  const trans = (translator || nullTranslator).load('calkit');

  // Create commands for the menu
  const commands = new CommandRegistry();

  const options: { value: OutputType; label: string }[] = [
    { value: 'none', label: trans.__('None') },
    { value: 'figure', label: trans.__('Figure') },
    { value: 'dataset', label: trans.__('Dataset') },
    { value: 'result', label: trans.__('Result') },
    { value: 'table', label: trans.__('Table') }
  ];

  // Register commands for each output type
  options.forEach(opt => {
    commands.addCommand(`set-output-type-${opt.value}`, {
      label: opt.label,
      execute: () => {
        setOutputType(cell, opt.value);
        updateButton(cell, button);
      }
    });
  });

  const button = new ToolbarButton({
    icon: tagIcon,
    tooltip: trans.__('Mark output type'),
    onClick: () => {
      // Create menu
      const menu = new Menu({ commands });

      options.forEach(opt => {
        menu.addItem({
          command: `set-output-type-${opt.value}`,
          args: {}
        });
      });

      // Show menu at button position
      const rect = button.node.getBoundingClientRect();
      menu.open(rect.left, rect.bottom);
    }
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
  button.node.classList.remove('calkit-output-marked');
  if (outputType !== 'none') {
    button.node.classList.add('calkit-output-marked');
  }
}

/**
 * Set the output type for a cell
 */
function setOutputType(cell: Cell<ICellModel>, outputType: OutputType): void {
  if (outputType === 'none') {
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
  const allTypes: OutputType[] = ['figure', 'dataset', 'result', 'table'];
  allTypes.forEach(type => {
    cell.node.classList.remove(`calkit-output-${type}`);
  });

  // Add current type class
  if (outputType !== 'none') {
    cell.node.classList.add(`calkit-output-${outputType}`);
  }
}

/**
 * Get the output type for a cell
 */
export function getCellOutputType(cell: Cell<ICellModel>): OutputType {
  return (cell.model.getMetadata(OUTPUT_TYPE_KEY) as OutputType) || 'none';
}
