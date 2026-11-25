# C++

Recognised by `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx`, `.ixx` and `.cppm` sources, and by CMake
(`CMakeLists.txt`), Meson (`meson.build`) or Bazel. A project is judged by the rules of the build system it uses; one
using none is judged as a CMake project. The CMake code itself is judged as [CMake](cmake.md), a format: it is
formatted and linted.

With Bazel (`MODULE.bazel`, `WORKSPACE` or `BUILD.bazel`), the tests are the test rules its BUILD files define
(`cc_test`), which `bazel test` or `bazel coverage` runs; a command's `--compilation_mode` is its build type (`dbg`
Debug, `opt` Release); and a bazel command runs with the options its `.bazelrc` gives it (those of `common` and the
commands it inherits, of each `--config` it names, and, with `--enable_platform_specific_config`, of the config for
its host's OS), so `--copt=-Werror` there counts as the command's own.

C++ and [C](c.md) are separate languages, judged separately: a project with sources in both is judged once for each,
each by its own flags (`CMAKE_CXX_FLAGS` and `$<COMPILE_LANGUAGE:CXX>` for C++; flags for every language count for
both). A `.h` or `.inc` header is the language of most sources below its nearest directory that has any, so headers
beside C++ sources are C++. CMake's `project()` enables C and C++ unless told otherwise, which says nothing about the
code: once there are C++ sources, a CMake file does not make the project a C one too.

## `tests-run`

With CMake: `enable_testing()` or `include(CTest)` is called, tests are registered (`add_test`, `*_discover_tests`,
...) and CI runs `ctest` (or `cmake --build … --target test`, or `cmake --workflow`); with `--build`, the project is
really configured and built, and `ctest` must list at least one test (a build that cannot run is unknown). With Meson:
`test()` is called in a `meson.build` and CI runs `meson test` (or ninja's `test` target).

## `fuzz-testing`

libFuzzer targets (files defining `LLVMFuzzerTestOneInput`) and AFL++ targets (`__AFL_LOOP`), run by a CI step that
passes a libFuzzer option to a binary (`./fuzz_tester -max_total_time=30`, a heuristic), by `afl-fuzz` (whose target, the words
after `--`, is not a `dotnet` program or a `.dll`), or by `ctest` when a CMake `add_test` passes a libFuzzer option to
its command (a test that only replays crash files does not count). The `ctest` command's `-R`/`-L` and `-E`/`-LE`
regexes are matched against the test's name. This is a heuristic: a fuzz test registered behind an option CI does not
turn on (`if(ENABLE_FUZZING)`) is still counted, and the run is credited to the CMake files' unit. RapidCheck tests alone warn: they are property-based tests, not
fuzz targets.

## `coverage`

A coverage tool CI runs, reporting branches: gcovr with any report but the default text one (`--xml`, `--html`,
`--json`, `--sonarqube`, `--print-summary`, `--txt-metric branch`, also in `gcovr.cfg`), lcov or genhtml with
`branch_coverage=1` (also in `.lcovrc`), `gcov -b`, or `llvm-cov report`, `export` or `show -show-branches`.
OpenCppCoverage (`--export_type cobertura:… -- ctest`, on Windows) reports lines only, and the tests it runs after
`--` count as run. Path or
MC/DC coverage is a bonus: gcov `--conditions` or `--prime-paths`, lcov `--mcdc-coverage`, `llvm-cov show -show-mcdc`,
or the instrumentation `-fcondition-coverage`, `-fpath-coverage` or `-fcoverage-mcdc` on a command line, in an
environment variable, or in the CMake files a CI `cmake` configuration reads (matched in their text).

## `platform-matrix`

The toolchains are compilers. A CI job that names no compiler counts with its runner's default compiler (gcc on Linux,
AppleClang on macOS, MSVC on Windows), unless it only runs another ecosystem's tools.

## `ci-build-types`

Every OS/compiler combination builds Debug and Release, each with and without sanitizers.

## `sanitizers`

AddressSanitizer and UndefinedBehaviorSanitizer are used in some configuration, whatever the compiler:
`-fsanitize=address,undefined` (MSVC's `/fsanitize=address`) among the build files' options or on a CI command line,
cmake_template's `ENABLE_SANITIZER_ADDRESS` and `ENABLE_SANITIZER_UNDEFINED_BEHAVIOR` options (with or without the
project's prefix) on by default or turned on by CI, Meson's `b_sanitize`, or a job in an R image built with them
(`rocker/r-devel-san` or a project's own `r-devel-<compiler>-san`: both; `rocker/r-devel-ubsan-clang`: UBSan). One of the two warns; neither fails.
ThreadSanitizer and MemorySanitizer are not asked, since they exclude the other two in one build.

## `compiler-warnings`

`-Wall -Wextra -Wpedantic -Wshadow -Wconversion`, plus `/W4` and `/permissive-` when MSVC is in CI.

## `warnings-as-errors`

`-Werror`, `/WX` or `COMPILE_WARNING_AS_ERROR` (Meson: `werror=true`) is enabled in at least one configuration.

## `compiler-extensions`

`CMAKE_CXX_EXTENSIONS` is turned off, or with Meson `cpp_std` names a standard such as `c++20` rather than `gnu++20`,
so `-std=c++NN` is used rather than `-std=gnu++NN`. The check was called `compiler-extensions`, which still selects it.

## `out-of-source-build`

In-source builds are prevented: a CMake file compares `CMAKE_SOURCE_DIR` (or `PROJECT_SOURCE_DIR`) with the binary
directory and stops with `message(FATAL_ERROR)` when they are equal, as cmake_template's `PreventInSourceBuilds.cmake`
does, or sets `CMAKE_DISABLE_IN_SOURCE_BUILD` or `CMAKE_DISABLE_SOURCE_CHANGES`. Meson refuses in-source builds itself,
so a Meson project passes. Warns otherwise.

## `compile-commands`

`compile_commands.json` is exported, so clang-tidy, clangd and IDEs can read the build: `CMAKE_EXPORT_COMPILE_COMMANDS`
on in the CMake files, in a preset or on the command line (`-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`). Meson always writes
it, so a Meson project passes. Warns otherwise.

## `top-level-guard`

Tests and developer-only settings are conditioned on the project being built on its own, so that it works as a
subproject through FetchContent, CPM or `add_subdirectory`: an `if()` on `PROJECT_IS_TOP_LEVEL` (or
`<project>_IS_TOP_LEVEL`, or the older `CMAKE_SOURCE_DIR STREQUAL PROJECT_SOURCE_DIR`), a `cmake_dependent_option`
depending on it, or with Meson an `if` on `meson.is_subproject()`. The validator sees what the project guards on, not
yet what it guards. Warns otherwise.

## `hardening`

`_FORTIFY_SOURCE`, `-fstack-protector-strong`, `-fcf-protection`, `-fstack-clash-protection` and
`_GLIBCXX_ASSERTIONS` or `_LIBCPP_HARDENING_MODE` (or GCC's `-fhardened`), plus `/sdl /guard:cf /DYNAMICBASE
/CETCOMPAT` when MSVC is in CI. Warns listing what is missing.

## `mutation-testing`

Mull (`mull-runner` or `mull-cxx`, settings in `mull.yml`; a build with its compiler plugin only embeds the mutants,
so it is not a run) or dextool (`dextool mutate`, settings in `.dextool_mutate.toml`). No changes-only mode is
recognised for either.

## `code-formatting`

The style is defined in a `.clang-format` (or `_clang-format`), at or above the code, and CI checks it:
`clang-format --dry-run -Werror` (or `-n --Werror`, also through `xargs`), `git clang-format --diff`, run-clang-format,
the `DoozyX/clang-format-lint-action` or `jidicula/clang-format-action` action, or the clang-format pre-commit hook
when CI runs pre-commit. `clang-format -i` enforces it only where the job then fails on a change
(`git diff --exit-code`) or commits it.

Artistic Style (with its `.astylerc`; it only rewrites, so the job must fail on the change) and uncrustify (with its
`uncrustify.cfg`; `--check` fails on an unformatted file) count where a project uses them, but only clang-format is
suggested.

## `security-scanning`

No security lints of its own here: CodeQL, GitLab SAST or semgrep in CI.

## `function-limits`

lizard runs in CI with a length limit (`-L`, `--length`, `-T length=` or `-T nloc=`), or clang-tidy runs (directly,
or through `CMAKE_CXX_CLANG_TIDY`) with a `.clang-tidy` that enables `readability-function-size` with a positive
`LineThreshold` or `StatementThreshold`. A `.clang-tidy` that sets the limit while nothing runs clang-tidy warns; one
that cannot be read makes the answer unknown.

## `static-analysis`

clang-tidy or cppcheck: run directly (`clang-tidy`, `run-clang-tidy`, `cppcheck`), through the
`cpp-linter/cpp-linter-action`, `ZedThree/clang-tidy-review` or `deep5050/cppcheck-action` actions, or by a build CI
configures with `CMAKE_CXX_CLANG_TIDY` / `CMAKE_CXX_CPPCHECK` (on the `cmake` command line, or in the CMake files,
target properties or presets), or a custom target CI builds (`cmake --build build --target lint`) that runs either.
clang-tidy needs its checks chosen in a `.clang-tidy`. The Clang Static Analyzer counts when CI runs the build under
`scan-build --status-bugs`, which fails on any finding; plain `scan-build` only reports.

## `dependency-management`

CPM, FetchContent, vcpkg (`vcpkg.json`), Conan (`conanfile.txt` / `conanfile.py`) or Meson wraps
(`subprojects/*.wrap`).

## `committed-artifacts`

Object files and libraries (`*.o`, `*.obj`, `*.a`, `*.lib`, `*.so`, `*.dylib`, `*.dll`), `*.exe`, `*.pdb`,
`CMakeCache.txt`, `CMakeFiles/`, `CMakeUserPresets.json`, and a top-level `build/`, `out/` or `builddir/`.

## `vcs-ignore`

`build/` or `out/`.
