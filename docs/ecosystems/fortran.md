# Fortran

Recognised by Fortran sources: fixed form (`.f`, `.for`, `.ftn`, `.f77`), free form (`.f90`, `.f95`, `.f03`, `.f08`,
`.f18`), preprocessed (`.F`, `.F90` and the like, `.fpp`, fypp templates `.fypp`); pFUnit's `.pf` files once the
project is known to be Fortran. Built with fpm (`fpm.toml`), CMake (a `project()` or `enable_language()` that enables
Fortran) or Meson (a `project()` that declares `'fortran'`).

The profile only adds what is Fortran's own. Everything else is shared with C and C++: CMake's and Meson's
facts, which already say which options apply to which languages and compilers (`add_compile_options` applies to
Fortran, `$<$<COMPILE_LANGUAGE:CXX>:…>` and `CMAKE_CXX_FLAGS` do not), ctest and `meson test`, gcov and the reports
built on it, and lizard.

## `tests-run`

ctest, `meson test`, or `fpm test`. fpm's tests are the Fortran test programs (and modules) in `test/` or `tests/`,
and pFUnit tests.

## `coverage`

gcov, gcovr and lcov, which cover what GCC compiles, Fortran included.

## `platform-matrix`

The toolchains are compilers: gfortran (GCC), Intel's ifx and ifort, and LLVM's flang. A job counts for Fortran when
it is seen building Fortran (gfortran, ifx, fpm, `fortran-lang/setup-fortran`) or with the build tools Fortran shares
with C and C++. `fortran-lang/setup-fortran`'s `compiler: intel` names Intel's compilers.

## `ci-build-types`

fpm builds its `--profile` (debug by default).

## `compiler-warnings`

For each compiler CI builds with: gfortran and flang take GCC-style flags, `-Wall -Wextra -Wpedantic
-Wimplicit-interface` for gfortran (`-Wall` includes `-Wconversion`) and `-pedantic` for flang; ifx and ifort take
`-warn all`. The flags count on a CI command line, in the CMake or Meson files for Fortran builds with that compiler,
or from fpm's own debug profile (`-Wall -Wextra -Wimplicit-interface`), which an fpm command builds with unless it
gives its own `--flag` (or `FPM_FFLAGS`) without a `--profile`.

## `warnings-as-errors`

`-Werror` (gfortran, flang) or `-warn errors` (ifx, ifort), on a command line, in the build files, or through
CMake's `COMPILE_WARNING_AS_ERROR` and Meson's `werror`.

## `hardening`

The stack and control-flow protections GCC's back end adds: `-fstack-protector-strong`, `-fcf-protection` and
`-fstack-clash-protection` (or GCC 14's `-fhardened`); ifx takes the first two. `_FORTIFY_SOURCE` and the C++ library
assertions are C's and C++'s. A project with no Fortran `program` outside its tests is a library, and skipped.

## `cxx-extensions`

Fortran compiled to a standard rather than the compiler's dialect: `-std=f2018` (or another standard, gfortran and
flang), `-stand f18` (ifx, ifort), or Meson's `fortran_std`.

## `code-formatting`

fprettify checking (`--diff` or `--stdout`); a `.fprettify.rc` holds its style.

## `static-analysis`

fortitude (`fortitude check`), whose default rules are worth running.

## `function-limits`

lizard, which measures Fortran.

## `dependency-management`

fpm's `[dependencies]` (and `[dev-dependencies]`) in `fpm.toml`; CMake's CPM and FetchContent and Meson's wraps,
which are the build systems' own. None has a lockfile: an fpm dependency is pinned by its `tag` or `rev`.

## `dependency-audit`

Skipped: no vulnerability database covers fpm's dependencies, which are git repositories.

## `security-scanning`

Skipped: no code security scanner the validator knows of analyses Fortran (CodeQL, GitLab SAST and semgrep do not).

## `committed-artifacts`

Object files, libraries, executables, compiled module files (`*.mod`, `*.smod`) and a top-level `build/`.

## `vcs-ignore`

`build/` (where fpm and CMake build), and `*.mod` or `*.smod`.
