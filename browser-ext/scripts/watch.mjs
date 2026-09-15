import { build } from "vite";

// Rebuild on save. Four separate builds, for the same reason the one-shot
// build has them: the pages and the service worker are ES modules built
// together, and each content script is its own IIFE because Rollup can't
// code-split one.
//
// Chrome still has to be told to reload the extension. A content script is
// read from disk when a page loads, and the service worker when it starts,
// so a rebuilt file doesn't reach a tab that's already open.
const entries = ["github", "overleaf", "references"];

console.log("Watching for changes; reload the extension in Chrome to pick");
console.log("them up (chrome://extensions).");

// Sequential, since the content config reads CONTENT_ENTRY when it's
// evaluated: each build() call evaluates its config before returning its
// watcher, so the variable is never read while another build is starting.
await build({ configFile: "vite.config.ts", build: { watch: {} } });
for (const entry of entries) {
  process.env.CONTENT_ENTRY = entry;
  await build({ configFile: "vite.content.config.ts", build: { watch: {} } });
}
