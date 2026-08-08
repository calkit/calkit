import { build } from "vite";

// One IIFE bundle per content script. Rollup can't code-split an IIFE, so
// these can't share a single multi-entry build.
const entries = ["github", "overleaf", "references"];

for (const entry of entries) {
  process.env.CONTENT_ENTRY = entry;
  await build({ configFile: "vite.content.config.ts" });
}
