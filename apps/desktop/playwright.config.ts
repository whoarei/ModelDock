import { defineConfig } from "@playwright/test";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "../..");
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 300000,
  expect: { timeout: 30000 },
  reporter: "list",
  use: {
    actionTimeout: 30000,
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {},
  },
  webServer: [
    {
      command: "uv run --project ../.. python -m modeldock.cli serve",
      url: "http://127.0.0.1:4317",
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
      env: {
        MODELDOCK_DATA_DIR: path.join(root, "test-results/browser-runtime"),
      },
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:1420",
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
    },
  ],
});
