import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin,
  ILayoutRestorer
} from '@jupyterlab/application';

import { WidgetTracker } from '@jupyterlab/apputils';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

import { requestAPI } from './request';
import { CalkitSidebarWidget } from './sidebar';

/**
 * Initialization data for the calkit extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'calkit:plugin',
  description: 'A JupyterLab extension for Calkit projects.',
  autoStart: true,
  requires: [ILayoutRestorer],
  optional: [ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    restorer: ILayoutRestorer,
    settingRegistry: ISettingRegistry | null
  ) => {
    console.log('JupyterLab extension calkit is activated!');

    // Create the sidebar widget
    const sidebar = new CalkitSidebarWidget();
    sidebar.id = 'calkit-sidebar';
    sidebar.title.label = 'Calkit';

    // Add the sidebar to the left panel
    app.shell.add(sidebar, 'left');

    // Create a widget tracker for the sidebar
    const tracker = new WidgetTracker<CalkitSidebarWidget>({
      namespace: 'calkit-sidebar'
    });

    // Restore the widget state
    void restorer.restore(tracker, {
      command: 'calkit:open-sidebar',
      name: () => 'calkit-sidebar',
      args: () => ({})
    });

    // Track the sidebar widget
    tracker.add(sidebar);

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('calkit settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error('Failed to load settings for calkit.', reason);
        });
    }

    requestAPI<any>('hello')
      .then(data => {
        console.log(data);
      })
      .catch(reason => {
        console.error(
          `The calkit server extension appears to be missing.\n${reason}`
        );
      });
  }
};

export default plugin;
