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
        // A production build, locally as well as in CI. The dev server watches the whole workspace — Next
        // infers the repo root here — so the embedded Postgres data directory and the test artefacts churn
        // under it and it rebuilds the page mid-test. A Fast Refresh rebuild remounts the client tree and
        // wipes the state of any form the test has filled in.
        command: process.env.CI ? "npm run start" : "npm run build && npm run start",
        url: baseURL,
        // Always the build Playwright starts itself: reusing a server someone else left running would put a
        // dev server (and its rebuilds) back in front of the tests. Use E2E_BASE_URL to point at a real one.
        reuseExistingServer: false,
        timeout: 300_000,
        env: { API_URL: process.env.API_URL || "http://localhost:8000" },
      },
});
