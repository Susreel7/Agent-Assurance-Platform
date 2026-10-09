import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // This value is consumed by Vite itself, not by browser code. Local `npm run dev`
  // reaches the host API; Compose overrides it with the `api` service name.
  const apiTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000";
  const proxy = {
    "/v1": { target: apiTarget, changeOrigin: true },
    "/readyz": { target: apiTarget, changeOrigin: true },
    "/healthz": { target: apiTarget, changeOrigin: true },
  };

  return {
    plugins: [react()],
    resolve: { alias: { "@": path.resolve(__dirname, "src") } },
    server: {
      host: true,
      port: 5173,
      // Keep authenticated API calls and operational probes on the console origin.
      proxy,
    },
    preview: { proxy },
    build: { outDir: "dist", sourcemap: true },
  };
});
