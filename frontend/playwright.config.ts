import { defineConfig, devices } from "@playwright/test";

// Browser-level E2E against the RUNNING full compose stack (no backend mocking).
// The base URL is the reverse-proxy single origin. Override with DARSON_ORIGIN.
const ORIGIN = process.env.DARSON_ORIGIN ?? "http://localhost:8080";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: ORIGIN,
    trace: "on-first-retry",
    headless: true,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
