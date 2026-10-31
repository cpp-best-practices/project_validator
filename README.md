# project_validator
A tool to validate CMake based projects against Best Practices

## Requirements

- Python 3.14+ (the system Python on Ubuntu 26.04 LTS; no installation step,
  run with `python3 -m project_validator <path>`)
- CMake / CTest (already required by any project being validated)

On a machine without Python 3.14, `uv run` or a distro backport will work.
In CI, use `actions/setup-python` with `python-version: "3.14"`.

## Usage

```sh
python3 -m project_validator path/to/project
python3 -m project_validator --list
python3 -m project_validator --only coverage,platform-matrix --format json path/to/project
```

| Option | Meaning |
|---|---|
| `--list` | list the available checks |
| `--only CHECKS` / `--skip CHECKS` | comma separated check names to run / not run |
| `--format text\|json` | output format |
| `--build` | configure and build the project in a temporary directory and ask `ctest` for its tests |
| `--strict` | treat warnings as failures |
| `--no-yaml` | ignore PyYAML even if it is installed |
| `--cmake PATH` / `--ctest PATH` | the executables used by `--build` |
| `--plugin-dir DIR` | load extra checks and CI providers from `DIR/*.py` |

Exit codes: `0` everything passed, `1` a check failed or raised an error, `2` usage error.

## Checks

| Check | Passes when |
|---|---|
| `ci-present` | at least one CI configuration is found |
| `ctest-runs` | `enable_testing()` or `include(CTest)` is called and tests are registered (`add_test`, `*_discover_tests`, ...); warns if no CI configuration runs `ctest`. With `--build`, the project is really configured and built, and `ctest` must list at least one test |
| `coverage` | branch coverage is reported (e.g. `gcovr --fail-under-branch`, `lcov --rc branch_coverage=1`, `llvm-cov -show-branches`); path coverage (`-fcondition-coverage`, `-fcoverage-mcdc`, `-fpath-coverage`, ...) is reported as a bonus |
| `platform-matrix` | CI covers at least 2 operating systems, 2 compilers and 3 OS/compiler combinations |

CI detection is pluggable too. GitHub Actions workflows (including `strategy.matrix`
with `include`/`exclude`) and GitLab CI pipelines (including `parallel: matrix:`)
are parsed when PyYAML is available. Azure Pipelines, AppVeyor, CircleCI, Travis CI,
Jenkins, Buildkite, Drone, Cirrus CI, Bitbucket Pipelines and Woodpecker are detected
and scanned heuristically. A job that names no compiler is counted with its runner's
default compiler (gcc on Linux, AppleClang on macOS, MSVC on Windows).

Known limitations:

- GitLab `extends:` is not resolved.
- A GitHub matrix computed by an expression (`fromJSON(...)`) cannot be expanded; those jobs are reported with an `unknown` OS.
- Evidence is found by scanning text, so all CMake files under the project (including test fixtures) are considered.

## Writing a Plugin

Any module-level `Check` or `CiProvider` in a file passed with `--plugin-dir` is picked up:

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

## Development

```sh
python3 -m unittest
cmake -S . -B build && ctest --test-dir build --output-on-failure
```

The CTest suite runs the unit tests and validates this repository with its own tool.

## Dependency Policy

The validator is meant to run anywhere a CMake project can be built,
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
| [PyYAML](https://pyyaml.org/) `>=6.0` | optional (`yaml` extra) | The standard library has no YAML parser, and CI configuration is YAML. PyYAML is mature, MIT licensed, has no dependencies, and is packaged by every major distro (`python3-yaml` on Ubuntu). Without it, CI files are scanned heuristically and `platform-matrix` reports `reduced accuracy: PyYAML is not available`; nothing fails because it is missing. |

There are no required dependencies.
