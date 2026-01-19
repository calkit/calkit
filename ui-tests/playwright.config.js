/**
 * Configuration for Playwright using default from @jupyterlab/galata
 */
const baseConfig = require("@jupyterlab/galata/lib/playwright-config");
const path = require("path");
const os = require("os");
const fs = require("fs");

// Create a temp directory for test runs
const tmpDir = path.join(os.tmpdir(), `galata-test-${Date.now()}`);
fs.mkdirSync(tmpDir, { recursive: true });

module.exports = {
  ...baseConfig,
  webServer: {
    command: `cd ${tmpDir} && jupyter lab --config jupyter_server_test_config.py`,
    url: "http://localhost:8888/lab",
    timeout: 120 * 1000,
    reuseExistingServer: !process.env.CI,
  },
};
