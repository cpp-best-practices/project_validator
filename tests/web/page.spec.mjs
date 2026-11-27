// The page and the report in a real browser, once per engine (playwright.config.mjs): what jsdom cannot show, that
// the worker starts, a folder is picked, the report shows in its frame and its scripts run. Pyodide is stood in for
// by a script that reports the files it was given, GitHub by answers routed in the page.
import path from "node:path";
import { expect, test } from "@playwright/test";
import { ROOT, report } from "./checkout.mjs";

const PYODIDE = `
self.loadPyodide = async () => {
  const written = [];
  return {
    loadPackage: async () => {},
    pyimport: () => ({ install: async () => {} }),
    FS: { mkdirTree() {}, writeFile(path) { written.push(path); }, truncate() {}, analyzePath: () => ({ exists: false }) },
    runPython: () => ({ toJs: () => [1, "<!DOCTYPE html><p>" + written.sort().join(" ") + "</p>"] }),
  };
};`;

test.beforeEach(async ({ page }) => {
  await page.route("https://cdn.jsdelivr.net/pyodide/**", (route) =>
    route.fulfill({ contentType: "text/javascript", body: PYODIDE }),
  );
  await page.route("**/web/wheel.txt", (route) => route.fulfill({ body: "project_validator-1.0-py3-none-any.whl" }));
});

test("a folder picked is validated and its report shown", async ({ page }) => {
  await page.goto("web/index.html");
  await page.locator("#folder").setInputFiles(path.join(ROOT, "tests/fixtures/bare_python"));
  await expect(page.locator("#status")).toHaveText("Done: some checks did not pass.");
  await expect(page.frameLocator("#report").locator("p")).toContainText("/project/bare_python/");
  await expect(page.locator("#download")).toBeVisible();
});

test("a repository linked with ?repo= is read from GitHub and validated", async ({ page }) => {
  const tree = [{ path: "main.py", type: "blob", mode: "100644", size: 9 }];
  await page.route("https://api.github.com/**", (route) =>
    route.fulfill({ json: route.request().url().includes("/commits/") ? { sha: "c0ffee0123456789" } : { tree } }),
  );
  await page.route("https://raw.githubusercontent.com/**", (route) => route.fulfill({ body: "print(1)\n" }));
  await page.goto("web/index.html?repo=o%2Fr");
  await expect(page.locator("#status")).toHaveText("Done: some checks did not pass. (commit c0ffee012345)");
  await expect(page.frameLocator("#report").locator("p")).toHaveText("/project/r/main.py");
});

test("the report filters its results and switches its theme", async ({ page }) => {
  const html = report();
  await page.route("**/report.html", (route) => route.fulfill({ contentType: "text/html", body: html }));
  await page.goto("report.html");
  const failed = page.locator('details.check[data-status="FAIL"]').first();
  await expect(failed).toBeVisible();
  await page.locator('.filter[data-filter="FAIL"]').click();
  await expect(failed).toBeHidden();
  const theme = await page.locator("html").getAttribute("data-theme");
  await page.locator(".theme-toggle").click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", theme ?? "");
});
