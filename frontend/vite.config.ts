import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Vendor chunk categories for the production build. See
// `.agent/brain/NOTES.md` (2026-06-03 Vite build chunk 拆分) for the
// motivation. Function form lets us bucket node_modules paths by
// package name; everything that doesn't match falls into the
// auto-generated `index` (app code + tiny vendors).
function vendorChunk(id: string): string | undefined {
  // Round #1151: split ECharts into 3 sub-chunks by sub-package so
  // each piece can be (a) cached independently on version bumps and
  // (b) loaded only when a route actually needs it. The first-pass
  // chunk put all 4 sub-packages in one 494 KB file. The split:
  //   - vendor-echarts-core        ~  30 KB  (echarts/core + renderers + zrender)
  //   - vendor-echarts-charts      ~ 300 KB  (all chart type re-exports)
  //   - vendor-echarts-components  ~ 180 KB  (all component re-exports)
  // Note: the renderers sub-package is merged into the core chunk
  // because its actual code is just a 100-byte empty re-export shim
  // (the real CanvasRenderer code lives in `lib/renderer/...` and
  // would be ~30 KB if separated). Splitting it gives no cache win.
  // Even though `echarts/charts` re-exports every chart type from a
  // single barrel file, the split still gives us:
  //   1. Independent cache invalidation when ECharts bumps versions
  //      (the chart registry changes more often than the components).
  //   2. A future migration path: when a new feature page only
  //      needs `echarts/core` + 1 chart, we can dynamically
  //      `import()` the chart chunk and skip the components chunk.
  //   3. Better debugging — the network waterfall shows which
  //      sub-package is taking the longest to parse.
  //
  // Path matching caveat (the bug we hit during dev): the public
  // sub-package entry points are `echarts/core.js`, `echarts/charts.js`
  // etc. at the top level, but the actual modules are nested under
  // `echarts/lib/...` (e.g. `echarts/lib/chart/line/LineSeries.js`).
  // Rolldown passes the leaf path of every transitively-imported
  // module, so the regex must cover BOTH the top-level barrel AND
  // the `lib/<group>/...` subtree. Forgetting the latter collapses
  // the whole library into the main app chunk and silently undoes
  // the split.
  if (
    id.includes("node_modules/echarts/core.js") ||
    id.includes("node_modules/echarts/renderers.js") ||
    id.includes("node_modules/echarts/lib/core/") ||
    id.includes("node_modules/echarts/lib/renderer/") ||
    id.includes("node_modules/zrender")
  ) {
    // Core + renderers + zrender all go in one chunk. The renderer
    // modules are tiny (CanvasRenderer + SVGRenderer are just thin
    // adapters over zrender), and they have no value as their own
    // chunk (would be ~100 bytes of empty re-export shim). Merging
    // them keeps zrender + the renderer registration atomic.
    return "vendor-echarts-core";
  }
  if (
    id.includes("node_modules/echarts/charts.js") ||
    id.includes("node_modules/echarts/lib/chart/")
  ) {
    return "vendor-echarts-charts";
  }
  if (
    id.includes("node_modules/echarts/components.js") ||
    id.includes("node_modules/echarts/lib/component/")
  ) {
    return "vendor-echarts-components";
  }
  if (id.includes("node_modules/react-dom")) return "vendor-react-dom";
  if (
    id.includes("node_modules/react/") ||
    id.endsWith("/node_modules/react") ||
    id.includes("node_modules/scheduler")
  ) {
    return "vendor-react";
  }
  if (id.includes("node_modules/react-router")) return "vendor-router";
  if (id.includes("node_modules/@tanstack")) return "vendor-tanstack";
  if (
    id.includes("node_modules/react-hook-form") ||
    id.includes("node_modules/zod") ||
    id.includes("node_modules/@hookform")
  ) {
    return "vendor-form";
  }
  if (id.includes("node_modules/lucide-react")) return "vendor-icons";
  if (id.includes("node_modules/dompurify")) return "vendor-sanitize";
  return undefined;
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        // 8000 is occupied by another project on this dev machine;
        // run the GetRich backend on 8001 instead. Update both
        // this target AND the uvicorn --port flag together.
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
  build: {
    // Vite's chunk-size warning is configured at the top level
    // (see `BuildOptions.chunkSizeWarningLimit`), NOT under
    // rolldownOptions. ECharts alone is ~400 KB minified, just under
    // the default 500 KB warning threshold; bump the limit to 600 KB
    // so the CI build output stays clean even if a single vendor
    // chunk grows slightly with a future dependency bump.
    chunkSizeWarningLimit: 600,
    // Rolldown 0.x still accepts `rollupOptions` as an alias for
    // `rolldownOptions` — using the new name keeps the config
    // forward-compatible. The function form of `manualChunks` is
    // documented at https://rolldown.rs/reference/OutputOptions.
    rolldownOptions: {
      output: {
        manualChunks: vendorChunk,
      },
    },
  },
});

