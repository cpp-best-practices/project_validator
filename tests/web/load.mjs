// The page's and the report's scripts, run in Node as a browser runs them: each in the global scope of a context (a
// jsdom window, or a stand-in for a worker's), under its own file name, so that c8 counts the lines the tests reach.
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { JSDOM } from "jsdom";
import { ROOT } from "./checkout.mjs";

export { ROOT, report } from "./checkout.mjs";

/** Runs the script at `relative` (to the repository) in `context`. */
export function run(context, relative) {
  const file = path.join(ROOT, relative);
  // StrykerJS (`npm run mutate`) names the mutant to switch on in the environment, which a context does not have.
  const mutant = process.env.__STRYKER_ACTIVE_MUTANT__;
  if (mutant !== undefined) context.__stryker__ = { activeMutant: mutant };
  vm.runInContext(readFileSync(file, "utf8"), context, { filename: file });
}

/** A page from `html` at `url`, its own inline scripts not run: the tests run the scripts under test themselves. */
export function page(html, url = "https://example.com/app/") {
  return new JSDOM(html, { url, runScripts: "outside-only", pretendToBeVisual: true });
}

/** Resolves once the tasks already queued (a handler's awaits) have run. */
export function settled() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
