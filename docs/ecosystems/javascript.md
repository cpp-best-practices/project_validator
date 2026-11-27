# JavaScript

Learn more: [JavaScript](https://developer.mozilla.org/en-US/docs/Web/JavaScript).

Recognised by `.js`, `.mjs`, `.cjs` and `.jsx` sources, a `package.json` that names an entry point (`main`, `module`,
`exports`, `bin`) or `deno.json`. The package scripts CI runs (`npm test`, `npm run lint`, Deno tasks) count as CI
configuration.

JavaScript and [TypeScript](typescript.md) are separate languages, judged separately: they share package.json, Deno,
their runtimes and their tools, but type checking is TypeScript's defining gate and not a norm of JavaScript, so
`type-checking` does not apply here. JavaScript tool configuration (`eslint.config.js`, `vite.config.mjs`,
`.prettierrc.cjs`, `gulpfile.js`) in a project with TypeScript sources is configuration, not JavaScript code, and a
package.json's `main` names the JavaScript a TypeScript package publishes, which makes it no JavaScript project.

## `tests-run`

`*.test.*`, `*.spec.*`, `*_test.*`, `__tests__/` or top-level `test/` files run by jest, vitest, mocha, ava, borp,
`node --test` (or node running a runner's entry point, or the test directory), `deno test`, `bun test`, playwright
or a package script (`npm test`, `nub run test`).

## `fuzz-testing`

Jazzer.js fuzz targets (an exported `fuzz` function, or `it.fuzz(` tests, in `.js`, `.mjs`, `.cjs` or `.ts` files), run
by a CI step `npx jazzer <target>` or by `jest` with `JAZZER_FUZZ=1` set in the step or job environment. fast-check
tests alone warn: they are property-based tests, not fuzz targets.

## `coverage`

c8, nyc, Jest (`--coverage`, or `collectCoverage: true` in the configuration it reads, or package.json's `jest`), Vitest
(`--coverage`, or coverage `enabled: true` in the configuration it reads), `deno test --coverage` or
`node --test --experimental-test-coverage`, run by CI directly, through `npx` and the other package runners, or
through the package scripts it runs. `bun test --coverage` counts lines only.

## `platform-matrix`

The toolchains are Node.js, Deno or Bun versions. A JavaScript action's self-test (a step `uses: ./`) runs the action
on the Node its `action.yml` names (`runs.using: node24`): actions/checkout's test jobs count as node 24 on each OS
they run on.

## `compiler-warnings`

A linter runs: eslint, `biome lint` / `biome ci`, `deno lint`, or oxlint.

## `warnings-as-errors`

A lint warning fails CI: `eslint --max-warnings 0`, `biome ci` or `--error-on-warnings`, `deno lint`, or
`oxlint --deny-warnings`.

## `mutation-testing`

StrykerJS (`stryker run`, also as `npx stryker run` or a package script; settings in `stryker.config.json`,
`.js`, `.mjs` or `.cjs`, or `stryker.conf.json` or `.js`). `stryker run --incremental` counts as
running on the changes only.

## `code-formatting`

`prettier --check` (or `-l`; settings in a `.prettierrc*`, `prettier.config.*` or the `prettier` key of
package.json), `biome format`, `biome check` or `biome ci` (without `--write`), `deno fmt --check`, `dprint check` or
`oxfmt --check`, in CI or the package scripts and Deno tasks it runs. They have a default style, so CI enforcement
alone passes.

## `function-limits`

lizard runs in CI with a length limit, or eslint runs with `max-lines-per-function` on (not `"off"` or `0`) in its
configuration. The rule on while CI does not run eslint warns.

## `static-analysis`

eslint (or `next lint`, or xo), oxlint, `biome lint` / `check` / `ci` or `deno lint`, in CI, a pre-commit hook CI runs,
or the package scripts CI runs.

## `security-scanning`

eslint with `eslint-plugin-security` (or `@microsoft/eslint-plugin-sdl`) in its configuration. In CI, where the tool
runs (a setting alone, which nothing CI runs reads, does not count); CodeQL, GitLab SAST or semgrep count too.

## `dependency-management`

Dependencies declared in `package.json` (or `imports` in `deno.json`) are locked by a committed `package-lock.json`,
`npm-shrinkwrap.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, `bun.lockb` or `deno.lock`, libraries included.

## `dependency-audit`

`npm audit` (not `npm audit signatures`), `pnpm audit`, `yarn npm audit` / `yarn audit` or `bun audit`.

## `license`

`license` in `package.json`.

## `committed-artifacts`

`node_modules/`, a top-level `coverage/` and `*.tsbuildinfo` (not `dist/`, which a JavaScript GitHub Action commits).

## `vcs-ignore`

`node_modules/`.
