import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests (blueprint 12, E2E-01). They need the core API running with demo seed data:
 *   locally: `python services/core-api/scripts/dev_api.py` (port 8000)
 *   CI:      the API container from .github/workflows/ci.yml
 * Point E2E_BASE_URL at a deployed web app to skip starting Next here.
 */
const baseURL = process.env.E2E_BASE_URL || "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: process.env.CI ? "npm run start" : "npm run dev",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
        env: { API_URL: process.env.API_URL || "http://localhost:8000" },
      },
});
