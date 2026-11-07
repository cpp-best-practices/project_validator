import json
import unittest

from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.core import Result, Status
from project_validator.ecosystems import C_FAMILY
from project_validator.ecosystems.c_cpp import C_AND_CXX
from project_validator.ecosystems.python import PYTHON
from project_validator.ecosystems.rust import RUST
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    WELL_CONFIGURED,
    WELL_CONFIGURED_RUST,
    c_family_layouts_built_with,
    ci_running,
    github_job,
    run_as,
    run_in_every_layout,
)


class CompilerWarningsTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        # Profiles and plugins add languages, so only the stable ones are pinned.
        self.assertLessEqual(C_FAMILY | {"Python", "Rust"}, compiler_warnings.languages)

    GCC_FLAGS = "-Wall -Wextra -Wpedantic -Wshadow -Wconversion"
    # Linux (GCC by default) and Windows (MSVC by default).
    MSVC_CI = json.dumps(
        {
            "jobs": {
                "linux": {"runs-on": "ubuntu-latest", "steps": [{"run": "cmake -S . -B build"}]},
                "windows": {"runs-on": "windows-latest", "steps": [{"run": "cmake -S . -B build"}]},
            }
        }
    )

    # Meson passes -Wall unless told otherwise (its warning_level is 1), so Meson projects are judged on their own.
    def _run(self, files: dict[str, str]) -> Result:
        return run_in_every_layout(
            self, compiler_warnings, files, c_family_layouts_built_with(compiler_warnings, "CMake")
        )

    def test_fails_when_no_warning_flags_are_found(self) -> None:
        result = self._run(BARE_PROJECT)
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("-Wall", result.message)

    def test_passes_with_the_well_configured_fixture(self) -> None:
        result = self._run(WELL_CONFIGURED)
        self.assertEqual(result.status, Status.PASS, result)

    def test_passes_with_the_minimum_gcc_and_clang_flags(self) -> None:
        result = self._run({"CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS})\n"})
        self.assertEqual(result.status, Status.PASS)
        self.assertIn("-Wconversion", result.message)

    def test_cmake_template_style_lists_count(self) -> None:
        result = self._run(
            {
                "cmake/CompilerWarnings.cmake": """\
                    set(CLANG_WARNINGS
                        -Wall
                        -Wextra # reasonable and standard
                        -Wshadow
                        -Wconversion
                        -pedantic)
                    target_compile_options(${project_name} INTERFACE ${CLANG_WARNINGS})
                """,
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_warns_and_lists_missing_flags(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-Wall -Wextra)\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("-Wpedantic", result.message)
        self.assertIn("-Wshadow", result.message)
        self.assertIn("-Wconversion", result.message)
        self.assertNotIn("-Wall,", result.message)

    def test_similar_flags_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(-Wshadow=local -Wno-conversion -Wall-extra)\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_commented_out_flags_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": f"# add_compile_options({self.GCC_FLAGS})\n"})
        self.assertEqual(result.status, Status.FAIL)

    def test_msvc_in_ci_requires_msvc_flags(self) -> None:
        result = self._run(
            {"CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS})\n", ".github/workflows/ci.yml": self.MSVC_CI}
        )
        self.assertEqual(
            result,
            Result.warned("missing compiler warning flags: /W4, /permissive- for msvc", f"found {self.GCC_FLAGS}"),
        )

    def test_msvc_in_ci_passes_with_msvc_flags(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"""\
                    if(MSVC)
                      add_compile_options(/Wall /permissive-)
                    else()
                      add_compile_options({self.GCC_FLAGS})
                    endif()
                """,
                ".github/workflows/ci.yml": self.MSVC_CI,
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_lowercase_msvc_flags_do_not_count(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS} /w4 /permissive-)\n",
                ".github/workflows/ci.yml": self.MSVC_CI,
            }
        )
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("/W4", result.message)

    def test_msvc_flags_are_not_required_without_msvc_in_ci(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": f"add_compile_options({self.GCC_FLAGS})\n",
                **github_job("ubuntu-latest", "make"),
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_flags_of_a_compiler_ci_does_not_use_do_not_count(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(/W4 /permissive-)\n"})
        self.assertEqual(result.status, Status.FAIL)
        self.assertIn("-Wall", result.message)

    def test_each_compiler_ci_uses_is_judged_by_the_flags_set_for_it(self) -> None:
        result = self._run(
            {
                "CMakeLists.txt": (
                    f"if(CMAKE_CXX_COMPILER_ID STREQUAL GNU)\n  add_compile_options({self.GCC_FLAGS})\nendif()\n"
                ),
                **github_job("ubuntu-latest", "CXX=clang++ cmake -S . -B build", matrix={"compiler": ["gcc", "clang"]}),
            }
        )
        self.assertEqual(
            result,
            Result.warned(
                "missing compiler warning flags: -Wall, -Wextra, -Wpedantic, -Wshadow, -Wconversion for clang",
                f"found {self.GCC_FLAGS}",
            ),
        )

    def test_meson_passes_wall_unless_told_otherwise(self) -> None:
        layouts = c_family_layouts_built_with(compiler_warnings, "Meson")
        result = run_in_every_layout(self, compiler_warnings, {}, layouts)
        self.assertEqual(result.status, Status.WARN)
        self.assertEqual(result.details, ("found -Wall",))

    def test_meson_warning_levels_pass_their_flags(self) -> None:
        build = (
            "project('app', 'cpp', default_options: ['warning_level=3'])\n"
            "add_project_arguments('-Wshadow', '-Wconversion', language: 'cpp')\n"
        )
        layouts = c_family_layouts_built_with(compiler_warnings, "Meson")
        result = run_in_every_layout(self, compiler_warnings, {"meson.build": build}, layouts)
        self.assertEqual(result, Result.passed(f"strict compiler warning flags are enabled: {self.GCC_FLAGS}"))


class PythonCompilerWarningsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, compiler_warnings, files, PYTHON)

    def test_warnings_as_errors_in_any_spelling_passes(self) -> None:
        spellings = {
            "python -W error": github_job("ubuntu-latest", "python3.14 -X dev -W error -m unittest"),
            "pytest -W error": github_job("ubuntu-latest", "pytest -q -W error"),
            "PYTHONWARNINGS": github_job("ubuntu-latest", "PYTHONWARNINGS=error python -m pytest"),
            "pyproject filterwarnings": {"pyproject.toml": "[tool.pytest.ini_options]\nfilterwarnings = ['error']\n"},
            "pytest.ini filterwarnings": {"pytest.ini": "[pytest]\nfilterwarnings =\n    error\n"},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                expected = Result.passed("strict Python warning settings are enabled: -W error")
                self.assertEqual(self._run(files), expected)

    def test_warnings_as_errors_in_any_ci_passes(self) -> None:
        for provider in CI_FILES:
            with self.subTest(ci=provider):
                self.assertEqual(self._run(ci_running(provider, "python -W error -m pytest")).status, Status.PASS)

    def test_fails_when_warnings_are_not_errors(self) -> None:
        result = self._run(github_job("ubuntu-latest", "python -W ignore -m pytest && cmake -DCMAKE_CXX_FLAGS=-Werror"))
        self.assertEqual(result, Result.failed("no Python warning settings found; enable at least -W error"))

    def test_c_and_cxx_flags_do_not_count(self) -> None:
        self.assertEqual(self._run(WELL_CONFIGURED).status, Status.FAIL)


class RustCompilerWarningsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, compiler_warnings, files, RUST)

    def test_passes_with_clippy_denied_warnings_and_pedantic_lints(self) -> None:
        self.assertEqual(
            self._run(dict(WELL_CONFIGURED_RUST)),
            Result.passed("strict Rust lint settings are enabled: cargo clippy -D warnings clippy::pedantic"),
        )

    def test_settings_in_cargo_and_source_files_count(self) -> None:
        files = {
            ".cargo/config.toml": '[build]\nrustflags = ["-D", "warnings"]\n',
            "src/lib.rs": "#![warn(clippy::pedantic)]\n",
            **github_job("ubuntu-latest", "cargo clippy"),
        }
        self.assertEqual(self._run(files).status, Status.PASS)

    def test_denying_warnings_in_cargo_lints_or_crate_attributes_counts(self) -> None:
        settings = {"Cargo.toml": '[lints.rust]\nwarnings = "deny"\n', "src/main.rs": "#![deny(warnings)]\n"}
        for name, text in settings.items():
            with self.subTest(name):
                result = self._run({name: text, **github_job("ubuntu-latest", "cargo clippy -- -W clippy::pedantic")})
                self.assertEqual(result.status, Status.PASS)

    def test_warns_and_lists_missing_lints(self) -> None:
        result = self._run(github_job("ubuntu-latest", "cargo clippy -- -Dwarnings"))
        self.assertEqual(
            result, Result.warned("missing Rust lint settings: clippy::pedantic", "found cargo clippy -D warnings")
        )

    def test_fails_without_lint_settings(self) -> None:
        result = self._run(github_job("ubuntu-latest", "cargo build -Dwarnings_as_errors"))
        self.assertEqual(
            result,
            Result.failed("no Rust lint settings found; enable at least cargo clippy -D warnings clippy::pedantic"),
        )


class MixedLanguageCompilerWarningsTests(unittest.TestCase):
    def test_every_language_needs_strict_warnings_and_findings_are_labelled(self) -> None:
        result = run_as(self, compiler_warnings, dict(WELL_CONFIGURED), C_AND_CXX, PYTHON)
        self.assertEqual(result.status, Status.FAIL)
        self.assertTrue(result.message.startswith("C/C++: strict compiler warning flags are enabled: -Wall"))
        self.assertTrue(result.message.endswith("; Python: no Python warning settings found; enable at least -W error"))
