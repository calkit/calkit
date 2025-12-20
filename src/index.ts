import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
  ILayoutRestorer,
} from "@jupyterlab/application";

import { WidgetTracker, IToolbarWidgetRegistry } from "@jupyterlab/apputils";

import { Widget } from "@lumino/widgets";

import { ILauncher } from "@jupyterlab/launcher";

import { INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";

import { ISettingRegistry } from "@jupyterlab/settingregistry";

import { ITranslator } from "@jupyterlab/translation";

import { IFileBrowserFactory } from "@jupyterlab/filebrowser";

import { Cell } from "@jupyterlab/cells";

import { requestAPI } from "./request";
import { CalkitSidebarWidget } from "./sidebar";
import { filterLauncher } from "./launcher-filter";
import { createOutputMarkerButton } from "./cell-output-marker";
import { addCommands, addContextMenuItems } from "./file-browser-menu";
import { createEnvironmentSelector } from "./environment-selector";
import { calkitIcon } from "./icons";

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
    ILauncher,
    INotebookTracker,
    IToolbarWidgetRegistry,
    ITranslator,
    IFileBrowserFactory,
  ],
  activate: (
    app: JupyterFrontEnd,
    restorer: ILayoutRestorer,
    settingRegistry: ISettingRegistry | null,
    launcher: ILauncher | null,
    notebookTracker: INotebookTracker | null,
    toolbarRegistry: IToolbarWidgetRegistry | null,
    translator: ITranslator | null,
    factory: IFileBrowserFactory | null,
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

      // Register environment selector for notebook toolbar
      toolbarRegistry.addFactory(
        "Notebook",
        "calkit-environment-selector",
        (widget) => {
          console.log("Creating environment selector for:", widget);
          if (widget instanceof NotebookPanel) {
            return createEnvironmentSelector(widget, translator || undefined);
          }
          console.warn("Widget is not a NotebookPanel:", widget);
          const emptyWidget = new Widget();
          emptyWidget.hide();
          return emptyWidget;
        },
      );
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
        })
        .catch((reason) => {
          console.error("Failed to load settings for calkit.", reason);
        });
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
