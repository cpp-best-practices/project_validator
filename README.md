# project_validator

[![ci](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml/badge.svg)](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cpp-best-practices/project_validator/graph/badge.svg)](https://codecov.io/gh/cpp-best-practices/project_validator)

A tool to validate a project's build, CI and tooling against best practices.

It recognises C and C++ (CMake or Meson), Python (`pyproject.toml` or `setup.py`),
Rust (Cargo), Go (Go modules), JavaScript/TypeScript (`package.json` or `deno.json`) JVM (Java and Kotlin, with Maven or Gradle) PHP (Composer) and Ruby (Bundler) projects, and judges each language by its own ecosystem's tools: a C++
project needs branch coverage from gcovr or llvm-cov, a Python project from coverage.py,
a Rust project from cargo-llvm-cov. Checks that do not apply to any of the project's
languages are reported as `SKIP`. A project using several languages is judged for each
of them and gets the worst result. In a project of no recognised language, only the
checks that apply to every project run. A C/C++ project is judged by the rules of the
build system it uses (CMake or Meson); one using neither is judged as a CMake project. A JVM project's Maven or Gradle build counts as CI configuration when CI runs it (`mvn verify`, `gradle check`), since that is where its plugins are wired in.
More ecosystems can be added with plugins (see [Adding an ecosystem](#adding-an-ecosystem)).

The validator itself is pure Python and has no build step; it only inspects
(and, with `--build`, configures and builds) the project it is pointed at.

## Requirements

- Python 3.14+ (the system Python on Ubuntu 26.04 LTS; no installation step,
  run with `python3 -m project_validator <path>`)
- [PyYAML](https://pyyaml.org/) 6.0+ (`python3-yaml` on Ubuntu, or `python3 -m pip install PyYAML`)
- Optionally [rich](https://github.com/Textualize/rich) 13.0+ for colored output
- CMake / CTest, only for `--build` (already required by any CMake project being validated)

On a machine without Python 3.14, `uv run` or a distro backport will work.
In CI, use `actions/setup-python` with `python-version: "3.14"`.

## Usage

```sh
python3 -m project_validator path/to/project
python3 -m project_validator --list
python3 -m project_validator --map path/to/project
python3 -m project_validator --only coverage,platform-matrix --format json path/to/project
```

| Option | Meaning |
|---|---|
| `--list` | list the available checks; with `--format json`, also the ecosystems each one applies to |
| `--map` | print the detected project structure as JSON: languages, build systems, the signals that recognised each ecosystem, the file suffixes no ecosystem recognises, and the CI providers, jobs and toolchains |
| `--only CHECKS` / `--skip CHECKS` | comma separated check names to run / not run |
| `--format text\|json` | output format |
| `--color auto\|always\|never` | color the text output (needs rich); `auto` colors only on a terminal when `NO_COLOR` is unset |
| `--exclude DIR` | leave `DIR`, relative to the project, out of the validation (e.g. test fixtures); may be repeated |
| `--build` | configure and build the project in a temporary directory and ask `ctest` for its tests |
| `--strict` | treat warnings as failures |
| `--max-file-size MIB` | committed files larger than this belong in Git LFS or DVC (default: 5) |
| `--allow-official-tags` | let the actions GitHub publishes (`actions/`, `github/`) be pinned to tags |
| `--cmake PATH` / `--ctest PATH` | the executables used by `--build` |
| `--plugin-dir DIR` | load extra checks and CI providers from `DIR/*.py` |

Exit codes: `0` everything passed, `1` a check failed or raised an error, `2` usage error.

## Checks

| Check | Applies to | Passes when |
|---|---|---|
| `ci-present` | all | at least one CI configuration is found |
| `tests-run` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | tests exist and CI runs them (`ctest-runs` is accepted as an old name). C/C++ with CMake: `enable_testing()` or `include(CTest)` is called, tests are registered (`add_test`, `*_discover_tests`, ...) and CI runs `ctest`; with `--build`, the project is really configured and built, and `ctest` must list at least one test. C/C++ with Meson: `test()` is called in a `meson.build` and CI runs `meson test`. Python: `test_*.py` / `*_test.py` files run by pytest, unittest, tox or nox. Rust: `#[test]` functions run by `cargo test` or nextest. Go: `Test` functions in `*_test.go` files run by `go test`. JavaScript/TypeScript: `*.test.*`, `*.spec.*`, `*_test.*` or `__tests__/` files run by jest, vitest, mocha, ava, `node --test`, `deno test`, `bun test`, playwright or `npm test`. JVM: `@Test` methods or Kotest specs under `src/test/java` or `src/test/kotlin`, run by `mvn test` / `verify` or `gradle test` / `check` / `build`. PHP: `*Test.php` files with PHPUnit test cases or Pest tests, run by phpunit, pest, paratest or `composer test`, in CI or the Composer scripts it runs. Ruby: `spec/**/*_spec.rb` or `test/**/*_test.rb` files run by rspec, `rake test` / `spec` or `rails test`, or by the Rakefile's test tasks when CI runs rake. Warns when CI never runs the tests |
| `coverage` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | CI reports branch coverage (Go's tools measure statements only, so Go needs statement coverage: `go test -cover` or `-coverprofile`). C/C++: gcovr, lcov, genhtml, gcov or llvm-cov branch options; Python: `coverage run --branch`, `--cov-branch` or `branch = true`; Rust: cargo-llvm-cov, cargo-tarpaulin or grcov with `--branch`; JavaScript/TypeScript: c8, nyc, `jest --coverage` (or `collectCoverage: true`), `vitest --coverage` (or coverage `enabled: true`), `deno test --coverage` or `node --experimental-test-coverage`, in CI, the package scripts it runs, or the test runner's configuration; JVM: JaCoCo (`jacoco-maven-plugin` with its `report` goal, `jacocoTestReport`) or Kover; PHP: PHPUnit `--path-coverage` (or `pathCoverage="true"`), which reports branch and path coverage together, so it also earns the path bonus (line coverage alone counts no branches); Ruby: SimpleCov with `enable_coverage :branch` (in `.simplecov` or a test helper). Path or MC/DC coverage (`-fcondition-coverage`, `-fcoverage-mcdc`, `--mcdc`, ...) is reported as a bonus |
| `platform-matrix` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | CI covers at least 2 operating systems, 2 toolchains (compilers, Python versions, Rust toolchains, Go versions, Node.js, Deno or Bun versions, JDK versions, PHP versions, or Ruby versions and implementations) and 3 OS/toolchain combinations |
| `ci-build-types` | C/C++, Rust | every OS/toolchain combination in CI builds Debug and Release (Rust: debug and release profiles), each with and without sanitizers |
| `compiler-warnings` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | a strict warning set is enabled. C/C++: `-Wall -Wextra -Wpedantic -Wshadow -Wconversion`, plus `/W4` and `/permissive-` when MSVC is in CI; Python: warnings are errors (`-W error`, `PYTHONWARNINGS=error`, pytest `filterwarnings = error`); Rust: `cargo clippy`, `-D warnings` and `clippy::pedantic`; Go: `go vet` and staticcheck (golangci-lint runs both); JavaScript/TypeScript: a linter runs (eslint, `biome lint` / `biome ci`, or `deno lint`); JVM: javac's `-Xlint:all` (a Kotlin-only project passes on Kotlin's default warnings); PHP: every error is reported while testing (`error_reporting` `-1` or `E_ALL` in `phpunit.xml`, `php.ini` or CI); Ruby: Ruby's warnings are on while testing (`ruby -w`, `RUBYOPT=-w`, `$VERBOSE = true`, RSpec's `--warnings` / `config.warnings`, or a test task's `warning = true`) and RuboCop or Standard runs. Warns listing what is missing |
| `warnings-as-errors` | C/C++, JavaScript/TypeScript, JVM, PHP  | C/C++: `-Werror`, `/WX` or `COMPILE_WARNING_AS_ERROR` (Meson: `werror=true`) is enabled in at least one configuration; JavaScript/TypeScript: a lint warning fails CI (`eslint --max-warnings 0`, `biome ci` or `--error-on-warnings`, or `deno lint`); JVM: `-Werror` for javac or kotlinc, or Kotlin's `allWarningsAsErrors`; PHP: PHPUnit's `failOnWarning`, `failOnNotice` and `failOnDeprecation` (or `failOnAllIssues`) |
| `cxx-extensions` | C/C++ | `CMAKE_CXX_EXTENSIONS` (or `CMAKE_C_EXTENSIONS` for C) is turned off, or with Meson `cpp_std` (`c_std`) names a standard such as `c++20` rather than `gnu++20`, so `-std=c++NN` is used rather than `-std=gnu++NN` |
| `hardening` | C/C++, Rust, Go | binary hardening is enabled: exploit mitigations that the build inserts into the binary (static analysis and dependency audits are judged by `security-scanning` and `dependency-audit`). C/C++: `_FORTIFY_SOURCE`, `-fstack-protector-strong`, `-fcf-protection`, `-fstack-clash-protection` and `_GLIBCXX_ASSERTIONS` or `_LIBCPP_HARDENING_MODE` (or GCC's `-fhardened`), plus `/sdl /guard:cf /DYNAMICBASE /CETCOMPAT` when MSVC is in CI; Rust: `overflow-checks` in release builds; Go: programs are built as position-independent executables (`-buildmode=pie`, not the default on Linux), and a module with no `package main` is skipped. Python, JavaScript/TypeScript, the JVM, PHP and Ruby build no native binary, so they are not judged. Warns listing what is missing |
| `code-formatting` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | the formatting style is defined (`.clang-format`; ruff or black settings; `rustfmt.toml`) and CI runs the formatter. Python, Rust, Go (gofmt, gofumpt, goimports) and JavaScript/TypeScript (`prettier --check`, `biome format` / `biome ci`, `deno fmt --check` or `dprint check`, in CI or the package scripts it runs) and JVM (Spotless, fmt-maven-plugin, google-java-format, ktfmt or ktlint) and PHP (`php-cs-fixer check` / `--dry-run`, phpcs or `pint --test`, in CI or the Composer scripts it runs) and Ruby (RuboCop, not `-a`; Standard; or `stree check`) formatters have a default style, so CI enforcement alone passes. Warns when the style is defined but CI does not enforce it |
| `function-limits` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | function length is limited: lizard runs with a length limit (`lizard --length 30`), or for C/C++, `.clang-tidy` enables `readability-function-size` with a threshold and clang-tidy runs, or for Go, golangci-lint runs with `funlen` enabled, or for JavaScript/TypeScript, eslint runs with `max-lines-per-function` enabled, or for the JVM, Checkstyle runs with `MethodLength` or detekt runs with `LongMethod` (on by default), or for PHP, PHPMD runs with its `codesize` rules (`ExcessiveMethodLength`), or for Ruby, RuboCop runs with `Metrics/MethodLength` not disabled (it is on by default) |
| `static-analysis` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | static analyzers run. C/C++: both clang-tidy (`CMAKE_CXX_CLANG_TIDY`, `run-clang-tidy`, or `clang-tidy` in CI) with its checks chosen in a `.clang-tidy`, and cppcheck (`CMAKE_CXX_CPPCHECK` or `cppcheck` in CI); Python: `ruff check`, pylint or flake8, in CI or as a pre-commit hook; Rust: `cargo clippy`; Go: golangci-lint with linters enabled beyond its defaults (`enable:` or `default: all` in a `.golangci.yml`); JavaScript/TypeScript: eslint, `biome lint` or `deno lint`, in CI, a pre-commit hook or the package scripts CI runs; JVM: Error Prone, SpotBugs, PMD, Checkstyle or detekt; PHP: PHPStan, Psalm, PHPMD or Phan; Ruby: RuboCop, Standard or Reek. Warns when an analyzer is configured but does not run, or runs short of that; fails when none runs |
| `type-checking` | Python, JavaScript/TypeScript, PHP, Ruby  | CI (or a pre-commit hook) runs a static type checker. Python: mypy, pyright or basedpyright, pyrefly, or ty; JavaScript/TypeScript: `tsc` (JavaScript with `checkJs`), or `deno check` / `deno test`, also through the package scripts CI runs; PHP: PHPStan or Psalm, also through the Composer scripts CI runs; Ruby: Sorbet (`srb tc`) or Steep (`steep check`). Strict mode is a bonus (`strict = true` in `[tool.mypy]` or a `[mypy]` section, `mypy --strict`, pyright's `typeCheckingMode` `strict`, `"strict": true` or `@tsconfig/strictest` in `tsconfig.json`, Deno, strict by default, PHPStan `level` 8 or higher, Psalm `errorLevel` 1 or 2, Sorbet's `# typed: strict`, or `D::Ruby.strict` in a Steepfile); without it the result suggests it. Warns when a type checker is configured but does not run; fails when none runs. Compiled languages, whose compilers check types, are not judged |
| `action-pinning` | all | every action and reusable workflow CI uses from another repository is pinned to a full commit SHA (`actions/checkout@<SHA> # v4.2.2`), and every `docker://` image to a digest. Fails when one is pinned to a branch or not at all; warns when one is pinned to a tag or an abbreviated commit (`--allow-official-tags` accepts tags for `actions/` and `github/`). Skipped without GitHub Actions |
| `ci-lint` | all | CI (or a pre-commit hook) lints the configuration of each CI provider it uses: GitHub Actions with actionlint or zizmor, GitLab CI with `glab ci lint` or `gitlab-ci-local --preview`, CircleCI with `circleci config validate`. Warns otherwise; skipped without CI, or when no linter is known for the providers used |
| `copy-paste-detection` | all | CI runs a duplicate code detector (PMD CPD, jscpd, Duplo, Simian, CCFinderX or SonarQube); warns otherwise |
| `security-scanning` | all | CI runs code security scanning (CodeQL or GitLab SAST), or every language in the project that has security lints enables them: Python: bandit (or ruff's `S` rules); Rust: `unsafe_code` forbidden crate-wide; Go: gosec; JavaScript/TypeScript: `eslint-plugin-security` (or `@microsoft/eslint-plugin-sdl`), or semgrep with a JavaScript ruleset; JVM: SpotBugs with Find Security Bugs, or PMD's `category/java/security.xml` rules; PHP: Psalm's taint analysis or phpcs-security-audit; Ruby: brakeman, or RuboCop, whose Security cops are on by default. Warns otherwise, naming the languages left unscanned |
| `secret-scanning` | all | CI or a pre-commit hook runs a secret scanner: gitleaks, TruffleHog, detect-secrets, ggshield or Nosey Parker. Warns otherwise, and says so when a scanner is configured (`.gitleaks.toml`, `.secrets.baseline`, `.gitguardian.yaml`) but nothing runs it. GitHub's own secret scanning is a repository setting, which cannot be seen from a checkout |
| `dependency-management` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | dependencies come from a package manager and are locked. C/C++: CPM, FetchContent, vcpkg (`vcpkg.json`), Conan (`conanfile.txt` / `conanfile.py`) or Meson wraps (`subprojects/*.wrap`); Python: dependencies declared in `pyproject.toml`, `setup.py` or requirements files are locked by a committed `uv.lock`, `poetry.lock`, `pdm.lock`, `Pipfile.lock` or `pylock.toml`, or by requirements pinned with `--hash`; Rust: a binary crate commits `Cargo.lock` (a library need not); Go: a module that requires others commits `go.sum`; JavaScript/TypeScript: dependencies declared in `package.json` (or `imports` in `deno.json`) are locked by a committed `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, `bun.lockb` or `deno.lock`, libraries included; JVM: dependencies declared in `pom.xml` or a Gradle build are verified by a committed `gradle/verification-metadata.xml` or `gradle.lockfile`, or Maven runs with `--strict-checksums`; PHP: dependencies required in `composer.json` (besides `php` and extensions) are locked by a committed `composer.lock`, unless the package is a `"type": "library"`; Ruby: gems in the `Gemfile` (or a gemspec's dependencies) are locked by a committed `Gemfile.lock`, unless the project is a gem (has a gemspec). Passes with a note when no dependencies are declared. Warns when they are not locked, or when third-party code is committed (`third_party/`, `external/`, `extern/`, `vendor/` other than `go mod vendor` output, or git submodules) |
| `dependency-audit` | Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | CI checks the dependencies against known vulnerabilities. Python: pip-audit or safety; Rust: cargo audit or `cargo deny check` (advisories); Go: govulncheck; JavaScript/TypeScript: `npm audit` (not `npm audit signatures`), `pnpm audit`, `yarn npm audit` / `yarn audit` or `bun audit`; JVM: OWASP dependency-check (`dependency-check-maven` bound to `check`, or `dependencyCheckAnalyze`); PHP: `composer audit`, or `roave/security-advisories` required; Ruby: bundler-audit. osv-scanner, `trivy fs` and `snyk test` count for every language. Warns otherwise |
| `data-wellformed` | all | every JSON, TOML, YAML and XML file parses, including the configuration in `.github/`, `.gitlab/`, `.circleci/`, `.buildkite/`, `.devcontainer/` and `.vscode/`. JSON that tools read with comments (`*.jsonc`, `tsconfig*.json`, `jsconfig.json`, `devcontainer.json`, `.vscode/*.json`) may have comments and trailing commas; YAML tags of any tool (GitLab's `!reference`) are accepted; XML external entities are never read. Files over 5 MiB are not parsed. Fails listing each file that does not parse, with the line and column |
| `large-files` | all | no committed file is larger than 5 MiB (`--max-file-size`) unless Git LFS stores it (`filter=lfs` in a `.gitattributes`) or DVC tracks it (a `.dvc` file beside it). In a git checkout only the files git tracks are judged. Warns listing the largest files |
| `security-policy` | all | a `SECURITY.md` (or `.rst`, `.txt`, ...) at the root, in `.github/` or in `docs/` says how to report a vulnerability: an email address, a link, or the forge's private vulnerability reporting. Warns otherwise |
| `license` | all | a license file (`LICENSE`, `LICENSE.md`, `LICENSE-MIT`, `COPYING`, `UNLICENSE`, ... or REUSE's `LICENSES/` directory) holds a recognised license: an `SPDX-License-Identifier` line, or the standard text of AGPL, LGPL, GPL, Apache-2.0, MPL-2.0, EPL-2.0, BSL-1.0, Unlicense, CC0-1.0, MIT, BSD, ISC, 0BSD or Zlib. Warns when the license is not recognised, or when a manifest declares another one (Python: `[project] license`; Rust: `[package] license`; JavaScript/TypeScript: `license` in `package.json`; PHP: `license` in `composer.json`; Ruby: the gemspec's `license` or `licenses`). Fails without a license file |
| `dependency-updates` | all | Dependabot or Renovate is configured; warns otherwise |
| `status-badges` | all | the README (at the root, in `.github/` or in `docs/`) shows a CI status badge of any supported CI provider (GitHub Actions `badge.svg`, GitLab pipeline, CircleCI, ... or their shields.io badges) and a quality badge (Codecov, Coveralls, SonarCloud, Codacy, Code Climate, DeepSource, Coverity Scan, OpenSSF Scorecard or Best Practices). Warns when only one kind is shown; fails when there is no README or no badge |
| `committed-artifacts` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | no build output is committed. C/C++: object files and libraries (`*.o`, `*.obj`, `*.a`, `*.lib`, `*.so`, `*.dylib`, `*.dll`), `*.exe`, `*.pdb`, `CMakeCache.txt`, `CMakeFiles/`, `CMakeUserPresets.json`, and a top-level `build/`, `out/` or `builddir/`; Python: `__pycache__/`, `*.py[co]`, `*.egg-info/`, a top-level `dist/` or `build/`; Rust: a top-level `target/`; Go: `*.test`, `*.out` and a top-level `bin/`; JavaScript/TypeScript: `node_modules/`, a top-level `coverage/` and `*.tsbuildinfo` (not `dist/`, which a JavaScript GitHub Action commits); JVM: `*.class`, plus Maven's `target/` or Gradle's `build/` and `.gradle/`; PHP: a top-level `vendor/`, `.phpunit.cache/` and `.phpunit.result.cache`; Ruby: `.bundle/`, `*.gem`, and a top-level `coverage/` or `pkg/` (a committed `vendor/bundle/` is reported by `dependency-management`). In a git checkout only the files git tracks are judged; `--exclude` keeps fixtures out. Fails listing the outputs |
| `vcs-ignore` | C/C++, Python, Rust, Go, JavaScript/TypeScript, JVM, PHP, Ruby  | a `.gitignore`, `.hgignore`, `.bzrignore` or `.fossil-settings/ignore-glob` ignores the build outputs (`build/` or `out/`, `__pycache__/` or `*.py[cod]`, `/target`, Go's `*.test` or `*.out`, `node_modules/`, Maven's `target/` or Gradle's `build/`, PHP's `vendor/`, Ruby's `.bundle/` or `vendor/bundle/`). Warns when an ignore file misses them |

CI detection is pluggable too. GitHub Actions workflows (including `strategy.matrix`
with `include`/`exclude`) and GitLab CI pipelines (including `parallel: matrix:`)
are parsed as YAML. Azure Pipelines, AppVeyor, CircleCI, Travis CI,
Jenkins, Buildkite, Drone, Cirrus CI, Bitbucket Pipelines and Woodpecker are detected
and scanned heuristically. A job that names no compiler is counted with its runner's
default compiler (gcc on Linux, AppleClang on macOS, MSVC on Windows).

Known limitations:

- GitLab `extends:` is not resolved.
- A GitHub matrix computed by an expression (`fromJSON(...)`) cannot be expanded; those jobs are reported with an `unknown` OS.
- Evidence is found by scanning text, so every file under the project is considered;
  use `--exclude` to leave out test fixtures or vendored code.
- A CI job that names no compiler counts as a C/C++ build with its runner's default compiler,
  unless it only runs another ecosystem's tools (e.g. pytest, but no CMake, Meson or compiler).

## Writing a Plugin

Any module-level `Check`, `CiProvider` or `Ecosystem` in a file passed with `--plugin-dir` is picked up:

```python
from project_validator.ci import CiProvider
from project_validator.core import Context, Result, check

EXAMPLE_CI = CiProvider(name="Example CI", files=("example-ci.yml",))


@check(name="has-readme", description="The project has a README")
def has_readme(context: Context) -> Result:
    if context.project.exists("README.md"):
        return Result.passed("README.md found")
    return Result.failed("no README.md")
```

### Adding an ecosystem

Everything the validator knows about a language lives in its profile under `project_validator/ecosystems/`:
how it is recognised (build systems, source suffixes, how CI names its toolchain versions) and the rules
it is judged by. The checks are generic: each one judges every ecosystem that has a rule of its type
(see `project_validator/rules.py`), and does not apply to the others. A plugin can add an ecosystem
the same way, without changing the validator.

A project is recognised as an ecosystem by any of:

- `BuildSystem.files`: exact names (`build.zig`), file name patterns (`*.csproj`) or directory patterns
  ending in `/` (`*.xcodeproj/`), matched anywhere in the project;
- `source_suffixes`: suffixes only this ecosystem uses;
- `detect`: a probe that reads the project (e.g. `project.read_head(path)`) and returns the languages it found,
  for ecosystems that file names cannot show;
- `ambiguous_suffixes`: suffixes other ecosystems may share (`.h`, `.pl`), counted only once the ecosystem
  was recognised another way. A suffix mapped to `None` is accounted for without adding a language.

Registering an ecosystem that claims another one's build file or source suffix is an error.
`--map` lists the suffixes no ecosystem recognises, so the gaps are visible.


```python
import re

from project_validator.ecosystems.model import BuildSystem, Ecosystem, ToolchainPatterns, versions_axis
from project_validator.rules import Formatter
from project_validator.text import pattern


def _no_config(context):
    return None


ZIG = Ecosystem(
    label="Zig",
    languages=frozenset({"Zig"}),
    build_systems=(BuildSystem(name="Zig build", files=("build.zig",), languages=frozenset({"Zig"})),),
    source_suffixes={".zig": "Zig"},
    toolchain=ToolchainPatterns(
        language="Zig", versions=(re.compile(r"\bzig-version\W+([\d.x]+)"),), usage=re.compile(r"\bzig\s+build\b")
    ),
    rules=(
        versions_axis("Zig version", "Zig"),  # platform-matrix: OS x Zig version
        Formatter(
            name="zig fmt",
            config_file=_no_config,
            runs=(pattern("zig fmt", r"\bzig\s+fmt\b"),),
            hint="run zig fmt --check in CI",
            default_style=True,
        ),  # code-formatting
    ),
)
```

`--list --format json` shows which ecosystems each check applies to, including those added by plugins.

## Development

```sh
python3 -W error -m unittest
```

The project validates itself; CI runs the same command:

```sh
python3 -m project_validator --strict --exclude tests/fixtures .
```

Each quality gate is its own CI job, so a pull request shows which one failed.
To run them locally:

| CI job | Command |
|---|---|
| `lint` | `ruff check .` |
| `formatting` | `ruff format --check --diff .` |
| `typing` | `mypy` |
| `copy-paste-detection` | `npx --yes jscpd@4.3.0` (settings in `.jscpd.json`) |
| `function-limits` | `lizard --length 30 --warnings_only project_validator tests` |

Branch coverage is measured with [coverage.py](https://coverage.readthedocs.io/)
(configured in `pyproject.toml`, which fails the report below 95%):

```sh
python3 -m pip install "coverage>=7.10"
coverage run --branch -m unittest
coverage report
```

CI uploads the coverage report to [Codecov](https://codecov.io/gh/cpp-best-practices/project_validator)
and fails if branch coverage drops below the threshold.

## Dependency Policy

The validator is meant to run anywhere a project can be built,
with as little setup as possible. To keep it that way:

- **The standard library comes first.** If something can reasonably be
  done with the Python standard library, do it that way.
- **External dependencies are allowed, but must be carefully weighed.**
  A PR that adds one must explain:
  - what problem it solves that the standard library can't reasonably solve
  - how mature it is, how well it's maintained, and its license
  - its transitive dependencies (fewer is better; pure-Python is preferred)
  - whether it can be **optional**, with the validator degrading gracefully
    (and saying so in its output) when it's missing
- **Required dependencies** are listed in `pyproject.toml` with a lower bound
  and justified in this section. **Optional dependencies** go in an
  `[project.optional-dependencies]` extra.
- Plugins (checks) must not add dependencies that the rest of the validator
  doesn't already have.

### Current Dependencies

| Dependency | Kind | Why |
|---|---|---|
| [PyYAML](https://pyyaml.org/) `>=6.0` | required | The standard library has no YAML parser, and CI configuration is YAML. PyYAML is mature, MIT licensed, has no dependencies, and is packaged by every major distro (`python3-yaml` on Ubuntu). It is required rather than optional because scanning CI files as text cannot tell which compiler runs on which OS, nor apply a matrix's `include`/`exclude`, so it over-counts platform combinations and can pass `platform-matrix` for a project that should fail. Without PyYAML the validator exits with an error that says how to install it. |
| [rich](https://github.com/Textualize/rich) `>=13.0` | optional (`pretty` extra) | Colored, aligned text output with a per-status summary. MIT licensed and widely used. Without it the validator prints plain text and says so. |
| [coverage.py](https://coverage.readthedocs.io/) `>=7.10` | development only (`coverage` extra) | Measures the branch coverage of the test suite; the standard library's `trace` module does not measure branches. coverage.py is the de facto Python coverage tool, Apache 2.0 licensed and has no required dependencies. The validator itself never imports it. |
| [ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy-lang.org/), [lizard](https://github.com/terryyin/lizard), [jscpd](https://github.com/kucherenko/jscpd) | CI only | The lint, typing, function-limits and copy-paste-detection quality gates. They are installed by their CI jobs and are never imported by the validator. |

PyYAML is the only required dependency.

The tools CI installs are locked with hashes: each `.github/requirements/<job>.in` names a job's tools,
and `<job>.txt` pins them and everything they depend on, by version and hash. CI installs them with
`--require-hashes`, so a tampered package fails the install. Dependabot updates both files; to change
a tool by hand, edit its `.in` file and recompile the lock with pip-tools:

```sh
cd .github/requirements
pip-compile --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url --output-file=<job>.txt <job>.in
```
