import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 30000,
  expect: { timeout: 15000 },
  use: { browserName: "chromium", viewport: { width: 1000, height: 900 }, timezoneId: "America/Chicago", locale: "en-US" },
  webServer: { command: "node reference-host.mjs --serve-only", url: "http://localhost:8080", reuseExistingServer: !process.env.CI },
  snapshotPathTemplate: "{testDir}/baselines/{arg}{ext}",
});
