import { JupyterFrontEnd } from "@jupyterlab/application";
import { IFileBrowserFactory } from "@jupyterlab/filebrowser";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import { RankedMenu } from "@jupyterlab/ui-components";
import { calkitIcon } from "./icons";
import { requestAPI } from "./request";
import { showNotebookRegistration } from "./notebook-registration";
import { showEnvironmentEditor } from "./environment-editor";

/**
 * The command IDs for file labeling
 */
export namespace CommandIDs {
  export const labelAsFigure = "calkit:label-as-figure";
  export const labelAsDataset = "calkit:label-as-dataset";
  export const labelAsResult = "calkit:label-as-result";
  export const labelAsTable = "calkit:label-as-table";
  export const removeLabel = "calkit:remove-label";
  export const newNotebookInEnvironment = "calkit:new-notebook-in-environment";
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

  // Create a new notebook in a chosen environment (in current or selected folder)
  commands.addCommand(CommandIDs.newNotebookInEnvironment, {
    label: trans.__("New notebook in environment"),
    icon: calkitIcon,
    isEnabled: () => !!factory,
    execute: async () => {
      const browser = (factory as any)?.defaultBrowser;
      const cwd = browser?.model?.path || "";
      const widget = factory.tracker.currentWidget;
      const selected = widget ? Array.from(widget.selectedItems()) : [];
      const targetDir =
        selected.length === 1 && selected[0].type === "directory"
          ? selected[0].path
          : cwd;

      // Fetch environments from project info
      let environments: Array<{ id: string; label: string }> = [];
      try {
        const info = await requestAPI<any>("project");
        environments = Object.keys(info.environments || {}).map(
          (name: string) => ({
            id: name,
            label: name,
          }),
        );
      } catch (error) {
        console.warn("Failed to fetch environments:", error);
      }

      const createEnvironmentCallback = async (): Promise<string | null> => {
        const result = await showEnvironmentEditor({ mode: "create" });
        if (!result) {
          return null;
        }
        try {
          await requestAPI("environment/create", {
            method: "POST",
            body: JSON.stringify({
              name: result.name,
              kind: result.kind,
              packages: result.packages,
            }),
          });
          return result.name;
        } catch (e) {
          console.error("Failed to create environment:", e);
          return null;
        }
      };

      // Prompt for notebook file name and environment
      const data = await showNotebookRegistration(
        "create",
        [],
        environments,
        createEnvironmentCallback,
      );
      if (!data) {
        return;
      }

      // Prepend the chosen directory to path if user provided a bare filename
      const nbPath = data.path.includes("/")
        ? data.path
        : [targetDir, data.path].filter(Boolean).join("/");

      try {
        await requestAPI("notebook/create", {
          method: "POST",
          body: JSON.stringify({
            ...data,
            path: nbPath,
          }),
        });
        // Open the newly created notebook
        await app.commands.execute("docmanager:open", { path: nbPath });
      } catch (error) {
        console.error("Failed to create/open notebook:", error);
      }
    },
  });

  // Label as Figure command
  commands.addCommand(CommandIDs.labelAsFigure, {
    label: trans.__("Label as figure"),
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
    label: trans.__("Label as dataset"),
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
    label: trans.__("Label as result"),
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
    label: trans.__("Label as table"),
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
    label: trans.__("Remove label"),
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

  // Add items to the submenu for items (files and folders)
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

  // Add the Calkit submenu for items (files and folders)
  app.contextMenu.addItem({
    type: "submenu",
    submenu: calkitMenu,
    selector: ".jp-DirListing-item",
    rank: 3,
  });

  // Create a separate menu for empty space
  const emptySpaceMenu = new RankedMenu({
    commands: app.commands,
  });
  emptySpaceMenu.title.label = trans.__("Calkit");
  emptySpaceMenu.title.icon = calkitIcon;

  emptySpaceMenu.addItem({
    command: CommandIDs.newNotebookInEnvironment,
    rank: 1,
  });

  // Add the empty space menu
  app.contextMenu.addItem({
    type: "submenu",
    submenu: emptySpaceMenu,
    selector: ".jp-DirListing-content",
    rank: 3,
  });
}
