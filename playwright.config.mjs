// The browser tests: the page and the report in each browser engine (Chromium, Firefox, WebKit), as visitors run them.
import { defineConfig, devices } from "@playwright/test";

const PORT = 8123;

export default defineConfig({
  testDir: "tests/web",
  testMatch: "*.spec.mjs",
  forbidOnly: true,
  reporter: process.env.CI ? "github" : "list",
  use: { baseURL: `http://localhost:${PORT}/` },
  webServer: { command: `node tests/web/serve.mjs ${PORT}`, url: `http://localhost:${PORT}/web/index.html` },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
