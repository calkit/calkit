/**
 * Centralized feature flags for the Calkit JupyterLab extension.
 *
 * This module controls which features are enabled or disabled in the extension.
 * Set a flag to `true` to enable a feature, or `false` to hide it.
 */

export interface IFeatureFlags {
  /** Basic project info display and editing */
  basicInfo: boolean;

  /** Environment management (create, edit, delete environments) */
  environments: boolean;

  /** Pipeline stages and execution */
  pipelineStages: boolean;

  /** Notebook creation, registration, and management */
  notebooks: boolean;

  /** Figure tracking and management */
  figures: boolean;

  /** Dataset tracking and management */
  datasets: boolean;

  /** Research questions tracking */
  questions: boolean;

  /** Git history, commit, and sync operations */
  history: boolean;

  /** Project setup and dependency checks */
  setup: boolean;

  /** Publication tracking and management */
  publications: boolean;

  /** Project notes */
  notes: boolean;

  /** ML models tracking */
  models: boolean;

  /** Cell output marking in notebooks */
  cellOutputMarking: boolean;

  /** File browser context menu items */
  fileBrowserMenu: boolean;

  /** Notebook toolbar customizations */
  notebookToolbar: boolean;

  /** Launcher menu items */
  launcherItems: boolean;
}

/**
 * Feature flag configuration.
 *
 * IMPLEMENTED FEATURES (set to true):
 * - basicInfo: Project metadata display and editing
 * - environments: Full environment management
 * - pipelineStages: Pipeline creation, editing, and execution
 * - notebooks: Notebook lifecycle management
 * - history: Git operations and commit history
 * - setup: Dependency checks and setup guidance
 * - cellOutputMarking: Mark notebook cell outputs
 * - fileBrowserMenu: File browser context menus
 * - notebookToolbar: Notebook toolbar items
 *
 * INCOMPLETE FEATURES (set to false):
 * - figures: No implementation yet
 * - datasets: Basic data structure only, no UI
 * - questions: Basic data structure only, no UI
 * - publications: Placeholder only, no backend
 * - notes: Placeholder only, no backend
 * - models: Placeholder only, no backend
 * - launcherItems: Not yet implemented
 */
export const FEATURE_FLAGS: Readonly<IFeatureFlags> = {
  // Fully implemented features
  basicInfo: true,
  environments: true,
  pipelineStages: true,
  notebooks: true,
  history: true,
  setup: true,
  notebookToolbar: true,

  // Incomplete features - disabled by default
  cellOutputMarking: false,
  fileBrowserMenu: false,
  figures: false,
  datasets: false,
  questions: false,
  publications: false,
  notes: false,
  models: false,
  launcherItems: false,
};

/**
 * Check if a feature is enabled.
 *
 * @param feature - The feature name to check
 * @returns true if the feature is enabled, false otherwise
 */
export function isFeatureEnabled(feature: keyof IFeatureFlags): boolean {
  return FEATURE_FLAGS[feature];
}

/**
 * Get all enabled features.
 *
 * @returns Array of enabled feature names
 */
export function getEnabledFeatures(): Array<keyof IFeatureFlags> {
  return (Object.keys(FEATURE_FLAGS) as Array<keyof IFeatureFlags>).filter(
    (key) => FEATURE_FLAGS[key],
  );
}

/**
 * Get all disabled features.
 *
 * @returns Array of disabled feature names
 */
export function getDisabledFeatures(): Array<keyof IFeatureFlags> {
  return (Object.keys(FEATURE_FLAGS) as Array<keyof IFeatureFlags>).filter(
    (key) => !FEATURE_FLAGS[key],
  );
}
