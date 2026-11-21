import { resolve } from "node:path";
import { defineConfig } from "vite";

// Content scripts run as classic scripts, so they can't be ES modules and
// can't be code-split. Each one is therefore bundled on its own into a
// self-contained IIFE, driven by scripts/build-content.mjs, which sets
// CONTENT_ENTRY once per script. emptyOutDir is off so these land alongside
// the output of the main config rather than replacing it.
const entry = process.env.CONTENT_ENTRY;
// Where each one's source is, by the name it's built to
const sources: Record<string, string> = {
  github: "src/github/index.ts",
  overleaf: "src/overleaf/index.ts",
  "overleaf-editor": "src/overleaf/editor.ts",
  references: "src/references/index.ts",
};

if (!entry || !sources[entry]) {
  throw new Error(
    `CONTENT_ENTRY should be one of ${Object.keys(sources).join(", ")}; ` +
      "build content scripts with node scripts/build-content.mjs",
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
      entry: resolve(__dirname, sources[entry]),
      name: `calkit_${entry.replace(/-/g, "_")}`,
      formats: ["iife"],
      fileName: () => `${entry}.js`,
    },
  },
});
