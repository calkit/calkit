import { resolve } from "node:path";
import { defineConfig } from "vite";

// The popup, the options page, and the service worker. Content scripts are
// built separately (see vite.content.config.ts), since Chrome runs them as
// classic scripts, which can't use the ES module output this build emits.
export default defineConfig({
  publicDir: resolve(__dirname, "public"),
  build: {
    outDir: resolve(__dirname, "dist"),
    emptyOutDir: true,
    sourcemap: true,
    target: "chrome114",
    // No <link rel="modulepreload"> hints. The viewer page is loaded in a
    // frame on a host page, where Chrome refuses to use a preload fetched
    // in the page's world for a module the extension's world imports --
    // "cross-world extension resource mismatch" -- so the hint is dead
    // weight that only shows up as a console error. The chunk still
    // loads normally when the entry imports it.
    modulePreload: false,
    rollupOptions: {
      // The pages live at the root so they're served from
      // chrome-extension://<id>/popup.html rather than a path under src/,
      // which both reads better and stays clear of content blockers that
      // match on generic source-tree paths
      input: {
        popup: resolve(__dirname, "popup.html"),
        options: resolve(__dirname, "options.html"),
        viewer: resolve(__dirname, "viewer.html"),
        background: resolve(__dirname, "src/background/index.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
});
