# C/C++

Recognised by `.c`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.ixx`, `.cppm` and similar sources, and by CMake (`CMakeLists.txt`)
or Meson (`meson.build`). A project is judged by the rules of the build system it uses; one using neither is judged as
a CMake project.

## `tests-run`

With CMake: `enable_testing()` or `include(CTest)` is called, tests are registered (`add_test`, `*_discover_tests`,
...) and CI runs `ctest`; with `--build`, the project is really configured and built, and `ctest` must list at least
one test. With Meson: `test()` is called in a `meson.build` and CI runs `meson test`.

## `coverage`

gcovr, lcov, genhtml, gcov or llvm-cov branch options, in CI or CMake files. Path or MC/DC coverage
(`-fcondition-coverage`, `-fpath-coverage`, gcov `--prime-paths`, `-fcoverage-mcdc`) is a bonus.

## `platform-matrix`

The toolchains are compilers. A CI job that names no compiler counts with its runner's default compiler (gcc on Linux,
AppleClang on macOS, MSVC on Windows), unless it only runs another ecosystem's tools.

## `ci-build-types`

Every OS/compiler combination builds Debug and Release, each with and without sanitizers.

## `compiler-warnings`

`-Wall -Wextra -Wpedantic -Wshadow -Wconversion`, plus `/W4` and `/permissive-` when MSVC is in CI.

## `warnings-as-errors`

`-Werror`, `/WX` or `COMPILE_WARNING_AS_ERROR` (Meson: `werror=true`) is enabled in at least one configuration.

## `cxx-extensions`

`CMAKE_CXX_EXTENSIONS` (or `CMAKE_C_EXTENSIONS` for C) is turned off, or with Meson `cpp_std` (`c_std`) names a
standard such as `c++20` rather than `gnu++20`, so `-std=c++NN` is used rather than `-std=gnu++NN`.

## `hardening`

`_FORTIFY_SOURCE`, `-fstack-protector-strong`, `-fcf-protection`, `-fstack-clash-protection` and
`_GLIBCXX_ASSERTIONS` or `_LIBCPP_HARDENING_MODE` (or GCC's `-fhardened`), plus `/sdl /guard:cf /DYNAMICBASE
/CETCOMPAT` when MSVC is in CI. Warns listing what is missing.

## `code-formatting`

The style is defined in a `.clang-format` and CI runs clang-format.

## `function-limits`

lizard runs with a length limit, or `.clang-tidy` enables `readability-function-size` with a threshold and clang-tidy
runs.

## `static-analysis`

Both clang-tidy (`CMAKE_CXX_CLANG_TIDY`, `run-clang-tidy`, or `clang-tidy` in CI) with its checks chosen in a
`.clang-tidy`, and cppcheck (`CMAKE_CXX_CPPCHECK` or `cppcheck` in CI).

## `dependency-management`

CPM, FetchContent, vcpkg (`vcpkg.json`), Conan (`conanfile.txt` / `conanfile.py`) or Meson wraps
(`subprojects/*.wrap`).

## `committed-artifacts`

Object files and libraries (`*.o`, `*.obj`, `*.a`, `*.lib`, `*.so`, `*.dylib`, `*.dll`), `*.exe`, `*.pdb`,
`CMakeCache.txt`, `CMakeFiles/`, `CMakeUserPresets.json`, and a top-level `build/`, `out/` or `builddir/`.

## `vcs-ignore`

`build/` or `out/`.
