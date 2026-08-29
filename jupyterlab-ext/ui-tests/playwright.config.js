/**
 * Configuration for Playwright using default from @jupyterlab/galata
 */
const baseConfig = require("@jupyterlab/galata/lib/playwright-config");

module.exports = {
  ...baseConfig,
  // These drive a real kernel and install real packages, so give a run that
  // trips over the machine underneath it one more chance before failing CI
  retries: process.env.CI ? 1 : 0,
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
