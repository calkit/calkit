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
// Remove testRegex when using projects
const { testRegex, ...baseConfigWithoutRegex } = baseConfig;

module.exports = {
  projects: [
    {
      displayName: "ui",
      ...baseConfigWithoutRegex,
      automock: false,
      testMatch: ["<rootDir>/src/__tests__/*.spec.ts"],
      testPathIgnorePatterns: ["useQueries"],
      transformIgnorePatterns: [`/node_modules/(?!${esModules}).+`],
    },
    {
      displayName: "hooks",
      preset: "ts-jest",
      testEnvironment: "node",
      testMatch: ["<rootDir>/src/__tests__/useQueries.spec.ts"],
    },
  ],
  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/**/*.d.ts",
    "!src/**/.ipynb_checkpoints/*",
  ],
  coverageReporters: ["lcov", "text"],
};
