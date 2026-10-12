/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Docker development uses the reverse proxy. The local no-Docker launcher
// points these same-origin requests directly at the local API instead.
const proxyTarget = process.env.DARSON_DEV_PROXY_TARGET ?? "http://localhost:8080";
const devPort = Number(process.env.DARSON_DEV_PORT ?? "5173");

export default defineConfig({
  plugins: [react()],
  server: {
    port: devPort,
    strictPort: true,
    proxy: {
      "/api": proxyTarget,
      "/events": proxyTarget,
      "/tracks": proxyTarget,
      "/incidents": proxyTarget,
      "/cameras": proxyTarget,
      "/patterns": proxyTarget,
      "/search": proxyTarget,
      "/health": proxyTarget,
      "/frigate": proxyTarget,
      "/mock-evidence": proxyTarget,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
