import json
import unittest

from project_validator.checks.hardening import hardening
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.rust import RUST
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    PROJECT_LAYOUTS,
    UNSTRUCTURED_CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_RUST,
    ci_running,
    github_job,
    run_as,
    run_in_every_layout,
)

GCC_FLAGS = (
    "-D_FORTIFY_SOURCE=3 -D_GLIBCXX_ASSERTIONS -fstack-protector-strong -fcf-protection -fstack-clash-protection"
)
GCC_OPTIONS = (
    "_FORTIFY_SOURCE, -fstack-protector-strong, -fcf-protection, -fstack-clash-protection, "
    "_GLIBCXX_ASSERTIONS or _LIBCPP_HARDENING_MODE"
)
MSVC_OPTIONS = "/sdl, /guard:cf, /DYNAMICBASE, /CETCOMPAT"
HINT = f"enable -fhardened (GCC 14+) or {GCC_OPTIONS}; for MSVC {MSVC_OPTIONS}"
# Linux (GCC by default) and Windows (MSVC by default).
LINUX_AND_WINDOWS = {
    GITHUB_WORKFLOW: json.dumps(
        {
            "jobs": {
                "linux": {"runs-on": "ubuntu-latest", "steps": [{"run": "cmake --build build"}]},
                "windows": {"runs-on": "windows-latest", "steps": [{"run": "cmake --build build"}]},
            }
        }
    )
}
GCC_AND_CLANG = github_job("ubuntu-latest", "cmake --build build", matrix={"compiler": ["gcc", "clang"]})
LINUX = github_job("ubuntu-latest", "cmake --build build")


class HardeningTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        # Profiles and plugins add languages, so only the stable ones are pinned.
        self.assertLessEqual(C_FAMILY | {"Rust", "Go"}, hardening.languages)

    # Binary hardening is what the build inserts into a binary. Python builds none: its security lints are judged by
    # security-scanning, and its dependencies by dependency-audit.
    def test_does_not_judge_ecosystems_that_build_no_binary(self) -> None:
        self.assertNotIn("Python", hardening.languages)


class CAndCxxHardeningTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(self, hardening, files)

    def test_fails_when_no_hardening_options_are_found(self) -> None:
        self.assertEqual(
            self._run(BARE_PROJECT), Result.failed(f"no hardening options found; enable {GCC_OPTIONS}", HINT)
        )

    def test_failure_lists_the_options_of_each_compiler_ci_uses(self) -> None:
        self.assertEqual(
            self._run(LINUX_AND_WINDOWS),
            Result.failed(f"no hardening options found; enable {GCC_OPTIONS}, {MSVC_OPTIONS}", HINT),
        )

    def test_passes_with_the_well_configured_fixture(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.PASS)

    def test_passes_with_every_gcc_and_clang_option_on_the_command_line(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                result = self._run(ci_running(provider, f"cmake -S . -B build -DCMAKE_CXX_FLAGS='{GCC_FLAGS}'"))
                if provider in UNSTRUCTURED_CI_FILES:  # scanned heuristically, which keeps no quoted command
                    self.assertEqual(result.status, Status.ERROR)
                else:
                    self.assertEqual(result, Result.passed(f"hardening options are enabled: {GCC_OPTIONS}"))

    def test_options_in_cmake_presets_count(self) -> None:
        preset = f'{{"configurePresets": [{{"name": "ci", "cacheVariables": {{"CMAKE_CXX_FLAGS": "{GCC_FLAGS}"}}}}]}}\n'
        for name in ("CMakePresets.json", "CMakeUserPresets.json"):
            with self.subTest(name):
                self.assertEqual(self._run({name: preset}).status, Status.PASS)

    def test_cmake_template_style_passes(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": """\
                    list(APPEND NEW_CXX_DEFINITIONS -D_GLIBCXX_ASSERTIONS)
                    list(APPEND NEW_COMPILE_OPTIONS -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3)
                    check_cxx_compiler_flag(-fstack-protector-strong STACK_PROTECTOR)
                    if(STACK_PROTECTOR)
                      list(APPEND NEW_COMPILE_OPTIONS -fstack-protector-strong)
                    endif()
                    list(APPEND NEW_COMPILE_OPTIONS -fcf-protection -fstack-clash-protection)
                    add_compile_options(${NEW_COMPILE_OPTIONS})
                    add_compile_definitions(${NEW_CXX_DEFINITIONS})
                """,
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_options_that_are_never_applied_do_not_count(self) -> None:
        result = self._run({"cmake/Hardening.cmake": f"set(NEW_COMPILE_OPTIONS {GCC_FLAGS})\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_libcxx_hardening_mode_counts_as_library_assertions(self) -> None:
        for mode in ("FAST", "EXTENSIVE", "DEBUG"):
            with self.subTest(mode):
                flags = GCC_FLAGS.replace(
                    "-D_GLIBCXX_ASSERTIONS", f"-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_{mode}"
                )
                self.assertEqual(self._run({"CMakeLists.txt": f"add_compile_options({flags})\n"}).status, Status.PASS)

    def test_warns_and_lists_missing_options(self) -> None:
        self.assertEqual(
            self._run({"CMakeLists.txt": "add_compile_options(-fstack-protector-strong)\n"}),
            Result.warned(
                "missing hardening options: _FORTIFY_SOURCE, -fcf-protection, -fstack-clash-protection, "
                "_GLIBCXX_ASSERTIONS or _LIBCPP_HARDENING_MODE",
                "found -fstack-protector-strong",
            ),
        )

    def test_disabled_options_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": """\
                    add_compile_options(-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -fcf-protection=none)
                    add_compile_options(-fno-stack-protector -fno-stack-clash-protection -fno-hardened)
                    add_compile_definitions(_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_NONE)
                """,
            }
        )
        self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_options_do_not_count(self) -> None:
        self.assertEqual(self._run({"CMakeLists.txt": f"# add_compile_options({GCC_FLAGS})\n"}).status, Status.FAIL)

    def test_fhardened_enables_every_gcc_option(self) -> None:
        self.assertEqual(
            self._run({"CMakeLists.txt": "add_compile_options(-fhardened)\n"}),
            Result.passed(f"hardening options are enabled: {GCC_OPTIONS}"),
        )

    def test_fhardened_is_gcc_only(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-fhardened)\n", **GCC_AND_CLANG})
        self.assertEqual(
            result, Result.warned(f"missing hardening options: {GCC_OPTIONS} for clang", f"found {GCC_OPTIONS}")
        )

    def test_fhardened_for_gcc_and_explicit_options_for_clang_pass(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"""\
                    if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
                      add_compile_options(-fhardened)
                    else()
                      add_compile_options({GCC_FLAGS})
                    endif()
                """,
                **GCC_AND_CLANG,
            }
        )
        self.assertEqual(result, Result.passed(f"hardening options are enabled: {GCC_OPTIONS}"))

    def test_msvc_in_ci_requires_msvc_options(self) -> None:
        result = self._run({"CMakeLists.txt": f"add_compile_options({GCC_FLAGS})\n", **LINUX_AND_WINDOWS})
        self.assertEqual(
            result, Result.warned(f"missing hardening options: {MSVC_OPTIONS} for msvc", f"found {GCC_OPTIONS}")
        )

    def test_msvc_in_ci_passes_with_msvc_options(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"""\
                    if(MSVC)
                      add_compile_options(/sdl /guard:cf)
                      add_link_options(/dynamicbase /CETCOMPAT)
                    else()
                      add_compile_options({GCC_FLAGS})
                    endif()
                """,
                **LINUX_AND_WINDOWS,
            }
        )
        expected = f"hardening options are enabled: {GCC_OPTIONS} for gcc; {MSVC_OPTIONS} for msvc"
        self.assertEqual(result, Result.passed(expected))

    def test_disabled_msvc_options_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"add_compile_options({GCC_FLAGS})\n"
                "add_compile_options(/sdl- /guard:cf- /DYNAMICBASE:NO /CETCOMPAT:NO)\n",
                **LINUX_AND_WINDOWS,
            }
        )
        self.assertEqual(
            result, Result.warned(f"missing hardening options: {MSVC_OPTIONS} for msvc", f"found {GCC_OPTIONS}")
        )

    def test_msvc_options_are_not_required_without_msvc_in_ci(self) -> None:
        result = self._run({"CMakeLists.txt": f"add_compile_options({GCC_FLAGS})\n", **LINUX})
        self.assertEqual(result.status, Status.PASS)

    def test_options_of_a_compiler_ci_does_not_use_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(/sdl /guard:cf)\n"})
        self.assertEqual(result.status, Status.FAIL)


class RustHardeningTests(unittest.TestCase):
    OVERFLOW_CHECKS = "[profile.release]\noverflow-checks = true\n"
    PASSED = Result.passed("hardening options are enabled: release overflow-checks")

    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, hardening, files, RUST)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        self.assertEqual(self._run(dict(WELL_CONFIGURED_RUST)), self.PASSED)

    def test_fails_without_hardening(self) -> None:
        files = {
            "Cargo.toml": "[profile.dev]\noverflow-checks = true\n",
            **github_job("ubuntu-latest", "cargo build -C overflow-checks=off"),
        }
        expected = Result.failed(
            "no hardening options found; enable release overflow-checks",
            "set overflow-checks = true in [profile.release] of Cargo.toml",
        )
        self.assertEqual(self._run(files), expected)

    def test_release_overflow_checks_in_any_spelling_count(self) -> None:
        spellings = {
            "release profile": {"Cargo.toml": self.OVERFLOW_CHECKS},
            "rustflags": {".cargo/config.toml": '[build]\nrustflags = ["-C", "overflow-checks"]\n'},
            "command line": github_job("ubuntu-latest", "cargo rustc --release -- -Coverflow-checks=on"),
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                self.assertEqual(self._run(files), self.PASSED)

    def test_overflow_checks_outside_the_release_profile_do_not_count(self) -> None:
        result = self._run({"Cargo.toml": "[profile.dev]\noverflow-checks = true\n"})
        self.assertEqual(result.status, Status.FAIL)

    # Forbidding unsafe code is a lint, judged by security-scanning, not something the build adds to the binary.
    def test_forbidding_unsafe_code_is_not_hardening(self) -> None:
        self.assertEqual(self._run({"src/lib.rs": "#![forbid(unsafe_code)]\n"}).status, Status.FAIL)

    def test_c_and_cxx_options_do_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)


class MixedLanguageHardeningTests(unittest.TestCase):
    def test_only_the_languages_that_build_binaries_are_judged(self) -> None:
        [layout] = [layout for layout in PROJECT_LAYOUTS if layout.languages == C_FAMILY | {"Python"}]
        result = run_in_every_layout(self, hardening, dict(WELL_CONFIGURED), (layout,))
        self.assertEqual(result.status, Status.PASS)
        self.assertTrue(result.message.startswith("hardening options are enabled: _FORTIFY_SOURCE"))
