// The JavaScript's lint (`npm run lint`, warnings fail it): ESLint's recommended rules and eslint-plugin-security's,
// with each script's globals: the page's and the report's run in a page, the worker's in a worker, the tests in Node.
import js from "@eslint/js";
import security from "eslint-plugin-security";
import globals from "globals";

export default [
  {
    ignores: [
      "node_modules/",
      "coverage/",
      "reports/",
      ".stryker-tmp/",
      "test-results/",
      "playwright-report/",
      "build/",
      "dist/",
      "site/",
      "_site/",
      "mutants/",
      "tests/fixtures/",
    ],
  },
  js.configs.recommended,
  security.configs.recommended,
  {
    files: ["web/*.js", "project_validator/views/assets/*.js"],
    languageOptions: { sourceType: "script", globals: globals.browser },
  },
  {
    // github.js's functions, the globals the page and the worker call.
    files: ["web/app.js"],
    languageOptions: { globals: { parseRepository: "readonly" } },
  },
  {
    files: ["web/worker.js"],
    languageOptions: { globals: { ...globals.worker, readRepository: "readonly" } },
  },
  {
    files: ["**/*.mjs", "tests/web/**/*.cjs"],
    languageOptions: { globals: globals.node },
  },
  {
    // The tests read this checkout's own files by path, serve.mjs serves only those below it, and the fuzz target
    // requires its own copy of github.js (so that Jazzer.js instruments it).
    files: ["tests/web/**"],
    rules: { "security/detect-non-literal-fs-filename": "off", "security/detect-non-literal-require": "off" },
  },
];
