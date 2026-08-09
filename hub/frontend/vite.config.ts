import { TanStackRouterVite } from "@tanstack/router-vite-plugin"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

const hash = Math.floor(Math.random() * 90000) + 10000

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), TanStackRouterVite()],
  server: {
    // Bind to all interfaces so it's reachable from host when running in Docker
    host: true, // equivalent to 0.0.0.0
    port: 5173,
    strictPort: true,
    // HMR generally works out-of-the-box when port is forwarded one-to-one.
    // If you run into websocket issues behind proxies, set explicit HMR host/port here.
    // hmr: { host: "localhost", port: 5173, protocol: "ws" },
  },
  build: {
    rollupOptions: {
      output: {
        entryFileNames: `[name]` + hash + `.js`,
        chunkFileNames: `[name]` + hash + `.js`,
        assetFileNames: `[name]` + hash + `.[ext]`,
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined
          }

          if (id.includes("plotly.js") || id.includes("react-plotly.js")) {
            return "vendor-plotly"
          }

          // Let mermaid and its rendering graph (d3, dagre, khroma, cytoscape,
          // elkjs, lodash-es) auto-chunk. Mermaid lazy-loads each diagram type
          // via internal dynamic import(); forcing the graph into one manual
          // chunk collapses those async boundaries into synchronous circular
          // references, which throw "Cannot access 'x' before initialization"
          // TDZ errors during theme setup and rendering. Returning undefined
          // lets Rollup preserve mermaid's internal async chunk boundaries.
          if (
            id.includes("mermaid") ||
            id.includes("/d3-") ||
            id.includes("/d3/") ||
            id.includes("dagre") ||
            id.includes("khroma") ||
            id.includes("cytoscape") ||
            id.includes("elkjs") ||
            id.includes("non-layered-tidy-tree-layout") ||
            id.includes("lodash-es")
          ) {
            return undefined
          }

          // react-ipynb-renderer, mathjax and katex form an interdependent
          // graph that also cross-imports the markdown/syntax chunks (and katex
          // is pulled in by mermaid). Force-merging them into one chunk creates
          // circular chunk dependencies whose const/class bindings evaluate out
          // of order, throwing "Cannot access 'x' before initialization" TDZ
          // errors on load. Let Rollup auto-chunk this graph instead.
          if (
            id.includes("react-ipynb-renderer") ||
            id.includes("mathjax") ||
            id.includes("katex")
          ) {
            return undefined
          }

          if (
            id.includes("@chakra-ui") ||
            id.includes("@emotion") ||
            id.includes("framer-motion")
          ) {
            return "vendor-ui"
          }

          if (id.includes("@tanstack")) {
            return "vendor-routing"
          }

          if (
            id.includes("pdfjs-dist") ||
            id.includes("react-pdf-highlighter")
          ) {
            return "vendor-pdf"
          }

          if (
            id.includes("react-syntax-highlighter") ||
            id.includes("highlight.js") ||
            id.includes("lowlight") ||
            id.includes("refractor")
          ) {
            return "vendor-syntax"
          }

          if (
            id.includes("react-markdown") ||
            id.includes("remark-") ||
            id.includes("rehype-") ||
            id.includes("micromark") ||
            id.includes("mdast-") ||
            id.includes("hast-") ||
            id.includes("unified") ||
            id.includes("unist-")
          ) {
            return "vendor-markdown"
          }

          if (id.includes("react-diff-viewer")) {
            return "vendor-diff"
          }

          return "vendor"
        },
      },
    },
  },
})
