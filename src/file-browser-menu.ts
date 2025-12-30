import { JupyterFrontEnd } from "@jupyterlab/application";
import { IFileBrowserFactory } from "@jupyterlab/filebrowser";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import { RankedMenu } from "@jupyterlab/ui-components";
import { calkitIcon } from "./icons";
// import { showErrorMessage } from "@jupyterlab/apputils";
import { requestAPI } from "./request";
import { showNotebookRegistration } from "./components/notebook-registration";
import { showEnvironmentEditor } from "./components/environment-editor";
import { NotebookPanel } from "@jupyterlab/notebook";

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
    label: trans.__("New notebook"),
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
        const data = await requestAPI<any>("environments?notebook_only=1");
        environments = Object.keys(data.environments || {}).map(
          (name: string) => ({
            id: name,
            label: name,
          }),
        );
      } catch (error) {
        console.warn("Failed to fetch environments:", error);
      }

      const createEnvironmentCallback = async (): Promise<string | null> => {
        let createdName: string | null = null;
        await showEnvironmentEditor({
          mode: "create",
          onSubmit: async ({ name, kind, path, packages }) => {
            await requestAPI("environments", {
              method: "POST",
              body: JSON.stringify({ name, kind, path, packages }),
            });
            createdName = name;
          },
        });
        return createdName;
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
        await requestAPI("notebooks", {
          method: "POST",
          body: JSON.stringify({
            ...data,
            path: nbPath,
          }),
        });
        // Open the newly created notebook
        const widget = (await app.commands.execute("docmanager:open", {
          path: nbPath,
        })) as any;
        // Set kernel to avoid selector dialog
        try {
          const kernel = await requestAPI<{ name: string }>("notebook/kernel", {
            method: "POST",
            body: JSON.stringify({
              path: nbPath,
              environment: data.environment,
            }),
          });
          if (
            widget &&
            (widget as NotebookPanel).sessionContext &&
            kernel?.name
          ) {
            await (widget as NotebookPanel).sessionContext.changeKernel({
              name: kernel.name,
            });
          }
        } catch (e) {
          console.warn("Failed to set kernel automatically:", e);
        }
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

  // New notebook entry (top of menu)
  calkitMenu.addItem({
    command: CommandIDs.newNotebookInEnvironment,
    rank: 0,
  });

  calkitMenu.addItem({
    type: "separator",
    rank: 0.5,
  });

  // Note: Labeling actions removed from context menu per request
  // Keep only actions relevant to notebooks

  // Bind a single Calkit submenu to the file browser content
  // Commands' `isVisible` determine whether actions show for items vs empty space
  app.contextMenu.addItem({
    type: "submenu",
    submenu: calkitMenu,
    selector: ".jp-DirListing-content",
    rank: 3,
  });

  // Note: Avoid adding a second submenu; a single binding prevents duplicates
}
