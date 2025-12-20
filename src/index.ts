import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

import { requestAPI } from './request';

/**
 * Initialization data for the calkit extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'calkit:plugin',
  description: 'A JupyterLab extension for Calkit projects.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null
  ) => {
    console.log('JupyterLab extension calkit is activated!');

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
