/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks to Vite (5173); API + WebSocket calls are proxied to FastAPI.
// Inside Docker, nginx does the same job (see nginx.conf).
const backend = process.env.VITE_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  base: process.env.VITE_BASE_PATH ?? "/",
  plugins: [react()],
  server: { port: 5173, host: true, proxy: { "/api": { target: backend, changeOrigin: false, ws: true } } },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/test-setup.ts" },
});
