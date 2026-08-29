/**
 * Configuration for Playwright using default from @jupyterlab/galata
 */
const baseConfig = require("@jupyterlab/galata/lib/playwright-config");

module.exports = {
  ...baseConfig,
  // No retries: the test builds a Calkit project in the server's root
  // directory, and the server outlives a retry, so a second attempt starts
  // against a project that already has the environment and stage it means to
  // create and fails on that instead of on whatever went wrong
  retries: 0,
  use: {
    ...baseConfig.use,
    // Without this a wrong selector waits out the whole test budget, which
    // buries what actually broke under a timeout ten minutes later. The
    // steps that genuinely take longer set their own timeout
    actionTimeout: 30000,
  },
  webServer: {
    command: "jlpm start",
    url: "http://localhost:8888/lab",
    timeout: 120 * 1000,
    reuseExistingServer: !process.env.CI,
  },
};
