import unittest

from project_validator.checks.compiler_warnings import compiler_warnings
from project_validator.core import Result, Status
from project_validator.ecosystems import C_AND_CXX, PYTHON, RUST
from project_validator.structure import C_FAMILY
from tests.support import (
    BARE_PROJECT,
    CI_FILES,
    GITHUB_WORKFLOW,
    WELL_CONFIGURED,
    WELL_CONFIGURED_RUST,
    run_as,
    run_in_every_layout,
)


class CompilerWarningsTests(unittest.TestCase):
    def test_declares_the_languages_it_judges(self) -> None:
        self.assertEqual(compiler_warnings.languages, C_FAMILY | {"Python", "Rust"})

    GCC_FLAGS = "-Wall -Wextra -Wpedantic -Wshadow -Wconversion"
    MSVC_CI = "jobs:\n  build:\n    runs-on: windows-latest\n    steps:\n      - run: cmake -S . -B build\n"

    def _run(self, files: dict[str, str]):
        return run_in_every_layout(self, compiler_warnings, files)

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
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("/W4", result.message)
        self.assertIn("/permissive-", result.message)

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
                ".github/workflows/ci.yml": "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make\n",
            }
        )
        self.assertEqual(result.status, Status.PASS)

    def test_only_unrequired_msvc_flags_warn_rather_than_fail(self) -> None:
        result = self._run({"CMakeLists.txt": "add_compile_options(/W4 /permissive-)\n"})
        self.assertEqual(result.status, Status.WARN)
        self.assertIn("-Wall", result.message)


class PythonCompilerWarningsTests(unittest.TestCase):
    def _run(self, files: dict[str, str]) -> Result:
        return run_as(self, compiler_warnings, files, PYTHON)

    def test_warnings_as_errors_in_any_spelling_passes(self) -> None:
        spellings = {
            "python -W error": {GITHUB_WORKFLOW: "run: python3.14 -X dev -W error -m unittest\n"},
            "pytest -W error": {GITHUB_WORKFLOW: "run: pytest -q -W error\n"},
            "PYTHONWARNINGS": {GITHUB_WORKFLOW: "env:\n  PYTHONWARNINGS: error\n"},
            "pyproject filterwarnings": {"pyproject.toml": "[tool.pytest.ini_options]\nfilterwarnings = ['error']\n"},
            "pytest.ini filterwarnings": {"pytest.ini": "[pytest]\nfilterwarnings =\n    error\n"},
        }
        for spelling, files in spellings.items():
            with self.subTest(spelling):
                expected = Result.passed("strict Python warning settings are enabled: -W error")
                self.assertEqual(self._run(files), expected)

    def test_warnings_as_errors_in_any_ci_passes(self) -> None:
        for provider, path in CI_FILES.items():
            with self.subTest(ci=provider):
                self.assertEqual(self._run({path: "script: python -W error -m pytest\n"}).status, Status.PASS)

    def test_fails_when_warnings_are_not_errors(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: python -W ignore -m pytest && cmake -DCMAKE_CXX_FLAGS=-Werror\n"})
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
            GITHUB_WORKFLOW: "run: cargo clippy\n",
        }
        self.assertEqual(self._run(files).status, Status.PASS)

    def test_denying_warnings_in_cargo_lints_or_crate_attributes_counts(self) -> None:
        settings = {"Cargo.toml": '[lints.rust]\nwarnings = "deny"\n', "src/main.rs": "#![deny(warnings)]\n"}
        for name, text in settings.items():
            with self.subTest(name):
                result = self._run({name: text, GITHUB_WORKFLOW: "run: cargo clippy -- -W clippy::pedantic\n"})
                self.assertEqual(result.status, Status.PASS)

    def test_warns_and_lists_missing_lints(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: cargo clippy -- -Dwarnings\n"})
        self.assertEqual(
            result, Result.warned("missing Rust lint settings: clippy::pedantic", "found cargo clippy -D warnings")
        )

    def test_fails_without_lint_settings(self) -> None:
        result = self._run({GITHUB_WORKFLOW: "run: cargo build -Dwarnings_as_errors\n"})
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
