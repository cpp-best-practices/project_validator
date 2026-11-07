# JavaScript/TypeScript

Recognised by `.js`, `.ts` and related sources, `package.json` or `deno.json`. The package scripts CI runs
(`npm test`, `npm run lint`, Deno tasks) count as CI configuration.

## `tests-run`

`*.test.*`, `*.spec.*`, `*_test.*` or `__tests__/` files run by jest, vitest, mocha, ava, `node --test`,
`deno test`, `bun test`, playwright or `npm test`.

## `coverage`

c8, nyc, `jest --coverage` (or `collectCoverage: true`), `vitest --coverage` (or coverage `enabled: true`),
`deno test --coverage` or `node --experimental-test-coverage`, in CI, the package scripts it runs, or the test
runner's configuration.

## `platform-matrix`

The toolchains are Node.js, Deno or Bun versions.

## `compiler-warnings`

A linter runs: eslint, `biome lint` / `biome ci`, or `deno lint`.

## `warnings-as-errors`

A lint warning fails CI: `eslint --max-warnings 0`, `biome ci` or `--error-on-warnings`, or `deno lint`.

## `type-checking`

`tsc` (JavaScript with `checkJs`), or `deno check` / `deno test`, also through the package scripts CI runs. Strict
mode is a bonus: `"strict": true` or `@tsconfig/strictest` in `tsconfig.json`, or Deno, strict by default.

## `code-formatting`

`prettier --check`, `biome format` / `biome ci`, `deno fmt --check` or `dprint check`, in CI or the package scripts
it runs; they have a default style, so CI enforcement alone passes.

## `function-limits`

lizard runs with a length limit, or eslint runs with `max-lines-per-function` enabled.

## `static-analysis`

eslint, `biome lint` or `deno lint`, in CI, a pre-commit hook or the package scripts CI runs.

## `security-scanning`

`eslint-plugin-security` (or `@microsoft/eslint-plugin-sdl`), or semgrep with a JavaScript ruleset.

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
