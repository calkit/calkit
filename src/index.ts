import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
  ILayoutRestorer,
} from "@jupyterlab/application";

import { WidgetTracker, IToolbarWidgetRegistry } from "@jupyterlab/apputils";

import { IStatusBar } from "@jupyterlab/statusbar";

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
import { CalkitSidebarWidget } from "./components/sidebar";
import { createOutputMarkerButton } from "./cell-output-marker";
import { addCommands, addContextMenuItems } from "./file-browser-menu";
import { createNotebookToolbar } from "./components/notebook-toolbar";
import { calkitIcon } from "./icons";
import { showCommitDialog } from "./components/commit-dialog";
import { IGitStatus } from "./hooks/useQueries";
import { isFeatureEnabled } from "./feature-flags";
import { queryClient } from "./queryClient";
import { PipelineStatusWidget } from "./components/pipeline-status-bar";
import { pipelineState } from "./pipeline-state";

// Import CSS
import "../style/pipeline-status-bar.css";

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
    IStatusBar,
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
    statusBar: IStatusBar | null,
  ) => {
    console.log("JupyterLab extension calkit is activated!");

    // Create the sidebar widget
    const sidebar = new CalkitSidebarWidget();
    sidebar.id = "calkit-sidebar";
    sidebar.title.label = ""; // icon-only label
    sidebar.title.caption = "Calkit";
    sidebar.title.icon = calkitIcon;
    sidebar.setCommands(app.commands);

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

    // Register cell toolbar button for marking outputs
    if (toolbarRegistry && isFeatureEnabled("cellOutputMarking")) {
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
    }

    // Register notebook toolbar with badges
    if (toolbarRegistry && isFeatureEnabled("notebookToolbar")) {
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
            pipelineState.setRunning(true, "Running pipeline...");
            await requestAPI("pipeline/runs", {
              method: "POST",
              body: JSON.stringify({ targets: [] }),
            });
            // Refetch pipeline status and project data
            await queryClient.invalidateQueries({
              queryKey: ["pipeline", "status"],
            });
            await queryClient.invalidateQueries({ queryKey: ["project"] });
          } catch (error) {
            const errorMsg =
              error instanceof Error ? error.message : String(error);
            console.error("Failed to run pipeline:", errorMsg);
          } finally {
            pipelineState.setRunning(false);
          }
        },
      });

      commands.addCommand("calkit:new-notebook", {
        label: "New notebook",
        caption: "Create a new notebook in the current folder",
        icon: calkitIcon,
        isEnabled: () => !!factory,
        execute: async () => {
          const browser = (factory as any)?.defaultBrowser;
          const cwd = browser?.model?.path || "";

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

          const { showEnvironmentEditor } = await import(
            "./components/environment-editor"
          );
          const { showNotebookRegistration } = await import(
            "./components/notebook-registration"
          );

          const createEnvironmentCallback = async (): Promise<
            string | null
          > => {
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

          // Show Calkit notebook creation dialog
          const data = await showNotebookRegistration(
            "create",
            [],
            environments,
            createEnvironmentCallback,
          );
          if (!data) {
            return;
          }

          // Prepend the current directory to path if user provided a bare filename
          const nbPath = data.path.includes("/")
            ? data.path
            : [cwd, data.path].filter(Boolean).join("/");

          try {
            // Use existing notebooks route
            await requestAPI("notebooks", {
              method: "POST",
              body: JSON.stringify({
                ...data,
                path: nbPath,
              }),
            });
            // Open the newly created notebook
            const widget: any = await commands.execute("docmanager:open", {
              path: nbPath,
            });
            // Set kernel to avoid selector dialog
            try {
              const kernel = await requestAPI<{ name: string }>(
                "notebook/kernel",
                {
                  method: "POST",
                  body: JSON.stringify({
                    path: nbPath,
                    environment: data.environment,
                  }),
                },
              );
              if (widget && widget.sessionContext && kernel?.name) {
                await widget.sessionContext.changeKernel({ name: kernel.name });
              }
            } catch (e) {
              console.warn("Failed to set kernel automatically:", e);
            }
          } catch (error) {
            console.error("Failed to create/open notebook:", error);
          }
        },
      });

      commands.addCommand("calkit:new-pipeline-stage", {
        label: "New pipeline stage",
        caption: "Create a new pipeline stage",
        icon: calkitIcon,
        execute: async () => {
          console.log("New pipeline stage - not yet implemented");
          // TODO: Implement pipeline stage creation
        },
      });

      commands.addCommand("calkit:new-publication", {
        label: "New publication",
        caption: "Create a new publication",
        icon: calkitIcon,
        execute: async () => {
          console.log("New publication - not yet implemented");
          // TODO: Implement publication creation
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
      if (isFeatureEnabled("pipelineStages")) {
        calkitMenu.addItem({ command: "calkit:new-pipeline-stage" });
      }
      if (isFeatureEnabled("publications")) {
        calkitMenu.addItem({ command: "calkit:new-publication" });
      }
      calkitMenu.addItem({ command: "calkit:save-project" });
      calkitMenu.addItem({ type: "separator" });
      calkitMenu.addItem({ command: "calkit:open-sidebar" });

      mainMenu.addMenu(calkitMenu, { rank: 90 });
    }

    // Add Calkit launcher items
    if (launcher && isFeatureEnabled("launcherItems")) {
      launcher.add({
        command: "calkit:new-notebook",
        category: "Calkit",
        rank: 1,
      });

      if (isFeatureEnabled("pipelineStages")) {
        launcher.add({
          command: "calkit:new-pipeline-stage",
          category: "Calkit",
          rank: 2,
        });
      }

      if (isFeatureEnabled("publications")) {
        launcher.add({
          command: "calkit:new-publication",
          category: "Calkit",
          rank: 3,
        });
      }
    }

    // Add file browser context menu items
    if (factory && isFeatureEnabled("fileBrowserMenu")) {
      try {
        addCommands(app, factory, translator || undefined);
      } catch (e) {
        console.error("calkit: addCommands failed", e);
      }
      try {
        addContextMenuItems(app, translator || undefined);
      } catch (e) {
        console.error("calkit: addContextMenuItems failed", e);
      }
    }

    // Add pipeline status indicator to status bar
    if (statusBar) {
      // Create a command to open sidebar to pipeline section
      app.commands.addCommand("calkit:open-sidebar-pipeline", {
        label: "Show pipeline status",
        execute: () => {
          app.shell.activateById(sidebar.id);
          // Trigger sidebar to expand pipeline section
          // This is handled via the sidebar's state management
          sidebar.expandPipelineSection?.();
        },
      });

      const pipelineStatusWidget = new PipelineStatusWidget(() => {
        void app.commands.execute("calkit:open-sidebar-pipeline");
      });
      statusBar.registerStatusItem("calkit-pipeline-status", {
        item: pipelineStatusWidget,
        align: "left",
        priority: 10,
      });
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
