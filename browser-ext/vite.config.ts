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
    rollupOptions: {
      input: {
        popup: resolve(__dirname, "src/popup/index.html"),
        options: resolve(__dirname, "src/options/index.html"),
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
