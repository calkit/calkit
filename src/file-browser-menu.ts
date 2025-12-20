import { JupyterFrontEnd } from "@jupyterlab/application";
import { IFileBrowserFactory } from "@jupyterlab/filebrowser";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import { RankedMenu } from "@jupyterlab/ui-components";
import { calkitIcon } from "./icons";
import { requestAPI } from "./request";

/**
 * The command IDs for file labeling
 */
export namespace CommandIDs {
  export const labelAsFigure = "calkit:label-as-figure";
  export const labelAsDataset = "calkit:label-as-dataset";
  export const labelAsResult = "calkit:label-as-result";
  export const labelAsTable = "calkit:label-as-table";
  export const removeLabel = "calkit:remove-label";
}

/**
 * Add Calkit commands to the application command registry
 */
export function addCommands(
  app: JupyterFrontEnd,
  factory: IFileBrowserFactory,
  translator?: ITranslator,
): void {
  const { commands } = app;
  const trans = (translator || nullTranslator).load("calkit");

  // Helper to get the current file path from the file browser
  const getSelectedPath = (): string | null => {
    const widget = factory.tracker.currentWidget;
    if (!widget) {
      return null;
    }
    const selected = Array.from(widget.selectedItems());
    if (selected.length !== 1) {
      return null;
    }
    return selected[0].path;
  };

  // Helper to check if a single item (file or folder) is selected
  const hasSelectedItem = (): boolean => {
    const widget = factory.tracker.currentWidget;
    if (!widget) {
      return false;
    }
    const selected = Array.from(widget.selectedItems());
    return selected.length === 1;
  };

  // Helper to check if a file (not directory) is selected
  const hasSelectedFile = (): boolean => {
    const widget = factory.tracker.currentWidget;
    if (!widget) {
      return false;
    }
    const selected = Array.from(widget.selectedItems());
    if (selected.length !== 1) {
      return false;
    }
    return selected[0].type !== "directory";
  };

  // Label as Figure command
  commands.addCommand(CommandIDs.labelAsFigure, {
    label: trans.__("Label as Figure"),
    icon: calkitIcon,
    execute: async () => {
      const path = getSelectedPath();
      if (path) {
        try {
          await requestAPI("label", {
            method: "POST",
            body: JSON.stringify({
              path,
              label: "figure",
            }),
          });
          console.log(`Labeled ${path} as figure`);
        } catch (error) {
          console.error("Failed to label file:", error);
        }
      }
    },
    isVisible: hasSelectedFile,
  });

  // Label as Dataset command (works on both files and folders)
  commands.addCommand(CommandIDs.labelAsDataset, {
    label: trans.__("Label as Dataset"),
    icon: calkitIcon,
    execute: async () => {
      const path = getSelectedPath();
      if (path) {
        try {
          await requestAPI("label", {
            method: "POST",
            body: JSON.stringify({
              path,
              label: "dataset",
            }),
          });
          console.log(`Labeled ${path} as dataset`);
        } catch (error) {
          console.error("Failed to label file:", error);
        }
      }
    },
    isVisible: hasSelectedItem,
  });

  // Label as Result command
  commands.addCommand(CommandIDs.labelAsResult, {
    label: trans.__("Label as Result"),
    icon: calkitIcon,
    execute: async () => {
      const path = getSelectedPath();
      if (path) {
        try {
          await requestAPI("label", {
            method: "POST",
            body: JSON.stringify({
              path,
              label: "result",
            }),
          });
          console.log(`Labeled ${path} as result`);
        } catch (error) {
          console.error("Failed to label file:", error);
        }
      }
    },
    isVisible: hasSelectedFile,
  });

  // Label as Table command
  commands.addCommand(CommandIDs.labelAsTable, {
    label: trans.__("Label as Table"),
    icon: calkitIcon,
    execute: async () => {
      const path = getSelectedPath();
      if (path) {
        try {
          await requestAPI("label", {
            method: "POST",
            body: JSON.stringify({
              path,
              label: "table",
            }),
          });
          console.log(`Labeled ${path} as table`);
        } catch (error) {
          console.error("Failed to label file:", error);
        }
      }
    },
    isVisible: hasSelectedFile,
  });

  // Remove Label command (works on both files and folders)
  commands.addCommand(CommandIDs.removeLabel, {
    label: trans.__("Remove Label"),
    execute: async () => {
      const path = getSelectedPath();
      if (path) {
        try {
          await requestAPI("label", {
            method: "DELETE",
            body: JSON.stringify({
              path,
            }),
          });
          console.log(`Removed label from ${path}`);
        } catch (error) {
          console.error("Failed to remove label:", error);
        }
      }
    },
    isVisible: hasSelectedItem,
  });
}

/**
 * Add Calkit context menu items to the file browser
 */
export function addContextMenuItems(
  app: JupyterFrontEnd,
  translator?: ITranslator,
): void {
  const trans = (translator || nullTranslator).load("calkit");

  // Create a submenu for Calkit
  const calkitMenu = new RankedMenu({
    commands: app.commands,
  });
  calkitMenu.title.label = trans.__("Calkit");
  calkitMenu.title.icon = calkitIcon;

  // Add items to the submenu
  calkitMenu.addItem({
    command: CommandIDs.labelAsFigure,
    rank: 1,
  });

  calkitMenu.addItem({
    command: CommandIDs.labelAsDataset,
    rank: 2,
  });

  calkitMenu.addItem({
    command: CommandIDs.labelAsResult,
    rank: 3,
  });

  calkitMenu.addItem({
    command: CommandIDs.labelAsTable,
    rank: 4,
  });

  calkitMenu.addItem({
    type: "separator",
    rank: 5,
  });

  calkitMenu.addItem({
    command: CommandIDs.removeLabel,
    rank: 6,
  });

  // Add the Calkit submenu to the context menu for all items (files and folders)
  app.contextMenu.addItem({
    type: "submenu",
    submenu: calkitMenu,
    selector: ".jp-DirListing-item",
    rank: 3,
  });
}
