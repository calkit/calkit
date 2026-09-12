const jestJupyterLab = require("@jupyterlab/testutils/lib/jest-config");

const esModules = [
  "@codemirror",
  "@jupyter/ydoc",
  "@jupyterlab/",
  "lib0",
  "nanoid",
  "vscode-ws-jsonrpc",
  "y-protocols",
  "y-websocket",
  "yjs",
].join("|");

const baseConfig = jestJupyterLab(__dirname);
// testRegex is replaced per project by testMatch, and the rest of these are
// only understood at the top level, so none of them belong in a project
const {
  testRegex,
  testTimeout,
  reporters,
  coverageReporters,
  coverageDirectory,
  ...projectBaseConfig
} = baseConfig;

// The UI tests build a project with its own virtual environment under
// ui-tests/test-project. Jest scanning it turns every package that ships a
// labextension into a duplicate module, so keep it out of the module map
const generatedPaths = ["<rootDir>/ui-tests/test-project/"];

module.exports = {
  testTimeout,
  reporters,
  coverageDirectory,
  modulePathIgnorePatterns: generatedPaths,
  projects: [
    {
      displayName: "ui",
      ...projectBaseConfig,
      automock: false,
      testMatch: ["<rootDir>/src/__tests__/*.spec.ts"],
      modulePathIgnorePatterns: generatedPaths,
      transformIgnorePatterns: [`/node_modules/(?!${esModules}).+`],
    },
    {
      displayName: "hooks",
      preset: "ts-jest",
      testEnvironment: "jsdom",
      testMatch: ["<rootDir>/src/hooks/__tests__/useQueries.test.tsx"],
      modulePathIgnorePatterns: generatedPaths,
    },
  ],
  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/**/*.d.ts",
    "!src/**/.ipynb_checkpoints/*",
  ],
  coverageReporters: ["lcov", "text"],
};
