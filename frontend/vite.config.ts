import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Vendor chunk categories for the production build. See
// `.agent/brain/NOTES.md` (2026-06-03 Vite build chunk 拆分) for the
// motivation. Function form lets us bucket node_modules paths by
// package name; everything that doesn't match falls into the
// auto-generated `index` (app code + tiny vendors).
function vendorChunk(id: string): string | undefined {
  if (id.includes("node_modules/echarts")) return "vendor-echarts";
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

