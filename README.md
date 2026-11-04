# project_validator

[![ci](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml/badge.svg)](https://github.com/cpp-best-practices/project_validator/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/cpp-best-practices/project_validator/graph/badge.svg)](https://codecov.io/gh/cpp-best-practices/project_validator)

A tool to validate a project's build, CI and tooling against best practices.

It recognises C and C++ (CMake or Meson), Python (`pyproject.toml` or `setup.py`),
Rust (Cargo) and Go (Go modules) projects, and judges each language by its own ecosystem's tools: a C++
project needs branch coverage from gcovr or llvm-cov, a Python project from coverage.py,
a Rust project from cargo-llvm-cov. Checks that do not apply to any of the project's
languages are reported as `SKIP`. A project using several languages is judged for each
of them and gets the worst result. In a project of no recognised language, only the
checks that apply to every project run. A C/C++ project is judged by the rules of the
build system it uses (CMake or Meson); one using neither is judged as a CMake project.
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
| `--cmake PATH` / `--ctest PATH` | the executables used by `--build` |
| `--plugin-dir DIR` | load extra checks and CI providers from `DIR/*.py` |

Exit codes: `0` everything passed, `1` a check failed or raised an error, `2` usage error.

## Checks

| Check | Applies to | Passes when |
|---|---|---|
| `ci-present` | all | at least one CI configuration is found |
| `tests-run` | C/C++, Python, Rust, Go | tests exist and CI runs them (`ctest-runs` is accepted as an old name). C/C++ with CMake: `enable_testing()` or `include(CTest)` is called, tests are registered (`add_test`, `*_discover_tests`, ...) and CI runs `ctest`; with `--build`, the project is really configured and built, and `ctest` must list at least one test. C/C++ with Meson: `test()` is called in a `meson.build` and CI runs `meson test`. Python: `test_*.py` / `*_test.py` files run by pytest, unittest, tox or nox. Rust: `#[test]` functions run by `cargo test` or nextest. Go: `Test` functions in `*_test.go` files run by `go test`. Warns when CI never runs the tests |
| `coverage` | C/C++, Python, Rust, Go | CI reports branch coverage (Go's tools measure statements only, so Go needs statement coverage: `go test -cover` or `-coverprofile`). C/C++: gcovr, lcov, genhtml, gcov or llvm-cov branch options; Python: `coverage run --branch`, `--cov-branch` or `branch = true`; Rust: cargo-llvm-cov, cargo-tarpaulin or grcov with `--branch`. Path or MC/DC coverage (`-fcondition-coverage`, `-fcoverage-mcdc`, `--mcdc`, ...) is reported as a bonus |
| `platform-matrix` | C/C++, Python, Rust, Go | CI covers at least 2 operating systems, 2 toolchains (compilers, Python versions, Rust toolchains or Go versions) and 3 OS/toolchain combinations |
| `ci-build-types` | C/C++, Rust | every OS/toolchain combination in CI builds Debug and Release (Rust: debug and release profiles), each with and without sanitizers |
| `compiler-warnings` | C/C++, Python, Rust, Go | a strict warning set is enabled. C/C++: `-Wall -Wextra -Wpedantic -Wshadow -Wconversion`, plus `/W4` and `/permissive-` when MSVC is in CI; Python: warnings are errors (`-W error`, `PYTHONWARNINGS=error`, pytest `filterwarnings = error`); Rust: `cargo clippy`, `-D warnings` and `clippy::pedantic`; Go: `go vet` and staticcheck (golangci-lint runs both). Warns listing what is missing |
| `warnings-as-errors` | C/C++ | `-Werror`, `/WX` or `COMPILE_WARNING_AS_ERROR` (Meson: `werror=true`) is enabled in at least one configuration |
| `cxx-extensions` | C/C++ | `CMAKE_CXX_EXTENSIONS` (or `CMAKE_C_EXTENSIONS` for C) is turned off, or with Meson `cpp_std` (`c_std`) names a standard such as `c++20` rather than `gnu++20`, so `-std=c++NN` is used rather than `-std=gnu++NN` |
| `hardening` | C/C++, Rust, Go | binary hardening is enabled: exploit mitigations that the build inserts into the binary (static analysis and dependency audits are judged by `security-scanning` and `dependency-audit`). C/C++: `_FORTIFY_SOURCE`, `-fstack-protector-strong`, `-fcf-protection`, `-fstack-clash-protection` and `_GLIBCXX_ASSERTIONS` or `_LIBCPP_HARDENING_MODE` (or GCC's `-fhardened`), plus `/sdl /guard:cf /DYNAMICBASE /CETCOMPAT` when MSVC is in CI; Rust: `overflow-checks` in release builds; Go: programs are built as position-independent executables (`-buildmode=pie`, not the default on Linux), and a module with no `package main` is skipped. Python builds no binary, so it is not judged. Warns listing what is missing |
| `code-formatting` | C/C++, Python, Rust, Go | the formatting style is defined (`.clang-format`; ruff or black settings; `rustfmt.toml`) and CI runs the formatter. Python, Rust and Go (gofmt, gofumpt, goimports) formatters have a default style, so CI enforcement alone passes. Warns when the style is defined but CI does not enforce it |
| `function-limits` | C/C++, Python, Rust, Go | function length is limited: lizard runs with a length limit (`lizard --length 30`), or for C/C++, `.clang-tidy` enables `readability-function-size` with a threshold and clang-tidy runs, or for Go, golangci-lint runs with `funlen` enabled |
| `copy-paste-detection` | all | CI runs a duplicate code detector (PMD CPD, jscpd, Duplo, Simian, CCFinderX or SonarQube); warns otherwise |
| `security-scanning` | all | CI runs code security scanning (CodeQL or GitLab SAST), or every language in the project that has security lints enables them: Python: bandit (or ruff's `S` rules); Rust: `unsafe_code` forbidden crate-wide; Go: gosec. Warns otherwise, naming the languages left unscanned |
| `dependency-audit` | Python, Rust, Go | CI checks the dependencies against known vulnerabilities. Python: pip-audit or safety; Rust: cargo audit or `cargo deny check` (advisories); Go: govulncheck. osv-scanner, `trivy fs` and `snyk test` count for every language. Warns otherwise |
| `dependency-updates` | all | Dependabot or Renovate is configured; warns otherwise |
| `vcs-ignore` | C/C++, Python, Rust, Go | a `.gitignore`, `.hgignore`, `.bzrignore` or `.fossil-settings/ignore-glob` ignores the build outputs (`build/` or `out/`, `__pycache__/` or `*.py[cod]`, `/target`, Go's `*.test` or `*.out`). Warns when an ignore file misses them |

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
