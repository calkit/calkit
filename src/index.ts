import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
  ILayoutRestorer,
} from "@jupyterlab/application";

import { WidgetTracker, IToolbarWidgetRegistry } from "@jupyterlab/apputils";

import { Widget, Menu } from "@lumino/widgets";

import { ILauncher } from "@jupyterlab/launcher";

import { INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";

import { ISettingRegistry } from "@jupyterlab/settingregistry";
import { IStateDB } from "@jupyterlab/statedb";

import { ITranslator } from "@jupyterlab/translation";

import { IFileBrowserFactory } from "@jupyterlab/filebrowser";

import { Cell } from "@jupyterlab/cells";
import { IMainMenu } from "@jupyterlab/mainmenu";

import { requestAPI } from "./request";
import { CalkitSidebarWidget } from "./sidebar";
import { filterLauncher } from "./launcher-filter";
import { createOutputMarkerButton } from "./cell-output-marker";
import { addCommands, addContextMenuItems } from "./file-browser-menu";
import { createNotebookToolbar } from "./notebook-toolbar";
import { calkitIcon } from "./icons";
import { showCommitDialog } from "./commit-dialog";
import { IGitStatus } from "./hooks/useQueries";

/**
 * Initialization data for the calkit extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: "calkit:plugin",
  description: "A JupyterLab extension for Calkit projects.",
  autoStart: true,
  requires: [ILayoutRestorer],
  optional: [
    ISettingRegistry,
    IStateDB,
    ILauncher,
    INotebookTracker,
    IToolbarWidgetRegistry,
    ITranslator,
    IFileBrowserFactory,
    IMainMenu,
  ],
  activate: (
    app: JupyterFrontEnd,
    restorer: ILayoutRestorer,
    settingRegistry: ISettingRegistry | null,
    stateDB: IStateDB | null,
    launcher: ILauncher | null,
    notebookTracker: INotebookTracker | null,
    toolbarRegistry: IToolbarWidgetRegistry | null,
    translator: ITranslator | null,
    factory: IFileBrowserFactory | null,
    mainMenu: IMainMenu | null,
  ) => {
    console.log("JupyterLab extension calkit is activated!");

    // Create the sidebar widget
    const sidebar = new CalkitSidebarWidget();
    sidebar.id = "calkit-sidebar";
    sidebar.title.label = ""; // icon-only label
    sidebar.title.caption = "Calkit";
    sidebar.title.icon = calkitIcon;

    // Add the sidebar to the left panel
    app.shell.add(sidebar, "left");

    // Create a widget tracker for the sidebar
    const tracker = new WidgetTracker<CalkitSidebarWidget>({
      namespace: "calkit-sidebar",
    });

    // Restore the widget state
    void restorer.restore(tracker, {
      command: "calkit:open-sidebar",
      name: () => "calkit-sidebar",
      args: () => ({}),
    });

    // Track the sidebar widget
    tracker.add(sidebar);

    // Register sidebar open command for restorer and menu
    app.commands.addCommand("calkit:open-sidebar", {
      label: "Open Calkit sidebar",
      execute: () => {
        app.shell.activateById(sidebar.id);
      },
    });

    // Filter launcher if calkit.yaml exists
    if (launcher) {
      void filterLauncher(launcher);
    }

    // Register cell toolbar button for marking outputs
    if (toolbarRegistry) {
      toolbarRegistry.addFactory("Cell", "calkit-output-marker", (widget) => {
        // Only add to code cells
        const cell = widget as Cell;
        if (cell.model.type === "code") {
          return createOutputMarkerButton(cell, translator || undefined);
        }
        // Return an empty widget for non-code cells (required by type)
        const emptyWidget = new Widget();
        emptyWidget.hide();
        return emptyWidget;
      });

      // Register notebook toolbar with badges
      toolbarRegistry.addFactory(
        "Notebook",
        "calkit-notebook-toolbar",
        (widget) => {
          console.log("Creating notebook toolbar for:", widget);
          if (widget instanceof NotebookPanel) {
            return createNotebookToolbar(widget, translator || undefined);
          }
          console.warn("Widget is not a NotebookPanel:", widget);
          const emptyWidget = new Widget();
          emptyWidget.hide();
          return emptyWidget;
        },
      );
    }

    // Add top-level Calkit menu
    if (mainMenu) {
      const { commands } = app;

      commands.addCommand("calkit:run-pipeline", {
        label: "Run pipeline",
        caption: "Run the current project's pipeline",
        execute: async () => {
          try {
            await requestAPI("pipeline/run", { method: "POST" });
          } catch (error) {
            console.error("Failed to run pipeline:", error);
          }
        },
      });

      commands.addCommand("calkit:new-notebook", {
        label: "New notebook",
        caption: "Create a new notebook in the current folder",
        isEnabled: () => !!factory,
        execute: async () => {
          const cwd = (factory as any)?.defaultBrowser?.model?.path || "";
          await app.commands.execute("notebook:create-new", { cwd });
        },
      });

      commands.addCommand("calkit:save-project", {
        label: "Save project",
        caption: "Commit project changes",
        execute: async () => {
          try {
            const status = await requestAPI<IGitStatus>("git/status");
            const trackedSet = new Set([...(status.tracked || [])]);
            const candidates = [
              ...(status.changed || []),
              ...(status.untracked || []),
            ];
            const files = candidates.map((path) => ({
              path,
              store_in_dvc: false,
              stage: true,
              tracked: trackedSet.has(path),
              size: status.sizes?.[path],
            }));
            const defaultMsg = files.length
              ? `Update ${files
                  .map((f) => f.path)
                  .slice(0, 5)
                  .join(", ")}${files.length > 5 ? ", …" : ""}`
              : "Update project";
            const msg = await showCommitDialog(defaultMsg, files);
            if (!msg) {
              return;
            }
            const ignoreForever = msg.files.filter((f) => f.ignore_forever);
            const stagedFiles = msg.files.filter((f) => f.stage);
            if (ignoreForever.length > 0) {
              await requestAPI("git/ignore", {
                method: "POST",
                body: JSON.stringify({
                  paths: ignoreForever.map((f) => f.path),
                }),
              });
            }
            if (stagedFiles.length === 0) {
              return;
            }
            await requestAPI("git/commit", {
              method: "POST",
              body: JSON.stringify({
                message: msg.message,
                files: stagedFiles,
              }),
            });
            if (msg.pushAfter) {
              await requestAPI("git/push", { method: "POST" });
            }
          } catch (error) {
            console.error("Failed to save project:", error);
          }
        },
      });

      const calkitMenu = new Menu({ commands });
      calkitMenu.title.label = "Calkit";
      calkitMenu.addItem({ command: "calkit:run-pipeline" });
      calkitMenu.addItem({ command: "calkit:new-notebook" });
      calkitMenu.addItem({ command: "calkit:save-project" });
      calkitMenu.addItem({ type: "separator" });
      calkitMenu.addItem({ command: "calkit:open-sidebar" });

      mainMenu.addMenu(calkitMenu, { rank: 90 });
    }

    // Add file browser context menu items
    if (factory) {
      addCommands(app, factory, translator || undefined);
      addContextMenuItems(app, translator || undefined);
    }

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then((settings) => {
          console.log("calkit settings loaded:", settings.composite);
          sidebar.setSettings(settings);
        })
        .catch((reason) => {
          console.error("Failed to load settings for calkit.", reason);
        });
    }

    if (stateDB) {
      sidebar.setStateDB(stateDB);
    }

    requestAPI<any>("hello")
      .then((data) => {
        console.log(data);
      })
      .catch((reason) => {
        console.error(
          `The calkit server extension appears to be missing.\n${reason}`,
        );
      });
  },
};

export default plugin;
