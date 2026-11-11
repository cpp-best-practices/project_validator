# Zig

Recognised by `.zig` sources and by `build.zig` (with `build.zig.zon`, the manifest of the dependencies, a file of the
ecosystem with no language of its own). `.zig-cache` (`zig-cache` before Zig 0.13) and `zig-out` beside `build.zig`
are build trees.

Zig has no warnings: an unused variable or a missing switch case is an error, so `compiler-warnings` and
`warnings-as-errors` have no rule and are skipped.

## `tests-run`

`test "…" {` blocks in the `.zig` files, run by `zig build test` (the build's `test` step) or `zig test src/main.zig`.

## `coverage`

kcov counts the lines a test binary runs: `zig test src/main.zig --test-cmd kcov --test-cmd kcov-output
--test-cmd-bin`, or kcov run on the binary.

## `platform-matrix`

The toolchains are Zig versions: the `version` of mlugg/setup-zig or goto-bus-stop/setup-zig (counted after their own
`uses:` line only, since every action has a `version` input), korandoru/setup-zig's `zig-version`, a matrix key `zig`,
or `zigup`.

## `ci-build-types`

`zig build` and `zig test` build their optimize mode (`-Doptimize=ReleaseSafe` to the build, `-O ReleaseSafe` to the
compiler): Debug by default, and the release modes ReleaseSafe, ReleaseFast and ReleaseSmall. CI builds each platform
in Debug and in a release mode, with and without sanitizers (`-fsanitize-c`, `-fsanitize-thread`).

## `hardening`

Zig's safety checks (bounds, integer overflow, null and undefined behaviour) are on in Debug and ReleaseSafe; the other
release modes drop them. A release build keeps them with `-Doptimize=ReleaseSafe` in CI, or with ReleaseSafe as the
default mode in `build.zig` (`standardOptimizeOption(.{ .preferred_optimize_mode = .ReleaseSafe })`). A build with no
`addExecutable` is a library, with no binary to harden, and skipped.

## `code-formatting`

`zig fmt --check .` fails on a file it would change; `zig fmt .` rewrites. zig fmt has one style.

## `function-limits`

lizard parses Zig, so CI runs it with a length limit.

## `committed-artifacts`

`.zig-cache/` (or `zig-cache/`) and `zig-out/`.

## `vcs-ignore`

`.zig-cache/` (or `zig-cache/`) and `zig-out/`.

## Not judged

Zig has no warnings (`compiler-warnings`, `warnings-as-errors`) and no standard to pick (`cxx-extensions`); it is
statically typed (`type-checking`); no code security scanner, dependency auditor, fuzzer or mutation testing tool the
validator knows reads Zig; the `.hash` of every dependency in `build.zig.zon` belongs to `dependency-management`, not
judged for Zig yet.
