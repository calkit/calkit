import { resolve } from "node:path";
import { defineConfig } from "vite";

// Content scripts run as classic scripts, so they can't be ES modules and
// can't be code-split. Each one is therefore bundled on its own into a
// self-contained IIFE, driven by scripts/build-content.mjs, which sets
// CONTENT_ENTRY once per script. emptyOutDir is off so these land alongside
// the output of the main config rather than replacing it.
const entry = process.env.CONTENT_ENTRY;

if (!entry) {
  throw new Error(
    "CONTENT_ENTRY is not set; build content scripts with " +
      "node scripts/build-content.mjs",
  );
}

export default defineConfig({
  publicDir: false,
  build: {
    outDir: resolve(__dirname, "dist/content"),
    emptyOutDir: false,
    sourcemap: true,
    target: "chrome114",
    lib: {
      entry: resolve(__dirname, `src/content/${entry}.ts`),
      name: `calkit_${entry}`,
      formats: ["iife"],
      fileName: () => `${entry}.js`,
    },
  },
});
