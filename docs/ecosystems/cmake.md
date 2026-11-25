# CMake

A format: the project's CMake code (`CMakeLists.txt`, `*.cmake`), judged beside the language it builds. CMake as the
build system of C and C++ (its flags, targets, presets and build types) is read for those profiles; what is asked of
the CMake code itself is hygiene. A CI job works with it when it runs `cmake`, `ctest`, gersemi, cmake-format,
cmake-lint or cmakelint.

## `code-formatting`

gersemi (`--check` or `--diff`, which fail on a file it would change; `-i` rewrites, which enforces the style with a
later `git diff --exit-code`), with its style in `.gersemirc`; or cmake-format (`--check`; `-i` rewrites), with its
style in `.cmake-format.yaml` (or `.cmake-format`, `.json`, `.py`). Their pre-commit hooks count where CI runs them.

## `static-analysis`

cmake-lint (cmakelang, configured as cmake-format is) or cmakelint (`.cmakelintrc`).

## Not judged

CMake code is not a program of its own: tests, coverage and the compiled-language checks belong to the language it
builds. The other checks have no tool for CMake and are skipped.
